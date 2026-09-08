"""Excel export (transactions + journal) + workbook builders"""
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
    _legacy_id_from_journal,
)
from .base import service_logger
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


class ExportMixin:
    @classmethod
    async def _fetch_collection_register(cls, conn: asyncpg.Connection, room_id: int) -> dict:
        """โปรเจคเก็บเงิน (fee_collections) แบบ Real-time + ยอดรวมอัตราการเก็บ."""
        as_of = datetime.now(THAI_TZ).date()
        rows = await conn.fetch(
            """SELECT FC.id, FC.title, FC.amount, FC.due_date, FC.status,
                      COUNT(SP.id)                    AS member_count,
                      COALESCE(SUM(SP.paid_amount), 0) AS paid_total
               FROM fee_collections FC
               LEFT JOIN student_payments SP
                      ON SP.collection_id = FC.id AND SP.deleted_at IS NULL
               WHERE FC.room_id = $1 AND FC.deleted_at IS NULL
               GROUP BY FC.id, FC.title, FC.amount, FC.due_date, FC.status
               ORDER BY FC.due_date NULLS LAST, FC.id ASC""",
            room_id,
        )

        projects: List[dict] = []
        total_expected = total_paid = total_pending = 0.0
        active_count = 0
        for r in rows:
            member_count = int(r["member_count"] or 0)
            fee_amount = float(r["amount"] or 0.0)
            paid = float(r["paid_total"] or 0.0)
            expected = round(fee_amount * member_count, 2)
            pending = round(max(expected - paid, 0.0), 2)
            completion_pct = round(paid / expected * 100.0, 2) if expected > 0 else 0.0
            is_active = (r["status"] or "active") == "active"
            if is_active:
                active_count += 1
            if expected > 0:
                total_expected += expected
                total_paid += paid
                total_pending += pending
            projects.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"] or "active",
                "due_date": r["due_date"],
                "fee_amount": fee_amount,
                "member_count": member_count,
                "expected": expected,
                "paid": paid,
                "pending": pending,
                "completion_pct": completion_pct,
                "is_active": is_active,
            })

        return {
            "as_of": as_of,
            "projects": projects,
            "project_count": len(projects),
            "active_count": active_count,
            "total_expected": round(total_expected, 2),
            "total_paid": round(total_paid, 2),
            "total_pending": round(total_pending, 2),
            "collection_rate_pct": round(total_paid / total_expected * 100.0, 2) if total_expected > 0 else None,
        }

    @classmethod
    async def _fetch_accounts_receivable(cls, conn: asyncpg.Connection, room_id: int) -> dict:
        """ทะเบียนลูกหนี้แบบ Real-time: student_payments.status='pending' (ยังไม่จ่ายครบ)."""
        as_of = datetime.now(THAI_TZ).date()
        rows = await conn.fetch(
            """SELECT S.id                                 AS student_id,
                      S.student_no, S.student_id            AS student_id_no,
                      U.first_name, U.last_name, U.nickname,
                      U.first_name_en, U.last_name_en, U.nickname_en,
                      FC.id          AS collection_id,
                      FC.title, FC.amount, FC.due_date, FC.status,
                      SP.id AS payment_id, SP.paid_amount,
                      (FC.amount - COALESCE(SP.paid_amount, 0)) AS outstanding
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               JOIN students S         ON SP.student_id = S.id
               LEFT JOIN users U       ON S.user_id = U.id
               WHERE SP.deleted_at IS NULL
                 AND SP.status = 'pending'
                 AND FC.deleted_at IS NULL
                 AND FC.room_id = $1
               ORDER BY S.student_no ASC, FC.due_date ASC NULLS LAST, FC.id ASC""",
            room_id,
        )

        entries: List[dict] = []
        seen_students: set = set()
        total_outstanding = 0.0
        for r in rows:
            first = (r["first_name"] or r.get("first_name_en") or "").strip()
            last = (r["last_name"] or r.get("last_name_en") or "").strip()
            name = " ".join(p for p in (first, last) if p) or "Unknown"
            nickname = r["nickname"] or r.get("nickname_en") or ""
            if nickname:
                name += f" ({nickname})"
            outstanding = round(float(r["outstanding"] or 0.0), 2)
            seen_students.add(r["student_id"])
            total_outstanding += outstanding
            entries.append({
                "student_id": r["student_id"],
                "student_no": r["student_no"],
                "student_id_no": r["student_id_no"],
                "name": name,
                "nickname": nickname,
                "collection_id": r["collection_id"],
                "title": r["title"],
                "fee_amount": round(float(r["amount"] or 0.0), 2),
                "paid_amount": round(float(r["paid_amount"] or 0.0), 2),
                "outstanding": outstanding,
                "due_date": r["due_date"],
                "collection_status": r["status"] or "active",
            })

        return {
            "as_of": as_of,
            "rows": entries,
            "debtor_count": len(seen_students),
            "total_outstanding": round(total_outstanding, 2),
        }

    @classmethod
    async def export_transactions_excel(
        cls, pool: asyncpg.Pool, req, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> io.BytesIO:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                collection_register = await cls._fetch_collection_register(conn, target_room_id)
                accounts_receivable = await cls._fetch_accounts_receivable(conn, target_room_id)

                month = getattr(req, "month", None)
                year = getattr(req, "year", None)
                start_date = getattr(req, "start_date", None)
                end_date = getattr(req, "end_date", None)

                if month is not None and year is not None:
                    if date(year, month, 1) >= CUTOFF_DATE:
                        return await cls._export_transactions_excel_v2(
                            conn=conn, room_id=target_room_id,
                            month=month, year=year, start_date=start_date, end_date=end_date,
                            client_source=client_source, actor_identifier=actor_identifier,
                            start_time=start_time,
                            reg=collection_register, ar=accounts_receivable,
                        )
                    return await cls._export_transactions_excel_legacy(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )

                if end_date is not None and end_date < CUTOFF_DATE:
                    return await cls._export_transactions_excel_legacy(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )
                if start_date is not None and start_date >= CUTOFF_DATE:
                    return await cls._export_transactions_excel_v2(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )
                return await cls._export_transactions_excel_merged(
                    conn=conn, room_id=target_room_id,
                    month=month, year=year, start_date=start_date, end_date=end_date,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                    reg=collection_register, ar=accounts_receivable,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _export_transactions_excel_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        where_clause, period_params, period_label = cls._resolve_export_period(
            _ExportPeriodView(month=month, year=year, start_date=start_date, end_date=end_date)
        )

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        rows = await conn.fetch(
            f"""
            SELECT
                T.id, T.transaction_type, T.amount, T.description, T.recorded_by,
                T.created_at, T.transfer_group_id, T.student_payment_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.deleted_at IS NULL {where_clause}
            ORDER BY T.created_at ASC, T.id ASC
            """,
            room_id, *period_params,
        )

        account_balances = await conn.fetch(
            "SELECT account_name, balance FROM finance_accounts WHERE room_id = $1 AND deleted_at IS NULL ORDER BY id",
            room_id,
        )

        final_rows = cls._consolidate_transfers([dict(r) for r in rows])
        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows, account_balances=[(r["account_name"], r["balance"]) for r in account_balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    @classmethod
    async def _export_transactions_excel_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        if month is not None and year is not None:
            period_label = f"{year}-{month:02d}"
            start_dt = date(year, month, 1)
            end_dt = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        elif start_date is not None or end_date is not None:
            if start_date and end_date and start_date > end_date:
                raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
            if start_date and end_date:
                period_label = f"{start_date.isoformat()} ถึง {end_date.isoformat()}"
            elif start_date:
                period_label = f"ตั้งแต่วันที่ {start_date.isoformat()}"
            else:
                period_label = f"จนถึงวันที่ {end_date.isoformat()}"
            start_dt = start_date or date.min
            end_dt = end_date or date.max
        else:
            period_label = "ทั้งหมด"
            start_dt, end_dt = None, None

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        txn_result = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=100000, offset=0,
            start_date=start_dt, end_date=end_dt,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None, 
        )
        raw_items = txn_result["items"]

        final_rows = cls._format_v2_rows(raw_items)
        final_rows.sort(key=lambda x: (x["created_at"] or datetime.min, x["id"] or ""))

        balances = await conn.fetch(
            """SELECT AL.account_name,
                      (SELECT COALESCE(SUM(L.debit - L.credit), 0)
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       WHERE L.ledger_id = AL.id
                         AND JE.deleted_at IS NULL
                         AND JE.status <> 'voided') AS net_balance
               FROM accounting_ledgers AL
               WHERE AL.room_id = $1 AND AL.account_type = 'asset' AND AL.is_active = TRUE
               ORDER BY AL.id""",
            room_id,
        )

        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows,
            account_balances=[(r["account_name"], r["net_balance"]) for r in balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    @classmethod
    async def _export_transactions_excel_merged(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        _, _, period_label = _resolve_inclusive_period(month, year, start_date, end_date)

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        legacy_end = CUTOFF_DATE - timedelta(days=1)
        params: List[Any] = [room_id, legacy_end]
        start_cond = ""
        if start_date is not None and start_date < CUTOFF_DATE:
            start_cond = " AND DATE(T.created_at) >= $3"
            params.append(start_date)
        legacy_rows = await conn.fetch(
            f"""
            SELECT
                T.id, T.transaction_type, T.amount, T.description, T.recorded_by,
                T.created_at, T.transfer_group_id, T.student_payment_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.deleted_at IS NULL
              AND DATE(T.created_at) <= $2 {start_cond}
            ORDER BY T.created_at ASC, T.id ASC
            """,
            *params,
        )
        final_legacy = cls._consolidate_transfers([dict(r) for r in legacy_rows])

        journal_start = start_date if (start_date is not None and start_date >= CUTOFF_DATE) else CUTOFF_DATE
        txn_result = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=100000, offset=0,
            start_date=journal_start, end_date=end_date,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None, 
        )
        final_v2 = cls._format_v2_rows(txn_result["items"])

        final_rows = final_legacy + final_v2
        final_rows.sort(key=lambda x: (_naive_thai_dt(x["created_at"]), x["id"] or ""))

        balances = await conn.fetch(
            """SELECT AL.account_name,
                      (SELECT COALESCE(SUM(L.debit - L.credit), 0)
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       WHERE L.ledger_id = AL.id
                         AND JE.deleted_at IS NULL
                         AND JE.status <> 'voided') AS net_balance
               FROM accounting_ledgers AL
               WHERE AL.room_id = $1 AND AL.account_type = 'asset' AND AL.is_active = TRUE
               ORDER BY AL.id""",
            room_id,
        )

        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows,
            account_balances=[(r["account_name"], r["net_balance"]) for r in balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    @classmethod
    def _format_v2_rows(cls, items: List[dict]) -> List[dict]:
        formatted: List[dict] = []
        for t in items:
            amount = float(t["amount"] or 0.0)
            if t.get("transfer_group_id") is not None:
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "โอนเงินระหว่างบัญชี",
                    "income": 0.0,
                    "expense": amount,
                    "description": t.get("description") or "",
                    "category": "โอนเงิน",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": True,
                })
            elif t["transaction_type"] == "income":
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "รายรับ",
                    "income": amount,
                    "expense": 0.0,
                    "description": t.get("description") or "",
                    "category": t.get("category_name") or "—",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": False,
                })
            else: 
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "รายจ่าย",
                    "income": 0.0,
                    "expense": amount,
                    "description": t.get("description") or "",
                    "category": t.get("category_name") or "—",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": False,
                })
        return formatted

    @staticmethod
    def _resolve_export_period(req) -> tuple:
        month, year = getattr(req, "month", None), getattr(req, "year", None)
        start_date = getattr(req, "start_date", None)
        end_date = getattr(req, "end_date", None)

        if month is not None and year is not None:
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1)
            else:
                end = date(year, month + 1, 1)
            return " AND T.created_at >= $2 AND T.created_at < $3", [start, end], f"{year}-{month:02d}"

        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
            return (
                " AND DATE(T.created_at) >= $2 AND DATE(T.created_at) <= $3",
                [start_date, end_date],
                f"{start_date.isoformat()} ถึง {end_date.isoformat()}",
            )
        if start_date is not None:
            return " AND DATE(T.created_at) >= $2", [start_date], f"ตั้งแต่วันที่ {start_date.isoformat()}"
        if end_date is not None:
            return " AND DATE(T.created_at) <= $2", [end_date], f"จนถึงวันที่ {end_date.isoformat()}"
        return "", [], "ทั้งหมด"

    @staticmethod
    def _clean_transfer_desc(description: Optional[str], transfer_group_id: Optional[int]) -> str:
        if not description:
            return ""
        if transfer_group_id is not None:
            return re.sub(r"^(โอนออก:|รับโอน:)\s*", "", description.strip())
        return description

    @classmethod
    def _consolidate_transfers(cls, rows: List[dict]) -> List[dict]:
        transfer_groups: Dict[int, dict] = {}
        regular_rows: List[dict] = []

        for r in rows:
            group_id = r.get("transfer_group_id")
            if group_id is None:
                regular_rows.append(r)
                continue
            if group_id not in transfer_groups or r["transaction_type"] == "expense":
                transfer_groups[group_id] = r

        final_rows = []
        for r in regular_rows:
            final_rows.append(cls._format_row(r, is_transfer=False))
        for group_id in sorted(transfer_groups.keys()):
            leg = transfer_groups[group_id]
            final_rows.append(cls._format_row(leg, is_transfer=True))
        final_rows.sort(key=lambda x: (x["created_at"], x["id"]))
        return final_rows

    @classmethod
    def _format_row(cls, r: dict, is_transfer: bool) -> dict:
        txn_type = r.get("transaction_type")
        amount = float(r.get("amount") or 0.0)
        account_name = r.get("account_name") or "—"
        category_name = r.get("category_name") or "—"

        if is_transfer:
            return {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "type": "โอนเงินระหว่างบัญชี",
                "income": 0.0,
                "expense": amount,
                "description": cls._clean_transfer_desc(r.get("description"), r.get("transfer_group_id")),
                "category": "โอนเงิน",
                "account": account_name,
                "recorded_by": r.get("recorded_by") or "—",
                "is_transfer": True,
            }

        if txn_type == "income":
            return {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "type": "รายรับ",
                "income": amount,
                "expense": 0.0,
                "description": r.get("description") or "",
                "category": category_name,
                "account": account_name,
                "recorded_by": r.get("recorded_by") or "—",
                "is_transfer": False,
            }
        return {
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "type": "รายจ่าย",
            "income": 0.0,
            "expense": amount,
            "description": r.get("description") or "",
            "category": category_name,
            "account": account_name,
            "recorded_by": r.get("recorded_by") or "—",
            "is_transfer": False,
        }

    @classmethod
    def _build_finance_workbook(
        cls, room_name: str, period_label: str, rows: List[dict],
        account_balances: Optional[List[tuple]] = None, generated_at: datetime = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        if generated_at is None:
            generated_at = datetime.now(THAI_TZ)

        non_transfer_rows = [
            r for r in rows
            if not (r.get("is_transfer") or r.get("type") == "โอนเงินระหว่างบัญชี")
        ]
        income_total = round(sum(r["income"] for r in non_transfer_rows), 2)
        expense_total = round(sum(r["expense"] for r in non_transfer_rows), 2)

        reg = reg or {}
        ar = ar or {}
        fee_projects: List[dict] = reg.get("projects") or []
        ar_rows: List[dict] = ar.get("rows") or []
        pending_by_collection: Dict[int, List[dict]] = {}
        for _ar in ar_rows:
            pending_by_collection.setdefault(_ar["collection_id"], []).append(_ar)
        live_as_of = reg.get("as_of") or ar.get("as_of")
        live_label = live_as_of.strftime("%d/%m/%Y") if live_as_of else "—"

        HEADER_FILL = PatternFill("solid", fgColor="1D4ED8")
        TOTAL_FILL = PatternFill("solid", fgColor="CBD5E1")
        SUBTOTAL_FILL = PatternFill("solid", fgColor="DBEAFE")
        INCOME_FILL = PatternFill("solid", fgColor="D1FAE5")
        EXPENSE_FILL = PatternFill("solid", fgColor="FEE2E2")
        ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
        white_bold = Font(bold=True, color="FFFFFF")
        title_font = Font(bold=True, size=16, color="0F172A")
        money = MONEY_NUM_FMT

        def money_cell(ws, row, col, val):
            cell = ws.cell(row=row, column=col)
            if val is None:
                return cell
            cell.value = float(val)
            cell.number_format = money
            return cell

        def fill_row(ws, row, cols, fill):
            for c in cols:
                ws.cell(row=row, column=c).fill = fill

        wb = Workbook()
        _generated = generated_at.strftime("%d/%m/%Y %H:%M")
        
        def acc_money_cell(ws, row, col, val, bold=False, double_underline=False, single_underline=False):
            cell = ws.cell(row=row, column=col)
            if val is not None:
                cell.value = float(val)
                cell.number_format = '#,##0.00;[Red](#,##0.00);"-"'
            if bold:
                cell.font = Font(bold=True)
            if double_underline:
                cell.border = Border(bottom=Side(style='double'))
            elif single_underline:
                cell.border = Border(bottom=Side(style='thin'))
            return cell

        # =====================================================================
        # Sheet 1: สรุปยอด (Dashboard)
        # =====================================================================
        ws_summary = wb.active
        ws_summary.title = "สรุปยอด"
        ws_summary.sheet_view.showGridLines = False
        ws_summary.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[0]
        ws_summary.column_dimensions["A"].width = 40
        ws_summary.column_dimensions["B"].width = 26

        ws_summary["A1"] = f"สรุปการเงิน — {room_name}"
        ws_summary["A1"].font = title_font
        ws_summary["A2"] = (
            f"รอบระยะเวลา: {period_label} · สร้างเมื่อ {_generated} น. (เวลาไทย)"
        )
        ws_summary["A2"].font = Font(color="64748B", size=10)

        ws_summary["A4"] = "รายรับรวม"
        ws_summary["B4"] = income_total
        ws_summary["A5"] = "รายจ่ายรวม"
        ws_summary["B5"] = expense_total
        ws_summary["A6"] = "คงเหลือ (รายรับ − รายจ่าย)"
        ws_summary["B6"] = round(income_total - expense_total, 2)
        for cell in ("A4", "B4"):
            ws_summary[cell].fill = INCOME_FILL
            ws_summary[cell].font = Font(bold=True)
        for cell in ("A5", "B5"):
            ws_summary[cell].fill = EXPENSE_FILL
            ws_summary[cell].font = Font(bold=True)
        for cell in ("A6", "B6"):
            ws_summary[cell].fill = TOTAL_FILL
            ws_summary[cell].font = Font(bold=True, size=12)
        for cell in ("B4", "B5", "B6"):
            ws_summary[cell].number_format = money

        row = 8
        sec_cell = ws_summary.cell(
            row=row, column=1,
            value=f"การเก็บเงิน / ลูกหนี้ — ข้อมูล ณ วันที่ {live_label} (Real-time)",
        )
        sec_cell.font = Font(bold=True, size=12, color="1E3A8A")
        row += 1

        rate = reg.get("collection_rate_pct")

        def summary_row(label, val, fmt=None, bold=False):
            nonlocal row
            lab = ws_summary.cell(row=row, column=1, value=label)
            lab.font = Font(bold=bold)
            vcell = money_cell(ws_summary, row, 2, val)
            if fmt:
                vcell.number_format = fmt
            row += 1

        summary_row("อัตราการเก็บเงินสำเร็จ (%)", rate, PCT_NUM_FMT if rate is not None else None, bold=True)
        summary_row("ยอดเรียกเก็บรวม (บาท)", reg.get("total_expected"), money)
        summary_row("เก็บเงินได้แล้ว (บาท)", reg.get("total_paid"), money)
        summary_row("หนี้ค้างชำระรวม — AR (บาท)", reg.get("total_pending"), money)
        summary_row("จำนวนลูกหนี้ที่ยังค้าง (คน)", ar.get("debtor_count"))
        summary_row("โปรเจคที่กำลังเก็บ (รายการ)", reg.get("active_count"))
        row += 1

        section = ws_summary.cell(row=row, column=1, value="ยอดคงเหลือรายบัญชี")
        section.font = Font(bold=True, size=12)
        row += 1
        for col, val in ((1, "บัญชี"), (2, "ยอดคงเหลือ (บาท)")):
            cell = ws_summary.cell(row=row, column=col, value=val)
            cell.fill = HEADER_FILL
            cell.font = white_bold
        row += 1
        for account, bal in (account_balances or []):
            ws_summary.cell(row=row, column=1, value=account)
            money_cell(ws_summary, row, 2, float(bal))
            row += 1
        if not account_balances:
            ws_summary.cell(row=row, column=1, value="(ไม่มีรายการในช่วงนี้)")
            money_cell(ws_summary, row, 2, 0.0)

        # =====================================================================
        # Sheet 2: ประวัติรายการ
        # =====================================================================
        ws_data = wb.create_sheet("ประวัติรายการ")
        ws_data.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[1]
        headers = [
            ("ลำดับ", 6), ("วันที่", 14), ("เวลา", 10), ("ประเภท", 14), ("รายรับ (บาท)", 14),
            ("รายจ่าย (บาท)", 14), ("รายการ", 42), ("หมวดหมู่", 20), ("บัญชี", 18), ("ผู้บันทึก", 16),
        ]
        ws_data.append([h[0] for h in headers])
        for idx, (_, width) in enumerate(headers, start=1):
            ws_data.column_dimensions[get_column_letter(idx)].width = width
            cell = ws_data.cell(row=1, column=idx)
            cell.fill = HEADER_FILL
            cell.font = white_bold
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for i, r in enumerate(rows, start=1):
            ts = r["created_at"]
            if ts is None:
                date_str, time_str = "", ""
            else:
                if isinstance(ts, datetime):
                    dt_local = ts.astimezone(THAI_TZ)
                else:
                    dt_local = datetime.combine(ts, dtime(0))
                date_str = dt_local.strftime("%d/%m/%Y")
                time_str = dt_local.strftime("%H:%M")
            ws_data.append([
                i, date_str, time_str, r["type"], r["income"], r["expense"],
                r["description"], r["category"], r["account"], r["recorded_by"],
            ])
            ws_data.cell(row=i + 1, column=5).number_format = money
            ws_data.cell(row=i + 1, column=6).number_format = money
            if i % 2 == 0:
                for col_idx in range(1, len(headers) + 1):
                    ws_data.cell(row=i + 1, column=col_idx).fill = ZEBRA_FILL

        ws_data.freeze_panes = "A2"
        ws_data.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws_data.max_row}"

        # =====================================================================
        # Sheet 3: สรุปรายหมวดหมู่
        # =====================================================================
        ws_cat = wb.create_sheet("สรุปรายหมวดหมู่")
        ws_cat.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[0]
        cat_headers = ["หมวดหมู่", "ประเภทรายการ", "ยอดรวม (บาท)"]
        ws_cat.append(cat_headers)
        ws_cat.column_dimensions["A"].width = 32
        ws_cat.column_dimensions["B"].width = 14
        ws_cat.column_dimensions["C"].width = 18
        for idx in range(1, len(cat_headers) + 1):
            cell = ws_cat.cell(row=1, column=idx)
            cell.fill = HEADER_FILL
            cell.font = white_bold

        cat_totals: Dict[str, dict] = {}
        for r in rows:
            if r.get("is_transfer") or r.get("type") == "โอนเงินระหว่างบัญชี":
                continue
            key = r["category"]
            entry = cat_totals.setdefault(key, {"type": r["type"], "total": 0.0})
            if r["type"] == "รายรับ":
                entry["total"] += r["income"]
            elif r["type"] == "รายจ่าย":
                entry["total"] += r["expense"]

        for idx, (name, info) in enumerate(sorted(cat_totals.items()), start=2):
            ws_cat.cell(row=idx, column=1, value=name)
            ws_cat.cell(row=idx, column=2, value=info["type"])
            cell = money_cell(ws_cat, idx, 3, round(info["total"], 2))
            cell.number_format = money
            if idx % 2 == 0:
                fill_row(ws_cat, idx, (1, 2, 3), ZEBRA_FILL)
        if not cat_totals:
            ws_cat.cell(row=2, column=1, value="(ไม่มีรายการในช่วงนี้)")

        ws_cat.freeze_panes = "A2"
        ws_cat.auto_filter.ref = f"A1:C{ws_cat.max_row}"

        # =====================================================================
        # Sheet 4: สรุปโปรเจคเก็บเงิน (Fee Collections)
        # =====================================================================
        ws_fee = wb.create_sheet("สรุปโปรเจคเก็บเงิน (Fee)")
        ws_fee.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[2]
        detail_headers = [
            ("เลขที่", 8), ("ชื่อ-นามสกุล", 32), ("สถานะการจ่าย", 14),
            ("เรียกเก็บ/คน (บาท)", 16), ("ชำระแล้ว (บาท)", 15), ("คงค้าง (บาท)", 15),
        ]
        ncols_fee = len(detail_headers)

        def _table_title(ws, title, subtitle, ncols):
            ws.sheet_view.showGridLines = False
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="0F172A")
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
            ws.cell(row=2, column=1, value=subtitle).font = Font(color="64748B", size=10)
            return 3

        def _write_header(ws, header_row, col_specs):
            for idx, (label, width) in enumerate(col_specs, start=1):
                ws.column_dimensions[get_column_letter(idx)].width = width
                cell = ws.cell(row=header_row, column=idx, value=label)
                cell.fill = HEADER_FILL
                cell.font = white_bold
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            return len(col_specs)

        def _merged_row(ws, row, ncols, text, *, fill=None, font=None, align="left"):
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            cell = ws.cell(row=row, column=1, value=text)
            if font is not None:
                cell.font = font
            cell.alignment = Alignment(horizontal=align, vertical="center")
            if fill:
                for cc in range(1, ncols + 1):
                    ws.cell(row=row, column=cc).fill = fill
            return cell

        def _money_label(val) -> str:
            return f"{float(val or 0.0):,.2f}"

        hr = _table_title(
            ws_fee, f"สรุปโปรเจคเก็บเงิน (Fee Collections) — {room_name}",
            f"รายชื่อผู้ค้างชำระรายคนใต้แต่ละโปรเจค · ข้อมูล ณ วันที่ {live_label} (Real-time) · "
            f"สร้างเมื่อ {generated_at.strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)",
            ncols_fee,
        )
        _write_header(ws_fee, hr, detail_headers)

        r = hr + 1
        grand_member = grand_expected = grand_paid = grand_pending = 0.0
        for p in fee_projects:
            member_count = int(p["member_count"] or 0)
            if member_count:
                grand_member += member_count
                grand_expected += p["expected"]
                grand_paid += p["paid"]
                grand_pending += p["pending"]

            status_label = COLLECTION_STATUS_LABELS.get(p["status"], p["status"])
            due_str = cls._fmt_date(p["due_date"])
            pending_here: List[dict] = pending_by_collection.get(p["id"], [])

            banner_text = (
                f'โปรเจค "{p["title"]}"  ·  {status_label}  ·  กำหนดชำระ {due_str or "—"}  ·  '
                f"สมาชิก {member_count} คน  ·  เรียกเก็บ {_money_label(p['fee_amount'])} บาท/คน  ·  "
                f"เป้าหมายรวม {_money_label(p['expected'])} บาท  ·  เก็บได้แล้ว {_money_label(p['paid'])} บาท  ·  "
                f"คงค้าง {_money_label(p['pending'])} บาท  ·  สำเร็จ {p['completion_pct']:,.2f}%"
            )
            _merged_row(
                ws_fee, r, ncols_fee, banner_text,
                fill=PatternFill("solid", fgColor="E0F2FE"),
                font=Font(bold=True, color="1E3A8A", size=11),
            )
            r += 1

            if not pending_here:
                _merged_row(
                    ws_fee, r, ncols_fee, "(ทุกคนจ่ายครบแล้วในโปรเจคนี้ 🎉)",
                    font=Font(italic=True, color="64748B", size=10),
                )
                r += 1
                continue

            for b in pending_here:
                pay_label = "ทยอยจ่ายแล้ว" if float(b["paid_amount"] or 0.0) > 0 else "ยังไม่จ่าย"
                ws_fee.cell(row=r, column=1, value=b["student_no"])
                ws_fee.cell(row=r, column=2, value=b["name"])
                ws_fee.cell(row=r, column=3, value=pay_label)
                money_cell(ws_fee, r, 4, b["fee_amount"])
                money_cell(ws_fee, r, 5, b["paid_amount"])
                money_cell(ws_fee, r, 6, b["outstanding"])
                if r % 2 == 0:
                    fill_row(ws_fee, r, tuple(range(1, ncols_fee + 1)), ZEBRA_FILL)
                r += 1

            sub_total = round(sum(float(x["outstanding"] or 0.0) for x in pending_here), 2)
            _merged_row(
                ws_fee, r, 5,
                f"รวมยอดคงค้างของคนที่ยังจ่ายไม่ครบในโปรเจคนี้ ({len(pending_here)} คน)",
                fill=SUBTOTAL_FILL, font=Font(bold=True, color="1E3A8A"),
            )
            money_cell(ws_fee, r, 6, sub_total).font = Font(bold=True, color="1E3A8A")
            r += 1

        if not fee_projects:
            _merged_row(ws_fee, r, ncols_fee, "(ยังไม่มีโปรเจคเก็บเงินในห้องนี้)",
                        font=Font(color="64748B"))
            r += 1
        else:
            total_text = (
                f"รวมทั้งสิ้น {len(fee_projects)} โปรเจค  ·  สมาชิกรวม {int(grand_member)} คน  ·  "
                f"เรียกเก็บรวม {_money_label(grand_expected)} บาท  ·  เก็บได้รวม {_money_label(grand_paid)} บาท  ·  "
                f"คงค้างรวม {_money_label(grand_pending)} บาท"
            )
            _merged_row(ws_fee, r, ncols_fee, total_text,
                        fill=TOTAL_FILL, font=Font(bold=True, color="0F172A"))
            r += 1
        ws_fee.freeze_panes = f"A{hr + 1}"
        ws_fee.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_fee)}{r - 1}"

        # =====================================================================
        # Sheet 5: ทะเบียนลูกหนี้ (Accounts Receivable)
        # =====================================================================
        ws_ar = wb.create_sheet("ทะเบียนลูกหนี้ (AR)")
        ws_ar.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[3]
        ar_headers = [
            ("เลขที่", 8), ("รหัสนักเรียน", 13), ("ชื่อ-นามสกุล", 30), ("รายการที่ค้างชำระ", 30),
            ("กำหนดชำระ", 12), ("ยอดเรียกเก็บ (บาท)", 15), ("ชำระแล้ว (บาท)", 14),
            ("ยอดคงค้าง (บาท)", 15), ("สถานะโปรเจค", 12),
        ]
        ncols_ar = len(ar_headers)
        hr = _table_title(
            ws_ar, f"ทะเบียนลูกหนี้ (Accounts Receivable) — {room_name}",
            f"หนี้ค้างชำระรายคน ณ วันที่ {live_label} (Real-time) · เฉพาะรายการที่ยังจ่ายไม่ครบ "
            f"(รวมโปรเจคที่ปิดไปแล้ว) · สร้างเมื่อ {generated_at.strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)",
            ncols_ar,
        )
        _write_header(ws_ar, hr, ar_headers)

        r = hr + 1
        i = 0
        while i < len(ar_rows):
            block = []
            cur_student = ar_rows[i]["student_id"]
            while i < len(ar_rows) and ar_rows[i]["student_id"] == cur_student:
                block.append(ar_rows[i])
                i += 1
            first = True
            for b in block:
                if first:
                    ws_ar.cell(row=r, column=1, value=b["student_no"])
                    ws_ar.cell(row=r, column=2, value=b["student_id_no"] or "—")
                    ws_ar.cell(row=r, column=3, value=b["name"])
                due_str = cls._fmt_date(b["due_date"])
                ws_ar.cell(row=r, column=4, value=b["title"])
                ws_ar.cell(row=r, column=5, value=due_str)
                money_cell(ws_ar, r, 6, b["fee_amount"])
                money_cell(ws_ar, r, 7, b["paid_amount"])
                money_cell(ws_ar, r, 8, b["outstanding"])
                ws_ar.cell(row=r, column=9, value=COLLECTION_STATUS_LABELS.get(b["collection_status"], b["collection_status"]))
                if r % 2 == 0:
                    fill_row(ws_ar, r, tuple(range(1, ncols_ar + 1)), ZEBRA_FILL)
                first = False
                r += 1
            subtotal = round(sum(float(b["outstanding"] or 0.0) for b in block), 2)
            _merged_row(
                ws_ar, r, 7,
                f"รวมหนี้ของ {block[0]['name']} — ค้าง {len(block)} รายการ",
                fill=SUBTOTAL_FILL, font=Font(bold=True, color="1E3A8A"),
            )
            money_cell(ws_ar, r, 8, subtotal).font = Font(bold=True, color="1E3A8A")
            r += 1

        if not ar_rows:
            _merged_row(ws_ar, r, ncols_ar, "(ไม่มีลูกหนี้ค้างชำระ — เก็บเงินครบทุกคนแล้ว 🎉)",
                        font=Font(color="64748B"))
            r += 1
        else:
            grand_total = float(ar.get("total_outstanding") or 0.0)
            _merged_row(
                ws_ar, r, 7,
                f"รวมลูกหนี้ทั้งสิ้น ({ar.get('debtor_count')} คน)",
                fill=TOTAL_FILL, font=Font(bold=True, color="0F172A"),
            )
            money_cell(ws_ar, r, 8, grand_total).font = Font(bold=True, color="0F172A")
            r += 1
        ws_ar.freeze_panes = f"A{hr + 1}"
        ws_ar.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_ar)}{r - 1}"

        # =====================================================================
        # Sheet 6: สรุปรายเดือน (Monthly Summary)
        # =====================================================================
        ws_monthly = wb.create_sheet("สรุปรายเดือน (Monthly)")
        ws_monthly.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[0]
        monthly_headers = ["เดือน (Month)", "รายรับรวม (Income)", "รายจ่ายรวม (Expense)", "คงเหลือสุทธิ (Net)"]
        ws_monthly.append(monthly_headers)
        ws_monthly.column_dimensions["A"].width = 24
        ws_monthly.column_dimensions["B"].width = 20
        ws_monthly.column_dimensions["C"].width = 20
        ws_monthly.column_dimensions["D"].width = 20
        
        for idx in range(1, len(monthly_headers) + 1):
            cell = ws_monthly.cell(row=1, column=idx)
            cell.fill = HEADER_FILL
            cell.font = white_bold
            cell.alignment = Alignment(horizontal="center", vertical="center")

        monthly_data = {}
        for row_data in non_transfer_rows:
            ts = row_data["created_at"]
            if ts is None:
                continue
            if isinstance(ts, datetime):
                dt_local = ts.astimezone(THAI_TZ)
            else:
                dt_local = datetime.combine(ts, dtime(0))
            
            month_key = dt_local.strftime("%Y-%m")
            month_label = dt_local.strftime("%B %Y")
            
            if month_key not in monthly_data:
                monthly_data[month_key] = {"label": month_label, "income": 0.0, "expense": 0.0}
                
            monthly_data[month_key]["income"] += row_data.get("income", 0.0)
            monthly_data[month_key]["expense"] += row_data.get("expense", 0.0)

        mr = 2
        total_m_income = 0.0
        total_m_expense = 0.0
        
        for month_key in sorted(monthly_data.keys()):
            data = monthly_data[month_key]
            ws_monthly.cell(row=mr, column=1, value=data["label"])
            acc_money_cell(ws_monthly, mr, 2, data["income"])
            acc_money_cell(ws_monthly, mr, 3, data["expense"])
            acc_money_cell(ws_monthly, mr, 4, data["income"] - data["expense"], bold=True)
            
            total_m_income += data["income"]
            total_m_expense += data["expense"]
            
            if mr % 2 == 1:
                fill_row(ws_monthly, mr, (1, 2, 3, 4), ZEBRA_FILL)
            mr += 1

        if not monthly_data:
            ws_monthly.cell(row=mr, column=1, value="(ไม่มีข้อมูล)")
            mr += 1

        ws_monthly.cell(row=mr, column=1, value="รวมทั้งสิ้น (Grand Total)").font = Font(bold=True)
        acc_money_cell(ws_monthly, mr, 2, total_m_income, bold=True, double_underline=True)
        acc_money_cell(ws_monthly, mr, 3, total_m_expense, bold=True, double_underline=True)
        acc_money_cell(ws_monthly, mr, 4, total_m_income - total_m_expense, bold=True, double_underline=True)
        fill_row(ws_monthly, mr, (1, 2, 3, 4), TOTAL_FILL)

        ws_monthly.freeze_panes = "A2"
        
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def _fmt_date(value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.astimezone(THAI_TZ).strftime("%d/%m/%Y")
        return value.strftime("%d/%m/%Y")

    @staticmethod
    def _journal_reference(reference_type: Optional[str], reference_id: Optional[str]) -> str:
        if not reference_type:
            return f"#{reference_id}" if reference_id not in (None, "") else "—"
        label = REFERENCE_TYPE_LABELS.get(reference_type, reference_type)
        if reference_id not in (None, ""):
            return f"{label} #{reference_id}"
        return label

    @classmethod
    async def export_journal_excel(
        cls, pool: asyncpg.Pool, *, client_source: str, actor_identifier: str,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> io.BytesIO:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                start_dt, end_dt, period_label = _resolve_inclusive_period(
                    month, year, start_date, end_date
                )

                start_dt, end_dt, clamped, _empty = _clamp_to_cutoff(start_dt, end_dt)
                note = ""
                if clamped:
                    period_label = f"{period_label} (ข้อมูลเริ่ม 2026-09-01)"
                    note = "ช่วงก่อน 2026-09-01 ไม่มีข้อมูลในบัญชีคู่ ถูกตัดออกจากรายงานนี้"
                elif start_dt is None and end_dt is None:
                    period_label = "ทั้งหมด (ตั้งแต่ขึ้นระบบบัญชีคู่ 2026-09-01)"

                room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", target_room_id)
                room_name = room["room_name"] if room else f"ห้อง #{target_room_id}"

                lower_dt = datetime.combine(start_dt, dtime.min) if start_dt else None
                upper_dt = datetime.combine(end_dt, dtime(23, 59, 59)) if end_dt else None
                pl_start = lower_dt or datetime.combine(CUTOFF_DATE, dtime.min)

                conditions = ["JE.room_id = $1", "JE.deleted_at IS NULL", "JE.status <> 'voided'"]
                params: List[Any] = [target_room_id]
                idx = 2
                if start_dt is not None:
                    conditions.append(f"DATE(JE.transaction_date) >= ${idx}")
                    params.append(start_dt)
                    idx += 1
                if end_dt is not None:
                    conditions.append(f"DATE(JE.transaction_date) <= ${idx}")
                    params.append(end_dt)
                    idx += 1

                lines = await conn.fetch(
                    f"""
                    SELECT JE.id AS entry_id,
                           JE.reference_type, JE.reference_id,
                           JE.description, JE.transaction_date, JE.recorded_by,
                           JE.metadata,
                           L.id AS line_id, L.debit, L.credit, L.line_description,
                           AL.account_code, AL.account_name, AL.account_type
                    FROM journal_entries JE
                    JOIN journal_lines L ON L.journal_entry_id = JE.id
                    JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY JE.transaction_date ASC, JE.id ASC, L.id ASC
                    """,
                    *params,
                )

                journal_rows: List[dict] = []
                prev_entry_id: Optional[str] = None
                for ln in lines:
                    entry_id = str(ln["entry_id"])
                    is_first_line = entry_id != prev_entry_id
                    raw_meta = ln["metadata"]
                    if isinstance(raw_meta, str):
                        try:
                            meta = json.loads(raw_meta)
                        except (ValueError, TypeError):
                            meta = {}
                    else:
                        meta = raw_meta or {}
                    base = {
                        "account_code": ln["account_code"] or "",
                        "account_name": ln["account_name"] or "—",
                        "debit": float(ln["debit"] or 0.0),
                        "credit": float(ln["credit"] or 0.0),
                        "module": ln["reference_type"] or "",
                        "doc_id": ln["reference_id"],
                        "legacy_tx_id": meta.get("legacy_transaction_id"),
                        "transfer_group_id": meta.get("transfer_group_id"),
                        "student_payment_id": meta.get("student_payment_id"),
                        "journal_entry_id": entry_id,
                        "journal_line_id": int(ln["line_id"]),
                    }
                    if is_first_line:
                        journal_rows.append({
                            **base,
                            "date_time": ln["transaction_date"],
                            "reference": cls._journal_reference(ln["reference_type"], ln["reference_id"]),
                            "description": ln["description"] or "",
                            "recorded_by": ln["recorded_by"] or "—",
                        })
                        prev_entry_id = entry_id
                    else:
                        journal_rows.append({
                            **base,
                            "date_time": None, "reference": None,
                            "description": None, "recorded_by": None,
                        })

                gl_rows = await cls._fetch_general_ledger(
                    conn, room_id=target_room_id, start_dt=lower_dt, end_dt=upper_dt,
                )
                tb = await cls._fetch_trial_balance_ledgers(
                    conn, room_id=target_room_id, as_of_dt=upper_dt,
                )
                pl = await cls._fetch_income_statement_rows(
                    conn, room_id=target_room_id, start_dt=pl_start, end_dt=upper_dt,
                )
                reg = await cls._fetch_collection_register(conn, target_room_id)
                ar = await cls._fetch_accounts_receivable(conn, target_room_id)

                if end_dt is not None:
                    as_of_str = cls._fmt_date(end_dt)
                else:
                    today_label = datetime.now(THAI_TZ).strftime("%d/%m/%Y")
                    as_of_str = f"ถึงข้อมูลล่าสุด ({today_label})"
                balance_sheet = cls._compose_balance_sheet(tb, pl["net_income"], as_of_str)

                assets_total = balance_sheet["assets_total"]
                dashboard = {
                    "as_of": as_of_str,
                    "net_worth": assets_total,
                    "total_revenue": pl["total_revenue"],
                    "total_expense": pl["total_expense"],
                    "net_income": pl["net_income"],
                    "margin_pct": pl["margin_pct"],
                    "ar_total": ar.get("total_outstanding"),
                    "ar_debtors": ar.get("debtor_count"),
                    "collection_rate_pct": reg.get("collection_rate_pct"),
                    "ledger_count": len(tb["ledgers"]),
                    "journal_entry_count": len(journal_rows),
                }

                excel_file = cls._build_accounting_workbook(
                    room_name=room_name, period_label=period_label,
                    generated_at=datetime.now(THAI_TZ),
                    journal_rows=journal_rows, gl_rows=gl_rows, tb=tb, pl=pl,
                    balance_sheet=balance_sheet, dashboard=dashboard, note=note,
                )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="ACCOUNTING_JOURNAL", status="success",
                    new_values={"period": period_label, "journal_lines": len(journal_rows)},
                    endpoint_or_command="FinanceService.export_journal_excel", execution_time_ms=exec_time
                )
                return excel_file
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="ACCOUNTING_JOURNAL", status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.export_journal_excel",
                        execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    def _build_accounting_workbook(
        cls, *, room_name: str, period_label: str, generated_at: datetime,
        journal_rows: List[dict], gl_rows: List[dict], tb: dict, pl: dict,
        balance_sheet: dict, dashboard: dict, note: str = "",
    ) -> io.BytesIO:
        double_bottom = Border(bottom=Side(style='double'))
        thin_bottom = Border(bottom=Side(style='thin'))
        HEADER_FILL = PatternFill("solid", fgColor="047857")     
        TOTAL_FILL = PatternFill("solid", fgColor="D1D5DB")
        SECTION_FILL = PatternFill("solid", fgColor="D1FAE5")
        SUBTOTAL_FILL = PatternFill("solid", fgColor="E0E7FF")
        ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
        white_bold = Font(bold=True, color="FFFFFF")
        money = MONEY_NUM_FMT

        def fill_row(ws, row, cols, fill):
            for c in cols:
                ws.cell(row=row, column=c).fill = fill

        def title_rows(ws, title, subtitle, ncols):
            ws.sheet_view.showGridLines = False
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="0F172A")
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
            ws.cell(row=2, column=1, value=subtitle).font = Font(color="64748B", size=10)
            return 3

        def write_header(ws, header_row, col_specs):
            for col_idx, (label, width) in enumerate(col_specs, start=1):
                ws.column_dimensions[get_column_letter(col_idx)].width = width
                cell = ws.cell(row=header_row, column=col_idx, value=label)
                cell.fill = HEADER_FILL
                cell.font = white_bold
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            return len(col_specs)

        wb = Workbook()

        _generated = generated_at.strftime("%d/%m/%Y %H:%M")
        
        def acc_money_cell(ws, row, col, val, bold=False, double_underline=False, single_underline=False):
            cell = ws.cell(row=row, column=col)
            if val is not None:
                cell.value = float(val)
                cell.number_format = '#,##0.00;[Red](#,##0.00);"-"'
            if bold:
                cell.font = Font(bold=True)
            if double_underline:
                cell.border = double_bottom
            elif single_underline:
                cell.border = thin_bottom
            return cell

        # =====================================================================
        # Sheet 1: Financial Dashboard
        # =====================================================================
        ws_dash = wb.active
        ws_dash.title = "Financial Dashboard"
        ws_dash.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[0]
        ws_dash.column_dimensions["A"].width = 42
        ws_dash.column_dimensions["B"].width = 26
        
        ws_dash["A1"] = f"สรุปภาพรวมการเงิน (Financial Dashboard) — {room_name}"
        ws_dash["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_dash["A2"] = (
            f"รอบ: {period_label} · ข้อมูล ณ วันที่ {dashboard['as_of']} · "
            f"สร้างเมื่อ {_generated} น. (เวลาไทย)"
        )
        ws_dash["A2"].font = Font(color="64748B", size=10)

        ws_dash["A4"] = "สรุปผลประกอบการ (Summary)"
        ws_dash["A4"].font = Font(bold=True, size=12, color="065F46")
        
        ws_dash["A5"] = "รายได้รวม (Total Revenue)"
        acc_money_cell(ws_dash, 5, 2, dashboard["total_revenue"])
        ws_dash["A5"].fill = SECTION_FILL
        ws_dash["B5"].fill = SECTION_FILL
        
        ws_dash["A6"] = "หัก: ค่าใช้จ่ายรวม (Total Expense)"
        acc_money_cell(ws_dash, 6, 2, -abs(dashboard["total_expense"]) if dashboard["total_expense"] != 0 else 0, single_underline=True)
        ws_dash["A6"].fill = SUBTOTAL_FILL
        ws_dash["B6"].fill = SUBTOTAL_FILL
        
        ws_dash["A7"] = "กำไร/ขาดทุนสุทธิ (Net Income)"
        ws_dash["A7"].font = Font(bold=True)
        ws_dash["A7"].fill = TOTAL_FILL
        acc_money_cell(ws_dash, 7, 2, dashboard["net_income"], bold=True, double_underline=True)
        ws_dash["B7"].fill = TOTAL_FILL

        if dashboard["margin_pct"] is not None:
            ws_dash["A8"] = "อัตรากำไร (Net Margin)"
            ws_dash["B8"] = dashboard["margin_pct"]
            ws_dash["B8"].number_format = PCT_NUM_FMT

        ws_dash["A10"] = "ค่าใช้จ่ายสูงสุด (Top Expenses)"
        ws_dash["A10"].font = Font(bold=True, size=12, color="065F46")
        r = 11
        sorted_exp = sorted(pl.get("expenses", []), key=lambda x: x["amount"], reverse=True)
        for i, exp in enumerate(sorted_exp[:5]):
            ws_dash.cell(row=r, column=1, value=f"  {i+1}. {exp['account_name']}")
            acc_money_cell(ws_dash, r, 2, exp["amount"])
            r += 1
        if not sorted_exp:
            ws_dash.cell(row=r, column=1, value="  (ไม่มีรายการค่าใช้จ่าย)")
            r += 1

        r += 1
        ws_dash.cell(row=r, column=1, value="สถานะความถูกต้อง (Health Check)").font = Font(bold=True, size=12, color="065F46")
        r += 1
        ws_dash.cell(row=r, column=1, value="ความสมดุลของสมการบัญชี (Dr = Cr)")
        if tb["is_balanced"]:
            ws_dash.cell(row=r, column=2, value="✅ สมดุล (Balanced)").font = Font(bold=True, color="047857")
        else:
            ws_dash.cell(row=r, column=2, value="❌ ไม่สมดุล (Unbalanced)").font = Font(bold=True, color="B91C1C")
        r += 1
        ws_dash.cell(row=r, column=1, value="งบแสดงฐานะการเงิน (Assets = Liab + Equity)")
        if balance_sheet["is_balanced"]:
            ws_dash.cell(row=r, column=2, value="✅ สมดุล (Balanced)").font = Font(bold=True, color="047857")
        else:
            ws_dash.cell(row=r, column=2, value="❌ ไม่สมดุล (Unbalanced)").font = Font(bold=True, color="B91C1C")

        r += 2
        ws_dash.cell(row=r, column=1, value="การเรียกเก็บเงิน / ลูกหนี้ (Real-time)").font = Font(bold=True, size=12, color="065F46")
        r += 1
        ws_dash.cell(row=r, column=1, value="ยอดหนี้ค้างชำระรวม — AR (บาท)")
        acc_money_cell(ws_dash, r, 2, dashboard["ar_total"])
        r += 1
        ws_dash.cell(row=r, column=1, value="จำนวนลูกหนี้ (คน)")
        ws_dash.cell(row=r, column=2, value=dashboard["ar_debtors"])

        if note:
            r += 2
            ncell = ws_dash.cell(row=r, column=1, value=f"หมายเหตุ: {note}")
            ncell.font = Font(color="B45309", size=10, italic=True)

        # =====================================================================
        # Sheet 2: งบแสดงฐานะการเงิน (Balance Sheet)
        # =====================================================================
        ws_bs = wb.create_sheet("งบแสดงฐานะการเงิน (BS)")
        ws_bs.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[5]
        ws_bs.column_dimensions["A"].width = 6
        ws_bs.column_dimensions["B"].width = 42
        ws_bs.column_dimensions["C"].width = 22
        ws_bs["A1"] = f"งบแสดงฐานะการเงิน (Balance Sheet) — {room_name}"
        ws_bs["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_bs["A2"] = (
            f"ข้อมูล ณ วันที่ {balance_sheet['as_of']} · สมการ: สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม · "
            f"สร้างเมื่อ {_generated} น."
        )
        ws_bs["A2"].font = Font(color="64748B", size=10)

        def _bs_section_row(ws, row, label):
            ws.cell(row=row, column=2, value=label).font = Font(bold=True, size=12, color="065F46")

        row_idx = 4
        _bs_section_row(ws_bs, row_idx, "สินทรัพย์ (Assets)")
        row_idx += 1
        for a in balance_sheet["assets"]:
            ws_bs.cell(row=row_idx, column=2, value=f"  {a['account_name']} ({a['account_code']})")
            acc_money_cell(ws_bs, row_idx, 3, a["balance"])
            row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมสินทรัพย์").font = Font(bold=True)
        acc_money_cell(ws_bs, row_idx, 3, balance_sheet["assets_total"], bold=True, double_underline=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), SECTION_FILL)
        row_idx += 2

        _bs_section_row(ws_bs, row_idx, "หนี้สิน (Liabilities)")
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="  (ระบบยังไม่มีหนี้สิน)")
        acc_money_cell(ws_bs, row_idx, 3, 0.0)
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมหนี้สิน").font = Font(bold=True)
        acc_money_cell(ws_bs, row_idx, 3, 0.0, bold=True, single_underline=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), SUBTOTAL_FILL)
        row_idx += 2

        _bs_section_row(ws_bs, row_idx, "ส่วนของเจ้าของ (Equity)")
        row_idx += 1
        for eq in balance_sheet["equities"]:
            ws_bs.cell(row=row_idx, column=2, value=f"  {eq['account_name']} ({eq['account_code']})")
            acc_money_cell(ws_bs, row_idx, 3, eq["balance"])
            row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="  กำไรสะสมถึงวันที่ (Retained Earnings)")
        acc_money_cell(ws_bs, row_idx, 3, balance_sheet["retained_earnings"], single_underline=True)
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมส่วนของเจ้าของ").font = Font(bold=True)
        acc_money_cell(ws_bs, row_idx, 3, balance_sheet["total_equity_side"], bold=True, double_underline=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), TOTAL_FILL)
        row_idx += 2

        ws_bs.cell(row=row_idx, column=2, value="ตรวจสอบสมดุล (Assets = Liab + Equity + Retained)")
        ws_bs.cell(row=row_idx, column=2).font = Font(bold=True, color="0F172A")
        ok = balance_sheet["is_balanced"]
        ws_bs.cell(row=row_idx, column=3, value="✅ สมดุล" if ok else "❌ ไม่สมดุล")
        ws_bs.cell(row=row_idx, column=3).font = Font(bold=True, color="047857" if ok else "B91C1C")

        # =====================================================================
        # Sheet 3: งบกำไรขาดทุน (Income Statement)
        # =====================================================================
        ws_pl = wb.create_sheet("งบกำไรขาดทุน (Income Statement)")
        ws_pl.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[4]
        ws_pl.column_dimensions["A"].width = 6
        ws_pl.column_dimensions["B"].width = 40
        ws_pl.column_dimensions["C"].width = 22
        ws_pl["A1"] = f"งบกำไรขาดทุน (Income Statement) — {room_name}"
        ws_pl["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_pl["A2"] = f"รอบ: {period_label} · ข้อมูล ณ วันที่ {dashboard['as_of']} · สร้างเมื่อ {_generated} น. (เวลาไทย)"
        ws_pl["A2"].font = Font(color="64748B", size=10)

        ws_pl["A4"] = "รายได้ (Revenue)"
        ws_pl["A4"].font = Font(bold=True, size=12, color="047857")
        hr = 5
        for rev in pl["revenues"]:
            ws_pl.cell(row=hr, column=2, value=f"  {rev['account_name']}")
            acc_money_cell(ws_pl, hr, 3, rev["amount"])
            hr += 1
        ws_pl.cell(row=hr, column=2, value="รวมรายได้").font = Font(bold=True, color="047857")
        acc_money_cell(ws_pl, hr, 3, pl["total_revenue"], bold=True, single_underline=True)
        fill_row(ws_pl, hr, (1, 2, 3), SECTION_FILL)
        hr += 2

        ws_pl.cell(row=hr, column=1, value="ค่าใช้จ่าย (Expense)")
        ws_pl.cell(row=hr, column=1).font = Font(bold=True, size=12, color="B91C1C")
        hr += 1
        for exp in pl["expenses"]:
            ws_pl.cell(row=hr, column=2, value=f"  {exp['account_name']}")
            acc_money_cell(ws_pl, hr, 3, exp["amount"])
            hr += 1
        ws_pl.cell(row=hr, column=2, value="รวมค่าใช้จ่าย").font = Font(bold=True, color="B91C1C")
        acc_money_cell(ws_pl, hr, 3, pl["total_expense"], bold=True, single_underline=True)
        fill_row(ws_pl, hr, (1, 2, 3), SUBTOTAL_FILL)
        hr += 2

        ws_pl.cell(row=hr, column=2, value="กำไร/ขาดทุนสุทธิ (Net Income)")
        ws_pl.cell(row=hr, column=2).font = Font(bold=True, size=12)
        acc_money_cell(ws_pl, hr, 3, pl["net_income"], bold=True, double_underline=True)
        fill_row(ws_pl, hr, (1, 2, 3), TOTAL_FILL)

        # =====================================================================
        # Sheet 4: งบทดลอง (Trial Balance)
        # =====================================================================
        ws_tb = wb.create_sheet("งบทดลอง (Trial Balance)")
        ws_tb.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[3]
        tb_headers = [
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 26), ("หมวด", 13),
            ("เดบิต (Dr.)", 18), ("เครดิต (Cr.)", 18), ("คงเหลือ (บาท)", 16),
        ]
        ncols_tb = len(tb_headers)
        hr = title_rows(
            ws_tb, f"งบทดลอง (Trial Balance) — {room_name}",
            f"ข้อมูล ณ วันที่ {dashboard['as_of']} · สร้างเมื่อ {_generated} น.",
            ncols_tb,
        )
        write_header(ws_tb, hr, tb_headers)
        r = hr + 1
        for row_no, lg in enumerate(tb["ledgers"], start=1):
            ws_tb.cell(row=r, column=1, value=lg["account_code"])
            ws_tb.cell(row=r, column=2, value=lg["account_name"])
            ws_tb.cell(row=r, column=3, value=ACCOUNT_TYPE_LABELS.get(lg["account_type"], lg["account_type"]))
            acc_money_cell(ws_tb, r, 4, lg["total_debit"])
            acc_money_cell(ws_tb, r, 5, lg["total_credit"])
            acc_money_cell(ws_tb, r, 6, lg["balance"])
            if row_no % 2 == 0:
                fill_row(ws_tb, r, tuple(range(1, ncols_tb + 1)), ZEBRA_FILL)
            r += 1
        if not tb["ledgers"]:
            ws_tb.cell(row=r, column=2, value="(ไม่มีรายการ)")
            r += 1
        
        ws_tb.cell(row=r, column=2, value="รวมทั้งสิ้น (Grand Total)").font = Font(bold=True)
        acc_money_cell(ws_tb, r, 4, tb["total_debit"], bold=True, double_underline=True)
        acc_money_cell(ws_tb, r, 5, tb["total_credit"], bold=True, double_underline=True)
        ws_tb.cell(row=r, column=6, value="✅ สมดุล" if tb["is_balanced"] else "❌ ไม่สมดุล")
        ws_tb.cell(row=r, column=6).font = Font(bold=True, color="047857" if tb["is_balanced"] else "B91C1C")
        fill_row(ws_tb, r, tuple(range(1, ncols_tb + 1)), TOTAL_FILL)
        ws_tb.freeze_panes = f"A{hr + 1}"
        ws_tb.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_tb)}{ws_tb.max_row}"

        # =====================================================================
        # Sheet 5: สมุดบัญชีแยกประเภท (General Ledger)
        # =====================================================================
        ws_gl = wb.create_sheet("สมุดบัญชีแยกประเภท (GL)")
        ws_gl.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[2]
        gl_headers = [
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 26), ("หมวด", 13),
            ("ยอดยกมา (Opening)", 18), ("เดบิต (Dr.)", 16), ("เครดิต (Cr.)", 16), ("ยอดยกไป (Closing)", 18),
        ]
        ncols_gl = len(gl_headers)
        hr = title_rows(
            ws_gl, f"สมุดบัญชีแยกประเภท (General Ledger) — {room_name}",
            f"รอบ: {period_label} · ข้อมูล ณ วันที่ {dashboard['as_of']} · สร้างเมื่อ {_generated} น.",
            ncols_gl,
        )
        write_header(ws_gl, hr, gl_headers)
        r = hr + 1
        for row_no, gl in enumerate(gl_rows, start=1):
            ws_gl.cell(row=r, column=1, value=gl["account_code"])
            ws_gl.cell(row=r, column=2, value=gl["account_name"])
            ws_gl.cell(row=r, column=3, value=ACCOUNT_TYPE_LABELS.get(gl["account_type"], gl["account_type"]))
            acc_money_cell(ws_gl, r, 4, gl["opening_balance"])
            acc_money_cell(ws_gl, r, 5, gl["period_debit"])
            acc_money_cell(ws_gl, r, 6, gl["period_credit"])
            acc_money_cell(ws_gl, r, 7, gl["closing_balance"], bold=True)
            if row_no % 2 == 0:
                fill_row(ws_gl, r, tuple(range(1, ncols_gl + 1)), ZEBRA_FILL)
            r += 1
        if not gl_rows:
            ws_gl.cell(row=r, column=2, value="(ไม่มีบัญชีในระบบ)")
            r += 1
        
        ws_gl.freeze_panes = f"A{hr + 1}"
        ws_gl.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_gl)}{ws_gl.max_row}"

        # =====================================================================
        # Sheet 6: สมุดรายวันทั่วไป (General Journal)
        # =====================================================================
        ws_j = wb.create_sheet("สมุดรายวันทั่วไป (GJ)")
        ws_j.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[1]
        j_headers = [
            ("วันที่", 12), ("เวลา", 8), ("อ้างอิง (Ref)", 16), ("คำอธิบายรายการ", 38),
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 24), ("เดบิต (Dr.)", 16), ("เครดิต (Cr.)", 16),
            ("ผู้บันทึก", 16),
            ("โมดูลต้นทาง", 18), ("Doc ID", 12),
            ("Legacy ID", 12), ("Transfer ID", 12), ("Payment ID", 12),
            ("Journal ID", 38),
        ]
        ncols_j = len(j_headers)
        hr = title_rows(
            ws_j, f"สมุดรายวันทั่วไป (General Journal) — {room_name}",
            f"รอบ: {period_label} · ข้อมูล ณ วันที่ {dashboard['as_of']} · สร้างเมื่อ {_generated} น. (เวลาไทย)"
            + (" · " + note if note else ""),
            ncols_j,
        )
        write_header(ws_j, hr, j_headers)

        def _fmt_j_datetime(v):
            if v is None:
                return "", ""
            dt_local = v.astimezone(THAI_TZ)
            return dt_local.strftime("%d/%m/%Y"), dt_local.strftime("%H:%M")

        r = hr + 1
        for jr in journal_rows:
            date_str, time_str = _fmt_j_datetime(jr.get("date_time"))
            ws_j.cell(row=r, column=1, value=date_str or None)
            ws_j.cell(row=r, column=2, value=time_str or None)
            ws_j.cell(row=r, column=3, value=jr.get("reference"))
            ws_j.cell(row=r, column=4, value=jr.get("description"))
            ws_j.cell(row=r, column=5, value=jr.get("account_code"))
            ws_j.cell(row=r, column=6, value=jr.get("account_name"))
            acc_money_cell(ws_j, r, 7, jr["debit"] if jr["debit"] else None)
            acc_money_cell(ws_j, r, 8, jr["credit"] if jr["credit"] else None)
            ws_j.cell(row=r, column=9, value=jr.get("recorded_by"))
            
            ws_j.cell(row=r, column=10, value=jr.get("module") or None)
            ws_j.cell(row=r, column=11, value=jr.get("doc_id") or None)
            ws_j.cell(row=r, column=12, value=jr.get("legacy_tx_id"))
            ws_j.cell(row=r, column=13, value=jr.get("transfer_group_id"))
            ws_j.cell(row=r, column=14, value=jr.get("student_payment_id"))
            ws_j.cell(row=r, column=15, value=jr.get("journal_entry_id"))
            
            if jr.get("description") is not None:
                for col in (3, 4, 9):
                    ws_j.cell(row=r, column=col).font = Font(bold=True)
            if (r - hr) % 2 == 0:
                fill_row(ws_j, r, tuple(range(1, ncols_j + 1)), ZEBRA_FILL)
            r += 1

        if not journal_rows:
            ws_j.cell(row=r, column=4, value="(ไม่มีรายการในช่วงนี้)")
            r += 1

        debit_total = round(sum(float(x.get("debit") or 0.0) for x in journal_rows), 2)
        credit_total = round(sum(float(x.get("credit") or 0.0) for x in journal_rows), 2)
        ws_j.cell(row=r, column=4, value="รวมทั้งสิ้น (Grand Total)").font = Font(bold=True)
        ws_j.cell(row=r, column=4).alignment = Alignment(horizontal="right")
        acc_money_cell(ws_j, r, 7, debit_total, bold=True, double_underline=True)
        acc_money_cell(ws_j, r, 8, credit_total, bold=True, double_underline=True)
        fill_row(ws_j, r, tuple(range(1, ncols_j + 1)), TOTAL_FILL)
        
        ws_j.freeze_panes = f"A{hr + 1}"
        ws_j.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_j)}{ws_j.max_row}"
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output
