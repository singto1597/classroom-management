"""ตารางเรียน (default schedule/override) + โน้ตรายวัน"""
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


class ScheduleMixin:
    @classmethod    
    async def set_default_schedule(cls, pool: asyncpg.Pool, day_of_week: str, attire: str, subjects: str, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
                    old_record = await conn.fetchrow("SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = $2 AND deleted_at IS NULL", room_id, day_of_week)
                    old_values = dict(old_record) if old_record else None

                    # ลบทุกแถว (รวม soft-deleted) → กันการสะสม row เมื่อ add → delete → add ซ้ำ
                    await conn.execute("DELETE FROM default_schedules WHERE room_id = $1 AND day_of_week = $2", room_id, day_of_week)
                    await conn.execute(
                        "INSERT INTO default_schedules (room_id, day_of_week, attire, subjects) VALUES ($1, $2, $3, $4)",
                        room_id, day_of_week, attire, subjects
                    )
                    new_values = {"day_of_week": day_of_week, "attire": attire, "subjects": subjects}
                    action = "UPDATE" if old_values else "CREATE"
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action=action, actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="DEFAULT_SCHEDULE", entity_id=day_of_week,
                        old_values=old_values, new_values=new_values, endpoint_or_command="set_default_schedule", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="CREATE_OR_UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, user_id=user_id, entity_type="DEFAULT_SCHEDULE", entity_id=day_of_week,
                    status="failed", error_detail=str(e), endpoint_or_command="set_default_schedule", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def set_override(cls, pool: asyncpg.Pool, target_date: date, new_attire: str, note: str, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
                    old_record = await conn.fetchrow("SELECT new_attire, note FROM schedule_overrides WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL", room_id, target_date)
                    old_values = dict(old_record) if old_record else None

                    # ลบทุกแถว (รวม soft-deleted) → กันการสะสม row เมื่อ add → delete → add ซ้ำ
                    await conn.execute("DELETE FROM schedule_overrides WHERE room_id = $1 AND target_date = $2", room_id, target_date)
                    await conn.execute(
                        "INSERT INTO schedule_overrides (room_id, target_date, new_attire, note) VALUES ($1, $2, $3, $4)",
                        room_id, target_date, new_attire, note
                    )
                    new_values = {"target_date": str(target_date), "new_attire": new_attire, "note": note}
                    action = "UPDATE" if old_values else "CREATE"
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action=action, actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="SCHEDULE_OVERRIDE", entity_id=str(target_date),
                        old_values=old_values, new_values=new_values, endpoint_or_command="set_override", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="CREATE_OR_UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, user_id=user_id, entity_type="SCHEDULE_OVERRIDE", entity_id=str(target_date),
                    status="failed", error_detail=str(e), endpoint_or_command="set_override", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def add_daily_note(cls, pool: asyncpg.Pool, target_date: date, bring_items: str, announcement: str, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_TASKS")
                    old_record = await conn.fetchrow("SELECT bring_items, announcement FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL", room_id, target_date)
                    old_values = dict(old_record) if old_record else None

                    # ลบทุกแถว (รวม soft-deleted) → กันการสะสม row เมื่อ add → delete → add ซ้ำ
                    await conn.execute("DELETE FROM daily_notes WHERE room_id = $1 AND target_date = $2", room_id, target_date)
                    await conn.execute(
                        "INSERT INTO daily_notes (room_id, target_date, bring_items, announcement) VALUES ($1, $2, $3, $4)",
                        room_id, target_date, bring_items, announcement
                    )
                    
                    new_values = {"target_date": str(target_date), "bring_items": bring_items, "announcement": announcement}
                    action = "UPDATE" if old_values else "CREATE"
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action=action, actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="DAILY_NOTE", entity_id=str(target_date),
                        old_values=old_values, new_values=new_values, endpoint_or_command="add_daily_note", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="CREATE_OR_UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, user_id=user_id, entity_type="DAILY_NOTE", entity_id=str(target_date),
                    status="failed", error_detail=str(e), endpoint_or_command="add_daily_note", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def delete_daily_note(cls, pool: asyncpg.Pool, target_date: date, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str) -> dict:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_TASKS")
                    old_record = await conn.fetchrow("SELECT bring_items, announcement, deleted_at FROM daily_notes WHERE room_id = $1 AND target_date = $2", room_id, target_date)
                    old_values = dict(old_record) if old_record else {}
                    
                    row = await conn.fetchrow(
                        "UPDATE daily_notes SET deleted_at = NOW() WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL RETURNING bring_items, announcement",
                        room_id, target_date
                    )
                    if not row: raise TaskNotFoundError("Note not found or already deleted")
                    
                    new_values = dict(row)
                    new_values["deleted_at"] = "NOW()"
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="DAILY_NOTE", entity_id=str(target_date),
                        old_values=old_values, new_values=new_values, endpoint_or_command="delete_daily_note", execution_time_ms=exec_time
                    )
                    return dict(row)
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, user_id=user_id, entity_type="DAILY_NOTE", entity_id=str(target_date),
                    status="failed", error_detail=str(e), endpoint_or_command="delete_daily_note", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_daily_summary(cls, pool: asyncpg.Pool, target_date: date, room_id: int, client_source: str, actor_identifier: str) -> dict:
        start_time = time.time()
        day_name = cls._get_thai_day(target_date)
        data = {"date": target_date, "day": day_name, "attire": "-", "subjects": "-", "bring": "-", "note": "-", "tasks_due": []}

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    default = await conn.fetchrow("SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = $2 AND deleted_at IS NULL", room_id, day_name)
                    if default:
                        data["attire"] = default["attire"]
                        data["subjects"] = default["subjects"]

                    override = await conn.fetchrow("SELECT new_attire, note FROM schedule_overrides WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL", room_id, target_date)
                    note_data = await conn.fetchrow("SELECT bring_items, announcement FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL", room_id, target_date)

                    if override: data["attire"] = f"🚨 {override['new_attire']} (กรณีพิเศษ)"
                    if note_data: data["bring"] = note_data["bring_items"]

                    notes = []
                    if override and override['note']: notes.append(f"⚠️ {override['note']}")
                    if note_data and note_data['announcement']: notes.append(f"📢 {note_data['announcement']}")
                    if notes: data["note"] = " | ".join(notes)
                    
                    today = datetime.now(THAI_TZ).date()
                    tasks = await conn.fetch("SELECT task_name, due_date FROM tasks WHERE room_id = $1 AND status = 'pending' AND deleted_at IS NULL ORDER BY due_date ASC", room_id)
                    
                    for t in tasks:
                        days_left = (t['due_date'] - today).days
                        if days_left < 0: status_text = f"🔴 **(เลยกำหนดมา {-days_left} วัน!)**"
                        elif days_left == 0: status_text = f"🔥 **(ส่งวันนี้!)**"
                        elif days_left == 1: status_text = f"⚠️ **(ส่งพรุ่งนี้!)**"
                        else: status_text = f"🟢 (เหลืออีก {days_left} วัน)"
                            
                        data["tasks_due"].append({
                            "task_name": t['task_name'],
                            "days_left": days_left,
                            "display_text": f"• {t['task_name']} {status_text}"
                        })

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="DAILY_SUMMARY", entity_id=str(target_date),
                        endpoint_or_command="get_daily_summary", execution_time_ms=exec_time
                    )
            return data
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="DAILY_SUMMARY", entity_id=str(target_date),
                    status="failed", error_detail=str(e), endpoint_or_command="get_daily_summary", execution_time_ms=exec_time
                )
            raise e
