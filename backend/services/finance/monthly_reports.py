"""📊 [FIN-V2 / P5.4] รายงานปิดงบเดือน (RPT) — snapshot จาก journal + นับเงินสด + version

═══════════════════════════════════════════════════════════════════════════════
สัญญาของรายงานนี้
═══════════════════════════════════════════════════════════════════════════════
- **อ่าน journal เท่านั้น** (`journal_entries`/`journal_lines`/`accounting_ledgers`)
  ❌ ห้ามใช้ `finance_transactions` — ตารางนั้นเป็น legacy mirror ที่ไม่มีแถวหลัง CUTOFF
- **ไม่แตะเงินเลย** — RPT ไม่มี INSERT/UPDATE บน `finance_accounts`/journal/credit
  (void ของ RPT = void เอกสาร ไม่ใช่ void รายการบัญชี; รายการบัญชีถูก reverse ด้วย
   กลไกของตัวเองตั้งแต่ก่อนรายงานถูกสร้าง)
- `closing_cash = opening_cash + total_income - total_expense` — **identity ที่ reproducible**
  ไม่ใช่ `SUM(balance)` สด: รายงานที่พิมพ์ไปแล้วต้องสร้างซ้ำได้หลังข้อมูลถูกแก้
  ผลต่างจากกระเป๋าสดเก็บไว้ใน `snapshot.cash_gap` เพื่อตรวจย้อน ไม่ block การสร้าง
- **หนึ่งงวด (room, year_be, month) มีใบ active (draft/final) ได้ใบเดียว**
  "แก้ไข" = void ใบเดิม → สร้าง version ใหม่ ⇒ `report_no` ได้ suffix `-v2`, `-v3`
- finalize ได้เฉพาะเมื่อ `variance` (เงินสดนับจริง − closing_cash) = 0 เศรษฐศาสตร์
  ❌ ไม่มีช่อง "อนุมัติทั้งที่ต่าง" — ดูเหตุผลใน brief P5.4 บันทึกการตัดสินใจข้อ 6

📅 ขอบเขตเดือนต้องเป็น **เวลาไทย** (`_thai_day_start`) — ส่ง `date` เปล่าเข้า
   timestamptz แล้ว transaction_date ช่วง 00:00–07:00 ไทยจะตกไปอยู่เดือนก่อน
"""
import calendar
import json
import time
from datetime import date, datetime
from typing import Optional, Tuple

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
from .constants import (
    BUDDHIST_ERA_OFFSET, DOC_TYPE_MONTHLY_REPORT, THAI_MONTHS_SHORT, THAI_TZ,
)
from .helpers import _thai_day_start, _thai_dt_parts, _thai_next_day_start

# 🖨️ partial ของ shell `receipt.html` — ต้องมีไฟล์จริง (เทสต์ P5.3 ตรวจทุก key ที่ลงทะเบียน)
MONTHLY_REPORT_BODY_TEMPLATE = "_monthly_report_body_v2.html"

# 🗓️ ชื่อเดือนไทยแบบเต็ม — ใช้ทั้งบนกระดาษและข้อความตอบกลับ
_THAI_MONTHS_FULL = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)

# 📌 รหัสบัญชีลูกหนี้ — ต้องกันออกจาก "เงินสด" (= asset ทั้งหมดลบลูกหนี้)
_AR_CODES = ("11001", "11002")

# 🎯 เพดานของผลต่างที่ถือว่า "ตรงกัน" (สตางค์ครึ่ง)
_VARIANCE_EPSILON = 0.005


class MonthlyReportConflictError(Exception):
    """RPT ขัดแย้งกับสถานะที่มีอยู่ (router แปลงเป็น 409)

    ⚠️ นิยามในโมดูล service **ไม่ใช่** `core/exceptions.py` — ไฟล์นั้นอยู่นอก owned
       ของ P5.4 และ exception นี้ไม่มีผู้ใช้นอกโมดูลการเงิน
    """


def _month_bounds(year_be: int, month: int) -> Tuple[date, date, date]:
    """(start, end_exclusive, end_inclusive) ของเดือนตามปฏิทินไทย

    `year_be` เป็น **พ.ศ.** ⇒ แปลงเป็น ค.ศ. ก่อนสร้าง `date` (ลบ 543)
    """
    if not (2400 <= year_be <= 2700):
        raise ValueError("ปี พ.ศ. ไม่ถูกต้อง — ต้องอยู่ระหว่าง 2400–2700")
    year_ce = year_be - BUDDHIST_ERA_OFFSET
    start = date(year_ce, month, 1)
    if month == 12:
        end_exclusive = date(year_ce + 1, 1, 1)
    else:
        end_exclusive = date(year_ce, month + 1, 1)
    end_inclusive = date(year_ce, month, calendar.monthrange(year_ce, month)[1])
    return start, end_exclusive, end_inclusive


def _as_snapshot(raw) -> dict:
    """jsonb → dict (asyncpg คืน **str** เพราะโปรเจกต์นี้ไม่ลง type codec)"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _report_no_for(year_be: int, month: int, version: int) -> str:
    """`RPT-2569-11` (v1) / `RPT-2569-11-v2` — เดือนต้อง 2 หลักเสมอ"""
    base = f"RPT-{year_be}-{month:02d}"
    return base if version <= 1 else f"{base}-v{version}"


def _period_text(value) -> Optional[str]:
    """วันของงวดใน snapshot (`date` หรือ ISO string) → "1 พ.ย. 2569" (พ.ศ.)

    ⚠️ snapshot เก็บ `period` เป็นสตริง ISO ⇒ ต้อง parse ก่อน ไม่ใช่พิมพ์ดิบ
       (ค.ศ. บนกระดาษที่เลขเอกสารเป็น พ.ศ. = ขัดแย้งกันเอง)
    """
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return (
            f"{value.day} {THAI_MONTHS_SHORT[value.month - 1]} "
            f"{value.year + BUDDHIST_ERA_OFFSET}"
        )
    return str(value)


def _shape_report(row) -> dict:
    """แถว `finance_monthly_reports` → dict สำหรับ response (Decimal → float)"""
    def _f(key):
        value = row[key]
        return None if value is None else round(float(value), 2)

    return {
        "id": row["id"],
        "report_no": row["report_no"],
        "year_be": row["year_be"],
        "month": row["month"],
        "version": row["version"],
        "status": row["status"],
        "total_income": _f("total_income"),
        "total_expense": _f("total_expense"),
        "opening_cash": _f("opening_cash"),
        "closing_cash": _f("closing_cash"),
        "counted_cash": _f("counted_cash"),
        "variance": _f("variance"),
        "finalized_at": row["finalized_at"],
        "finalized_by": row["finalized_by"],
        "voided_at": row["voided_at"],
        "void_reason": row["void_reason"],
        "created_at": row["created_at"],
        "snapshot": _as_snapshot(row["snapshot"]),
    }


class MonthlyReportsMixin:
    """RPT — รายการ/สร้าง/รายละเอียด/finalize/void/PDF (ไม่แตะเงิน)"""

    # ─────────────────────────────────────────────────────────────── รายการ
    @classmethod
    async def list_monthly_reports(
        cls,
        pool: asyncpg.Pool,
        *,
        client_source: str,
        actor_identifier: str,
        year_be: Optional[int] = None,
        status: Optional[str] = None,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายงานปิดงบของห้อง — กรองปี พ.ศ./สถานะได้ (ทุกสถานะแสดงเสมอ)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                where = "WHERE room_id = $1"
                params = [target_room_id]
                if year_be is not None:
                    params.append(year_be)
                    where += f" AND year_be = ${len(params)}"
                if status is not None:
                    if status not in ("draft", "final", "voided"):
                        raise ValueError("สถานะต้องเป็น draft, final หรือ voided")
                    params.append(status)
                    where += f" AND status = ${len(params)}"

                rows = await conn.fetch(
                    f"""SELECT id, room_id, year_be, month, version, report_no, status,
                               snapshot, total_income, total_expense, opening_cash,
                               closing_cash, counted_cash, variance, finalized_at,
                               finalized_by, voided_at, void_reason, created_at
                          FROM finance_monthly_reports
                          {where}
                         ORDER BY year_be DESC, month DESC, version DESC""",
                    *params,
                )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_MONTHLY_REPORT", status="success",
                    endpoint_or_command="FinanceService.list_monthly_reports",
                    execution_time_ms=exec_time,
                )
                items = [_shape_report(r) for r in rows]
                return {"status": "success", "items": items, "total": len(items)}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.list_monthly_reports",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── รายละเอียด
    @classmethod
    async def get_monthly_report(
        cls,
        pool: asyncpg.Pool,
        *,
        report_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายงาน 1 ใบ + ลายเซ็น (ใบที่ void แล้ว **อ่านได้เสมอ**)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                row = await cls._fetch_report(conn, target_room_id, int(report_id))
                if row is None:
                    raise RoomNotFoundError("ไม่พบรายงานปิดงบเลขที่นี้")
                signatures = await cls._load_report_signatures(conn, row["id"])

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_MONTHLY_REPORT",
                    entity_id=str(row["id"]), status="success",
                    endpoint_or_command="FinanceService.get_monthly_report",
                    execution_time_ms=exec_time,
                )
                report = _shape_report(row)
                return {
                    "status": "success",
                    "message": (
                        f"{report['report_no']} — {report['status']} · "
                        f"ปิดงบ {report['closing_cash']:,.2f} บาท"
                    ),
                    "report": report,
                    "signatures": signatures,
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(report_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_monthly_report",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── สร้าง (draft)
    @classmethod
    async def create_monthly_report(
        cls,
        pool: asyncpg.Pool,
        *,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """สร้าง RPT ฉบับร่าง — snapshot งวดจาก journal ณ เวลานี้

        🔴 ไม่คำนวณ `counted_cash`/`variance` ที่นี่ (ยังไม่มีใครนับเงิน) — เป็น NULL
           จนกว่าจะ finalize
        🔴 `_lock_room_money` เป็นคำสั่งแรกหลัง RBAC: ถ้าไม่มี หรือวางหลังการอ่าน
           ยอดรวม ชุดตัวเลขกับ snapshot อาจมาจากคนละช่วงเวลาของการรับเงิน
        """
        start_time = time.time()
        target_room_id = room_id
        report_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    year_be = int(req.year_be)
                    month = int(req.month)
                    start_day, end_exclusive, end_inclusive = _month_bounds(year_be, month)

                    active = await conn.fetchval(
                        """SELECT 1 FROM finance_monthly_reports
                            WHERE room_id = $1 AND year_be = $2 AND month = $3
                              AND status IN ('draft', 'final')
                            LIMIT 1""",
                        target_room_id, year_be, month,
                    )
                    if active:
                        raise MonthlyReportConflictError(
                            f"งวด {_THAI_MONTHS_FULL[month - 1]} {year_be} "
                            "มีรายงานปิดงบที่ยังใช้งานอยู่แล้ว — "
                            "ยกเลิกใบเดิมก่อนจึงจะสร้างฉบับใหม่ได้"
                        )

                    start_thai = _thai_day_start(start_day)
                    end_thai = _thai_day_start(end_exclusive)

                    totals = await cls._period_totals(conn, target_room_id, start_thai, end_thai)
                    income_by_category = await cls._category_breakdown(
                        conn, target_room_id, start_thai, end_thai, "revenue"
                    )
                    expense_by_category = await cls._category_breakdown(
                        conn, target_room_id, start_thai, end_thai, "expense"
                    )
                    opening_cash = await cls._opening_cash(
                        conn, target_room_id, year_be, month, start_thai
                    )
                    live_balance = await conn.fetchval(
                        """SELECT COALESCE(SUM(balance), 0) FROM finance_accounts
                            WHERE room_id = $1 AND deleted_at IS NULL""",
                        target_room_id,
                    )
                    live_balance = round(float(live_balance or 0), 2)

                    total_income = totals["income"]
                    total_expense = totals["expense"]
                    closing_cash = round(opening_cash + total_income - total_expense, 2)
                    cash_gap = round(live_balance - closing_cash, 2)

                    version = int(await conn.fetchval(
                        """SELECT COALESCE(MAX(version), 0) + 1 FROM finance_monthly_reports
                            WHERE room_id = $1 AND year_be = $2 AND month = $3""",
                        target_room_id, year_be, month,
                    ))
                    report_no = _report_no_for(year_be, month, version)
                    created_at = await conn.fetchval("SELECT CURRENT_TIMESTAMP")

                    snapshot = {
                        "period": {
                            "year_be": year_be,
                            "month": month,
                            "month_name": _THAI_MONTHS_FULL[month - 1],
                            "start": start_day.isoformat(),
                            "end": end_inclusive.isoformat(),
                        },
                        "income_by_category": income_by_category,
                        "expense_by_category": expense_by_category,
                        "cash": {
                            "opening": opening_cash,
                            "income": total_income,
                            "expense": total_expense,
                            "closing": closing_cash,
                            "live_balance_at_build": live_balance,
                        },
                        "cash_gap": cash_gap,
                        "note": req.note,
                        "meta": {
                            "created_by": user_id,
                            "at": created_at.isoformat(),
                            "source": "journal_lines",
                        },
                    }

                    report_id = await conn.fetchval(
                        """INSERT INTO finance_monthly_reports
                               (room_id, year_be, month, version, report_no, status,
                                snapshot, total_income, total_expense, opening_cash,
                                closing_cash)
                           VALUES ($1, $2, $3, $4, $5, 'draft', $6::jsonb, $7, $8, $9, $10)
                           RETURNING id""",
                        target_room_id, year_be, month, version, report_no,
                        json.dumps(snapshot, ensure_ascii=False),
                        total_income, total_expense, opening_cash, closing_cash,
                    )

                    # ✍️ ช่อง "ผู้จัดทำ" — ผู้อนุมัติ/ผู้ตรวจสอบลงนามบนกระดาษภายหลัง
                    signer_name = await cls._resolve_student_name(conn, user_id) if user_id else "—"
                    await conn.execute(
                        """INSERT INTO finance_document_signatures
                               (room_id, doc_type, doc_id, role, signer_name, sort_order)
                           VALUES ($1, $2, $3, 'prepared', $4, 0)""",
                        target_room_id, DOC_TYPE_MONTHLY_REPORT, report_id, signer_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(report_id),
                        status="success",
                        new_values={
                            "report_no": report_no, "version": version,
                            "total_income": total_income, "total_expense": total_expense,
                            "opening_cash": opening_cash, "closing_cash": closing_cash,
                        },
                        endpoint_or_command="FinanceService.create_monthly_report",
                        execution_time_ms=exec_time,
                    )

                    row = await cls._fetch_report(conn, target_room_id, report_id)
                    return {
                        "status": "success",
                        "message": f"สร้างรายงานปิดงบ {report_no} แล้ว (ฉบับร่าง)",
                        "report": _shape_report(row),
                    }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT",
                        entity_id=str(report_id) if report_id else None,
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_monthly_report",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── finalize
    @classmethod
    async def finalize_monthly_report(
        cls,
        pool: asyncpg.Pool,
        *,
        report_id: int,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ปิดงบ — ต้องนับเงินสดตรงกับ `closing_cash` ภายใน 0.005 บาท

        ❗ ต่างเกิน → `ValueError` ที่บอก **สามตัวเลข** (นับได้/ควรเป็น/ต่าง) → 400
           ไม่ใช่ 409 เพราะเป็นข้อมูลที่แก้ได้ (นับผิด/ลืมรายการ) ไม่ใช่ state ชนกัน
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    row = await cls._fetch_report(
                        conn, target_room_id, int(report_id), for_update=True
                    )
                    if row is None:
                        raise RoomNotFoundError("ไม่พบรายงานปิดงบเลขที่นี้")
                    if row["status"] == "final":
                        raise MonthlyReportConflictError(
                            "รายงานนี้ปิดงบแล้ว — ยกเลิกแล้วสร้างฉบับใหม่ถ้าต้องแก้"
                        )
                    if row["status"] == "voided":
                        raise MonthlyReportConflictError("รายงานนี้ถูกยกเลิกแล้ว")

                    counted = round(float(req.counted_cash), 2)
                    closing = round(float(row["closing_cash"]), 2)
                    variance = round(counted - closing, 2)
                    if abs(variance) >= _VARIANCE_EPSILON:
                        raise ValueError(
                            "ยอดเงินสดนับได้ไม่ตรงกับบัญชี — "
                            f"นับได้ {counted:,.2f} บาท · ควรเป็น {closing:,.2f} บาท · "
                            f"ต่าง {variance:,.2f} บาท"
                        )

                    note = (getattr(req, "note", None) or "").strip() or None
                    await conn.execute(
                        """UPDATE finance_monthly_reports
                              SET counted_cash = $2,
                                  variance = $3,
                                  status = 'final',
                                  finalized_at = CURRENT_TIMESTAMP,
                                  finalized_by = $4,
                                  snapshot = snapshot || jsonb_strip_nulls(
                                      jsonb_build_object('finalize_note', $5::text))
                            WHERE id = $1""",
                        row["id"], counted, variance, user_id, note,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(row["id"]),
                        status="success",
                        old_values={"status": row["status"]},
                        new_values={
                            "status": "final", "counted_cash": counted,
                            "variance": variance, "finalize_note": note,
                        },
                        endpoint_or_command="FinanceService.finalize_monthly_report",
                        execution_time_ms=exec_time,
                    )

                    fresh = await cls._fetch_report(conn, target_room_id, row["id"])
                    return {
                        "status": "success",
                        "message": (
                            f"ปิดงบ {fresh['report_no']} แล้ว — "
                            f"เงินสดนับได้ตรงกับบัญชี ({counted:,.2f} บาท)"
                        ),
                        "report": _shape_report(fresh),
                    }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(report_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.finalize_monthly_report",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── void
    @classmethod
    async def void_monthly_report(
        cls,
        pool: asyncpg.Pool,
        *,
        report_id: int,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิกรายงาน — **ได้เฉพาะใบล่าสุด (version สูงสุด) ของเดือนนั้น**

        🗂️ เก็บ `report_no`/`version`/`snapshot` ไว้ทั้งหมด — เลขไม่ถูกคืน
           (หลักฐานว่าเลขนี้เคยถูกออก และเป็นอะไร)
        🔴 ไม่แตะ journal/`finance_receipts` — RPT ไม่เคยแตะเงิน
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    reason = (getattr(req, "reason", None) or "").strip()
                    if not reason:
                        raise ValueError("กรุณาระบุเหตุผลที่ยกเลิกรายงาน")

                    row = await cls._fetch_report(
                        conn, target_room_id, int(report_id), for_update=True
                    )
                    if row is None:
                        raise RoomNotFoundError("ไม่พบรายงานปิดงบเลขที่นี้")
                    if row["status"] == "voided":
                        raise MonthlyReportConflictError("รายงานนี้ถูกยกเลิกแล้ว")

                    latest_version = await conn.fetchval(
                        """SELECT MAX(version) FROM finance_monthly_reports
                            WHERE room_id = $1 AND year_be = $2 AND month = $3""",
                        target_room_id, row["year_be"], row["month"],
                    )
                    if int(row["version"]) < int(latest_version):
                        raise MonthlyReportConflictError(
                            "ยกเลิกได้เฉพาะรายงานฉบับล่าสุดของเดือนนี้ — "
                            "ยกเลิกฉบับล่าสุดก่อน"
                        )

                    await conn.execute(
                        """UPDATE finance_monthly_reports
                              SET status = 'voided',
                                  voided_at = CURRENT_TIMESTAMP,
                                  void_reason = $2
                            WHERE id = $1""",
                        row["id"], reason,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(row["id"]),
                        status="success",
                        old_values={"status": row["status"]},
                        new_values={"status": "voided", "void_reason": reason},
                        endpoint_or_command="FinanceService.void_monthly_report",
                        execution_time_ms=exec_time,
                    )

                    return {
                        "status": "success",
                        "message": f"ยกเลิกรายงานปิดงบ {row['report_no']} แล้ว",
                    }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(report_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.void_monthly_report",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── PDF
    @classmethod
    async def render_monthly_report_pdf(
        cls,
        pool: asyncpg.Pool,
        *,
        report_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[bytes, str]:
        """PDF ของ RPT → (bytes, filename)

        ⚠️ import `html_to_pdf` **ในฟังก์ชัน** — เทสต์ patch `services.finance.pdf.html_to_pdf`
           ถ้าผูกที่หัวไฟล์ patch จะไม่ถูกเห็น
        """
        from .pdf import html_to_pdf, render_receipt_html

        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                row = await cls._fetch_report(conn, target_room_id, int(report_id))
                if row is None:
                    raise RoomNotFoundError("ไม่พบรายงานปิดงบเลขที่นี้")
                signatures = await cls._load_report_signatures(conn, row["id"])
                room = await conn.fetchrow(
                    "SELECT room_name, room_code FROM rooms WHERE id = $1",
                    target_room_id,
                )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="PRINT", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(row["id"]),
                    status="success",
                    endpoint_or_command="FinanceService.render_monthly_report_pdf",
                    execution_time_ms=exec_time,
                )
            # ⬅️ คืน connection ก่อนเรนเดอร์ (Chromium ใช้เวลาเป็นวินาที)
            html = render_receipt_html(cls._monthly_report_context(row, signatures, room))
            pdf_bytes = await html_to_pdf(html)
            return pdf_bytes, f"monthly-report-{row['report_no']}.pdf"
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="PRINT", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_MONTHLY_REPORT", entity_id=str(report_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.render_monthly_report_pdf",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ═══════════════════════════════════════════════════════════ helpers ภายใน

    @staticmethod
    async def _fetch_report(
        conn: asyncpg.Connection, room_id: int, report_id: int, *, for_update: bool = False
    ):
        """แถวรายงานของห้อง — `for_update` ใช้ในเส้นทางที่เขียน"""
        lock = " FOR UPDATE" if for_update else ""
        return await conn.fetchrow(
            f"""SELECT id, room_id, year_be, month, version, report_no, status,
                       snapshot, total_income, total_expense, opening_cash,
                       closing_cash, counted_cash, variance, finalized_at,
                       finalized_by, voided_at, void_reason, created_at
                  FROM finance_monthly_reports
                 WHERE room_id = $1 AND id = $2{lock}""",
            room_id, int(report_id),
        )

    @staticmethod
    async def _load_report_signatures(conn: asyncpg.Connection, report_id: int) -> list:
        rows = await conn.fetch(
            """SELECT role, person_id, signer_name, signed_at
                 FROM finance_document_signatures
                WHERE doc_type = $1 AND doc_id = $2
                ORDER BY sort_order, id""",
            DOC_TYPE_MONTHLY_REPORT, int(report_id),
        )
        return [
            {
                "role": r["role"],
                "person_id": r["person_id"],
                "signer_name": r["signer_name"],
                "signed_at": r["signed_at"],
            }
            for r in rows
        ]

    @staticmethod
    async def _period_totals(
        conn: asyncpg.Connection, room_id: int, start_thai: datetime, end_thai: datetime
    ) -> dict:
        """รายได้/รายจ่ายของงวดจาก **journal ที่ posted** เท่านั้น

        🚫 ไม่นับ `opening_balance` (ทุน ไม่ใช่รายได้) และไม่นับ draft/voided
        """
        row = await conn.fetchrow(
            """SELECT
                 COALESCE(SUM(CASE WHEN AL.account_type = 'revenue'
                                   THEN L.credit - L.debit ELSE 0 END), 0) AS total_income,
                 COALESCE(SUM(CASE WHEN AL.account_type = 'expense'
                                   THEN L.debit - L.credit ELSE 0 END), 0) AS total_expense
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
              WHERE JE.room_id = $1
                AND JE.deleted_at IS NULL
                AND JE.status = 'posted'
                AND JE.reference_type <> 'opening_balance'
                AND JE.transaction_date >= $2
                AND JE.transaction_date < $3""",
            room_id, start_thai, end_thai,
        )
        return {
            "income": round(float(row["total_income"] or 0), 2),
            "expense": round(float(row["total_expense"] or 0), 2),
        }

    @staticmethod
    async def _category_breakdown(
        conn: asyncpg.Connection, room_id: int, start_thai: datetime,
        end_thai: datetime, account_type: str,
    ) -> list:
        """ยอดแยกรายบัญชี — `account_type` รับแค่ 'revenue'/'expense' (ค่าจากโค้ด ไม่ใช่ client)"""
        if account_type not in ("revenue", "expense"):
            raise ValueError("account_type ต้องเป็น revenue หรือ expense")
        sign = "L.credit - L.debit" if account_type == "revenue" else "L.debit - L.credit"
        rows = await conn.fetch(
            f"""SELECT AL.account_code, AL.account_name, SUM({sign}) AS amount
                  FROM journal_lines L
                  JOIN journal_entries JE ON L.journal_entry_id = JE.id
                  JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                 WHERE JE.room_id = $1
                   AND JE.deleted_at IS NULL
                   AND JE.status = 'posted'
                   AND JE.reference_type <> 'opening_balance'
                   AND JE.transaction_date >= $2
                   AND JE.transaction_date < $3
                   AND AL.account_type = $4
                 GROUP BY AL.account_code, AL.account_name
                 ORDER BY amount DESC, AL.account_name""",
            room_id, start_thai, end_thai, account_type,
        )
        return [
            {
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "amount": round(float(r["amount"] or 0), 2),
            }
            for r in rows
        ]

    @staticmethod
    async def _opening_cash(
        conn: asyncpg.Connection, room_id: int, year_be: int, month: int,
        start_thai: datetime,
    ) -> float:
        """เงินสดยกมา — ใช้ `closing_cash` ของ RPT final ล่าสุดก่อนงวดนี้

        ถ้ายังไม่เคยปิดงบ ⇒ ถอยไปใช้ยอดสุทธิของ ledger **asset ที่ไม่ใช่ลูกหนี้**
        (11001/11002) ก่อนต้นงวด = เงินในกระเป๋า + เงินที่ผู้รับถือ
        """
        previous = await conn.fetchval(
            """SELECT closing_cash FROM finance_monthly_reports
                WHERE room_id = $1 AND status = 'final'
                  AND (year_be < $2 OR (year_be = $2 AND month < $3))
                ORDER BY year_be DESC, month DESC, version DESC
                LIMIT 1""",
            room_id, year_be, month,
        )
        if previous is not None:
            return round(float(previous), 2)

        baseline = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
                 FROM journal_lines L
                 JOIN journal_entries JE ON L.journal_entry_id = JE.id
                 JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                WHERE JE.room_id = $1
                  AND JE.deleted_at IS NULL
                  AND JE.status = 'posted'
                  AND AL.account_type = 'asset'
                  AND COALESCE(AL.account_code, '') NOT IN ('11001', '11002')
                  AND JE.transaction_date < $2""",
            room_id, start_thai,
        )
        return round(float(baseline or 0), 2)

    @classmethod
    def _monthly_report_context(cls, row, signatures: list, room) -> dict:
        """แถวรายงาน → context ของ partial — **ตั้งทุกคีย์เสมอ** (Jinja trap)"""
        report = _shape_report(row)
        snapshot = report["snapshot"]
        period = snapshot.get("period") or {}
        cash = snapshot.get("cash") or {}
        month = int(report["month"])
        year_be = int(report["year_be"])

        by_role = {s["role"]: s["signer_name"] for s in signatures}
        is_voided = report["status"] == "voided"
        finalized_date, finalized_time = _thai_dt_parts(report["finalized_at"])
        return {
            "body_template": MONTHLY_REPORT_BODY_TEMPLATE,
            "doc_type": DOC_TYPE_MONTHLY_REPORT,
            "doc_type_label": "รายงานปิดงบ",
            # 🖨️ หัวเอกสาร A4 อ่านคีย์นี้ (RPT ไม่มี `doc_title` จาก base context)
            "doc_title": "รายงานปิดงบ",
            "document_date_only_text": finalized_date,
            "document_time_text": finalized_time,
            "finalized_date_text": finalized_date,
            "finalized_time_text": finalized_time,
            # 🧾 shell อ่าน `doc_no_text or receipt_no` สำหรับ `<title>`
            "doc_no_text": report["report_no"],
            "receipt_no": report["report_no"],
            "report_no": report["report_no"],
            "year_be": year_be,
            "month": month,
            "month_text": _THAI_MONTHS_FULL[month - 1],
            "period_start": period.get("start"),
            "period_end": period.get("end"),
            "period_start_text": _period_text(period.get("start")),
            "period_end_text": _period_text(period.get("end")),
            "version": report["version"],
            "status": report["status"],
            "status_text": {"draft": "ฉบับร่าง", "final": "ปิดงบแล้ว", "voided": "ยกเลิก"}.get(
                report["status"], report["status"]
            ),
            "is_voided": is_voided,
            "void_reason": report["void_reason"],
            "room_name": (room["room_name"] if room else "—") or "—",
            "room_code": (room["room_code"] if room else None),
            "total_income": report["total_income"],
            "total_expense": report["total_expense"],
            "opening_cash": report["opening_cash"],
            "closing_cash": report["closing_cash"],
            "counted_cash": report["counted_cash"],
            "variance": report["variance"],
            "income_by_category": snapshot.get("income_by_category") or [],
            "expense_by_category": snapshot.get("expense_by_category") or [],
            "cash": {
                "opening": cash.get("opening", report["opening_cash"]),
                "income": cash.get("income", report["total_income"]),
                "expense": cash.get("expense", report["total_expense"]),
                "closing": cash.get("closing", report["closing_cash"]),
            },
            "cash_gap": snapshot.get("cash_gap"),
            "note": snapshot.get("finalize_note") or snapshot.get("note"),
            "finalized_at": report["finalized_at"],
            "prepared_by": by_role.get("prepared"),
            "approved_by": by_role.get("approved"),
            "checked_by": by_role.get("receiver"),
        }
