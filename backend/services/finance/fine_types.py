"""ประเภทความผิด / อัตราค่าปรับ (`fine_types`) — Phase 3

🎯 แยกอัตราต่อห้อง แก้ไขได้ · seed 5 รายการให้ห้องใหม่ผ่าน `ensure_default_fine_types`
   (migration 0010 seed ให้ห้องที่มีอยู่ก่อน deploy แล้ว)
⚠️ ประเภทที่ผู้ใช้ลบจะ **ไม่ถูก seed กลับ** — `ensure_default_fine_types` ทำงานเฉพาะ
   ห้องที่ยังไม่เคยมีแถวเลย (นับรวม soft-deleted) ⇒ การลบเป็นเจตนาของผู้ใช้
"""
from __future__ import annotations

import time
from typing import List, Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
from .constants import DEFAULT_FINE_TYPES


class FineTypesMixin:
    # =================================================================
    # seed (เรียกจาก room_service ตอนสร้างห้อง — ไม่ได้ยึด lock เอง)
    # =================================================================
    @classmethod
    async def ensure_default_fine_types(
        cls, conn: asyncpg.Connection, room_id: int
    ) -> int:
        """seed 5 ประเภทเริ่มต้นให้ห้องที่ยังไม่เคยมี `fine_types` เลย — คืนจำนวนที่เพิ่ม

        ⚠️ ต้องอยู่ใน transaction ของผู้เรียก (room_service สร้างห้อง) —
           ไม่เปิด transaction เอง เพื่อให้ห้อง + หมวด + บัญชี + ประเภท เป็นชุดเดียว
        """
        existing = await conn.fetchval(
            "SELECT 1 FROM fine_types WHERE room_id = $1 LIMIT 1", room_id
        )
        if existing:
            return 0
        rows = [
            (room_id, t["name"], t["default_amount"], t["default_due_days"],
             t["description"], t["sort_order"])
            for t in DEFAULT_FINE_TYPES
        ]
        await conn.executemany(
            """INSERT INTO fine_types
                   (room_id, name, default_amount, default_due_days, description, sort_order)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            rows,
        )
        return len(rows)

    # =================================================================
    # อ่าน
    # =================================================================
    @classmethod
    async def get_fine_types(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None, active_only: bool = False,
    ) -> List[dict]:
        target_room_id = room_id
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            cond = "AND is_active = TRUE" if active_only else ""
            rows = await conn.fetch(
                f"""SELECT id, name, default_amount, default_due_days, description,
                           is_active, sort_order
                    FROM fine_types
                    WHERE room_id = $1 AND deleted_at IS NULL {cond}
                    ORDER BY sort_order ASC, id ASC""",
                target_room_id,
            )
        return [
            {
                "id": r["id"], "name": r["name"],
                "default_amount": float(r["default_amount"]),
                "default_due_days": r["default_due_days"],
                "description": r["description"], "is_active": r["is_active"],
                "sort_order": r["sort_order"],
            }
            for r in rows
        ]

    # =================================================================
    # เขียน
    # =================================================================
    @classmethod
    async def create_fine_type(
        cls, pool: asyncpg.Pool, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    # 🔒 อัตราเป็นตัวกำหนดยอดค่าปรับที่ออกในอนาคต — ยึดล็อกห้องเดียวกับ
                    #    เส้นทางเงินเพื่อให้การเปลี่ยนอัตรากับการออกค่าปรับไม่มีช่วงแข่งกัน
                    await _lock_room_money(conn, target_room_id)
                    new_id = await conn.fetchval(
                        """INSERT INTO fine_types
                               (room_id, name, default_amount, default_due_days,
                                description, sort_order)
                           VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                        target_room_id, req.name, req.default_amount,
                        req.default_due_days, req.description, req.sort_order,
                    )
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", entity_id=str(new_id), status="success",
                        new_values=cls._extract_req_data(req),
                        endpoint_or_command="FinanceService.create_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {"status": "success", "message": f"เพิ่มประเภทความผิด {req.name} แล้ว", "id": new_id}
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_fine_type(
        cls, pool: asyncpg.Pool, fine_type_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """PATCH — `amount` เป็น **อัตราเริ่มต้น** ของประเภท ไม่กระทบบิลที่ออกไปแล้ว"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)
                    old = await conn.fetchrow(
                        "SELECT * FROM fine_types WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        fine_type_id, target_room_id,
                    )
                    if not old:
                        raise RoomNotFoundError("ไม่พบประเภทความผิดนี้")

                    data = req.model_dump(exclude_unset=True)
                    allowed = {"name", "default_amount", "default_due_days",
                               "description", "sort_order", "is_active"}
                    sets, values, idx = [], [], 1
                    for key in allowed:
                        if key in data:
                            sets.append(f"{key} = ${idx}")
                            values.append(data[key])
                            idx += 1
                    if not sets:
                        return {"status": "success", "message": "ไม่มีข้อมูลให้เปลี่ยนแปลง"}
                    values.extend([fine_type_id, target_room_id])
                    res = await conn.execute(
                        f"""UPDATE fine_types SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ${idx} AND room_id = ${idx + 1} AND deleted_at IS NULL""",
                        *values,
                    )
                    if res == "UPDATE 0":
                        raise RoomNotFoundError("ไม่พบประเภทความผิดนี้")
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", entity_id=str(fine_type_id), status="success",
                        old_values=dict(old), new_values=data,
                        endpoint_or_command="FinanceService.update_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {"status": "success", "message": "อัปเดตประเภทความผิดสำเร็จ"}
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", entity_id=str(fine_type_id), status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.update_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_fine_type(
        cls, pool: asyncpg.Pool, fine_type_id: int, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """soft delete — บิลที่เคยออกด้วยประเภทนี้เก็บ snapshot ชื่อไว้แล้ว (ไม่หาย)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)
                    old = await conn.fetchrow(
                        "SELECT * FROM fine_types WHERE id = $1 AND room_id = $2",
                        fine_type_id, target_room_id,
                    )
                    if not old:
                        raise RoomNotFoundError("ไม่พบประเภทความผิดนี้")
                    res = await conn.execute(
                        """UPDATE fine_types SET deleted_at = NOW(), is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                        fine_type_id, target_room_id,
                    )
                    if res == "UPDATE 0":
                        raise RoomNotFoundError("ไม่พบประเภทความผิดนี้")
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", entity_id=str(fine_type_id), status="success",
                        old_values=dict(old),
                        endpoint_or_command="FinanceService.delete_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {"status": "success", "message": "ลบประเภทความผิดสำเร็จ"}
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINE_TYPE", entity_id=str(fine_type_id), status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_fine_type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e
