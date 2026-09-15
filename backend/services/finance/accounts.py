"""กระเป๋าเงิน / บัญชี (finance_accounts)"""
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
from .base import _lock_room_money, service_logger


# 🏦 [F6] ฟิลด์ของกระเป๋าเงินที่ PATCH แก้ได้ — **allowlist เดียวในระบบ**
# 🔴 ต้องเป็น allowlist ไม่ใช่ "ทุกคีย์ที่ส่งมา": ชื่อคอลัมน์ถูกต่อเข้าไปใน SQL
#    (ดู `update_account`) ⇒ ถ้ารับคีย์อิสระ เท่ากับเปิดให้ผู้ใช้กำหนด SQL เอง
# ⚠️ `user_name` **ไม่อยู่ในลิสต์** โดยเจตนา — มันเป็นชื่อผู้ทำรายการ (audit) ไม่ใช่ข้อมูลกระเป๋า
_ACCOUNT_PATCHABLE = (
    "account_name", "account_kind",
    "bank_name", "bank_account_no", "bank_account_name",
)


class AccountsMixin:
    @classmethod
    async def create_account(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)
                    
                    # [DUAL-WRITE] ดึง id ของแถว legacy เพื่อ map ลง accounting_ledgers
                    # 🏦 [F6] ช่องทางจ่ายเงินถูกบันทึก **พร้อมกันตอนสร้าง** ไม่ใช่แก้ทีหลัง
                    #    ⇒ ใบสำคัญจ่ายที่ออกให้รายการแรกของกระเป๋าใบนั้นก็รู้ช่องทางแล้ว
                    new_account_id = await conn.fetchval(
                        "INSERT INTO finance_accounts"
                        " (room_id, account_name, balance, account_kind,"
                        "  bank_name, bank_account_no, bank_account_name)"
                        " VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                        target_room_id, req.account_name, req.initial_balance,
                        req.account_kind or "cash",
                        req.bank_name, req.bank_account_no, req.bank_account_name,
                    )

                    # [DUAL-WRITE] สร้าง ledger ฝั่ง Double-Entry (asset 1xxxx) ภายใน transaction เดียวกัน
                    # รหัสบัญชี '1' || LPAD(id, 4, '0') — ตรงกับ migrate_phase2_ledgers.py
                    await conn.execute(
                        """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description)
                           VALUES ($1, $2, $3, 'asset', $4, 'Created via dual-write (create_account)')""",
                        target_room_id, f"1{new_account_id:04d}", req.account_name, new_account_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"สร้างบัญชี {req.account_name} สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_accounts(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                # 🏦 [F6] ส่งช่องทางจ่ายเงินออกไปด้วย — หน้าจอใช้แสดงชิป "เงินสด/โอน"
                #    ⚠️ ต้องประกาศใน `AccountResponse` ด้วย ไม่งั้น `response_model` ตัดทิ้งเงียบ ๆ
                rows = await conn.fetch(
                    "SELECT id, account_name, balance, account_kind,"
                    " bank_name, bank_account_no, bank_account_name"
                    " FROM finance_accounts WHERE room_id = $1 ORDER BY id",
                    target_room_id
                )
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="success",
                    endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_account(cls, pool: asyncpg.Pool, account_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)

                    # ══ 🏦 [F6] PATCH จริง: แก้เฉพาะฟิลด์ที่ส่งมา ──────────────────────
                    # 🔴 เดิมโค้ดนี้ตั้ง `account_name` ตรง ๆ จาก req เสมอ ⇒ เพิ่มช่องทางจ่าย
                    #    (เงินสด/โอน + ธนาคาร) เข้ามาแล้ว **แก้ช่องทางโดยไม่แตะชื่อไม่ได้**
                    #    เว้นแต่ frontend จะส่งชื่อเดิมกลับมา ซึ่งพังเงียบเมื่อชื่อถูกแก้ที่อื่น
                    # ⚠️ `exclude_unset` แปลว่า "ส่ง `null` มา" = **ตั้งใจล้างค่านั้น**
                    #    ⇒ การส่ง `null` ต้องไม่กลายเป็น "ไม่แตะ" โดยบังเอิญ
                    patch = {
                        k: v for k, v in req.model_dump(exclude_unset=True).items()
                        if k in _ACCOUNT_PATCHABLE
                    }
                    if not patch:
                        raise ValueError("ไม่มีข้อมูลที่จะแก้ไข")
                    # 🔴 ชื่อกระเป๋าเป็น NOT NULL ⇒ ส่ง `null` มาแล้วเขียนตาม = NotNullViolation
                    #    = 500 แทนที่จะเป็นคำตอบที่อ่านออก · ตีความ `null` ที่ชื่อว่า "ไม่แตะชื่อ"
                    #    (จะ "ล้างชื่อ" ไม่ได้โดยธรรมชาติของคอลัมน์ ไม่ใช่เพราะโค้ดนี้ปิดกั้น)
                    if patch.get("account_name") is not None:
                        patch["account_name"] = patch["account_name"].strip()
                        if not patch["account_name"]:
                            raise ValueError("ต้องระบุชื่อกระเป๋าเงิน")
                    else:
                        patch.pop("account_name", None)

                    # ⚠️ f-string เฉพาะ **ชื่อคอลัมน์** ซึ่งมาจาก `_ACCOUNT_PATCHABLE`
                    #    (ค่าคงที่ในไฟล์นี้) ไม่ใช่จาก request — **ค่าทุกค่าเป็น `$n` เสมอ**
                    #    ⇒ ยังคงกฎ "ห้าม f-string SQL" ในความหมายที่สำคัญ: ผู้ใช้กำหนด SQL ไม่ได้
                    set_parts, params = [], [account_id, target_room_id]
                    for col, val in patch.items():
                        params.append(val)
                        set_parts.append(f"{col} = ${len(params)}")
                    res = await conn.execute(
                        f"UPDATE finance_accounts SET {', '.join(set_parts)}"
                        f" WHERE id = $1 AND room_id = $2",
                        *params
                    )
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบบัญชีนี้")

                    # [DUAL-WRITE] ซิงก์ชื่อไปยัง accounting_ledgers (ถ้ามี) — กัน ledger ค้างชื่อเก่า
                    # 🚫 เรียกเฉพาะเมื่อ **ชื่อถูกแก้จริง** — คำสั่งเดิมเขียนทับด้วยชื่อเดิมทุกครั้ง
                    #    (ไม่ผิด แต่ทำให้ `updated_at` ของ ledger ขยับทั้งที่ไม่มีอะไรเปลี่ยน)
                    if "account_name" in patch:
                        await conn.execute(
                            "UPDATE accounting_ledgers SET account_name = $1, updated_at = CURRENT_TIMESTAMP WHERE legacy_account_id = $2 AND room_id = $3",
                            patch["account_name"], account_id, target_room_id
                        )

                    # 📝 audit บันทึก **สิ่งที่ถูกเขียนจริง** (patch) ไม่ใช่ทั้ง req
                    #    ⇒ อ่าน log แล้วรู้ทันทีว่าคำขอนี้แก้ช่องทางหรือแก้ชื่อ โดยไม่ต้องเดา
                    new_values = cls._extract_req_data(patch)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_account(cls, pool: asyncpg.Pool, account_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)
                    
                    bal = old_data['balance']
                    if bal > 0: raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากยังมีเงินคงเหลืออยู่!")
                    if await conn.fetchval("SELECT 1 FROM student_payments WHERE paid_to_account_id = $1 LIMIT 1", account_id):
                        raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติการรับเงินผูกกับบัญชีนี้อยู่!")
                    # 🛡️ กันประวัติธุรกรรมหาย: ถ้ามี finance_transactions อ้างถึงบัญชีนี้ ห้าม hard-delete
                    # (FK account_id ON DELETE SET NULL → ประวัติรายรับ/รายจ่ายจะกลายเป็น NULL)
                    if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE account_id = $1 LIMIT 1", account_id):
                        raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติธุรกรรมผูกกับบัญชีนี้!")

                    await conn.execute("DELETE FROM finance_accounts WHERE id = $1", account_id)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
