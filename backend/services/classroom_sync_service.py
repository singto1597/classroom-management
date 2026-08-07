import time
import asyncpg
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, TaskNotFoundError, ForbiddenError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

THAI_TZ = ZoneInfo("Asia/Bangkok")

service_logger = AuditLogger(service_name="CLASSROOM")

class ClassroomService:

    @classmethod
    async def get_room_data(cls, pool: asyncpg.Pool, target_id: int, target_type: str, client_source: str, actor_identifier: str, user_id: Optional[int] = None):
        """
        ดึงข้อมูลห้องตาม target_type:
        - 'server' → ค้นจากคอลัมน์ server_id (Discord Server ID สโนว์เฟลก 19 หลัก)
        - 'room' (หรืออื่น) → ค้นจากคอลัมน์ id (room_id)
        สลับคอลัมน์ที่ WHERE โดยตรง ไม่ต้อง resolve ผ่าน query แยก (กัน 404 งง ๆ)
        คืน dict ที่มี id, server_id, room_name, announcement_channel_id, notify_time
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                if target_type == "server":
                    # 🤖 Bot path: ค้นด้วย server_id (Discord snowflake 19 หลัก)
                    where_column = "server_id"
                    not_found_msg = f"ไม่พบห้องเรียนที่ผูกกับ Server ID: {target_id}"
                else:
                    # 🌐 Web path: ค้นด้วย room_id
                    where_column = "id"
                    not_found_msg = f"ไม่พบห้องเรียน ID: {target_id}"

                room = await conn.fetchrow(
                    f"SELECT id, server_id, room_code, room_name, announcement_channel_id, birthday_channel_id, "
                    f"minor_notify_channel_id, notify_time "
                    f"FROM rooms WHERE {where_column} = $1 AND deleted_at IS NULL",
                    target_id,
                )
                if not room:
                    raise RoomNotFoundError(not_found_msg)

                room_id = room["id"]

                # 🔒 ตรวจ member หลังจาก room มีอยู่จริง → 404 ก่อน 403
                # (บอท path ส่ง user_id=None → ข้าม กันบอทซึ่งไม่ใช่สมาชิกห้องถูก block)
                if user_id is not None:
                    await require_member(conn, room_id, user_id)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="ROOM", entity_id=str(room_id),
                    endpoint_or_command="get_room_data", execution_time_ms=exec_time
                )
                return dict(room)
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                # room ไม่มีอยู่จริง → อย่า log ผูกกับ room_id ที่ไม่มี FK (กัน FK violation กลบ exception เดิม)
                safe_room_id = None
                async with fallback_conn.transaction():
                    # หา room_id จริงเพื่อ log (ถ้าเจอ) หรือปล่อย None ถ้าเป็น RoomNotFoundError
                    if not isinstance(e, RoomNotFoundError):
                        safe_room_id = await fallback_conn.fetchval(
                            "SELECT id FROM rooms WHERE id = $1 OR server_id = $1",
                            target_id,
                        )
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=safe_room_id, entity_type="ROOM", entity_id=str(target_id), status="failed",
                    error_detail=str(e), endpoint_or_command="get_room_data", execution_time_ms=exec_time
                )
            raise e

    @staticmethod
    def _get_thai_day(date_obj: date) -> str:
        days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        return days[date_obj.weekday()]

    @classmethod
    async def get_audit_logs(cls, pool: asyncpg.Pool, room_id: int, client_source: str, actor_identifier: str, limit: int = 20, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                if user_id is not None:
                    await require_member(conn, room_id, user_id)
                # ป้องกัน LIMIT ติดลบ → asyncpg error "LIMIT must not be negative"
                safe_limit = max(0, limit)
                rows = await conn.fetch(
                    "SELECT actor_identifier AS user_name, action, endpoint_or_command AS detail, created_at FROM audit_logs WHERE room_id = $1 ORDER BY created_at DESC LIMIT $2",
                    room_id, safe_limit
                )
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="AUDIT_LOG", endpoint_or_command="get_audit_logs", execution_time_ms=exec_time
                )
                return [dict(r) for r in rows]
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=room_id, entity_type="AUDIT_LOG", status="failed", error_detail=str(e),
                    endpoint_or_command="get_audit_logs", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def setup_room(cls, pool: asyncpg.Pool, room_name: str, user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, user_id: Optional[int] = None):
        """
        🛡️ ปิดความสามารถสร้างห้องใหม่จาก Bot แล้ว (Frontend /create เป็นระบบหลัก)
        - ต้องมี server_id เสมอ: ห้องต้องถูกสร้างผ่านเว็บ (POST /api/classroom/create) ก่อน
        - ห้องจะถูกค้นจาก server_id ว่าเคยผูกไว้หรือยัง
        - ถ้ายังไม่เคยผูก: ต้องระบุ room_name ให้ตรงกับห้องที่มีอยู่ (สร้างผ่านเว็บ) แล้วจึงผูก server_id
        - ถ้าเคยผูกแล้ว: อัปเดตแค่ชื่อห้อง (ห้อง Discord กับ Web จะได้ตรงกัน)
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # ห้องต้องถูกสร้างผ่านเว็บก่อนเสมอ — bot เป็นเพียง option เสริม
                    if not server_id:
                        raise ValueError("ไม่สามารถสร้างห้องจาก Bot ได้อีกต่อไป กรุณาสร้างห้องผ่านเว็บแอปพลิเคชันก่อน (POST /api/classroom/create)")

                    old_values = None
                    new_values = {"room_name": room_name, "server_id": server_id}
                    action = "UPDATE"

                    # ค้นห้องที่เคยผูก server_id ไว้แล้ว
                    old_record = await conn.fetchrow("SELECT id, room_name FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
                    if old_record:
                        # 🔒 เปลี่ยนชื่อห้องของ server ที่ผูกอยู่ → ต้องเป็นสมาชิกของห้องนั้นก่อน
                        if user_id is not None:
                            await require_member(conn, old_record['id'], user_id)
                        old_values = dict(old_record)
                        room_id = old_record['id']
                        await conn.execute("UPDATE rooms SET room_name = $1 WHERE id = $2", room_name, room_id)
                    else:
                        # ยังไม่เคยผูก: ต้องมีห้องที่สร้างผ่านเว็บ และชื่อต้องตรงกันก่อนผูก
                        existing_room = await conn.fetchrow(
                            "SELECT id FROM rooms WHERE room_name = $1 AND server_id IS NULL AND deleted_at IS NULL ORDER BY id LIMIT 1",
                            room_name
                        )
                        if not existing_room:
                            raise ValueError(
                                f"ไม่พบห้อง '{room_name}' ที่สร้างผ่านเว็บ กรุณาสร้างห้องผ่านเว็บแอปพลิเคชันก่อน แล้วลองใหม่อีกครั้ง"
                            )
                        room_id = existing_room['id']
                        await conn.execute("UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, room_id)
                        action = "UPDATE"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action=action, actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, entity_type="ROOM", entity_id=str(room_id), old_values=old_values,
                        new_values=new_values, endpoint_or_command="setup_room", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="CREATE_OR_UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    entity_type="ROOM", status="failed", error_detail=str(e), endpoint_or_command="setup_room", execution_time_ms=exec_time
                )
            raise e

    # 🎯 แผนที่ชื่อช่อง → คอลัมน์ในตาราง rooms (ใช้กับ set_channel + ดึง channel ตามประเภท)
    CHANNEL_TYPE_COLUMNS = {
        "announcement": "announcement_channel_id",
        "birthday": "birthday_channel_id",
        "minor": "minor_notify_channel_id",
    }

    @classmethod
    async def set_channel(cls, pool: asyncpg.Pool, channel_id: int, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str, channel_type: str = "announcement"):
        start_time = time.time()
        try:
            column = cls.CHANNEL_TYPE_COLUMNS.get(channel_type)
            if not column:
                raise ValueError(f"channel_type ไม่ถูกต้อง: {channel_type} (ต้องเป็น announcement/birthday/minor)")

            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
                    # 🚨 สร้าง SQL แบบ parameterized — ชื่อคอลัมน์มาจาก whitelist ข้างบนเท่านั้น (กัน SQL injection)
                    old_record = await conn.fetchrow(
                        f"SELECT {column} FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id
                    )
                    if not old_record:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")
                    old_values = dict(old_record)

                    await conn.execute(f"UPDATE rooms SET {column} = $1 WHERE id = $2", channel_id, room_id)
                    new_values = {column: channel_id}

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="ROOM", entity_id=str(room_id),
                        old_values=old_values, new_values=new_values, endpoint_or_command="set_channel", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=safe_room_id, user_id=user_id, entity_type="ROOM", entity_id=str(room_id),
                    status="failed", error_detail=str(e), endpoint_or_command="set_channel", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def set_notify_time(cls, pool: asyncpg.Pool, notify_time: str, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
                    old_record = await conn.fetchrow("SELECT notify_time FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id)
                    if not old_record:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")
                    old_values = dict(old_record)

                    await conn.execute("UPDATE rooms SET notify_time = $1 WHERE id = $2", notify_time, room_id)
                    new_values = {"notify_time": notify_time}
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=room_id, user_id=user_id, entity_type="ROOM", entity_id=str(room_id),
                        old_values=old_values, new_values=new_values, endpoint_or_command="set_notify_time", execution_time_ms=exec_time
                    )
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=safe_room_id, user_id=user_id, entity_type="ROOM", entity_id=str(room_id),
                    status="failed", error_detail=str(e), endpoint_or_command="set_notify_time", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_rooms_to_notify(cls, pool: asyncpg.Pool, current_time: str, client_source: str, actor_identifier: str) -> List[dict]:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT server_id, announcement_channel_id FROM rooms WHERE notify_time = $1 AND announcement_channel_id IS NOT NULL AND deleted_at IS NULL",
                    current_time
                )

                exec_time = int((time.time() - start_time) * 1000)
                # await service_logger.log(
                #     conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                #     entity_type="ROOM", endpoint_or_command="get_rooms_to_notify", execution_time_ms=exec_time
                # )
                return [dict(row) for row in rows]
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    entity_type="ROOM", status="failed", error_detail=str(e), endpoint_or_command="get_rooms_to_notify", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_birthday_celebrants(cls, pool: asyncpg.Pool, target_date: date, client_source: str, actor_identifier: str) -> List[dict]:
        """
        🎂 หาคนที่มีวันเกิดตรงกับ target_date (วันนี้) ทุกห้องที่ผูก Discord แล้ว
        - ใช้ date_part('month', ...) + date_part('day', ...) เปรียบเทียบ → กันปัญหา leap year (29 ก.พ.)
        - คืนเฉพาะห้องที่มี birthday_channel_id หรือ announcement_channel_id (ไม่งั้นบอทส่งที่ไหนไม่ได้)
        - คืน celebrants แบบ active (status='active' + deleted_at IS NULL) เท่านั้น
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT r.server_id, r.birthday_channel_id, r.announcement_channel_id,
                           u.id AS user_id, s.student_no, u.first_name, u.last_name, u.nickname
                    FROM rooms r
                    JOIN students s ON s.room_id = r.id AND s.status = 'active' AND s.deleted_at IS NULL
                    JOIN users u ON u.id = s.user_id AND u.deleted_at IS NULL
                    WHERE r.deleted_at IS NULL
                      AND r.server_id IS NOT NULL
                      AND (r.birthday_channel_id IS NOT NULL OR r.announcement_channel_id IS NOT NULL)
                      AND u.birthday IS NOT NULL
                      AND date_part('month', u.birthday) = date_part('month', $1::date)
                      AND date_part('day', u.birthday) = date_part('day', $1::date)
                    ORDER BY r.server_id, s.student_no
                    """,
                    target_date,
                )

                # รวมตามห้อง (server_id) → หนึ่งห้องหนึ่งรายการ มี celebrants เป็นลิสต์
                rooms_map: Dict[int, dict] = {}
                for row in rows:
                    server_id = row["server_id"]
                    if server_id not in rooms_map:
                        rooms_map[server_id] = {
                            "server_id": server_id,
                            "birthday_channel_id": row["birthday_channel_id"],
                            "announcement_channel_id": row["announcement_channel_id"],
                            "celebrants": [],
                        }
                    rooms_map[server_id]["celebrants"].append({
                        "student_no": row["student_no"],
                        "first_name": row["first_name"],
                        "last_name": row["last_name"],
                        "nickname": row["nickname"],
                    })

                return list(rooms_map.values())
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=fallback_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    entity_type="BIRTHDAY", status="failed", error_detail=str(e),
                    endpoint_or_command="get_birthday_celebrants", execution_time_ms=exec_time
                )
            raise e

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