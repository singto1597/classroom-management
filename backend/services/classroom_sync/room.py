"""ข้อมูลห้อง + การตั้งค่าช่อง/เวลาแจ้งเตือน + audit log + วันเกิด"""
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


class RoomMixin:
    CHANNEL_TYPE_COLUMNS = {
        "announcement": "announcement_channel_id",
        "birthday": "birthday_channel_id",
        "minor": "minor_notify_channel_id",
        "info": "info_channel_id",
    }

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
                    f"minor_notify_channel_id, info_channel_id, muted_channel_ids, notify_time "
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

    @classmethod
    async def set_channel(cls, pool: asyncpg.Pool, channel_id: int, user_name: str, user_id: int, room_id: int, client_source: str, actor_identifier: str, channel_type: str = "announcement"):
        start_time = time.time()
        try:
            column = cls.CHANNEL_TYPE_COLUMNS.get(channel_type)
            if not column:
                raise ValueError(f"channel_type ไม่ถูกต้อง: {channel_type} (ต้องเป็น announcement/birthday/minor/info)")

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
    async def apply_channel_defaults(
        cls,
        pool: asyncpg.Pool,
        room_id: int,
        channels: Dict[str, int],
        client_source: str,
        actor_identifier: str,
    ) -> Dict[str, Dict[str, int]]:
        """🤖 system RPC ของบอท: บันทึกช่องที่บอท **สร้างเอง** ตอนเข้าร่วมเซิร์ฟเวอร์

        🔑 **ไม่ทับค่าที่แอดมินตั้งไว้** — เติมเฉพาะคอลัมน์ที่ยังเป็น NULL
           ถ้าทับได้ การเชิญบอทกลับเข้าเซิร์ฟเวอร์ (หรือการ join ซ้ำหลังลบช่อง)
           จะเปลี่ยนช่องแจ้งเตือนที่แอดมินเลือกไว้เงียบ ๆ โดยไม่มีใครสั่ง

        คืน `{"updated": {...}, "kept": {...}}` แยก "บันทึกใหม่" กับ "ของเดิมไม่ถูกแตะ"
        ⇒ บอทบอกผู้ใช้ได้ตรง ๆ ว่าเกิดอะไรขึ้น (ไม่ใช่ "สำเร็จ" ลอย ๆ ทุกกรณี)
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    room = await conn.fetchrow(
                        "SELECT id, announcement_channel_id, birthday_channel_id, "
                        "minor_notify_channel_id, info_channel_id "
                        "FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                        room_id,
                    )
                    if not room:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")

                    updated: Dict[str, int] = {}
                    kept: Dict[str, int] = {}
                    for channel_type, channel_id in channels.items():
                        column = cls.CHANNEL_TYPE_COLUMNS.get(channel_type)
                        if column is None:
                            continue  # ชนิดที่ไม่รู้จัก — ข้าม ไม่ทำให้ทั้งคำขอล้ม
                        if room[column] is None:
                            updated[channel_type] = int(channel_id)
                        else:
                            kept[channel_type] = int(room[column])

                    if updated:
                        assignments = []
                        values = []
                        for index, (channel_type, channel_id) in enumerate(updated.items(), start=2):
                            assignments.append(f"{cls.CHANNEL_TYPE_COLUMNS[channel_type]} = ${index}")
                            values.append(channel_id)
                        await conn.execute(
                            f"UPDATE rooms SET {', '.join(assignments)} WHERE id = $1",
                            room_id,
                            *values,
                        )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=room_id, entity_type="ROOM",
                        entity_id=str(room_id),
                        old_values={cls.CHANNEL_TYPE_COLUMNS[k]: v for k, v in kept.items()},
                        new_values={cls.CHANNEL_TYPE_COLUMNS[k]: v for k, v in updated.items()},
                        endpoint_or_command="apply_channel_defaults", execution_time_ms=exec_time,
                    )
                    return {"updated": updated, "kept": kept}
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, entity_type="ROOM",
                    entity_id=str(room_id), status="failed", error_detail=str(e),
                    endpoint_or_command="apply_channel_defaults", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def set_channel_muted(
        cls,
        pool: asyncpg.Pool,
        room_id: int,
        channel_id: int,
        muted: bool,
        user_name: str,
        user_id: int,
        client_source: str,
        actor_identifier: str,
    ) -> Dict[str, object]:
        """🔇 เปิด/ปิดการส่งข้อความของบอท **รายช่อง** (ไม่ใช่ปิดบอททั้งห้อง)

        - รับเฉพาะช่องที่เป็นช่องแจ้งเตือนของห้องนี้อยู่แล้ว (announcement/birthday/
          minor/info) ⇒ กัน `muted_channel_ids` เต็มไปด้วย ID ที่ไม่มีความหมาย
          และกันการ mute ช่องของห้องอื่นโดยไม่ตั้งใจ
        - เรียกซ้ำด้วยค่าเดิม = ไม่แก้อะไร (idempotent) แต่ยังคืนสถานะล่าสุด
        - ใช้ BIGINT[] + `array_append/array_remove`-สไตล์ฝั่ง Python เพื่อให้อ่าน
          audit log ง่าย (old_values/new_values เป็นลิสต์ทั้งก้อน)
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

                    room = await conn.fetchrow(
                        "SELECT announcement_channel_id, birthday_channel_id, "
                        "minor_notify_channel_id, info_channel_id, muted_channel_ids "
                        "FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                        room_id,
                    )
                    if not room:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")

                    configured = {
                        room[column]
                        for column in cls.CHANNEL_TYPE_COLUMNS.values()
                        if room[column] is not None
                    }
                    channel_id = int(channel_id)
                    if channel_id not in configured:
                        raise ValueError(
                            "ช่องนี้ยังไม่ได้ตั้งเป็นช่องแจ้งเตือนของห้องนี้ "
                            "— ตั้งช่องให้บอทก่อนแล้วค่อย mute"
                        )

                    old_ids = [int(c) for c in (room["muted_channel_ids"] or [])]
                    if muted and channel_id not in old_ids:
                        new_ids = old_ids + [channel_id]
                    elif not muted and channel_id in old_ids:
                        new_ids = [c for c in old_ids if c != channel_id]
                    else:
                        new_ids = old_ids

                    if new_ids != old_ids:
                        await conn.execute(
                            "UPDATE rooms SET muted_channel_ids = $1::bigint[] WHERE id = $2",
                            new_ids,
                            room_id,
                        )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=room_id, user_id=user_id,
                        entity_type="ROOM", entity_id=str(room_id),
                        old_values={"muted_channel_ids": old_ids},
                        new_values={"muted_channel_ids": new_ids},
                        endpoint_or_command="set_channel_muted", execution_time_ms=exec_time,
                    )
                    # หลังอัปเดต สถานะจริง = ค่าที่ขอ (ทั้งกรณีเปลี่ยนและกรณีซ้ำค่าเดิม)
                    return {
                        "channel_id": channel_id,
                        "muted": muted,
                        "muted_channel_ids": new_ids,
                    }
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await service_logger.log(
                    conn=fallback_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ROOM", entity_id=str(room_id), status="failed",
                    error_detail=str(e), endpoint_or_command="set_channel_muted",
                    execution_time_ms=exec_time,
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
                # 🔇 `NOT (… = ANY(muted_channel_ids))` = ช่องที่ถูก mute ไม่ต้องส่งสรุปรายวัน
                #    กรองที่ backend เพราะลูปของบอทไม่ควรมีตรรกะธุรกิจ (และคำตอบนี้
                #    ถูกใช้เป็น "รายชื่อห้องที่ต้องแจ้ง" โดยตรง — ถ้ากรองฝั่งบอท
                #    ลูปจะต้องดึงข้อมูลห้องเพิ่มอีกหนึ่งรอบต่อห้อง)
                rows = await conn.fetch(
                    "SELECT server_id, announcement_channel_id FROM rooms "
                    "WHERE notify_time = $1 "
                    "AND announcement_channel_id IS NOT NULL "
                    "AND NOT (announcement_channel_id = ANY(muted_channel_ids)) "
                    "AND deleted_at IS NULL",
                    current_time
                )

                exec_time = int((time.time() - start_time) * 1000)
                # 📌 ไม่ log VIEW ตอนสำเร็จ **โดยเจตนา** — เมธอดนี้ถูกเรียกจากลูปทุกนาที
                #    ของบอท ⇒ 1,440 แถว/วันของ audit ที่ไม่มีใครอ่าน และไปกลบร่องรอย
                #    ที่มีความหมายจริงในตารางเดียวกัน
                #    แนวเดียวกับ `get_birthday_celebrants` ในไฟล์นี้ ซึ่งถูกเรียกจากลูป
                #    เดียวกันและ log เฉพาะตอนล้มเหลว (ไม่มีบล็อกสำเร็จเลย)
                #
                # 🔴 ผลตรวจระบบ 2026-09-23 → L6: บล็อกที่คอมเมนต์ค้างไว้ถูกลบ
                #    โค้ดที่คอมเมนต์ไว้ไม่มีเทสต์ ไม่ถูกรัน ไม่มีใครรู้ว่ายังถูกต้องไหม
                #    และเมื่อแก้โค้ดรอบข้าง มันจะเน่าอยู่ตรงนั้นโดยไม่มีอะไรเตือน
                #    ⚠️ ถ้าต้องการ audit การอ่านรายชื่อห้องเพื่อแจ้งเตือนจริง ๆ
                #       ให้เปิดที่ระดับ "มีคนขอข้อมูล" ไม่ใช่ที่ระดับ "ลูปทำงานเอง"
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
                           u.id AS user_id, s.student_no, u.first_name, u.last_name, u.nickname,
                           u.first_name_en, u.last_name_en
                    FROM rooms r
                    JOIN students s ON s.room_id = r.id AND s.status = 'active' AND s.deleted_at IS NULL
                    JOIN v_student_profiles u ON u.student_id = s.id AND u.deleted_at IS NULL
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
                        "first_name_en": row["first_name_en"],
                        "last_name_en": row["last_name_en"],
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
