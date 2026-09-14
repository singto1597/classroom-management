"""งบการเงิน (summary / trial balance / income statement / GL)"""
import asyncpg
import io
import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import (
    THAI_TZ, CUTOFF_DATE, MONEY_NUM_FMT, PCT_NUM_FMT, ACCOUNT_TYPE_LABELS,
    COLLECTION_STATUS_LABELS, REFERENCE_TYPE_LABELS, MANAGEMENT_TAB_COLORS,
    ACCOUNTING_TAB_COLORS, RECONCILE_REFERENCE_TYPE, RECONCILE_EQUITY_CODE,
    RECONCILE_EQUITY_NAME, _CLAMP_START_NOTE, _CLAMP_EMPTY_NOTE,
)
from .helpers import (
    _naive_thai_dt, _clamp_to_cutoff, _ExportPeriodView, _resolve_inclusive_period,
    _legacy_id_from_journal, _thai_day_start, _thai_day_end, _thai_next_day_start,
)
from .base import service_logger


class ReportingMixin:
    @classmethod
    # =====================================================================
    # [ROUTER] get_summary — เลือกอ่านจาก legacy หรือ Double-Entry ตามช่วงเวลา
    # =====================================================================
    @classmethod
    async def get_summary(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        month: Optional[int] = None, year: Optional[int] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                # 💡 month/year ต้องระบุพร้อมกันเสมอ (ไม่งั้น params เลื่อนทำให้ SQL error)
                if (month is None) != (year is None):
                    raise ValueError("ต้องระบุทั้ง month และ year พร้อมกัน หรือไม่ระบุทั้งคู่")

                # [ROUTER] จุดแบ่งเวลา: งวดที่เริ่มหลัง CUTOFF_DATE → ระบบบัญชีคู่
                # (ไม่ระบุงวด = เดือนปัจจุบัน → ขึ้นอยู่กับ wall clock ว่าเลยวันที่ตัดหรือยัง)
                period_start = cls._period_start(month, year, None, None)
                use_v2 = period_start >= CUTOFF_DATE

                if use_v2:
                    return await cls._get_summary_v2(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                return await cls._get_summary_legacy(
                    conn=conn, room_id=target_room_id,
                    month=month, year=year,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _get_summary_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-LEGACY] Logic เดิมของ get_summary — อ่านจาก finance_accounts + finance_transactions."""
        net_worth = await conn.fetchval("SELECT SUM(balance) FROM finance_accounts WHERE room_id = $1", room_id) or 0.0

        # [TIMEZONE] `created_at` เป็น TIMESTAMP (naive) ที่เก็บ **เวลา UTC** ไม่ใช่เวลาไทย
        # ⇒ ต้อง unwrap ฝั่ง param ด้วย `AT TIME ZONE 'UTC'` แล้วเทียบกับขอบเขตเวลาไทย
        # เดิมใช้ `EXTRACT(MONTH/YEAR FROM created_at)` / `CURRENT_DATE` ⇒ ได้ปฏิทิน UTC
        # ⇒ ยอด "เดือนนี้" ของแดชบอร์ดไม่ตรงกับงบกำไรขาดทุน (F1) ที่ใช้เวลาไทย
        # (ดู helpers บล็อก [TIMEZONE])
        if month and year:
            start_d = date(year, month, 1)
            end_d = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            period_str = f"{year}-{month:02d}"
        else:
            today = datetime.now(THAI_TZ).date()
            start_d = date(today.year, today.month, 1)
            end_d = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
            period_str = "current_month"

        params = [room_id, _thai_day_start(start_d), _thai_day_start(end_d)]
        date_cond = (
            "AND created_at >= ($2::timestamptz AT TIME ZONE 'UTC')"
            " AND created_at < ($3::timestamptz AT TIME ZONE 'UTC')"
        )
        date_cond_t = (
            "AND T.created_at >= ($2::timestamptz AT TIME ZONE 'UTC')"
            " AND T.created_at < ($3::timestamptz AT TIME ZONE 'UTC')"
        )

        stats = await conn.fetchrow(f"""
            SELECT
                SUM(CASE WHEN transaction_type = 'income' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_inc,
                SUM(CASE WHEN transaction_type = 'expense' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_exp
            FROM finance_transactions WHERE room_id = $1 AND deleted_at IS NULL {date_cond}
        """, *params)

        breakdown = await conn.fetch(f"""
            SELECT C.category_name, SUM(T.amount) as total_amount
            FROM finance_transactions T
            JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.transaction_type = 'expense' AND T.transfer_group_id IS NULL AND T.deleted_at IS NULL {date_cond_t}
            GROUP BY C.category_name ORDER BY total_amount DESC
        """, *params)

        pending_collection = await conn.fetchval("""
            SELECT SUM(FC.amount - SP.paid_amount) FROM student_payments SP
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE SP.status = 'pending' AND FC.room_id = $1 AND FC.status = 'active'
        """, room_id) or 0.0

        result = {
            "net_worth": float(net_worth), "total_income": float(stats['total_inc'] or 0),
            "total_expense": float(stats['total_exp'] or 0), "pending_collection_amount": float(pending_collection),
            "period": period_str, "expense_breakdown": [dict(b) for b in breakdown]
        }

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="success",
                endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
            )
        return result

    @classmethod
    async def _get_summary_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """สรุปยอดจากระบบบัญชีคู่ (journal_lines) แทนการรวมจาก finance_transactions.

        - Net Worth : SUM(Dr) − SUM(Cr) ของทุก ledger ประเภท 'asset' (ยอดสะสมทั้งหมด)
        - รายได้     : SUM(Cr) − SUM(Dr) ของ 'revenue' ในงวดที่ขอ
        - รายจ่าย   : SUM(Dr) − SUM(Cr) ของ 'expense' ในงวดที่ขอ
        - Expense Breakdown: group ตาม account_name ของ ledger ประเภท 'expense'
        - ยอดยกมา (opening_balance) ไม่ถูกนับเป็นรายได้ของงวด (มันคือทุน ไม่ใช่รายได้)
        """
        if month is not None and year is not None:
            start_d = date(year, month, 1)
            end_d = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            period_str = f"{year}-{month:02d}"
        else:
            today = datetime.now(THAI_TZ).date()
            start_d = date(today.year, today.month, 1)
            end_d = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
            period_str = "current_month"

        # [TIMEZONE] `JE.transaction_date` เป็น timestamptz ⇒ ต้องส่งขอบเขต **tz-aware เวลาไทย**
        # เดิมส่ง `date` เปล่า ๆ ⇒ Postgres cast เป็น timestamptz ที่เที่ยงคืน **UTC** = 07:00 น. ไทย
        # ⇒ ยอดของงวดตกหล่นรายการเช้ามืด (00:00–07:00 ไทย) ของวันแรก และไปกินเช้ามืดของ
        #   วันแรกของเดือนถัดไปแทน — ทำให้ยอด "เดือนนี้" ไม่ตรงกับงบกำไรขาดทุน (F1)
        # end_d คือวันที่ 1 ของเดือนถัดไปอยู่แล้ว จึงใช้ `_thai_day_start` เป็นขอบบนแบบไม่รวม
        start_dt = _thai_day_start(start_d)
        end_dt = _thai_day_start(end_d)

        # [DOUBLE-ENTRY] ยอดสินทรัพย์สะสมทั้งห้อง (ไม่จำกัดงวด) — เทียบเท่า SUM(balance)
        # 💡 นับเฉพาะ journal ที่ไม่ได้ void และไม่ได้ลบ (ลบ legacy ที่ delete ไป)
        net_worth = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = 'asset'
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id,
        ) or 0.0

        # [DOUBLE-ENTRY] ยอดรายได้/รายจ่ายภายในงวด (เฉพาะ journal ที่ไม่ใช่ opening_balance)
        period_stats = await conn.fetchrow(
            """SELECT
                 COALESCE(SUM(CASE WHEN AL.account_type = 'revenue' THEN L.credit - L.debit ELSE 0 END), 0) AS total_inc,
                 COALESCE(SUM(CASE WHEN AL.account_type = 'expense' THEN L.debit - L.credit ELSE 0 END), 0) AS total_exp
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND JE.reference_type <> 'opening_balance'
                 AND JE.transaction_date >= $2 AND JE.transaction_date < $3""",
            room_id, start_dt, end_dt,
        )

        # [DOUBLE-ENTRY] รายจ่ายรายหมวด (จากชื่อ ledger ฝั่ง expense) ภายในงวด
        breakdown_rows = await conn.fetch(
            """SELECT AL.account_name AS category_name, SUM(L.debit - L.credit) AS total_amount
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND JE.reference_type <> 'opening_balance'
                 AND AL.account_type = 'expense'
                 AND JE.transaction_date >= $2 AND JE.transaction_date < $3
               GROUP BY AL.account_name
               ORDER BY total_amount DESC""",
            room_id, start_dt, end_dt,
        )

        pending_collection = await conn.fetchval("""
            SELECT SUM(FC.amount - SP.paid_amount) FROM student_payments SP
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE SP.status = 'pending' AND FC.room_id = $1 AND FC.status = 'active'
        """, room_id) or 0.0

        result = {
            "net_worth": float(net_worth),
            "total_income": float(period_stats["total_inc"] or 0),
            "total_expense": float(period_stats["total_exp"] or 0),
            "pending_collection_amount": float(pending_collection),
            "period": period_str,
            "expense_breakdown": [
                {"category_name": b["category_name"], "total_amount": float(b["total_amount"])}
                for b in breakdown_rows
            ],
        }

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="success",
                endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
            )
        return result

    @classmethod
    async def get_trial_balance(
        cls, pool: asyncpg.Pool, room_id: int,
        client_source: str = "", actor_identifier: str = "",
        user_id: Optional[int] = None, as_of_date: Optional[date] = None, server_id: Optional[int] = None,
    ) -> dict:
        """งบทดลอง: ยอด YTD (Year-to-Date) ของทุก ledger ที่ยัง active ในห้อง.

        กติกาการหักยอดตามประเภทบัญชี (สเปค Phase 4):
        - Assets & Expenses   : Dr − Cr
        - Liabilities, Equity, Revenue : Cr − Dr

        คืน {"ledgers": [...], "total_debit": X, "total_credit": Y, "is_balanced": bool}
        โดย total_debit/total_credit คือผลรวมของยอด Dr/Cr รวม (ไม่ใช่สุทธิ) ของทุก ledger
        → ถ้า journal ทุกรายการสมดุล (Dr = Cr เสมอ) ค่าเท่ากัน และ is_balanced = True
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ ข้อมูลการเงิน → ต้องเป็นสมาชิกห้องเท่านั้น
                await require_member(conn, target_room_id, user_id)

                # [CLAMP] งบทดลองอ่านจาก journal ล้วน (ไม่มี ledger ของยุค Single-Entry)
                # → ถ้า as_of_date อยู่ก่อนวันที่ตัด กลับค่าว่าง + note (ไม่มีข้อมูลให้สรุป)
                if as_of_date is not None and as_of_date < CUTOFF_DATE:
                    return {
                        "ledgers": [],
                        "total_debit": 0.0,
                        "total_credit": 0.0,
                        "is_balanced": True,
                        "note": _CLAMP_EMPTY_NOTE,
                    }

                # [DOUBLE-ENTRY] ขอบเขตเวลา: ถึง as_of_date (ถ้าไม่ระบุ = ทั้งหมดจนถึงตอนนี้)
                # [TIMEZONE] ขอบบนแบบไม่รวม (ต้นวันถัดไปตามเวลาไทย) — ห้ามใช้ naive datetime
                # ไม่งั้นจะกินข้อมูลเข้าไปถึงเช้าวันถัดไป (ดูคำอธิบายใน helpers._thai_day_start)
                if as_of_date is not None:
                    date_filter = "AND JE.transaction_date < $2"
                    params = [target_room_id, _thai_next_day_start(as_of_date)]
                else:
                    date_filter = ""
                    params = [target_room_id]

                # [DOUBLE-ENTRY] รวม Dr/Cr ของทุก ledger ที่ active ยังไม่ void
                rows = await conn.fetch(
                    f"""SELECT
                            AL.id AS ledger_id,
                            AL.account_code,
                            AL.account_name,
                            AL.account_type,
                            COALESCE(NET.total_debit, 0)  AS total_debit,
                            COALESCE(NET.total_credit, 0) AS total_credit
                        FROM accounting_ledgers AL
                        LEFT JOIN (
                            SELECT L.ledger_id,
                                   SUM(L.debit)  AS total_debit,
                                   SUM(L.credit) AS total_credit
                            FROM journal_lines L
                            JOIN journal_entries JE ON L.journal_entry_id = JE.id
                            WHERE JE.deleted_at IS NULL
                              AND JE.status <> 'voided'
                              {date_filter}
                            GROUP BY L.ledger_id
                        ) NET ON NET.ledger_id = AL.id
                        WHERE AL.room_id = $1 AND AL.is_active = TRUE
                        ORDER BY AL.account_code NULLS LAST, AL.id""",
                    *params,
                )

                ledgers: List[dict] = []
                grand_debit = 0.0
                grand_credit = 0.0
                for r in rows:
                    dr = float(r["total_debit"])
                    cr = float(r["total_credit"])
                    # [DOUBLE-ENTRY] ตามสมการปกติของงบทดลอง
                    if r["account_type"] in ("asset", "expense"):
                        balance = dr - cr
                    else:  # liability / equity / revenue
                        balance = cr - dr
                    grand_debit += dr
                    grand_credit += cr
                    ledgers.append({
                        "ledger_id": r["ledger_id"],
                        "account_code": r["account_code"],
                        "account_name": r["account_name"],
                        "account_type": r["account_type"],
                        "total_debit": dr,
                        "total_credit": cr,
                        "balance": balance,
                    })

                result = {
                    "ledgers": ledgers,
                    "total_debit": grand_debit,
                    "total_credit": grand_credit,
                    "is_balanced": abs(grand_debit - grand_credit) < 0.01,  # เผื่อ floating noise
                }

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="TRIAL_BALANCE", status="success",
                    endpoint_or_command="FinanceService.get_trial_balance", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="TRIAL_BALANCE", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_trial_balance", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_income_statement(
        cls, pool: asyncpg.Pool, room_id: int, start_date: date, end_date: date,
        client_source: str = "", actor_identifier: str = "",
        user_id: Optional[int] = None, server_id: Optional[int] = None,
    ) -> dict:
        """งบกำไรขาดทุน: รวมรายได้/ค่าใช้จ่ายภายในช่วงเวลาที่กำหนด.

        - revenues: group ตามชื่อ ledger ประเภท 'revenue' (SUM(credit − debit))
        - expenses: group ตามชื่อ ledger ประเภท 'expense' (SUM(debit − credit))
        - net_income = Total Revenue − Total Expense
        - ไม่นับยอดยกมา (opening_balance) เพราะมันคือทุน ไม่ใช่รายได้ของงวด
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if start_date > end_date:
                    raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")

                # [CLAMP] งบกำไรขาดทุนอ่านจาก journal ล้วน (ข้อมูลก่อนวันที่ตัดไม่อยู่ในนี้)
                query_start, _, clamped, empty = _clamp_to_cutoff(start_date, end_date)
                if empty:
                    return {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "revenues": [],
                        "expenses": [],
                        "total_revenue": 0.0,
                        "total_expense": 0.0,
                        "net_income": 0.0,
                        "note": _CLAMP_EMPTY_NOTE,
                    }

                # [DOUBLE-ENTRY] ขอบเขตปลาย → คร่อมทั้งวันของ end_date (end ยังเป็นค่าเดิม)
                # [TIMEZONE] ต้องเป็น tz-aware เวลาไทย **ทั้งสองข้าง** ไม่ใช่ naive
                # `query_start` ออกมาจาก `_clamp_to_cutoff` เป็น `date` เปล่า ๆ — ถ้าส่งเข้า
                # `JE.transaction_date >= $2` ตรง ๆ Postgres จะ cast เป็น timestamptz ที่
                # เที่ยงคืน **UTC** (= 07:00 น. ไทย) ⇒ งวดตกหล่นรายการเช้ามืดของวันแรก
                end_bound = _thai_day_end(end_date)
                query_start = _thai_day_start(query_start) if query_start is not None else None

                rev_rows = await conn.fetch(
                    """SELECT AL.account_name,
                              COALESCE(SUM(L.credit - L.debit), 0) AS total
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                       WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                         AND JE.reference_type <> 'opening_balance'
                         AND AL.account_type = 'revenue'
                         AND JE.transaction_date >= $2 AND JE.transaction_date <= $3
                       GROUP BY AL.account_name
                       ORDER BY total DESC""",
                    target_room_id, query_start, end_bound,
                )

                exp_rows = await conn.fetch(
                    """SELECT AL.account_name,
                              COALESCE(SUM(L.debit - L.credit), 0) AS total
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                       WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                         AND JE.reference_type <> 'opening_balance'
                         AND AL.account_type = 'expense'
                         AND JE.transaction_date >= $2 AND JE.transaction_date <= $3
                       GROUP BY AL.account_name
                       ORDER BY total DESC""",
                    target_room_id, query_start, end_bound,
                )

                revenues = [
                    {"account_name": r["account_name"], "amount": float(r["total"])} for r in rev_rows
                ]
                expenses = [
                    {"account_name": r["account_name"], "amount": float(r["total"])} for r in exp_rows
                ]
                total_revenue = sum(r["amount"] for r in revenues)
                total_expense = sum(r["amount"] for r in expenses)

                result = {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "revenues": revenues,
                    "expenses": expenses,
                    "total_revenue": total_revenue,
                    "total_expense": total_expense,
                    "net_income": total_revenue - total_expense,
                }

                # [CLAMP] ถ้าช่วงที่ขอเริ่มก่อน 1 ก.ย. แล้วถูกดันมา → แจ้งในผลลัพธ์
                if clamped:
                    result["note"] = _CLAMP_START_NOTE

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="INCOME_STATEMENT", status="success",
                    endpoint_or_command="FinanceService.get_income_statement", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="INCOME_STATEMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_income_statement", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_balance_sheet(
        cls, pool: asyncpg.Pool, room_id: int,
        client_source: str = "", actor_identifier: str = "",
        user_id: Optional[int] = None, as_of_date: Optional[date] = None, server_id: Optional[int] = None,
    ) -> dict:
        """งบแสดงฐานะการเงิน (Balance Sheet) ณ วันที่ — journal-native.

        สมการที่ต้องเป็นจริง: สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม

        [CLAMP] งบดุลอ่านจาก journal ล้วน (ไม่มี ledger ของยุค Single-Entry)
        → ถ้า as_of_date อยู่ก่อนวันที่ตัด กลับค่าว่าง + note **เหมือน get_trial_balance เป๊ะ**
        ⚠️ เป็นกฎ "ตรงข้าม" กับ F2 (งบประมาณ) ที่อ่าน finance_transactions และ **ห้าม clamp**
           — ห้าม refactor ให้สองที่ใช้ helper ร่วมกัน (era assumption คนละอัน)

        เรียก `_fetch_trial_balance_ledgers` / `_fetch_income_statement_rows` ที่มีอยู่แล้ว
        **ไม่เขียน query งบทดลองใหม่** และ **ห้าม await `_compose_balance_sheet`** (เป็น sync)
        """
        start_time = time.time()
        target_room_id = room_id

        # [DOUBLE-ENTRY] ขอบเขตวันที่ — คำนวณก่อน branch การ clamp เพื่อให้ทั้งสองเส้นทาง
        # รายงาน period เดียวกัน (ไม่งั้น period_net_income ในเส้นทางว่างจะไร้ที่มา)
        as_of = as_of_date if as_of_date is not None else datetime.now(THAI_TZ).date()
        as_of_str = cls._fmt_date(as_of)
        # [สำคัญ] pl_start_date ใช้กับ `period_net_income` (memo ของ "งวดที่ขอ") เท่านั้น
        #   ⚠️ `retained_earnings` ในงบดุล **ไม่ได้** มาจากค่านี้ — มันคือ Σ(revenue − expense)
        #      ของ *ทุกงวด* ที่ `_fetch_trial_balance_ledgers` คืนมา (ทั้งหมด ≤ as_of)
        #   ⇒ ถ้ามีใครแก้โค้ดให้ retained_earnings ใช้ pl_start_date ตามคอมเมนต์นี้
        #     ยอดสองข้างของสมการจะไม่เท่ากันอีกต่อไป (is_balanced = False ถาวร)
        pl_start_date = max(CUTOFF_DATE, date(as_of.year, 1, 1))
        period_start = pl_start_date.isoformat()
        period_end = as_of.isoformat()

        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ ข้อมูลการเงิน → ต้องเป็นสมาชิกห้องเท่านั้น (อ่านอย่างเดียว, transparency)
                await require_member(conn, target_room_id, user_id)

                # [CLAMP] เหมือน get_trial_balance — ก่อนวันที่ตัดไม่มีการเคลื่อนไหวในบัญชีคู่
                if as_of_date is not None and as_of_date < CUTOFF_DATE:
                    # ⚠️ ในเส้นทางนี้ "ไม่มีงวด" จริง ๆ (ไม่มีข้อมูลให้สรุป) จึงคืน
                    #    period_start = period_end = as_of แทนค่าที่คำนวณจาก CUTOFF_DATE
                    #    เพราะค่านั้นจะกลายเป็น period_start (2026-09-01) > period_end (2026-08-31)
                    #    ซึ่งเป็น payload ที่ขัดแย้งกันเอง → UI จะแสดงช่วงวันที่ย้อนกลับ
                    #    ความจริงว่า "ทำไมว่าง" สื่อผ่าน `note` อยู่แล้ว
                    return {
                        "as_of": as_of_str,
                        "assets": [],
                        "assets_total": 0.0,
                        "liabilities": [],
                        "liability_total": 0.0,
                        "equities": [],
                        "equity_total": 0.0,
                        "retained_earnings": 0.0,
                        "total_equity_side": 0.0,
                        "total_liabilities_and_equity": 0.0,
                        "is_balanced": True,
                        "period_net_income": 0.0,
                        "period_start": period_end,
                        "period_end": period_end,
                        "note": _CLAMP_EMPTY_NOTE,
                    }

                # ใช้ขอบบนเป็น "สิ้นวัน" ให้ตรงกับ `_fetch_trial_balance_ledgers`
                # ที่เทียบด้วย `<=` — รายการวันที่เท่า as_of ต้องถูกนับ
                # [TIMEZONE] tz-aware เวลาไทยทั้งคู่ (ดู helpers._thai_day_end / _thai_day_start)
                as_of_dt = _thai_day_end(as_of)
                pl_start_dt = _thai_day_start(pl_start_date)

                tb = await cls._fetch_trial_balance_ledgers(
                    conn, room_id=target_room_id, as_of_dt=as_of_dt,
                )
                pl = await cls._fetch_income_statement_rows(
                    conn, room_id=target_room_id, start_dt=pl_start_dt, end_dt=as_of_dt,
                )

                # ⚠️ sync @classmethod — ห้าม await (ถ้า await จะได้
                #    TypeError: object dict can't be used in 'await' expression)
                result = cls._compose_balance_sheet(tb, pl["net_income"], as_of_str)
                result["period_start"] = period_start
                result["period_end"] = period_end

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="BALANCE_SHEET", status="success",
                    endpoint_or_command="FinanceService.get_balance_sheet", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="BALANCE_SHEET", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_balance_sheet", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _fetch_general_ledger(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None,
    ) -> List[dict]:
        """สมุดบัญชีแยกประเภท (GL): ต่อ ledger → ยอดยกมา / เดบิต-เครดิตในงวด / ยอดยกไป.

        - opening (ก่อน start_dt) = เคลื่อนไหวสะสมก่อนงวด (ถ้าไม่ระบุ start = ว่าง)
        - period  (ใน [start_dt, end_dt]) = เคลื่อนไหวของงวด
        - closing (ยอดยกไป) = opening + period (คำนวณฝั่ง Python, ตาม normal side)
        ไม่นับ journal ที่ void / soft-delete (เงื่อนไขเดียวกับ reconcile/balance)
        """
        rows = await conn.fetch(
            """SELECT AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                      COALESCE(OP.op_dr, 0)  AS op_dr,
                      COALESCE(OP.op_cr, 0)  AS op_cr,
                      COALESCE(PER.per_dr, 0) AS per_dr,
                      COALESCE(PER.per_cr, 0) AS per_cr
               FROM accounting_ledgers AL
               LEFT JOIN (
                   SELECT L.ledger_id,
                          SUM(L.debit)  AS op_dr,
                          SUM(L.credit) AS op_cr
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   WHERE JE.deleted_at IS NULL AND JE.status <> 'voided'
                     AND ($2::timestamptz IS NOT NULL AND JE.transaction_date < $2)
                   GROUP BY L.ledger_id
               ) OP ON OP.ledger_id = AL.id
               LEFT JOIN (
                   SELECT L.ledger_id,
                          SUM(L.debit)  AS per_dr,
                          SUM(L.credit) AS per_cr
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   WHERE JE.deleted_at IS NULL AND JE.status <> 'voided'
                     AND ($2::timestamptz IS NULL OR JE.transaction_date >= $2)
                     AND ($3::timestamptz IS NULL OR JE.transaction_date <= $3)
                   GROUP BY L.ledger_id
               ) PER ON PER.ledger_id = AL.id
               WHERE AL.room_id = $1 AND AL.is_active = TRUE
               ORDER BY AL.account_code NULLS LAST, AL.id""",
            room_id, start_dt, end_dt,
        )

        result: List[dict] = []
        for r in rows:
            op_dr = float(r["op_dr"])
            op_cr = float(r["op_cr"])
            per_dr = float(r["per_dr"])
            per_cr = float(r["per_cr"])
            typ = r["account_type"]
            signed = lambda dr, cr: (dr - cr) if typ in ("asset", "expense") else (cr - dr)  # noqa: E731
            result.append({
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "account_type": typ,
                "opening_balance": round(signed(op_dr, op_cr), 2),
                "period_debit": round(per_dr, 2),
                "period_credit": round(per_cr, 2),
                "closing_balance": round(signed(op_dr + per_dr, op_cr + per_cr), 2),
            })
        return result

    @classmethod
    async def _fetch_trial_balance_ledgers(
        cls, conn: asyncpg.Connection, *, room_id: int, as_of_dt: Optional[datetime] = None,
    ) -> dict:
        """งบทดลอง: ยอด YTD (≤ as_of_dt) ของทุก ledger active. เลียนแบบ get_trial_balance.

        คืน {"ledgers": [...], "total_debit", "total_credit", "is_balanced"}
        ใช้สร้าง Sheet งบทดลอง + ต่อยอด Balance Sheet (สินทรัพย์/ทุน/กำไรสะสม)
        """
        if as_of_dt is not None:
            date_filter = "AND JE.transaction_date <= $2"
            params: List[Any] = [room_id, as_of_dt]
        else:
            date_filter = ""
            params = [room_id]

        rows = await conn.fetch(
            f"""SELECT AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                       COALESCE(NET.total_debit, 0)  AS total_debit,
                       COALESCE(NET.total_credit, 0) AS total_credit
                FROM accounting_ledgers AL
                LEFT JOIN (
                    SELECT L.ledger_id,
                           SUM(L.debit)  AS total_debit,
                           SUM(L.credit) AS total_credit
                    FROM journal_lines L
                    JOIN journal_entries JE ON L.journal_entry_id = JE.id
                    WHERE JE.deleted_at IS NULL
                      AND JE.status <> 'voided'
                      {date_filter}
                    GROUP BY L.ledger_id
                ) NET ON NET.ledger_id = AL.id
                WHERE AL.room_id = $1 AND AL.is_active = TRUE
                ORDER BY AL.account_code NULLS LAST, AL.id""",
            *params,
        )

        ledgers: List[dict] = []
        grand_debit = grand_credit = 0.0
        for r in rows:
            dr = float(r["total_debit"])
            cr = float(r["total_credit"])
            balance = (dr - cr) if r["account_type"] in ("asset", "expense") else (cr - dr)
            grand_debit += dr
            grand_credit += cr
            ledgers.append({
                "ledger_id": r["ledger_id"],
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "account_type": r["account_type"],
                "total_debit": round(dr, 2),
                "total_credit": round(cr, 2),
                "balance": round(balance, 2),
            })
        return {
            "ledgers": ledgers,
            "total_debit": round(grand_debit, 2),
            "total_credit": round(grand_credit, 2),
            "is_balanced": abs(grand_debit - grand_credit) < 0.01,
        }

    @classmethod
    async def _fetch_income_statement_rows(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None,
    ) -> dict:
        """งบกำไรขาดทุนของงวด [start_dt, end_dt] — เลียนแบบ get_income_statement.

        ไม่นับ opening_balance (คือทุน ไม่ใช่รายได้ของงวด). คืน revenues/expenses/totals/net.
        """
        def _fetch_rows(account_type: str):
            # revenue: กำไรฝั่ง Cr−Dr / expense: ค่าใช้จ่ายฝั่ง Dr−Cr
            diff_expr = "(L.credit - L.debit)" if account_type == "revenue" else "(L.debit - L.credit)"
            return conn.fetch(
                f"""SELECT AL.account_name,
                          COALESCE(SUM({diff_expr}), 0) AS total
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                   WHERE JE.room_id = $1 AND JE.deleted_at IS NULL
                     AND JE.status <> 'voided'
                     AND JE.reference_type <> 'opening_balance'
                     AND AL.account_type = $4
                     AND ($2::timestamptz IS NULL OR JE.transaction_date >= $2)
                     AND ($3::timestamptz IS NULL OR JE.transaction_date <= $3)
                   GROUP BY AL.account_name
                   ORDER BY total DESC""",
                room_id, start_dt, end_dt, account_type,
            )

        rev_rows = await _fetch_rows("revenue")
        exp_rows = await _fetch_rows("expense")

        revenues = [{"account_name": r["account_name"], "amount": float(r["total"])} for r in rev_rows]
        expenses = [{"account_name": r["account_name"], "amount": float(r["total"])} for r in exp_rows]
        total_revenue = sum(x["amount"] for x in revenues)
        total_expense = sum(x["amount"] for x in expenses)
        net_income = total_revenue - total_expense
        return {
            "revenues": revenues,
            "expenses": expenses,
            "total_revenue": round(total_revenue, 2),
            "total_expense": round(total_expense, 2),
            "net_income": round(net_income, 2),
            "margin_pct": round(net_income / total_revenue * 100.0, 2) if total_revenue else None,
        }

    @classmethod
    def _compose_balance_sheet(cls, tb: dict, period_net_income: float, as_of_str: str) -> dict:
        """สร้างโครงงบแสดงฐานะการเงินจากงบทดลอง (YTD ≤ as_of).

        สมการที่พิสูจน์: สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสมถึงวันที่
        โดยกำไรสะสม = Σ(revenue) − Σ(expense) สะสมนับจากเริ่มบัญชีคู่ (2026-09-01).
        period_net_income = กำไร/ขาดทุนสุทธิของ *งวดที่ขอ* (จากงบกำไรขาดทุน) — เก็บไว้เป็น memo
        เพื่อให้ผู้ตรวจเทียบ งบกำไรขาดทุน ↔ งบดุล ได้ชัดเจน

        หมายเหตุ sign: `balance` ที่ได้จาก `_fetch_trial_balance_ledgers` เป็น
        `Dr − Cr` สำหรับ asset/expense และ `Cr − Dr` สำหรับ liability/equity/revenue
        → ยอดหนี้สินมาเป็นบวกอยู่แล้ว **ห้ามกลับเครื่องหมายซ้ำ**
        """
        assets: List[dict] = []
        liabilities: List[dict] = []
        equities: List[dict] = []
        retained = 0.0
        assets_total = liability_total = equity_total = 0.0

        for lg in tb["ledgers"]:
            typ = lg["account_type"]
            if typ == "asset":
                assets.append(lg)
                assets_total += lg["balance"]
            elif typ == "liability":
                liabilities.append(lg)
                liability_total += lg["balance"]   # liability balance = Cr−Dr (หนี้สินเป็นบวก)
            elif typ == "equity":
                equities.append(lg)
                equity_total += lg["balance"]
            elif typ == "revenue":
                retained += lg["balance"]      # revenue balance = Cr−Dr (กำไร)
            elif typ == "expense":
                retained -= lg["balance"]      # expense balance = Dr−Cr → ลบออกจากกำไร
            else:
                # [สำคัญ] account_type ที่ไม่รู้จักจะถูก "ตัดออกจากทุกฝ่าย" โดยเจตนา
                #   ตาราง accounting_ledgers ไม่มี CHECK constraint บน account_type (มีแค่คอมเมนต์)
                #   → พิมพ์ผิด ('Asset') หรือเพิ่มประเภทใหม่ในอนาคตจะมาถึงตรงนี้
                #   ผลที่ตั้งใจ: ยอดสองข้างของสมการไม่เท่ากัน → is_balanced = False
                #   ⇒ ผู้ใช้เห็นสัญญาณเตือนบนเอกสารทันที (ดีกว่าเงียบ ๆ ไปรวมเป็นค่าใช้จ่าย
                #     แล้วได้ is_balanced = True ทั้งที่เงินถูกจัดประเภทผิด)
                pass

        retained = round(retained, 2)
        assets_total = round(assets_total, 2)
        liability_total = round(liability_total, 2)
        equity_total = round(equity_total, 2)
        total_equity_side = round(equity_total + retained, 2)
        total_liabilities_and_equity = round(liability_total + total_equity_side, 2)

        return {
            "as_of": as_of_str,
            "assets": assets,
            "assets_total": assets_total,
            "liabilities": liabilities,
            "liability_total": liability_total,
            "equities": equities,
            "equity_total": equity_total,
            "retained_earnings": retained,
            "total_equity_side": total_equity_side,
            "total_liabilities_and_equity": total_liabilities_and_equity,
            # ⚠️ ต้องเทียบกับ total_liabilities_and_equity (ไม่ใช่ total_equity_side)
            #    ไม่งั้นพอนักบัญชีสร้าง liability ledger ตัวแรก is_balanced จะเป็น False
            #    ตลอดกาล กลายเป็นสัญญาณเตือนเท็จบนเอกสารที่พิมพ์ออกมา
            "is_balanced": abs(assets_total - total_liabilities_and_equity) < 0.01,
            "period_net_income": round(period_net_income, 2),
        }
