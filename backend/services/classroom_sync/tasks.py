"""งาน (tasks) — เพิ่ม/ดู/แก้/เสร็จ/ลบ/กู้คืน"""
import time
import asyncpg
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, TaskNotFoundError, ForbiddenError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import THAI_TZ, service_logger


class TasksMixin:
    @classmethod
    async def add_task(cls, pool: asyncpg.Pool, task_name: str, task_detail: str, due_date: date, user_name: str, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None):
        start_time = time.time()
        discord_server_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # 🔒 กันคนนอกห้อง (ไม่ใช่สมาชิก active) เพิ่มงาน — สมาชิกทุกคน add ได้ (UX เดิม)
                    if user_id is not None:
                        await require_member(conn, room_id, user_id)
                    room = await conn.fetchrow("SELECT id, server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id)
                    if not room:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")
                    await conn.execute(
                        "INSERT INTO tasks (room_id, task_name, task_detail, due_date) VALUES ($1, $2, $3, $4)",
                        room_id, task_name, task_detail, due_date
                    )
                    new_values = {"task_name": task_name, "task_detail": task_detail, "due_date": str(due_date)}

                    discord_server_id = room['server_id']
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="TASK", new_values=new_values,
                        endpoint_or_command="add_task", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await service_logger.log(
                    conn=fallback_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=safe_room_id, entity_type="TASK", status="failed", error_detail=str(e),
                    endpoint_or_command="add_task", execution_time_ms=exec_time
                )
            raise e
            
        if discord_server_id:
            await ActionService.notify_new_task(discord_server_id, task_name, task_detail, due_date, user_name)

    @classmethod
    async def get_tasks(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, status: str = 'pending', room_id: int = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                if user_id is not None:
                    await require_member(conn, room_id, user_id)
                if status == "all":
                    # ✨ status=all → คืนทั้ง pending + done (ใช้ในหน้า Web) — bot ยังส่ง pending/done ตามเดิม
                    rows = await conn.fetch(
                        "SELECT id, task_name, task_detail, due_date, status, created_at FROM tasks WHERE room_id = $1 AND deleted_at IS NULL ORDER BY due_date ASC",
                        room_id
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT id, task_name, task_detail, due_date, status, created_at FROM tasks WHERE room_id = $1 AND status = $2 AND deleted_at IS NULL ORDER BY due_date ASC",
                        room_id, status
                    )
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", endpoint_or_command="get_tasks", execution_time_ms=exec_time
                )
                return [dict(row) for row in rows]
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", status="failed", error_detail=str(e),
                    endpoint_or_command="get_tasks", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_task_by_id(cls, pool: asyncpg.Pool, task_id: int, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                if user_id is not None:
                    await require_member(conn, room_id, user_id)
                row = await conn.fetchrow(
                    "SELECT id, task_name, task_detail, due_date, status, created_at FROM tasks WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL", 
                    task_id, room_id
                )
                if not row: raise TaskNotFoundError("Task not found or access denied")
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", entity_id=str(task_id),
                    endpoint_or_command="get_task_by_id", execution_time_ms=exec_time
                )
                return dict(row)
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", entity_id=str(task_id), status="failed",
                    error_detail=str(e), endpoint_or_command="get_task_by_id", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def edit_task(cls, pool: asyncpg.Pool, task_id: int, task_name: str, task_detail: str, due_date: date, user_name: str, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if user_id is not None:
                        await require_member(conn, room_id, user_id)
                    old_record = await conn.fetchrow("SELECT task_name, task_detail, due_date FROM tasks WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL", task_id, room_id)
                    old_values = dict(old_record) if old_record else {}

                    res = await conn.execute(
                        "UPDATE tasks SET task_name = $1, task_detail = $2, due_date = $3 WHERE id = $4 AND room_id = $5 AND deleted_at IS NULL",
                        task_name, task_detail, due_date, task_id, room_id
                    )
                    if res == "UPDATE 0": raise TaskNotFoundError("Task not found")
                    
                    new_values = {"task_name": task_name, "task_detail": task_detail, "due_date": str(due_date)}
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="TASK", entity_id=str(task_id), old_values=old_values,
                        new_values=new_values, endpoint_or_command="edit_task", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", entity_id=str(task_id), status="failed",
                    error_detail=str(e), endpoint_or_command="edit_task", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def mark_task_done(cls, pool: asyncpg.Pool, task_id: int, user_name: str, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None) -> str:
        start_time = time.time()
        discord_server_id = None
        task_name = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if user_id is not None:
                        await require_member(conn, room_id, user_id)
                    old_record = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL", task_id, room_id)
                    old_values = dict(old_record) if old_record else {}

                    task_name = await conn.fetchval("UPDATE tasks SET status = 'done' WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL RETURNING task_name", task_id, room_id)
                    if not task_name: raise TaskNotFoundError("Task not found")
                    
                    new_values = {"status": "done"}
                    discord_server_id = await conn.fetchval("SELECT server_id FROM rooms WHERE id = $1", room_id)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="TASK", entity_id=str(task_id), old_values=old_values,
                        new_values=new_values, endpoint_or_command="mark_task_done", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", entity_id=str(task_id), status="failed",
                    error_detail=str(e), endpoint_or_command="mark_task_done", execution_time_ms=exec_time
                )
            raise e

        if discord_server_id and task_name:
            await ActionService.notify_task_done(discord_server_id, task_name, user_name)

        return task_name

    @classmethod
    async def delete_task(cls, pool: asyncpg.Pool, task_id: int, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str) -> str:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_TASKS")
                    old_record = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1 AND room_id = $2", task_id, room_id)
                    old_values = dict(old_record) if old_record else {}
                    
                    task_name = await conn.fetchval("UPDATE tasks SET deleted_at = NOW() WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL RETURNING task_name", task_id, room_id)
                    if not task_name: raise TaskNotFoundError("Task not found or already deleted")

                    new_values = {"deleted_at": "soft-deleted"}
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="TASK", entity_id=str(task_id),
                        old_values=old_values, new_values=new_values, endpoint_or_command="delete_task", execution_time_ms=exec_time
                    )
                    return task_name
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, user_id=user_id, entity_type="TASK", entity_id=str(task_id),
                    status="failed", error_detail=str(e), endpoint_or_command="delete_task", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_deleted_tasks(cls, pool: asyncpg.Pool, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                if user_id is not None:
                    await require_member(conn, room_id, user_id)
                rows = await conn.fetch(
                    "SELECT id, task_name, task_detail, due_date, status, created_at, deleted_at FROM tasks WHERE room_id = $1 AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
                    room_id
                )
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", endpoint_or_command="get_deleted_tasks", execution_time_ms=exec_time
                )
                return [dict(row) for row in rows]
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", status="failed", error_detail=str(e),
                    endpoint_or_command="get_deleted_tasks", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def restore_task(cls, pool: asyncpg.Pool, task_id: int, user_name: str, room_id: int, client_source: str, actor_identifier: str, user_id: Optional[int] = None) -> str:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if user_id is not None:
                        await require_member(conn, room_id, user_id)
                    old_record = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1 AND room_id = $2", task_id, room_id)
                    old_values = dict(old_record) if old_record else {}

                    task_name = await conn.fetchval("UPDATE tasks SET deleted_at = NULL WHERE id = $1 AND room_id = $2 AND deleted_at IS NOT NULL RETURNING task_name", task_id, room_id)
                    if not task_name: raise TaskNotFoundError("ไม่พบงานที่ถูกลบ")
                    
                    new_values = {"deleted_at": None}
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="TASK", entity_id=str(task_id), old_values=old_values,
                        new_values=new_values, endpoint_or_command="restore_task", execution_time_ms=exec_time
                    )
                    return task_name
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="TASK", entity_id=str(task_id), status="failed",
                    error_detail=str(e), endpoint_or_command="restore_task", execution_time_ms=exec_time
                )
            raise e
