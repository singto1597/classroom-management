import asyncpg
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

from core.audit import log_action
from core.exceptions import RoomNotFoundError, TaskNotFoundError, ForbiddenError
from core.rbac import require_permission
from services.action_service import ActionService

THAI_TZ = ZoneInfo("Asia/Bangkok")

class ClassroomService:
    
    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        """
        Helper สำหรับดึงและตรวจสอบ room_id รองรับทั้งระบบ Web (room_id) และ Bot (server_id)
        """
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: 
                raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id อย่างใดอย่างหนึ่ง")

    @classmethod
    async def get_room_data(cls, pool: asyncpg.Pool, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            r_id = await cls.resolve_room_id(conn, server_id, room_id)
            room = await conn.fetchrow(
                "SELECT id, server_id, room_code, room_name, announcement_channel_id, notify_time FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                r_id
            )
            return dict(room)

    @staticmethod
    def _get_thai_day(date_obj: date) -> str:
        days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        return days[date_obj.weekday()]

    @classmethod
    async def get_audit_logs(cls, pool: asyncpg.Pool, server_id: Optional[int] = None, room_id: Optional[int] = None, limit: int = 20) -> List[dict]:
        async with pool.acquire() as conn:
            r_id = await cls.resolve_room_id(conn, server_id, room_id)
            rows = await conn.fetch(
                "SELECT user_name, action, detail, created_at FROM audit_logs WHERE room_id = $1 ORDER BY created_at DESC LIMIT $2",
                r_id, limit
            )
            return [dict(r) for r in rows]

    @classmethod
    async def setup_room(cls, pool: asyncpg.Pool, room_name: str, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                if server_id:
                    # Setup via Bot
                    await conn.execute(
                        """INSERT INTO rooms (server_id, room_name) 
                           VALUES ($1, $2) 
                           ON CONFLICT (server_id) DO UPDATE SET room_name = EXCLUDED.room_name""",
                        server_id, room_name
                    )
                else:
                    # Setup via Web
                    await conn.execute(
                        "INSERT INTO rooms (room_name) VALUES ($1)",
                        room_name
                    )
                
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await log_action(conn, r_id, user_name, "Setup Room", f"ตั้งชื่อห้องเป็น {room_name}")

    @classmethod
    async def set_channel(cls, pool: asyncpg.Pool, channel_id: int, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_SETTINGS")
                await conn.execute("UPDATE rooms SET announcement_channel_id = $1 WHERE id = $2", channel_id, r_id)
                await log_action(conn, r_id, user_name, "Set Channel", f"ตั้งค่าไปที่ห้อง {channel_id}")

    @classmethod
    async def set_notify_time(cls, pool: asyncpg.Pool, notify_time: str, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_SETTINGS")
                await conn.execute("UPDATE rooms SET notify_time = $1 WHERE id = $2", notify_time, r_id)
                await log_action(conn, r_id, user_name, "Set Time", f"เปลี่ยนเวลาเตือนเป็น {notify_time}")

    @classmethod
    async def get_rooms_to_notify(cls, pool: asyncpg.Pool, current_time: str) -> List[dict]:
        # Method นี้ query จากเวลา ไม่ได้ผูกกับ room_id โดยตรง จึงเหมือนเดิม
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT server_id, announcement_channel_id FROM rooms WHERE notify_time = $1 AND announcement_channel_id IS NOT NULL AND deleted_at IS NULL", 
                current_time
            )
            return [dict(row) for row in rows]

    @classmethod    
    async def set_default_schedule(cls, pool: asyncpg.Pool, day_of_week: str, attire: str, subjects: str, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_SETTINGS")
                await conn.execute("DELETE FROM default_schedules WHERE room_id = $1 AND day_of_week = $2", r_id, day_of_week)
                await conn.execute(
                    "INSERT INTO default_schedules (room_id, day_of_week, attire, subjects) VALUES ($1, $2, $3, $4)",
                    r_id, day_of_week, attire, subjects
                )
                await log_action(conn, r_id, user_name, "Set Schedule", f"แก้วัน{day_of_week} เป็นชุด {attire}")

    @classmethod
    async def set_override(cls, pool: asyncpg.Pool, target_date: date, new_attire: str, note: str, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_SETTINGS")
                await conn.execute("DELETE FROM schedule_overrides WHERE room_id = $1 AND target_date = $2", r_id, target_date)
                await conn.execute(
                    "INSERT INTO schedule_overrides (room_id, target_date, new_attire, note) VALUES ($1, $2, $3, $4)",
                    r_id, target_date, new_attire, note
                )
                await log_action(conn, r_id, user_name, "Set Override", f"ตั้งชุด/หมายเหตุพิเศษวันที่ {target_date}")

    @classmethod
    async def add_task(cls, pool: asyncpg.Pool, task_name: str, task_detail: str, due_date: date, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await conn.execute(
                    "INSERT INTO tasks (room_id, task_name, task_detail, due_date) VALUES ($1, $2, $3, $4)",
                    r_id, task_name, task_detail, due_date
                )
                await log_action(conn, r_id, user_name, "Add Task", f"สั่งงานใหม่: {task_name}")
                
                # Fetch server_id for Discord notification if request came from Web
                discord_server_id = server_id or await conn.fetchval("SELECT server_id FROM rooms WHERE id = $1", r_id)
                
        if discord_server_id:
            await ActionService.notify_new_task(discord_server_id, task_name, task_detail, due_date, user_name)

    @classmethod
    async def get_tasks(cls, pool: asyncpg.Pool, status: str = 'pending', server_id: Optional[int] = None, room_id: Optional[int] = None) -> List[dict]:
        async with pool.acquire() as conn:
            r_id = await cls.resolve_room_id(conn, server_id, room_id)
            rows = await conn.fetch(
                "SELECT id, task_name, task_detail, due_date, status, created_at FROM tasks WHERE room_id = $1 AND status = $2 AND deleted_at IS NULL ORDER BY due_date ASC",
                r_id, status
            )
            return [dict(row) for row in rows]

    @classmethod
    async def get_task_by_id(cls, pool: asyncpg.Pool, task_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        async with pool.acquire() as conn:
            r_id = await cls.resolve_room_id(conn, server_id, room_id) 
            row = await conn.fetchrow(
                "SELECT id, task_name, task_detail, due_date, status, created_at FROM tasks WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL", 
                task_id, r_id
            )
            if not row:
                raise TaskNotFoundError("Task not found or access denied")
            return dict(row)

    @classmethod
    async def edit_task(cls, pool: asyncpg.Pool, task_id: int, task_name: str, task_detail: str, due_date: date, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                res = await conn.execute(
                    "UPDATE tasks SET task_name = $1, task_detail = $2, due_date = $3 WHERE id = $4 AND room_id = $5",
                    task_name, task_detail, due_date, task_id, r_id
                )
                if res == "UPDATE 0": 
                    raise TaskNotFoundError("Task not found or access denied")
                await log_action(conn, r_id, user_name, "Edit Task", f"แก้งาน: {task_name}")
        
    @classmethod
    async def mark_task_done(cls, pool: asyncpg.Pool, task_id: int, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> str:
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                task_name = await conn.fetchval(
                    "UPDATE tasks SET status = 'done' WHERE id = $1 AND room_id = $2 RETURNING task_name", 
                    task_id, r_id
                )
                if not task_name:
                    raise TaskNotFoundError("Task not found or access denied")
                
                await log_action(conn, r_id, user_name, "Mark Done", f"ส่งงาน {task_name} แล้ว")
                discord_server_id = server_id or await conn.fetchval("SELECT server_id FROM rooms WHERE id = $1", r_id)
        
        if discord_server_id:
            await ActionService.notify_task_done(discord_server_id, task_name, user_name)

        return task_name

    @classmethod
    async def delete_task(cls, pool: asyncpg.Pool, task_id: int, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None) -> str:
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_TASKS")
                task_name = await conn.fetchval(
                    "UPDATE tasks SET deleted_at = NOW() WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL RETURNING task_name",
                    task_id, r_id
                )
                if not task_name:
                    raise TaskNotFoundError("Task not found or already deleted")
                await log_action(conn, r_id, user_name, "Soft Delete Task", f"ลบงาน {task_name}")
                return task_name

    @classmethod
    async def get_deleted_tasks(cls, pool: asyncpg.Pool, server_id: Optional[int] = None, room_id: Optional[int] = None) -> List[dict]:
        async with pool.acquire() as conn:
            r_id = await cls.resolve_room_id(conn, server_id, room_id)
            rows = await conn.fetch(
                "SELECT id, task_name, task_detail, due_date, status, created_at, deleted_at FROM tasks WHERE room_id = $1 AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
                r_id
            )
            return [dict(row) for row in rows]

    @classmethod
    async def restore_task(cls, pool: asyncpg.Pool, task_id: int, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> str:
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                task_name = await conn.fetchval(
                    "UPDATE tasks SET deleted_at = NULL WHERE id = $1 AND room_id = $2 AND deleted_at IS NOT NULL RETURNING task_name",
                    task_id, r_id
                )
                if not task_name:
                    raise TaskNotFoundError("ไม่พบงานที่ถูกลบ หรืออาจจะถูกลบถาวรไปแล้ว")
                await log_action(conn, r_id, user_name, "Restore Task", f"กู้คืนงาน {task_name}")
                return task_name
        
    @classmethod
    async def add_daily_note(cls, pool: asyncpg.Pool, target_date: date, bring_items: str, announcement: str, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction(): 
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_TASKS")
                await conn.execute("DELETE FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL", r_id, target_date)
                await conn.execute(
                    "INSERT INTO daily_notes (room_id, target_date, bring_items, announcement) VALUES ($1, $2, $3, $4)",
                    r_id, target_date, bring_items, announcement
                )
                await log_action(conn, r_id, user_name, "Add Note", f"เพิ่มโน้ตรายวันสำหรับวันที่ {target_date}")
        
    @classmethod
    async def delete_daily_note(cls, pool: asyncpg.Pool, target_date: date, user_name: str, requester_discord_id: int, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                r_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, r_id, requester_discord_id, "MANAGE_CLASSROOM_TASKS")
                row = await conn.fetchrow(
                    "UPDATE daily_notes SET deleted_at = NOW() WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL RETURNING bring_items, announcement",
                    r_id, target_date
                )
                if not row:
                    raise TaskNotFoundError("Note not found or already deleted")
                await log_action(conn, r_id, user_name, "Soft Delete Note", f"ลบโน้ตวันที่ {target_date}")
                return dict(row)

    @classmethod
    async def get_daily_summary(cls, pool: asyncpg.Pool, target_date: date, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        day_name = cls._get_thai_day(target_date)
        data = {"date": target_date, "day": day_name, "attire": "-", "subjects": "-", "bring": "-", "note": "-", "tasks_due": []}

        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                r_id = await cls.resolve_room_id(conn, server_id, room_id)

                default = await conn.fetchrow("SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = $2", r_id, day_name)
                if default:
                    data["attire"] = default["attire"]
                    data["subjects"] = default["subjects"]
                
                override = await conn.fetchrow("SELECT new_attire, note FROM schedule_overrides WHERE room_id = $1 AND target_date = $2", r_id, target_date)
                note_data = await conn.fetchrow("SELECT bring_items, announcement FROM daily_notes WHERE room_id = $1 AND target_date = $2", r_id, target_date)

                if override: data["attire"] = f"🚨 {override['new_attire']} (กรณีพิเศษ)"
                if note_data: data["bring"] = note_data["bring_items"]

                notes = []
                if override and override['note']: notes.append(f"⚠️ {override['note']}")
                if note_data and note_data['announcement']: notes.append(f"📢 {note_data['announcement']}")
                if notes: data["note"] = " | ".join(notes)
                
                today = datetime.now(THAI_TZ).date()
                tasks = await conn.fetch("SELECT task_name, due_date FROM tasks WHERE room_id = $1 AND status = 'pending' AND deleted_at IS NULL ORDER BY due_date ASC", r_id)
                
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

        return data