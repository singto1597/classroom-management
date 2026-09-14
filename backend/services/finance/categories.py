"""หมวดหมู่รายรับ-รายจ่าย (finance_categories)"""
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


class CategoriesMixin:
    @classmethod
    async def create_category(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
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
                    new_category_id = await conn.fetchval(
                        "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
                        target_room_id, req.category_name, req.category_type
                    )

                    # [DUAL-WRITE] สร้าง ledger ฝั่ง Double-Entry (income → 'revenue' 4xxxx, expense → 5xxxx)
                    # รหัสบัญชีตรงกับ migrate_phase2_ledgers.py
                    if req.category_type == 'income':
                        ledger_type, ledger_code = 'revenue', f"4{new_category_id:04d}"
                    else:
                        ledger_type, ledger_code = 'expense', f"5{new_category_id:04d}"
                    await conn.execute(
                        """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_category_id, description)
                           VALUES ($1, $2, $3, $4, $5, 'Created via dual-write (create_category)')""",
                        target_room_id, ledger_code, req.category_name, ledger_type, new_category_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"เพิ่มหมวดหมู่ {req.category_name} แล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_categories(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, cat_type: Optional[str] = None, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                # 🗑️ กรอง `deleted_at IS NULL` — หมวดที่ถูกลบ (soft delete) ต้องหายจากรายการนี้
                #    ไม่ใช่แค่ซ่อนฝั่ง frontend ไม่งั้นมันจะโผล่มาให้เลือกใน dropdown แล้ว
                #    ผู้ใช้สร้างรายการใหม่ผูกกับหมวดที่ "ลบไปแล้ว"
                if cat_type:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 AND category_type = $2 AND deleted_at IS NULL ORDER BY id", target_room_id, cat_type)
                else:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 AND deleted_at IS NULL ORDER BY id", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="success",
                    endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_category(cls, pool: asyncpg.Pool, category_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)
                    
                    # 🗑️ `deleted_at IS NULL` — ห้ามแก้ชื่อหมวดที่ถูกลบไปแล้ว (มันไม่โผล่ใน UI แล้ว
                    #    การแก้ได้จะทำให้ประวัติ/ledger ที่อ้างชื่อนี้เล่าไม่ตรงกัน)
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    res = await conn.execute("UPDATE finance_categories SET category_name = $1 WHERE id = $2 AND room_id = $3", req.category_name, category_id, target_room_id)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")

                    # [DUAL-WRITE] ซิงก์ชื่อไปยัง accounting_ledgers (ถ้ามี) — กัน ledger ค้างชื่อเก่า
                    await conn.execute(
                        "UPDATE accounting_ledgers SET account_name = $1, updated_at = CURRENT_TIMESTAMP WHERE legacy_category_id = $2 AND room_id = $3",
                        req.category_name, category_id, target_room_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_category(cls, pool: asyncpg.Pool, category_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE category_id = $1 LIMIT 1", category_id):
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากมีการใช้หมวดหมู่นี้อยู่!")
                    # 🛡️ [F2] guard คู่กับ FK `ON DELETE RESTRICT` ของ finance_budgets
                    #    ตัว FK กันข้อมูลพังได้จริง แต่ถ้าปล่อยให้มันทำงานก่อน จะได้
                    #    `ForeignKeyViolationError` ดิบทะลุเป็น HTTP 500 แทนที่จะเป็น 400 ที่อ่านรู้เรื่อง
                    #
                    # ⚠️ นับ **ทุกแถวรวมที่ soft delete แล้ว** (ไม่ใส่ `deleted_at IS NULL`) — ตั้งใจ
                    #    FK ของ `finance_budgets.category_id` เป็น NOT NULL + RESTRICT ⇒
                    #    ลบหมวดที่ "เคย" มีงบไม่ได้เลยไม่ว่าจะลบงบไปแล้วหรือยัง
                    #    ถ้ากรองแค่ `deleted_at IS NULL` จะเจอเคส: ผู้ใช้ลบงบ (หายจากหน้าจอแล้ว)
                    #    → กดลบหมวด → guard ผ่าน → FK ระเบิดเป็น 500 ที่ไม่มีใครอธิบายได้
                    #    ⇒ ให้ guard สื่อความจริงข้อเดียวกันกับ FK เถอะ
                    #    (เข้าท่าเดียวกับ guard `finance_transactions` ข้างบนซึ่งก็เป็น "เคยใช้" เช่นกัน)
                    if await conn.fetchval("SELECT 1 FROM finance_budgets WHERE category_id = $1 LIMIT 1", category_id):
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากมีงบประมาณผูกอยู่!")

                    # 🗑️ [SOFT DELETE] ไม่ใช่ `DELETE FROM` — เปลี่ยนเมื่อ 2026-09-13
                    #
                    # ทำไม: `accounting_ledgers.legacy_category_id` และ `finance_transactions.category_id`
                    # เป็น FK `ON DELETE SET NULL` ⇒ การ hard delete **ไม่ได้ลบประวัติ** แต่ "ตัดสาย mapping" ทิ้ง:
                    # ledger ที่ผูกหมวดนี้กลายเป็น orphan (`legacy_category_id = NULL`) และพอสร้างหมวด
                    # ชื่อเดิมใหม่ `create_category` จะออก ledger รหัสใหม่ (`4{id:04d}` ตาม id ใหม่)
                    # ⇒ ผังบัญชีคู่มี ledger ชื่อซ้ำสองตัวโดยไม่มีอะไรเชื่อมถึงกัน = ข้อมูลเบี้ยวถาวร
                    # แถม `finance_categories.deleted_at` มีอยู่ในสคีมาตั้งแต่แรกและ **ไม่เคยถูกเขียนเลย**
                    #
                    # ปลอดภัยเพราะ guard สองตัวข้างบนรับประกันว่าหมวดที่จะถูกลบ **ไม่มี**
                    # `finance_transactions` และ **ไม่มี** `finance_budgets` ผูกอยู่เลย ⇒
                    # `get_categories` ที่กรอง `deleted_at IS NULL` เป็นที่เดียวที่พฤติกรรมเปลี่ยน
                    # (transactions.py:333 ยังใช้ LEFT JOIN แบบไม่กรอง เพื่อให้ประวัติโชว์ชื่อหมวดเดิมได้)
                    #
                    # ⚠️ `AND deleted_at IS NULL` ทำให้กดซ้ำไม่ error และ **ไม่ทับเวลาเดิม** (idempotent)
                    res = await conn.execute(
                        "UPDATE finance_categories SET deleted_at = NOW() WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        category_id, target_room_id
                    )
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
