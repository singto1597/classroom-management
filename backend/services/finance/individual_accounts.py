"""👤 [FIN-V2 / P1.3] บัญชีรายบุคคล — ยอดค้าง/เครดิต/บิลเปิด/ประวัติ และ statement

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี (แทนสองหน้าจอเดิม)
═══════════════════════════════════════════════════════════════════════════════
วันนี้ "ผู้ค้างชำระ" (`/finance/debtors`) กับ "เงินรับล่วงหน้า" (`/finance/credits`)
เป็นคนละ endpoint คนละโมเดล ⇒ ครูต้องเปิดสองหน้าเพื่อตอบคำถามเดียวว่า
"นักเรียนคนนี้ค้างเท่าไร มีเครดิตเท่าไร และควรเก็บอีกเท่าไร"

API นี้รวมทุกอย่างของนักเรียน 1 คนไว้ในคำตอบเดียว (อ่านอย่างเดียว):
  outstanding_total · overdue_total · upcoming_total · credit_balance ·
  ready_to_apply · open_bills[] · recent_events[] + statement ตามช่วงวันที่

═══════════════════════════════════════════════════════════════════════════════
📌 สูตรกลาง (ต้องตรงกับทั้งระบบ)
═══════════════════════════════════════════════════════════════════════════════
    outstanding = FC.amount - COALESCE(SP.paid_amount, 0)
                                - COALESCE(SP.written_off_amount, 0)

และ predicate บิลเปิดใช้ `_open_bill_predicate()` ตัวเดียวกับ accrual/receivables
**ห้ามพิมพ์สูตรซ้ำ** — ถ้าวันหนึ่งนิยามบิลเปิดเปลี่ยน ทุกยอดต้องเปลี่ยนพร้อมกัน

⚠️ Clamp `GREATEST(outstanding, 0)` **เฉพาะตอนแสดงผล/รวมยอด** เพราะข้อมูลเก่าอาจมี
   paid เกินจาก rounding · แต่ห้าม clamp ใน WHERE ของ predicate (brief §Schema)

═══════════════════════════════════════════════════════════════════════════════
🔐 สิทธิ์
═══════════════════════════════════════════════════════════════════════════════
`require_member` (ไม่ใช่ MANAGE_FINANCE) — หน้านี้แทน "ผู้ค้างชำระ" ที่สมาชิกเคย
เห็นได้ และเป็น read-only · ถ้าบังคับ MANAGE_FINANCE นักเรียนจะดูยอดตัวเองไม่ได้

═══════════════════════════════════════════════════════════════════════════════
⏱️ "วันนี้" คือวันไทย
═══════════════════════════════════════════════════════════════════════════════
`due_date` เป็น DATE ในโซนผู้ใช้ ⇒ เทียบกับ `(NOW() AT TIME ZONE 'Asia/Bangkok')::date`
ไม่ใช่ `CURRENT_DATE` ของ session (container รัน UTC — ช่วง 00:00–07:00 ไทยจะเลื่อนวัน)
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

import asyncpg

from core.rbac import require_member
from core.exceptions import StudentNotFoundError

from .base import service_logger

# จำนวนเหตุการณ์รับเงินล่าสุดต่อคนที่ส่งไปให้หน้าจอ (แค่พรีวิว — ประวัติเต็มอยู่ที่ P3.4)
RECENT_EVENTS_LIMIT = 5
# เพดานบรรทัด statement — กันช่วงวันที่กว้างเกินจน DB สร้าง response ยักษ์
STATEMENT_MAX_ROWS = 2000
# ค่าที่รับได้ของตัวกรอง `status` (ใช้ค่าเดียวแทน boolean หลายตัว ให้ FE สลับง่าย)
VALID_ACCOUNT_STATUS = ("all", "outstanding", "credit", "settled")
VALID_FUND_TYPES = ("room_fund", "pass_through")

# 🗂️ วันไทย — ค่าเดียวกันทั้งระบบ (ดู home_summary_service)
_THAI_TODAY_SQL = "SELECT (NOW() AT TIME ZONE 'Asia/Bangkok')::date"

# ประเภท journal ที่ยืนยันว่า "บิลนี้ถูกออกเมื่อไร" (student_payments ไม่มี created_at)
_BILL_ISSUE_REF_TYPES = ("student_payment_issue", "opening_receivable")


def _money_str(value) -> str:
    """เงินทุกฟิลด์ใน API v2 เป็นสตริงทศนิยม 2 ตำแหน่ง (api-v2 §2)

    ⚠️ รับ `Decimal` จาก asyncpg ได้โดยตรง — cast `float()` ก่อนจัดรูป (บทเรียน DECIMAL)
    """
    return f"{float(value or 0):.2f}"


def _student_name(row) -> str:
    """ชื่อที่แสดง = first_name → first_name_en → Unknown (+ nickname ในวงเล็บ)

    ⚠️ ต้องประกอบเอง — `v_student_profiles` ไม่มีคอลัมน์ `display_name`
       (ตรงกับ `_resolve_student_name` ใน base.py และ receivables/credits)
    """
    name = row["first_name"] or row["first_name_en"] or "Unknown"
    if row["nickname"]:
        name += f" ({row['nickname']})"
    return name


class IndividualAccountsMixin:
    """บัญชีรายบุคคล (อ่านอย่างเดียว) + statement — ไม่แตะเงิน/journal/lock"""

    # ═════════════════════════════════════════════════════════════════
    # อ่าน — ตัวช่วยภายใน
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def _load_individual_accounts(
        cls, conn: asyncpg.Connection, room_id: int, *,
        student_id: Optional[int] = None,
        fund_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> tuple[date, List[dict]]:
        """โหลดบัญชีรายบุคคลทุกคน (หรือคนเดียว) ด้วย query ข้อมูลคงที่ 4 ตัว

        Query count = 4 (students · open bills · latest credit · recent events)
        + 1 scalar clock query ไม่ว่า N จะเท่าไร ⇒ ไม่มี N+1
        ถ้าไม่มีนักเรียนเลยจะข้าม 3 query ที่เหลือ

        Returns: (วันนี้ตามเวลาไทย, items[])
        """
        today = await conn.fetchval(_THAI_TODAY_SQL)

        params: list = [room_id]
        conds = ["S.room_id = $1", "S.deleted_at IS NULL"]
        if student_id is not None:
            params.append(student_id)
            conds.append(f"S.id = ${len(params)}")
        if q and q.strip():
            params.append(f"%{q.strip()}%")
            idx = len(params)
            conds.append(
                f"(S.student_no::text ILIKE ${idx}"
                f" OR U.first_name ILIKE ${idx} OR U.last_name ILIKE ${idx}"
                f" OR U.nickname ILIKE ${idx}"
                f" OR U.first_name_en ILIKE ${idx} OR U.last_name_en ILIKE ${idx}"
                f" OR U.nickname_en ILIKE ${idx})"
            )

        students = await conn.fetch(
            f"""
            SELECT S.id AS student_id, S.student_no,
                   U.first_name, U.nickname, U.first_name_en,
                   U.last_name_en, U.nickname_en
            FROM students S
            LEFT JOIN v_student_profiles U ON U.student_id = S.id
            WHERE {' AND '.join(conds)}
            ORDER BY S.student_no ASC, S.id ASC
            """,
            *params,
        )
        if not students:
            return today, []

        student_ids = [r["student_id"] for r in students]
        # 🔢 ยอดบิลจาก FC.amount เสมอ — `student_payments` ไม่มีคอลัมน์ amount
        bill_params: list = [room_id, student_ids]
        bill_conds = [
            "FC.room_id = $1",
            cls._open_bill_predicate(),
            "SP.student_id = ANY($2::int[])",
        ]
        if fund_type is not None:
            bill_params.append(fund_type)
            bill_conds.append(f"FC.fund_type = ${len(bill_params)}")
        bills = await conn.fetch(
            f"""
            SELECT SP.id AS student_payment_id, SP.student_id,
                   FC.id AS collection_id, FC.title,
                   FC.amount, COALESCE(SP.paid_amount, 0) AS paid_amount,
                   COALESCE(SP.written_off_amount, 0) AS written_off_amount,
                   FC.due_date, SP.status,
                   FC.collection_kind, FC.fund_type
            FROM student_payments SP
            JOIN fee_collections FC ON FC.id = SP.collection_id
            WHERE {' AND '.join(bill_conds)}
            ORDER BY FC.due_date ASC NULLS LAST, SP.id ASC
            """,
            *bill_params,
        )

        # 💰 ยอดเครดิต = snapshot แถวล่าสุด (ไม่ใช่ SUM — reverse ทำให้ SUM เพี้ยน)
        credit_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (SC.student_id) SC.student_id, SC.balance_after
            FROM student_credits SC
            WHERE SC.room_id = $1 AND SC.deleted_at IS NULL
              AND SC.student_id = ANY($2::int[])
            ORDER BY SC.student_id, SC.id DESC
            """,
            room_id, student_ids,
        )
        credit_map = {r["student_id"]: float(r["balance_after"] or 0) for r in credit_rows}

        # 🧾 เหตุการณ์รับเงินล่าสุด 5 รายการ/คน — ตารางว่างจนถึง P2.1 (query ต้องทน 0 แถว)
        event_rows = await conn.fetch(
            """
            SELECT event_id, student_id, event_at, amount_received,
                   credit_used, receiver_name
            FROM (
                SELECT E.id AS event_id, E.student_id, E.event_at,
                       E.amount_received, E.credit_used, E.receiver_name,
                       ROW_NUMBER() OVER (
                           PARTITION BY E.student_id
                           ORDER BY E.event_at DESC, E.id DESC
                       ) AS rn
                FROM finance_payment_events E
                WHERE E.room_id = $1 AND E.status = 'active'
                  AND E.student_id = ANY($2::int[])
            ) X
            WHERE rn <= $3
            ORDER BY student_id, event_at DESC, event_id DESC
            """,
            room_id, student_ids, RECENT_EVENTS_LIMIT,
        )
        event_map: dict = {}
        for r in event_rows:
            event_map.setdefault(r["student_id"], []).append({
                "event_id": r["event_id"],
                "event_at": r["event_at"],
                "amount_received": _money_str(r["amount_received"]),
                "credit_used": _money_str(r["credit_used"]),
                "receiver_name": r["receiver_name"],
            })

        bills_map: dict = {}
        for b in bills:
            outstanding = max(
                float(b["amount"]) - float(b["paid_amount"]) - float(b["written_off_amount"]),
                0.0,
            )
            bills_map.setdefault(b["student_id"], []).append({
                "student_payment_id": b["student_payment_id"],
                "collection_id": b["collection_id"],
                "title": b["title"],
                "amount": _money_str(b["amount"]),
                "paid_amount": _money_str(b["paid_amount"]),
                "written_off_amount": _money_str(b["written_off_amount"]),
                "outstanding": _money_str(outstanding),
                "due_date": b["due_date"],
                "status": b["status"],
                "collection_kind": b["collection_kind"],
                "fund_type": b["fund_type"],
                "_outstanding_num": outstanding,
                "_is_overdue": b["due_date"] is not None and b["due_date"] < today,
            })

        items: List[dict] = []
        for s in students:
            sid = s["student_id"]
            open_bills = bills_map.get(sid, [])
            outstanding_total = round(sum(b["_outstanding_num"] for b in open_bills), 2)
            overdue_total = round(
                sum(b["_outstanding_num"] for b in open_bills if b["_is_overdue"]), 2
            )
            credit_balance = round(credit_map.get(sid, 0.0), 2)
            ready_to_apply = round(min(credit_balance, outstanding_total), 2)

            # ตัดฟิลด์ภายในที่ใช้คำนวณ (`_…`) ออกก่อนส่งออก
            clean_bills = [
                {k: v for k, v in b.items() if not k.startswith("_")}
                for b in open_bills
            ]

            items.append({
                "student_id": sid,
                "student_no": s["student_no"],
                "name": _student_name(s),
                "outstanding_total": _money_str(outstanding_total),
                "overdue_total": _money_str(overdue_total),
                "upcoming_total": _money_str(outstanding_total - overdue_total),
                "credit_balance": _money_str(credit_balance),
                "ready_to_apply": _money_str(ready_to_apply),
                "open_bills": clean_bills,
                "recent_events": event_map.get(sid, []),
                # เก็บตัวเลขไว้กรอง status หลังประกอบ item (หลุด response_model อยู่แล้ว)
                "_outstanding_num": outstanding_total,
                "_credit_num": credit_balance,
            })

        return today, items

    @staticmethod
    def _strip_internal(item: dict) -> dict:
        """ตัดคีย์ภายใน (`_…`) — ใช้กับทั้ง list และ detail ก่อนส่งต่อ router"""
        return {k: v for k, v in item.items() if not k.startswith("_")}

    @staticmethod
    def _filter_by_status(items: List[dict], status: Optional[str]) -> List[dict]:
        if status in (None, "all"):
            return items
        if status == "outstanding":
            return [i for i in items if i["_outstanding_num"] > 0]
        if status == "credit":
            return [i for i in items if i["_credit_num"] > 0]
        # settled = ไม่มีทั้งค้างและเครดิต
        return [
            i for i in items
            if i["_outstanding_num"] <= 0 and i["_credit_num"] <= 0
        ]

    # ═════════════════════════════════════════════════════════════════
    # อ่าน — API 3 ตัว
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def list_individual_accounts(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, status: Optional[str] = None, q: Optional[str] = None,
        fund_type: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """บัญชีรายบุคคลทุกคนของห้อง — กรองได้ด้วย status/q/fund_type"""
        if status not in (None, *VALID_ACCOUNT_STATUS):
            raise ValueError(f"สถานะ '{status}' ไม่ถูกต้อง (ใช้ all/outstanding/credit/settled)")
        if fund_type is not None and fund_type not in VALID_FUND_TYPES:
            raise ValueError("fund_type ต้องเป็น room_fund หรือ pass_through")

        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            as_of, items = await cls._load_individual_accounts(
                conn, target_room_id, fund_type=fund_type, q=q,
            )
            items = cls._filter_by_status(items, status)

            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=None,
                entity_type="INDIVIDUAL_ACCOUNT", entity_id=str(target_room_id),
                status="success",
                endpoint_or_command="FinanceService.list_individual_accounts",
            )
            return {
                "as_of": as_of,
                "items": [cls._strip_internal(i) for i in items],
            }

    @classmethod
    async def get_individual_account(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, student_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """บัญชีของนักเรียน 1 คน — 404 ถ้าไม่ใช่สมาชิกของห้องนี้"""
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            _, items = await cls._load_individual_accounts(
                conn, target_room_id, student_id=student_id,
            )
            if not items:
                raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้อง")

            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=None,
                entity_type="INDIVIDUAL_ACCOUNT", entity_id=str(student_id),
                status="success",
                endpoint_or_command="FinanceService.get_individual_account",
            )
            return cls._strip_internal(items[0])

    # ═════════════════════════════════════════════════════════════════
    # statement — timeline บิล/รับเงิน/เครดิต ในช่วงวันที่
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def get_student_statement(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, student_id: int,
        date_from: Optional[date] = None, date_to: Optional[date] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """statement (เดินบัญชี) ของนักเรียน — บิล (+), รับเงิน (−), เครดิต (±)

        ⚠️ `amount` มีเครื่องหมายตาม **ผลต่อยอดที่นักเรียนค้าง**:
           บิล + · รับเงิน − · เติมเครดิต + · ใช้เครดิต − · คืนเครดิต +
           (`balance_after` มีเฉพาะบรรทัดเครดิต — เป็นยอดเครดิตคงเหลือหลังรายการนั้น)
        ⚠️ บิลที่ไม่มี journal ออกบิล (ข้อมูลยุคก่อน accrual) **ไม่ปรากฏ** ในไทม์ไลน์
           เพราะไม่มีวันที่ออกที่เชื่อถือได้ — การรับเงิน/เครดิตของบิลนั้นยังปรากฏปกติ
        """
        if date_from and date_to and date_from > date_to:
            raise ValueError("วันที่เริ่มต้นต้องไม่หลังวันที่สิ้นสุด")

        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            student = await conn.fetchrow(
                """
                SELECT S.id AS student_id, S.student_no,
                       U.first_name, U.nickname, U.first_name_en,
                       U.last_name_en, U.nickname_en
                FROM students S
                LEFT JOIN v_student_profiles U ON U.student_id = S.id
                WHERE S.id = $1 AND S.room_id = $2 AND S.deleted_at IS NULL
                """,
                student_id, target_room_id,
            )
            if not student:
                raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้อง")

            entries: List[dict] = []

            # ── 1) บิลที่ออกในช่วง (วันที่จาก journal ออกบิล) ──
            bill_params: list = [target_room_id, student_id]
            bill_conds = [
                "SP.student_id = $2",
                f"J.reference_type = ANY($3::text[])",
                "J.room_id = $1",
                "J.deleted_at IS NULL",
                "J.status <> 'voided'",
                "SP.deleted_at IS NULL",
                "FC.deleted_at IS NULL",
            ]
            bill_params.append(list(_BILL_ISSUE_REF_TYPES))
            date_conds, date_params = cls._statement_date_conds(
                "(J.transaction_date AT TIME ZONE 'Asia/Bangkok')", date_from, date_to,
                start_index=len(bill_params) + 1,
            )
            bill_params.extend(date_params)
            bills = await conn.fetch(
                f"""
                SELECT SP.id AS ref_id, FC.title, FC.amount,
                       MIN(J.transaction_date) AS occurred_at
                FROM student_payments SP
                JOIN fee_collections FC ON FC.id = SP.collection_id
                JOIN journal_entries J
                     ON J.reference_id = SP.id::text
                    AND J.reference_type = ANY($3::text[])
                WHERE {' AND '.join(bill_conds + date_conds)}
                GROUP BY SP.id, FC.title, FC.amount
                """,
                *bill_params,
            )
            for b in bills:
                entries.append({
                    "entry_id": f"bill-{b['ref_id']}",
                    "kind": "bill",
                    "occurred_at": b["occurred_at"],
                    "description": f"ออกบิล: {b['title']}",
                    "amount": _money_str(b["amount"]),
                    "balance_after": None,
                    "reference_id": b["ref_id"],
                    "_sid": b["ref_id"],
                })

            # ── 2) รับเงิน (legacy transactions — event v2 มี payment_event_id) ──
            pay_params: list = [target_room_id, student_id]
            pay_conds = [
                "T.room_id = $1",
                "SP.student_id = $2",
                "T.deleted_at IS NULL",
                "T.payment_event_id IS NULL",
            ]
            date_conds, date_params = cls._statement_date_conds(
                "(T.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Bangkok')",
                date_from, date_to, start_index=len(pay_params) + 1,
            )
            pay_params.extend(date_params)
            payments = await conn.fetch(
                f"""
                SELECT T.id AS ref_id, T.amount, T.description,
                       (T.created_at AT TIME ZONE 'UTC') AS occurred_at
                FROM finance_transactions T
                JOIN student_payments SP ON SP.id = T.student_payment_id
                WHERE {' AND '.join(pay_conds + date_conds)}
                """,
                *pay_params,
            )
            for p in payments:
                entries.append({
                    "entry_id": f"payment-{p['ref_id']}",
                    "kind": "payment",
                    "occurred_at": p["occurred_at"],
                    "description": p["description"] or "รับเงิน",
                    "amount": _money_str(-float(p["amount"])),
                    "balance_after": None,
                    "reference_id": p["ref_id"],
                    "_sid": p["ref_id"],
                })

            # ── 3) เครดิต (topup / apply / reverse — snapshot ledger) ──
            credit_params: list = [target_room_id, student_id]
            credit_conds = [
                "SC.room_id = $1",
                "SC.student_id = $2",
                "SC.deleted_at IS NULL",
            ]
            date_conds, date_params = cls._statement_date_conds(
                "(SC.created_at AT TIME ZONE 'Asia/Bangkok')",
                date_from, date_to, start_index=len(credit_params) + 1,
            )
            credit_params.extend(date_params)
            credit_rows = await conn.fetch(
                f"""
                SELECT SC.id AS ref_id, SC.entry_type, SC.amount,
                       SC.balance_after, SC.created_at AS occurred_at,
                       SC.student_payment_id
                FROM student_credits SC
                WHERE {' AND '.join(credit_conds + date_conds)}
                """,
                *credit_params,
            )
            for c in credit_rows:
                kind = f"credit_{c['entry_type']}"
                label = {
                    "credit_topup": "เติมเครดิต",
                    "credit_apply": "ใช้เครดิตปิดบิล",
                    "credit_reverse": "ยกเลิกการใช้เครดิต",
                }[kind]
                sign = -1 if c["entry_type"] == "apply" else 1
                entries.append({
                    "entry_id": f"credit-{c['ref_id']}",
                    "kind": kind,
                    "occurred_at": c["occurred_at"],
                    "description": label,
                    "amount": _money_str(sign * float(c["amount"])),
                    "balance_after": _money_str(c["balance_after"]),
                    "reference_id": c["ref_id"],
                    "_sid": c["ref_id"],
                })

            # ── 4) payment events v2 (ตารางว่างจนถึง P2.1) ──
            ev_params: list = [target_room_id, student_id]
            ev_conds = ["E.room_id = $1", "E.student_id = $2", "E.status = 'active'"]
            date_conds, date_params = cls._statement_date_conds(
                "(E.event_at AT TIME ZONE 'Asia/Bangkok')",
                date_from, date_to, start_index=len(ev_params) + 1,
            )
            ev_params.extend(date_params)
            events = await conn.fetch(
                f"""
                SELECT E.id AS ref_id, E.amount_received, E.receiver_name,
                       E.event_at AS occurred_at
                FROM finance_payment_events E
                WHERE {' AND '.join(ev_conds + date_conds)}
                """,
                *ev_params,
            )
            for e in events:
                entries.append({
                    "entry_id": f"event-{e['ref_id']}",
                    "kind": "payment_event",
                    "occurred_at": e["occurred_at"],
                    "description": f"รับเงิน (ผู้รับ: {e['receiver_name']})",
                    "amount": _money_str(-float(e["amount_received"])),
                    "balance_after": None,
                    "reference_id": e["ref_id"],
                    "_sid": e["ref_id"],
                })

            if len(entries) > STATEMENT_MAX_ROWS:
                raise ValueError(
                    f"ช่วงวันที่กว้างเกินไป ({len(entries)} รายการ) — "
                    f"กรุณาแคบช่วงให้เหลือไม่เกิน {STATEMENT_MAX_ROWS} รายการ"
                )

            # เรียงตามเวลา แล้วให้ id จริงของแหล่งข้อมูลเป็นตัวตัดสินเมื่อเวลาเท่ากัน
            # ⚠️ ห้ามเรียงด้วย `entry_id` (สตริง) — "bill-10" จะมาก่อน "bill-9"
            entries.sort(key=lambda e: (e["occurred_at"], e["_sid"]))
            for e in entries:
                e.pop("_sid", None)

            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=None,
                entity_type="STUDENT_STATEMENT", entity_id=str(student_id),
                status="success",
                endpoint_or_command="FinanceService.get_student_statement",
            )
            return {
                "student_id": student["student_id"],
                "student_no": student["student_no"],
                "name": _student_name(student),
                "date_from": date_from,
                "date_to": date_to,
                "entries": entries,
                # 📄 [P5.1] registry ยังไม่เกิด — คืนโครงว่างไว้ให้ FE ต่อได้โดยไม่ต้องแก้สัญญา
                "documents": [],
            }

    @staticmethod
    def _statement_date_conds(
        occurred_expr: str, date_from: Optional[date], date_to: Optional[date],
        *, start_index: int,
    ) -> tuple[List[str], list]:
        """สร้างเงื่อนไขช่วงวันที่แบบรวมปลายทั้งสองด้าน

        `occurred_expr` ต้องเป็น expression ที่คืน **วันที่ตามเวลาไทย** แล้ว
        (ผู้เรียกเป็นคนใส่ `AT TIME ZONE` เอง เพราะชนิดคอลัมน์ต่างกัน)
        """
        conds: List[str] = []
        params: list = []
        if date_from is not None:
            conds.append(f"{occurred_expr}::date >= ${start_index + len(params)}")
            params.append(date_from)
        if date_to is not None:
            conds.append(f"{occurred_expr}::date <= ${start_index + len(params)}")
            params.append(date_to)
        return conds, params
