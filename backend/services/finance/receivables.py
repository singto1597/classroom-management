"""ผู้ค้างชำระ — รายงานอายุหนี้ (aging) + สรุปแดชบอร์ดค่าปรับ — Phase 5

📊 `get_receivables_aging`  — งานของผู้ค้างชำระทุกบิล (โปรเจกต์ + ค่าปรับ) ณ วันใดวันหนึ่ง
⚖️ `get_fine_summary`       — ภาพรวมค่าปรับ (ออก/ค้าง/ชำระ/ยกเว้น/ยกเลิก/คืนเงิน + เลยกำหนด)

📌 ไฟล์นี้อ่านอย่างเดียว — **ไม่มี journal, ไม่ยึด advisory lock** (ไม่เขียนเงิน)
   ⇒ ไม่ต้องอยู่ใน `_MONEY_PATHS` ของ `test_finance_money_lock.py`
📌 predicate "บิลเปิด" ใช้ `_open_bill_predicate()` ตัวเดียวกับทั้งระบบ (ดู accrual.py)
   ⇒ ยอดรวมในรายงานนี้ต้องตรงกับ AR ledger, `get_all_debtors` และใบแจ้งหนี้รวม
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import asyncpg

from core.rbac import has_any_permission, require_member

from .base import service_logger
from .constants import (
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    FINE_STATUS_CANCELLED,
)

_EPS = 0.005

# 🗂️ ถังอายุหนี้ — เรียงตามที่แสดงบนจอ
#    · `no_due` มาก่อนเพราะ "ไม่ระบุ" ไม่ควรปนกับ "ยังไม่ครบกำหนด"
#    · บิลที่ครบกำหนดวันนี้ = `not_due` (overdue 0 วัน ไม่ใช่ "ค้าง 1 วัน")
AGING_BUCKETS = [
    ("no_due", "ไม่ระบุกำหนด"),
    ("not_due", "ยังไม่ครบกำหนด"),
    ("1_30", "ค้าง 1–30 วัน"),
    ("31_60", "ค้าง 31–60 วัน"),
    ("61_90", "ค้าง 61–90 วัน"),
    ("over_90", "ค้างเกิน 90 วัน"),
]
_BUCKET_LABEL = dict(AGING_BUCKETS)


def aging_bucket_for(due_date: Optional[date], as_of: date) -> tuple[str, int]:
    """คืน (bucket, overdue_days) — overdue_days = 0 เมื่อยังไม่เลยกำหนด/ไม่ระบุ"""
    if due_date is None:
        return "no_due", 0
    overdue = (as_of - due_date).days
    if overdue <= 0:
        return "not_due", 0
    if overdue <= 30:
        return "1_30", overdue
    if overdue <= 60:
        return "31_60", overdue
    if overdue <= 90:
        return "61_90", overdue
    return "over_90", overdue


class ReceivablesMixin:
    # =================================================================
    # รายงานอายุหนี้
    # =================================================================
    @classmethod
    async def get_receivables_aging(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, as_of: Optional[date] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """บิลเปิดทุกใบ + อายุหนี้ ณ `as_of` (default = วันนี้ตามเวลาไทย)

        ⚠️ ยอดค้างคิดจาก `FC.amount - SP.paid_amount` **ต่อบิล** ไม่ใช่ยอดหลังหักเครดิต
           (เครดิตที่ยังไม่ถูกใช้ไม่ใช่การชำระ — หน้าลูกหนี้มี `net_pending_amount` แยก)
        """
        as_of = as_of or date.today()
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            rows = await conn.fetch(
                f"""
                SELECT SP.id AS payment_id, SP.student_id,
                       S.student_no,
                       U.first_name, U.nickname, U.first_name_en,
                       U.last_name_en, U.nickname_en,
                       FC.id AS collection_id, FC.title AS collection_title,
                       FC.collection_kind AS collection_kind, FC.due_date,
                       F.id AS fine_id,
                       (FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)) AS outstanding
                FROM student_payments SP
                JOIN fee_collections FC ON FC.id = SP.collection_id
                JOIN students S ON S.id = SP.student_id
                LEFT JOIN v_student_profiles U ON U.student_id = S.id
                LEFT JOIN fines F
                       ON F.student_payment_id = SP.id AND F.deleted_at IS NULL
                WHERE FC.room_id = $1
                  AND {cls._open_bill_predicate()}
                  AND (FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)) > {_EPS}
                ORDER BY FC.due_date ASC NULLS LAST, SP.id ASC
                """,
                target_room_id,
            )

            detail_rows: list[dict] = []
            project_total = 0.0
            fine_total = 0.0
            bucket_acc = {
                key: {"bucket": key, "label": label, "count": 0, "amount": 0.0,
                      "project_amount": 0.0, "fine_amount": 0.0}
                for key, label in AGING_BUCKETS
            }

            for r in rows:
                outstanding = round(float(r["outstanding"] or 0), 2)
                if outstanding <= _EPS:
                    continue
                kind = r["collection_kind"] or COLLECTION_KIND_PROJECT
                bucket, overdue_days = aging_bucket_for(r["due_date"], as_of)
                name = r["first_name"] or r["first_name_en"] or "Unknown"
                if r["nickname"]:
                    name += f" ({r['nickname']})"

                detail_rows.append({
                    "payment_id": r["payment_id"],
                    "student_id": r["student_id"],
                    "student_no": r["student_no"],
                    "student_name": name,
                    "collection_id": r["collection_id"],
                    "collection_title": r["collection_title"],
                    "collection_kind": kind,
                    "fine_id": r["fine_id"],
                    "due_date": r["due_date"],
                    "outstanding": outstanding,
                    "overdue_days": overdue_days,
                    "bucket": bucket,
                    "bucket_label": _BUCKET_LABEL[bucket],
                })

                acc = bucket_acc[bucket]
                acc["count"] += 1
                acc["amount"] = round(acc["amount"] + outstanding, 2)
                if kind == COLLECTION_KIND_FINE:
                    fine_total = round(fine_total + outstanding, 2)
                    acc["fine_amount"] = round(acc["fine_amount"] + outstanding, 2)
                else:
                    project_total = round(project_total + outstanding, 2)
                    acc["project_amount"] = round(acc["project_amount"] + outstanding, 2)

            result = {
                "as_of": as_of,
                "project_total": round(project_total, 2),
                "fine_total": round(fine_total, 2),
                "grand_total": round(project_total + fine_total, 2),
                "buckets": list(bucket_acc.values()),
                "rows": detail_rows,
            }

            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=None,
                entity_type="RECEIVABLES_AGING", entity_id=str(target_room_id),
                status="success",
                endpoint_or_command="FinanceService.get_receivables_aging",
            )
            return result

    # =================================================================
    # สรุปค่าปรับ (แดชบอร์ด)
    # =================================================================
    @classmethod
    async def get_fine_summary(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, as_of: Optional[date] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ภาพรวมค่าปรับของห้อง — คำนวณฝั่ง backend ทั้งหมด (frontend ไม่ต้องรวมเอง)

        🔐 นักเรียนที่มีแถว `students` ในห้องนี้เห็นสรุป **เฉพาะค่าปรับของตัวเอง**
           (เหมือน `list_fines`) — กันยอดรวม/รายชื่อคนอื่นรั่ว
        ⚠️ ค่าปรับ `cancelled` ยังนับ "จำนวน" ใน `by_status` แต่ **ไม่มียอดค้าง**
           (บิลถูก soft-delete; `fines.amount` คงเดิมไว้เป็นประวัติ)
        """
        as_of = as_of or date.today()
        soon_limit = as_of + timedelta(days=3)
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            params: list = [target_room_id]
            conds = ["F.room_id = $1", "F.deleted_at IS NULL"]
            # 🔐 เหมือน `list_fines`: ผู้มี MANAGE_FINANCE/admin เห็นทั้งห้อง
            #    ที่เหลือ (นักเรียน) เห็นเฉพาะของตัวเอง
            if not await has_any_permission(conn, target_room_id, user_id, ("MANAGE_FINANCE",)):
                my_student_id = await conn.fetchval(
                    """SELECT id FROM students
                       WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL
                       ORDER BY id LIMIT 1""",
                    target_room_id, int(user_id),
                )
                if my_student_id is not None:
                    params.append(my_student_id)
                    conds.append(f"F.student_id = ${len(params)}")

            rows = await conn.fetch(
                f"""
                SELECT F.id, F.status, F.fine_type_name, F.created_at,
                       F.student_id, F.due_date,
                       F.original_amount, F.amount, F.waived_amount, F.refunded_amount,
                       COALESCE(SP.paid_amount, 0) AS paid_amount,
                       SP.deleted_at AS payment_deleted_at,
                       S.student_no,
                       U.first_name, U.nickname, U.first_name_en,
                       U.last_name_en, U.nickname_en
                FROM fines F
                JOIN student_payments SP ON SP.id = F.student_payment_id
                LEFT JOIN students S ON S.id = F.student_id
                LEFT JOIN v_student_profiles U ON U.student_id = F.student_id
                WHERE {' AND '.join(conds)}
                """,
                *params,
            )

            totals = {
                "count": 0, "original_total": 0.0, "outstanding_total": 0.0,
                "paid_total": 0.0, "waived_total": 0.0, "refunded_total": 0.0,
                "overdue_count": 0, "overdue_amount": 0.0,
                "due_soon_count": 0, "due_soon_amount": 0.0,
            }
            by_status: dict[str, dict] = {}
            by_type: dict[str, dict] = {}
            by_student: dict[int, dict] = {}

            for r in rows:
                status = r["status"]
                amount = float(r["amount"] or 0)
                paid = float(r["paid_amount"] or 0)
                original = float(r["original_amount"] or 0)
                waived = float(r["waived_amount"] or 0)
                refunded = float(r["refunded_amount"] or 0)
                payment_alive = r["payment_deleted_at"] is None
                outstanding = (
                    round(max(amount - paid, 0.0), 2)
                    if payment_alive and status != FINE_STATUS_CANCELLED else 0.0
                )

                totals["count"] += 1
                totals["original_total"] = round(totals["original_total"] + original, 2)
                totals["waived_total"] = round(totals["waived_total"] + waived, 2)
                totals["refunded_total"] = round(totals["refunded_total"] + refunded, 2)
                totals["outstanding_total"] = round(totals["outstanding_total"] + outstanding, 2)
                if status != FINE_STATUS_CANCELLED:
                    totals["paid_total"] = round(totals["paid_total"] + paid, 2)

                st = by_status.setdefault(status, {"status": status, "count": 0,
                                                    "amount": 0.0, "outstanding": 0.0})
                st["count"] += 1
                st["amount"] = round(st["amount"] + amount, 2)
                st["outstanding"] = round(st["outstanding"] + outstanding, 2)

                tp = by_type.setdefault(r["fine_type_name"],
                                        {"fine_type_name": r["fine_type_name"],
                                         "count": 0, "amount": 0.0, "outstanding": 0.0})
                tp["count"] += 1
                tp["amount"] = round(tp["amount"] + amount, 2)
                tp["outstanding"] = round(tp["outstanding"] + outstanding, 2)

                if outstanding > _EPS:
                    if r["due_date"] is not None and r["due_date"] < as_of:
                        totals["overdue_count"] += 1
                        totals["overdue_amount"] = round(
                            totals["overdue_amount"] + outstanding, 2
                        )
                    elif r["due_date"] is not None and r["due_date"] <= soon_limit:
                        totals["due_soon_count"] += 1
                        totals["due_soon_amount"] = round(
                            totals["due_soon_amount"] + outstanding, 2
                        )

                    name = r["first_name"] or r["first_name_en"] or "Unknown"
                    if r["nickname"]:
                        name += f" ({r['nickname']})"
                    sd = by_student.setdefault(r["student_id"], {
                        "student_id": r["student_id"],
                        "student_no": r["student_no"],
                        "student_name": name,
                        "count": 0,
                        "outstanding": 0.0,
                    })
                    sd["count"] += 1
                    sd["outstanding"] = round(sd["outstanding"] + outstanding, 2)

            result = {
                "as_of": as_of,
                "totals": totals,
                "by_status": sorted(by_status.values(), key=lambda x: x["status"]),
                "by_type": sorted(by_type.values(), key=lambda x: -x["amount"]),
                "top_debtors": sorted(
                    by_student.values(), key=lambda x: -x["outstanding"]
                )[:10],
            }

            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=None,
                entity_type="FINE_SUMMARY", entity_id=str(target_room_id),
                status="success",
                endpoint_or_command="FinanceService.get_fine_summary",
            )
            return result
