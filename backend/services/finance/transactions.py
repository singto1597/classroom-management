"""รายการรับ-จ่าย / โอนเงิน / revert + time-based routing legacy/v2/merged"""
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


class TransactionsMixin:
    @classmethod
    async def add_transaction(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        req.account_id, target_room_id
                    )
                    if current_balance is None: raise ValueError("ไม่พบบัญชีนี้ในห้องของคุณ")
                    # 💡 balance กลับมาจาก DECIMAL เป็น Decimal (มี binary noise จาก float ที่เก็บเข้า)
                    # ต้อง cast float() ทั้งสองฝั่งก่อนเปรียบเทียบ (ตาม CLAUDE.md: cast float ก่อนเสมอ)
                    if req.transaction_type == 'expense' and float(current_balance) < float(req.amount):
                        raise ValueError(f"เงินไม่พอ! ยอดคงเหลือคือ {current_balance} บาท")

                    cat = await conn.fetchrow("SELECT room_id, category_type FROM finance_categories WHERE id = $1 AND deleted_at IS NULL", req.category_id)
                    if not cat or cat['room_id'] != target_room_id: raise ValueError("หมวดหมู่นี้ไม่มีอยู่ หรือไม่ใช่ของห้องคุณ!")
                    if cat['category_type'] != req.transaction_type:
                        raise ValueError(f"ประเภทหมวดหมู่ ({cat['category_type']}) ไม่ตรงกับประเภทการบันทึก ({req.transaction_type})!")

                    # [DUAL-WRITE] ดึง id ของ legacy transaction เพื่อเก็บลง journal metadata (สำหรับ revert)
                    new_tx_id = await conn.fetchval(
                        """INSERT INTO finance_transactions
                           (room_id, account_id, category_id, amount, description, transaction_type, slip_image_url, recorded_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                        target_room_id, req.account_id, req.category_id, req.amount,
                        req.description, req.transaction_type, req.slip_image_url, req.user_name
                    )

                    if req.transaction_type == 'income':
                        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.account_id)
                    elif req.transaction_type == 'expense':
                        await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.account_id)

                    # [DUAL-WRITE] เขียนฝั่ง Double-Entry (หัวบิล + 2 บรรทัด เดบิต/เครดิต) ใน transaction เดียวกัน
                    asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, req.account_id)
                    category_ledger_id = await cls._resolve_category_ledger(conn, target_room_id, req.category_id, req.transaction_type)
                    if req.transaction_type == 'income':
                        lines = [
                            {"ledger_id": asset_ledger_id, "debit": req.amount, "credit": 0, "line_description": f"รับเงินเข้าบัญชี: {req.account_id}"},
                            {"ledger_id": category_ledger_id, "debit": 0, "credit": req.amount, "line_description": f"รายได้: {req.description}"},
                        ]
                    else:  # expense
                        lines = [
                            {"ledger_id": category_ledger_id, "debit": req.amount, "credit": 0, "line_description": f"ค่าใช้จ่าย: {req.description}"},
                            {"ledger_id": asset_ledger_id, "debit": 0, "credit": req.amount, "line_description": f"เงินออกจากบัญชี: {req.account_id}"},
                        ]
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="manual_transaction",
                        reference_id=str(new_tx_id),
                        description=req.description,
                        slip_image_url=req.slip_image_url,
                        recorded_by=req.user_name,
                        metadata={"legacy_transaction_id": new_tx_id},
                        lines=lines,
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: มีรายรับ/รายจ่ายใหม่ (ไม่ @everyone — แค่โชว์ความโปร่งใส)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_new_finance(
                    server_id=room_server_id,
                    txn_type=req.transaction_type,
                    amount=float(req.amount),
                    description=req.description,
                    user_name=req.user_name,
                )
            return {"status": "success", "message": "บันทึกรายการสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def transfer_money(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        if req.from_account_id == req.to_account_id: raise ValueError("โอนเงินเข้าบัญชีเดิมไม่ได้!")

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        req.from_account_id, target_room_id
                    )
                    if current_balance is None: raise RoomNotFoundError("ไม่พบบัญชีต้นทาง")
                    # Decimal vs float — cast float() ทั้งสองฝั่ง (ลบ binary noise) ก่อนเทียบ
                    if float(current_balance) < float(req.amount): raise ValueError("ยอดเงินในบัญชีต้นทางไม่เพียงพอ!")

                    # 🛡️ กันการโอนเงินข้ามห้อง (cross-room leak): ต้องเช็คบัญชีปลายทางด้วย
                    if not await conn.fetchval(
                        "SELECT 1 FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        req.to_account_id, target_room_id
                    ):
                        raise RoomNotFoundError("ไม่พบบัญชีปลายทาง")

                    group_id = await conn.fetchval("SELECT nextval('transfer_group_id_seq')")
                    
                    await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.from_account_id)
                    # [DUAL-WRITE] ดึง id ของ legacy transaction ขาออก เพื่อเก็บใน journal metadata
                    tx_from_id = await conn.fetchval(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by)
                           VALUES ($1, $2, $3, $4, 'expense', $5, $6) RETURNING id""",
                        target_room_id, req.from_account_id, req.amount, f"โอนออก: {req.description}", group_id, req.user_name
                    )

                    await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.to_account_id)
                    # [DUAL-WRITE] ดึง id ของ legacy transaction ขาเข้า เพื่อเก็บใน journal metadata
                    tx_to_id = await conn.fetchval(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by)
                           VALUES ($1, $2, $3, $4, 'income', $5, $6) RETURNING id""",
                        target_room_id, req.to_account_id, req.amount, f"รับโอน: {req.description}", group_id, req.user_name
                    )

                    # [DUAL-WRITE] เขียนฝั่ง Double-Entry: ย้ายเงินระหว่างบัญชีสินทรัพย์ (Dr ปลายทาง / Cr ต้นทาง)
                    # เก็บ transfer_group_id + legacy_transaction_id ทั้งสองข้างไว้ใน metadata → revert ยกเลิกได้ทั้งกลุ่ม
                    ledger_id_from = await cls._resolve_asset_ledger(conn, target_room_id, req.from_account_id)
                    ledger_id_to = await cls._resolve_asset_ledger(conn, target_room_id, req.to_account_id)
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="transfer",
                        reference_id=str(group_id),
                        description=req.description or "Transfer",
                        recorded_by=req.user_name,
                        metadata={
                            "transfer_group_id": group_id,
                            "legacy_transaction_id": tx_from_id,
                            "legacy_transaction_ids": [tx_from_id, tx_to_id],
                        },
                        lines=[
                            {"ledger_id": ledger_id_to, "debit": req.amount, "credit": 0, "line_description": f"รับโอนเข้าบัญชี: {req.to_account_id}"},
                            {"ledger_id": ledger_id_from, "debit": 0, "credit": req.amount, "line_description": f"โอนออกจากบัญชี: {req.from_account_id}"},
                        ],
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", entity_id=str(group_id), status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "โอนเงินสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_transactions(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                # [ROUTER] แบ่งอ่านตามยุคของช่วงที่ขอ (CUTOFF_DATE = 2026-09-01):
                #   - ทั้งช่วงก่อนเส้นตัด        → legacy (finance_transactions)
                #   - เริ่มที่/หลังเส้นตัด        → บัญชีคู่ (journal) 100%
                #   - "ทั้งหมด" (ไม่กรอง) / คร่อมเส้น → MERGE: legacy < 1 ก.ย. + journal >= 1 ก.ย.
                # (เหตุผล: หลังวันที่ตัด ข้อมูลมีใน journal เป็นหลัก — อ่าน legacy เฉพาะข้อมูลเก่า)
                if start_date is None and end_date is None:
                    return await cls._get_transactions_merged(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )

                period_start = start_date or date.min
                if period_start >= CUTOFF_DATE:
                    # [ROUTER] ขอข้อมูลหลังวันที่ตัด → อ่านจาก journal_entries/journal_lines
                    return await cls._get_transactions_v2(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                if end_date is not None and end_date < CUTOFF_DATE:
                    # [ROUTER] ทั้งช่วงก่อนวันที่ตัด → อ่านจากตารางเก่า
                    return await cls._get_transactions_legacy(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                # [ROUTER] ช่วงคร่อมเส้นตัด / ระบุแค่ start_date (ปลายเปิด) → MERGE 2 ยุค
                return await cls._get_transactions_merged(
                    conn=conn, room_id=target_room_id,
                    limit=limit, offset=offset,
                    start_date=start_date, end_date=end_date,
                    account_id=account_id, category_id=category_id,
                    transaction_type=transaction_type,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _fetch_legacy_items(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        max_date_cap: Optional[date] = None,
    ) -> List[dict]:
        """[ROUTER-LEGACY] ดึงแถว finance_transactions ของห้องแบบไม่จำกัดหน้า (LIMIT) —
        ใช้ร่วมกันโดย legacy worker (แล้ว slice เอง) และ merge (บังคับ cap ก่อนเส้นตัด).
        max_date_cap: ถ้าตั้ง → บังคับ DATE(T.created_at) <= cap (merge ใช้ cap = วันก่อน CUTOFF_DATE)"""
        where_clause = "WHERE T.room_id = $1 AND T.deleted_at IS NULL"
        params = [room_id]
        param_idx = 2

        if start_date:
            where_clause += f" AND DATE(T.created_at) >= ${param_idx}"
            params.append(start_date); param_idx += 1
        effective_end = end_date
        if max_date_cap is not None and (effective_end is None or max_date_cap < effective_end):
            effective_end = max_date_cap
        if effective_end is not None:
            where_clause += f" AND DATE(T.created_at) <= ${param_idx}"
            params.append(effective_end); param_idx += 1
        if account_id:
            where_clause += f" AND T.account_id = ${param_idx}"
            params.append(account_id); param_idx += 1
        if category_id:
            where_clause += f" AND T.category_id = ${param_idx}"
            params.append(category_id); param_idx += 1
        if transaction_type:
            where_clause += f" AND T.transaction_type = ${param_idx}"
            params.append(transaction_type); param_idx += 1

        rows = await conn.fetch(f"""
            SELECT
                T.id, T.amount, T.description, T.transaction_type, T.created_at,
                T.slip_image_url, T.recorded_by, T.transfer_group_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            {where_clause}
            ORDER BY T.created_at DESC, T.id DESC
        """, *params)
        return [dict(row) for row in rows]

    @classmethod
    async def _get_transactions_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-LEGACY] ประวัติฝั่ง Single-Entry — ดึงทั้งชุดแล้ว slice ที่ฝั่ง Python
        (volume ห้องเรียนเล็ก; ทำให้ legacy/v2/merge ใช้ pagination แบบเดียวกัน)"""
        items = await cls._fetch_legacy_items(
            conn=conn, room_id=room_id,
            start_date=start_date, end_date=end_date,
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
        )
        result = {"total_count": len(items), "items": items[offset:offset + limit]}

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return result

    @classmethod
    async def _get_transactions_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """อ่านประวัติจากระบบบัญชีคู่ (journal_entries + journal_lines) แล้วจัดรูป
        ให้เหมือน legacy (TransactionResponse) เพื่อ frontend ไม่ต้องแก้เลย.

        หลักการจัดประเภท (ตามสเปค Phase 4):
        - income  : สินทรัพย์ เดบิต>0  + บัญชีรายได้ เครดิต>0  (รับเงินเข้า)
        - expense : สินทรัพย์ เครดิต>0 + บัญชีค่าใช้จ่าย เดบิต>0 (เงินออก)
        - transfer: สินทรัพย์ 2 บัญชี (ฝั่งหนึ่ง เดบิต>0 / อีกฝั่ง เครดิต>0)
        - opening_balance: แสดงเป็น income (เงินเข้า Asset) — ยอด = เดบิตฝั่ง Asset
        """
        where_cond, params = ["JE.room_id = $1 AND JE.deleted_at IS NULL"], [room_id]
        idx = 2
        if start_date:
            where_cond.append(f"DATE(JE.transaction_date) >= ${idx}"); params.append(start_date); idx += 1
        if end_date:
            where_cond.append(f"DATE(JE.transaction_date) <= ${idx}"); params.append(end_date); idx += 1
        if account_id:
            # [DOUBLE-ENTRY] กรองด้วยบัญชีสินทรัพย์: journal ใดก็ตามที่ asset ledger นี้มีบทบาท (Dr หรือ Cr)
            where_cond.append(f"""
                EXISTS (
                    SELECT 1 FROM journal_lines JLx
                    JOIN accounting_ledgers ALx ON JLx.ledger_id = ALx.id
                    WHERE JLx.journal_entry_id = JE.id AND ALx.room_id = $1
                      AND ALx.legacy_account_id = ${idx} AND (JLx.debit > 0 OR JLx.credit > 0)
                )""")
            params.append(account_id); idx += 1
        if category_id:
            # [DOUBLE-ENTRY] กรองด้วยหมวดหมู่ (revenue/expense): journal ที่ ledger นั้นมีบทบาท
            where_cond.append(f"""
                EXISTS (
                    SELECT 1 FROM journal_lines JLx2
                    JOIN accounting_ledgers ALx2 ON JLx2.ledger_id = ALx2.id
                    WHERE JLx2.journal_entry_id = JE.id AND ALx2.room_id = $1
                      AND ALx2.legacy_category_id = ${idx} AND (JLx2.debit > 0 OR JLx2.credit > 0)
                )""")
            params.append(category_id); idx += 1

        # [DOUBLE-ENTRY] ยกทุกบรรทัดของ journal ที่ผ่าน filter ขึ้นมา (หลายบรรทัดต่อ 1 บิล)
        # แล้วจัดประเภทที่ฝั่ง Python (อ่านง่ายกว่า SQL หลายชั้น)
        data_sql = f"""
            SELECT
                JE.id AS journal_entry_id,
                JE.reference_type, JE.reference_id,
                JE.description AS entry_description,
                JE.transaction_date, JE.recorded_by,
                JE.slip_image_url, JE.metadata,
                L.id AS line_id, L.debit, L.credit, L.line_description,
                AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                AL.legacy_account_id, AL.legacy_category_id
            FROM journal_entries JE
            JOIN journal_lines L ON L.journal_entry_id = JE.id
            JOIN accounting_ledgers AL ON L.ledger_id = AL.id
            WHERE {' AND '.join(where_cond)}
              AND JE.status <> 'voided'
            ORDER BY JE.transaction_date DESC, JE.id DESC
        """
        rows = await conn.fetch(data_sql, *params)

        # [DOUBLE-ENTRY] กลุ่มบรรทัดตามหัวบิล
        entries: Dict[str, dict] = {}
        for r in rows:
            entry_id = str(r["journal_entry_id"])
            if entry_id not in entries:
                entries[entry_id] = {
                    "journal_entry_id": entry_id,
                    "reference_type": r["reference_type"],
                    "reference_id": r["reference_id"],
                    "description": r["entry_description"],
                    "transaction_date": r["transaction_date"],
                    "recorded_by": r["recorded_by"],
                    "slip_image_url": r["slip_image_url"],
                    "metadata": r["metadata"] or {},
                    "lines": [],
                }
            entries[entry_id]["lines"].append(r)

        # [DOUBLE-ENTRY] แปลงแต่ละบิล → TransactionResponse
        # 📌 หมายเหตุเรื่อง id: TransactionResponse.id เป็น int และ frontend ใช้เรียก
        # revert_transaction (ซึ่งค้นจาก finance_transactions.id) → สังเคราะห์จาก legacy
        # transaction id ใน metadata; ถ้าไม่มี (เช่น opening_balance) ใช้ค่าลบจาก UUID
        # เพื่อให้คอลัมน์มีค่าไม่ซ้ำกัน (เป็น id ที่ "ไม่ใช้ได้จริง" กับ revert)
        items: List[dict] = []
        for entry in entries.values():
            txn = cls._classify_journal_entry(entry, transaction_type)
            if txn is None:
                continue  # ถูกกรองด้วย transaction_type ด้านบนแล้ว
            items.append(txn)

        # [DOUBLE-ENTRY] จำลอง pagination ฝั่ง application (ชุดข้อมูลนี้เล็ก —
        # ต่อบิลมีแค่ 2-3 บรรทัด) เพื่อคง API เดิม (limit/offset + total_count)
        total_count = len(items)
        paged = items[offset:offset + limit]

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return {"total_count": total_count, "items": paged}

    @classmethod
    async def _get_transactions_merged(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-MERGE] ประวัติที่ครอบ 2 ยุค (ขอ "ทั้งหมด" หรือช่วงคร่อมเส้นตัด):
        legacy < CUTOFF_DATE + journal >= CUTOFF_DATE นำมารวม เรียง created_at DESC.

        แบ่งที่เส้นกัน dual-write เบิ้ล: legacy ถูก cap ที่ DATE <= วันก่อน 1 ก.ย.,
        journal ถูก floor ที่ DATE >= 1 ก.ย. (dual-write ใช้ timestamp เดียวกันทั้ง 2 ตาราง
        → แต่ละรายการจะโผล่จากฝั่งเดียวเท่านั้น)
        """
        # [MERGE] ฝั่ง legacy: เฉพาะวันที่ < CUTOFF_DATE (DATE <= 2026-08-31)
        legacy_res = await cls._get_transactions_legacy(
            conn=conn, room_id=room_id,
            limit=1_000_000, offset=0,
            start_date=start_date, end_date=CUTOFF_DATE - timedelta(days=1),
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,  # ไม่ log ที่ worker (log รวมที่ merged)
        )
        # [MERGE] ฝั่ง journal: วันที่ >= CUTOFF_DATE (floor start ที่ 1 ก.ย.)
        journal_start = start_date if (start_date is not None and start_date >= CUTOFF_DATE) else CUTOFF_DATE
        v2_res = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=1_000_000, offset=0,
            start_date=journal_start, end_date=end_date,
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,
        )
        # [MERGE] รวม + เรียง DESC (Python stable → ลำดับภายในฝั่งเดียวกันคงเดิม),
        # normalize tz ก่อน sort (legacy naive ↔ journal aware)
        merged = sorted(
            legacy_res["items"] + v2_res["items"],
            key=lambda it: _naive_thai_dt(it["created_at"]),
            reverse=True,
        )
        paged = merged[offset:offset + limit]

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return {"total_count": len(merged), "items": paged}

    @classmethod
    async def revert_transaction(cls, pool: asyncpg.Pool, transaction_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    t = await conn.fetchrow(
                        "SELECT * FROM finance_transactions WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        transaction_id, target_room_id
                    )
                    if not t: raise TransactionNotFoundError("ไม่พบรายการธุรกรรมนี้")

                    # [FIX B] Freeze Legacy: รายการที่สร้างก่อนวันที่ขึ้นระบบบัญชีคู่ (CUTOFF_DATE)
                    # ไม่มี journal ให้ void ได้ → ห้ามยกเลิกเด็ดขาด (ให้บันทึกรายจ่ายปรับปรุงยอดแทน)
                    # กันการ "ย้อน legacy ฝั่งเดียว" จนยอด 2 ระบบเบี้ยวซ้ำอีก (guard ก่อนแตะ balance)
                    cutoff_dt = datetime.combine(CUTOFF_DATE, dtime.min)
                    freeze_msg = ("ไม่สามารถยกเลิกรายการก่อนขึ้นระบบบัญชีคู่ได้ "
                                  "ให้ใช้วิธีบันทึกรายจ่ายปรับปรุงยอดแทน")
                    if t['transfer_group_id']:
                        earliest = await conn.fetchval(
                            """SELECT MIN(created_at) FROM finance_transactions
                               WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            t['transfer_group_id'], target_room_id,
                        )
                        if earliest is not None and _naive_thai_dt(earliest) < cutoff_dt:
                            raise ValueError(freeze_msg)
                    elif _naive_thai_dt(t['created_at']) < cutoff_dt:
                        raise ValueError(freeze_msg)

                    old_values = dict(t)

                    if t['transfer_group_id']:
                        group_trans = await conn.fetch("SELECT * FROM finance_transactions WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE", t['transfer_group_id'], target_room_id)
                        for gt in group_trans:
                            if gt['transaction_type'] == 'expense': 
                                await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", gt['amount'], gt['account_id'])
                            elif gt['transaction_type'] == 'income':
                                curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", gt['account_id'])
                                if float(curr_bal) < float(gt['amount']): raise ValueError("เงินในบัญชีรับโอนไม่พอหักคืน")
                                await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", gt['amount'], gt['account_id'])
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE transfer_group_id = $1 AND room_id = $2", t['transfer_group_id'], target_room_id)
                        # [DUAL-WRITE] ยกเลิก journal ของรายการโอนเงิน (หาด้วย metadata.transfer_group_id)
                        # 💡 ถ้ายังไม่มี journal (ข้อมูลเก่าที่ไม่ได้ผ่าน dual-write) → no-op ไม่พัง
                        await conn.execute(
                            """UPDATE journal_entries
                               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
                               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                                 AND metadata->>'transfer_group_id' = $2""",
                            target_room_id, str(t['transfer_group_id']),
                        )
                        action_detail = "ยกเลิกรายการโอนเงิน"
                    else:
                        if t['transaction_type'] == 'income':
                            curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", t['account_id'])
                            if float(curr_bal) < float(t['amount']): raise ValueError("เงินในบัญชีไม่พอหักคืน")
                            await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", t['amount'], t['account_id'])
                            
                            if t['student_payment_id']:
                                sp_id = t['student_payment_id']
                                sp_info = await conn.fetchrow("SELECT paid_amount, FC.amount as total_amount FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id WHERE SP.id = $1 FOR UPDATE", sp_id)
                                new_paid = float(sp_info['paid_amount']) - float(t['amount'])
                                new_status = 'paid' if new_paid >= float(sp_info['total_amount']) else 'pending'
                                # 💡 ถ้ายกเลิกจน paid_amount กลับเป็น 0 ให้ล้าง field การชำระทั้งหมด
                                # (กันสถานะ "จ่ายครบ" ค้างทั้งที่ยอดโดนหักคืนแล้ว)
                                if new_paid <= 0:
                                    await conn.execute(
                                        """UPDATE student_payments
                                           SET paid_amount = 0, status = 'pending', paid_to_account_id = NULL,
                                               slip_image_url = NULL, recorded_by = NULL, paid_at = NULL, transaction_id = NULL
                                           WHERE id = $1""", sp_id
                                    )
                                else:
                                    await conn.execute("UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3", new_paid, new_status, sp_id)

                        elif t['transaction_type'] == 'expense': 
                            await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", t['amount'], t['account_id'])
                        
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", transaction_id)
                        # [DUAL-WRITE] ยกเลิก journal ของรายการปกติ (หาด้วย metadata.legacy_transaction_id)
                        # 💡 ถ้ายังไม่มี journal (ข้อมูลเก่า/จาก test ที่ insert ตรง) → no-op ไม่พัง
                        await conn.execute(
                            """UPDATE journal_entries
                               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
                               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                                 AND metadata->>'legacy_transaction_id' = $2""",
                            target_room_id, str(transaction_id),
                        )
                        action_detail = f"ยกเลิกรายการ {t['transaction_type']}"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="success",
                        old_values=old_values, new_values={"action": action_detail}, endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": action_detail}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
