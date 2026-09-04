"""นักเรียน (students + users) — เพิ่ม/bulk/แก้/ค้นหา/profile/status/ลบ/sync discord"""
import asyncpg
import io
import json
import time
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.config import settings
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from core.logger import AuditLogger
from core.name_utils import normalize_nfc, normalize_en, identity_pair
from core.privacy import can_view_pii, mask_private_fields, is_real_claimed_account, PRIVATE_STUDENT_FIELDS
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import (
    STUDENT_PATCHABLE_COLUMNS, GLOBAL_FIELDS, NAME_NFC_FIELDS, LOCAL_FIELDS,
    THAI_TZ, THAI_MONTH_NAMES, EXPORT_HEADER_LABELS, ROLE_LABELS, STATUS_LABELS,
    DEFAULT_COL_WIDTH, EXPORT_COLUMN_WIDTHS, CENTER_FIELDS, WRAP_TEXT_FIELDS,
)
from .base import service_logger


class StudentsMixin:
    @classmethod
    async def add_student(cls, pool: asyncpg.Pool, student_no: int, first_name: str, last_name: str, user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, actor_user_id: Optional[int] = None, first_name_en: str = "", last_name_en: str = "", nickname: str = "", nickname_en: str = ""):
        start_time = time.time()
        target_room_id = None
        new_values = {"student_no": student_no, "first_name": first_name, "last_name": last_name, "first_name_en": first_name_en or None, "last_name_en": last_name_en or None, "nickname": nickname or None, "nickname_en": nickname_en or None, "user_name": user_name}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: ต้องมี MANAGE_STUDENTS ถึงจะเพิ่มนักเรียนได้ (กันนักเรียนธรรมดาเพิ่มเพื่อนเอง)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_STUDENTS")
                    user_id, is_real = await cls._find_or_create_user(conn, first_name, last_name, first_name_en, last_name_en, nickname, nickname_en)

                    if is_real:
                        # 🛡️ กันซ้ำ: บัญชีจริงที่เป็นสมาชิกห้องนี้อยู่แล้ว → ไม่สร้างคำเชิญซ้ำ
                        # (กรณี ghost ที่อยู่ในห้องแล้ว ยังให้ add ที่เลขที่ใหม่ได้ — reuse ชื่อเดิมตาม behavior เดิม)
                        already_member = await conn.fetchval(
                            "SELECT 1 FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL",
                            target_room_id, user_id,
                        )
                        if already_member:
                            raise ValueError(f"เลขที่ {student_no} มีรายชื่ออยู่ในห้องนี้แล้ว")
                        # 🔒 Consent Model: เจอบัญชีจริงที่เจ้าตัวยืนยันแล้ว (ไม่ใช่ ghost) → สร้าง "คำเชิญ" pending
                        # เจ้าตัวต้อง login แล้วกดรับ (accept_invite) ก่อนถึงจะกลายเป็นสมาชิก + เปิดข้อมูลส่วนตัว
                        res = await conn.execute("""
                            INSERT INTO students (room_id, student_no, user_id, status, identity_claimed, added_by)
                            SELECT $1, $2, $3, 'pending', FALSE, $4 WHERE NOT EXISTS (
                                SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                            )
                        """, target_room_id, student_no, user_id, actor_user_id)

                        if res == "INSERT 0 1":
                            exec_time = int((time.time() - start_time) * 1000)
                            await service_logger.log(
                                conn=conn, action="CREATE", actor_identifier=actor_identifier,
                                client_source=client_source, room_id=target_room_id, user_id=user_id,
                                entity_type="STUDENT_INVITE", entity_id=str(student_no), status="success",
                                new_values=new_values, endpoint_or_command="add_student_invite", execution_time_ms=exec_time
                            )
                            # 📢 แจ้งเตือน Discord: มีคำเชิญเข้าร่วมห้อง (เจ้าตัวต้องกดรับเอง — ไม่ใช่ NEW_STUDENT)
                            room_server_id = await conn.fetchval(
                                "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", target_room_id
                            )
                            if room_server_id:
                                await ActionService.notify_student_invite(
                                    server_id=room_server_id,
                                    student_no=student_no,
                                    first_name=first_name,
                                    last_name=last_name,
                                    first_name_en=first_name_en,
                                    last_name_en=last_name_en,
                                    user_name=user_name,
                                )
                        else:
                            raise ValueError(f"เลขที่ {student_no} มีรายชื่ออยู่ในห้องนี้แล้ว")
                    else:
                        # ghost / ผู้ใช้ใหม่ → เป็นสมาชิก active ได้ทันที (มีแค่ชื่อ ไม่มี PII ให้รั่ว)
                        res = await conn.execute("""
                            INSERT INTO students (room_id, student_no, user_id, status, identity_claimed, added_by)
                            SELECT $1, $2, $3, 'active', FALSE, $4 WHERE NOT EXISTS (
                                SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                            )
                        """, target_room_id, student_no, user_id, actor_user_id)

                        if res == "INSERT 0 1":
                            exec_time = int((time.time() - start_time) * 1000)
                            await service_logger.log(
                                conn=conn, action="CREATE", actor_identifier=actor_identifier,
                                client_source=client_source, room_id=target_room_id, user_id=user_id,
                                entity_type="STUDENT", entity_id=str(student_no), status="success",
                                new_values=new_values, endpoint_or_command="add_student", execution_time_ms=exec_time
                            )
                            # 📢 แจ้งเตือน Discord: มีสมาชิกใหม่ (ไม่ @everyone)
                            room_server_id = await conn.fetchval(
                                "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", target_room_id
                            )
                            if room_server_id:
                                await ActionService.notify_new_student(
                                    server_id=room_server_id,
                                    student_no=student_no,
                                    first_name=first_name,
                                    last_name=last_name,
                                    first_name_en=first_name_en,
                                    last_name_en=last_name_en,
                                    user_name=user_name,
                                )
                        else:
                            raise ValueError(f"เลขที่ {student_no} มีรายชื่ออยู่ในห้องนี้แล้ว")
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT",
                    entity_id=str(student_no), status="failed", error_detail=str(e),
                    new_values=new_values, endpoint_or_command="add_student", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def bulk_add_students(cls, pool: asyncpg.Pool, students: List[dict], user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, actor_user_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        new_values = {"students": students, "user_name": user_name}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: ต้องมี MANAGE_STUDENTS ถึงจะเพิ่มนักเรียน bulk ได้
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_STUDENTS")
                    # 🌟 identity: ชื่ออังกฤษเป็นกุญแจหลัก (English-primary), fallback ไทย NFC
                    # — ใช้ _find_or_create_user จุดเดียวกับ add_student กัน dedupe พัง
                    # Consent Model: (user_id, is_real) — is_real → pending invite, ghost → active
                    user_map = {}
                    user_by_index = {}
                    for idx, s in enumerate(students):
                        key = identity_pair(
                            s.get('first_name_en'), s.get('last_name_en'),
                            s['first_name'], s['last_name'],
                        )
                        if key not in user_map:
                            user_map[key] = await cls._find_or_create_user(
                                conn, s['first_name'], s['last_name'],
                                s.get('first_name_en') or '', s.get('last_name_en') or '',
                                s.get('nickname') or '', s.get('nickname_en') or '',
                            )
                        user_by_index[idx] = user_map[key]

                    active_tuples = []
                    pending_tuples = []
                    pending_infos = []  # (student_no, first, last, first_en, last_en) สำหรับแจ้งคำเชิญ
                    for i, s in enumerate(students):
                        uid, is_real = user_by_index[i]
                        # 🛡️ กันซ้ำ: คนที่อยู่ในห้องนี้อยู่แล้ว (active หรือ pending) → ข้าม ไม่สร้างซ้ำ
                        if await conn.fetchval(
                            "SELECT 1 FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL",
                            target_room_id, uid,
                        ):
                            continue
                        row = (target_room_id, s['student_no'], uid, actor_user_id)
                        if is_real:
                            pending_tuples.append(row)
                            pending_infos.append((
                                s['student_no'], s['first_name'], s['last_name'],
                                s.get('first_name_en') or '', s.get('last_name_en') or '',
                            ))
                        else:
                            active_tuples.append(row)

                    if active_tuples:
                        await conn.executemany("""
                            INSERT INTO students (room_id, student_no, user_id, status, identity_claimed, added_by)
                            SELECT $1, $2, $3, 'active', FALSE, $4 WHERE NOT EXISTS (
                                SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                            )
                        """, active_tuples)
                    if pending_tuples:
                        await conn.executemany("""
                            INSERT INTO students (room_id, student_no, user_id, status, identity_claimed, added_by)
                            SELECT $1, $2, $3, 'pending', FALSE, $4 WHERE NOT EXISTS (
                                SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                            )
                        """, pending_tuples)

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, entity_type="STUDENT_BULK",
                        status="success", new_values=new_values, endpoint_or_command="bulk_add_students", execution_time_ms=exec_time
                    )

                    # 📢 ถ้ามีคำเชิญ pending → แจ้งเตือน Discord ต่อคน (มี server_id เท่านั้น)
                    room_server_id = await conn.fetchval(
                        "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", target_room_id
                    )
                    if room_server_id and pending_infos:
                        for info in pending_infos:
                            await ActionService.notify_student_invite(
                                server_id=room_server_id,
                                student_no=info[0], first_name=info[1], last_name=info[2],
                                first_name_en=info[3], last_name_en=info[4],
                                user_name=user_name,
                            )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT_BULK",
                    status="failed", error_detail=str(e), new_values=new_values, 
                    endpoint_or_command="bulk_add_students", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def update_student(cls, pool: asyncpg.Pool, student_no: int, update_data: dict, updater_user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        new_values = update_data.copy()
        old_values = None
        
        new_student_no = update_data.pop('new_student_no', None)
        
        if 'permissions' in update_data:
            update_data['permissions'] = json.dumps(update_data['permissions']) if update_data['permissions'] else '[]'

        clean_data = {k: v for k, v in update_data.items() if v is not None and k in STUDENT_PATCHABLE_COLUMNS}
        if not clean_data and new_student_no is None: return

        # 🌟 NFC-normalize ชื่อไทยก่อนเขียนลง users (แก้ อำ/อํา ฯลฯ ให้ exact-match ตรงกัน)
        for k in list(clean_data):
            if k in NAME_NFC_FIELDS:
                clean_data[k] = normalize_nfc(clean_data[k])

        global_updates = {k: v for k, v in clean_data.items() if k in GLOBAL_FIELDS}
        local_updates = {k: v for k, v in clean_data.items() if k in LOCAL_FIELDS}

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    
                    old_row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2 AND s.deleted_at IS NULL", target_room_id, student_no)
                    if old_row: old_values = dict(old_row)

                    target_info = await conn.fetchrow(
                        "SELECT user_id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", 
                        target_room_id, student_no
                    )
                    if not target_info: raise StudentNotFoundError("ไม่พบเลขที่นี้")
                    target_user_id = target_info['user_id']

                    actor_row = await conn.fetchrow("SELECT is_admin, permissions FROM students WHERE room_id = $1 AND user_id = $2", target_room_id, updater_user_id)
                    actor_is_god = actor_row['is_admin'] if actor_row else False
                    
                    from core.config import settings
                    is_super_admin = settings.SUPER_ADMIN_ID and int(updater_user_id) == int(settings.SUPER_ADMIN_ID)
                    if is_super_admin: actor_is_god = True

                    is_editing_self = (target_user_id == updater_user_id)
                    has_manage_permission = False
                    
                    try:
                        await require_permission(conn, target_room_id, updater_user_id, "MANAGE_STUDENTS")
                        has_manage_permission = True
                    except ForbiddenError:
                        pass

                    if not is_editing_self and not has_manage_permission:
                        raise ForbiddenError("คุณไม่มีสิทธิ์แก้ไขข้อมูลของผู้อื่น")

                    if not actor_is_god:
                        local_updates.pop('is_admin', None)
                        local_updates.pop('permissions', None)
                        if not has_manage_permission:
                            local_updates.pop('class_role', None)
                            local_updates.pop('status', None)
                            if new_student_no and new_student_no != student_no:
                                raise ForbiddenError("คุณไม่มีสิทธิ์แก้ไขเลขที่ของตนเอง")

                    if new_student_no and new_student_no != student_no:
                        exists = await conn.fetchval("SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", target_room_id, new_student_no)
                        if exists: raise ValidationError(f"เลขที่ {new_student_no} มีคนใช้ไปแล้วในห้องนี้")
                        
                        await conn.execute("UPDATE students SET student_no = $1, updated_at = CURRENT_TIMESTAMP WHERE room_id = $2 AND student_no = $3", new_student_no, target_room_id, student_no)
                        student_no = new_student_no 

                    if global_updates and target_user_id:
                        keys = sorted(global_updates.keys())
                        set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(keys)]
                        values = [target_user_id] + [global_updates[k] for k in keys]
                        await conn.execute(f"UPDATE users SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE id = $1", *values)

                    if local_updates:
                        keys = sorted(local_updates.keys())
                        set_clauses = [f"{key} = ${i+3}" if key != 'permissions' else f"{key} = ${i+3}::jsonb" for i, key in enumerate(keys)]
                        values = [target_room_id, student_no] + [local_updates[k] for k in keys]
                        await conn.execute(f"UPDATE students SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE room_id = $1 AND student_no = $2", *values)

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=updater_user_id,
                        entity_type="STUDENT", entity_id=str(new_student_no or student_no), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="update_student", execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=updater_user_id,
                    entity_type="STUDENT", entity_id=str(student_no), status="failed", error_detail=str(e),
                    old_values=old_values, new_values=new_values, endpoint_or_command="update_student", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_student_by_user_id(cls, pool: asyncpg.Pool, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND u.id = $2 AND s.deleted_at IS NULL", target_room_id, user_id)
                if not row: raise StudentNotFoundError("คุณยังไม่มีรายชื่อนักเรียนในห้องนี้")
                data = dict(row)
                data['permissions'] = cls._parse_permissions(data['permissions'])
                data['data_completion'] = cls._calculate_completion(data)
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT", status="success", endpoint_or_command="get_student_by_user_id", execution_time_ms=exec_time
                )
                return data
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT", status="failed", error_detail=str(e), 
                    endpoint_or_command="get_student_by_user_id", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_all_students(cls, pool: asyncpg.Pool, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                is_member = await conn.fetchval("SELECT 1 FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL", target_room_id, user_id)
                
                from core.config import settings
                is_super_admin = settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID)
                
                if not is_member and not is_super_admin: raise ForbiddenError("คุณไม่มีสิทธิ์ดูรายชื่อ เพราะไม่ได้อยู่ในห้องเรียนนี้")

                rows = await conn.fetch(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.deleted_at IS NULL ORDER BY s.student_no ASC", target_room_id)
                
                results = []
                for row in rows:
                    full_data = dict(row)
                    results.append({
                        "id": full_data["id"],
                        "student_no": full_data["student_no"],
                        "student_id": full_data.get("student_id"),
                        "first_name": full_data["first_name"],
                        "last_name": full_data["last_name"],
                        "nickname": full_data.get("nickname"),
                        "first_name_en": full_data.get("first_name_en"),
                        "last_name_en": full_data.get("last_name_en"),
                        "nickname_en": full_data.get("nickname_en"),
                        "class_role": full_data["class_role"],
                        "status": full_data["status"],
                        "is_admin": full_data.get("is_admin", False),
                        "identity_claimed": bool(full_data.get("identity_claimed", False)),
                        "added_by": full_data.get("added_by"),
                        "discord_id_str": str(full_data['discord_id']) if full_data.get('discord_id') else None,
                        "data_completion": cls._calculate_completion(full_data)
                    })
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT_LIST", status="success", endpoint_or_command="get_all_students", execution_time_ms=exec_time
                )
                return results
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT_LIST", status="failed", error_detail=str(e), 
                    endpoint_or_command="get_all_students", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def search_students(cls, pool, query: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันการค้นหาข้ามห้อง / คนนอก)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)
                sql_query = f"""
                    {cls.BASE_STUDENT_SELECT}
                    WHERE s.room_id = $1
                    AND (
                        u.first_name ILIKE $2 OR
                        u.last_name ILIKE $2 OR
                        u.first_name_en ILIKE $2 OR
                        u.last_name_en ILIKE $2 OR
                        u.nickname ILIKE $2 OR
                        u.nickname_en ILIKE $2 OR
                        CAST(s.student_no AS TEXT) = $3
                    )
                    AND s.status = 'active'
                    AND s.deleted_at IS NULL
                    AND u.deleted_at IS NULL
                    LIMIT 5
                """
                search_pattern = f"%{query}%"
                rows = await conn.fetch(sql_query, target_room_id, search_pattern, query)

                # 🛡️ Consent Model: mask PII ต่อแถว — สมาชิกห้องค้นชื่อได้ (transparency) แต่ PII ของคนที่
                # ยังไม่ยืนยันตัวตนถูก 🔒 ซ่อน (กัน search รั่วเบอร์/ที่อยู่/ข้อมูลสุขภาพเต็ม ๆ)
                is_super_admin = settings.SUPER_ADMIN_ID and user_id and int(user_id) == int(settings.SUPER_ADMIN_ID)
                viewer_has_view_all = False
                if not is_super_admin and user_id is not None:
                    try:
                        await require_permission(conn, target_room_id, user_id, "VIEW_ALL_STUDENTS")
                        viewer_has_view_all = True
                    except ForbiddenError:
                        viewer_has_view_all = False

                results = []
                for r in rows:
                    d = dict(r)
                    # asyncpg คืน JSONB เป็น str/dict ตามเวอร์ชัน → normalize ก่อน (StudentResponse expects List[str])
                    d['permissions'] = cls._parse_permissions(d.get('permissions'))
                    can_view = can_view_pii(
                        requester_user_id=user_id,
                        target_user_id=d.get("user_id"),
                        identity_claimed=d.get("identity_claimed"),
                        is_super_admin=is_super_admin,
                        viewer_has_view_all=viewer_has_view_all,
                    )
                    results.append(mask_private_fields(d, can_view))

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT_SEARCH",
                    status="success", new_values={"query": query}, endpoint_or_command="search_students", execution_time_ms=exec_time
                )
                return results
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT_SEARCH",
                    status="failed", error_detail=str(e), new_values={"query": query},
                    endpoint_or_command="search_students", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_student_profile(cls, pool: asyncpg.Pool, student_no: int, requester_user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                target_row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2 AND s.deleted_at IS NULL", target_room_id, student_no)
                if not target_row: raise StudentNotFoundError("ไม่พบข้อมูลนักเรียน")

                target_data = dict(target_row)
                target_user_id = target_data.get('user_id')
                target_data['permissions'] = cls._parse_permissions(target_data['permissions'])

                is_super_admin = settings.SUPER_ADMIN_ID and int(requester_user_id) == int(settings.SUPER_ADMIN_ID)

                has_permission = False
                if not is_super_admin:
                    # 🛡️ ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันการอ่านโปรไฟล์ข้ามห้อง)
                    await require_member(conn, target_room_id, requester_user_id)
                    try:
                        await require_permission(conn, target_room_id, requester_user_id, "VIEW_ALL_STUDENTS")
                        has_permission = True
                    except ForbiddenError:
                        has_permission = False

                # 🛡️ Consent Model (ดู core/privacy.py): PII เห็นได้เฉพาะ super admin / ดูตัวเอง /
                # (สมาชิกยืนยันตัวตนแล้ว AND มี VIEW_ALL_STUDENTS) — แอดมินก็เห็น PII ของสมาชิกที่ยังไม่
                # ยืนยันตัวตนไม่ได้ (กันแฮ็กเกอร์สร้างห้องแล้วแอดชื่อคนอื่นเพื่อเก็บข้อมูล)
                can_view = can_view_pii(
                    requester_user_id=requester_user_id,
                    target_user_id=target_user_id,
                    identity_claimed=target_data.get("identity_claimed"),
                    is_super_admin=is_super_admin,
                    viewer_has_view_all=has_permission,
                )
                mask_private_fields(target_data, can_view)

                target_data['data_completion'] = cls._calculate_completion(dict(target_row))

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=requester_user_id,
                    entity_type="STUDENT", entity_id=str(student_no), status="success",
                    endpoint_or_command="get_student_profile", execution_time_ms=exec_time
                )
                return target_data
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=requester_user_id,
                    entity_type="STUDENT", entity_id=str(student_no), status="failed", error_detail=str(e),
                    endpoint_or_command="get_student_profile", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_user_rooms(cls, pool, user_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                query = """
                    SELECT 
                        r.id as room_id, r.server_id, r.room_code, r.room_name, 
                        s.class_role as role, s.status, s.is_admin, s.permissions
                    FROM students s
                    JOIN rooms r ON s.room_id = r.id
                    WHERE s.user_id = $1 AND s.deleted_at IS NULL AND r.deleted_at IS NULL
                """
                rows = await conn.fetch(query, user_id)
                res = []
                for row in rows:
                    d = dict(row)
                    d['permissions'] = cls._parse_permissions(d['permissions'])
                    res.append(d)
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, user_id=user_id, entity_type="ROOM_LIST",
                    status="success", endpoint_or_command="get_user_rooms", execution_time_ms=exec_time
                )
                return res
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, user_id=user_id, entity_type="ROOM_LIST",
                    status="failed", error_detail=str(e), endpoint_or_command="get_user_rooms", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def update_status(cls, pool, student_no: int, status: str, user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        old_values = None
        new_values = {"status": status}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: มีแค่ผู้ดูแล (MANAGE_STUDENTS) ถึงจะเปลี่ยนสถานะสมาชิกได้
                    if user_id is not None:
                        await require_permission(conn, target_room_id, user_id, "MANAGE_STUDENTS")

                    old_row = await conn.fetchrow(
                        "SELECT user_id, status, is_admin FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
                        target_room_id, student_no
                    )
                    if old_row: old_values = dict(old_row)

                    # 🛡️ กันการปลดตัวเอง / ปลด admin อีกคน / ปลด owner (เลข 0)
                    if old_row and user_id is not None:
                        is_super_admin = settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID)
                        if not is_super_admin:
                            if int(old_row['user_id']) == int(user_id):
                                raise ForbiddenError("ไม่สามารถเปลี่ยนสถานะของตนเองได้")
                            if old_row['is_admin'] or student_no == 0:
                                raise ForbiddenError("ไม่สามารถเปลี่ยนสถานะผู้ดูแลห้องได้")

                    res = await conn.execute("UPDATE students SET status = $1 WHERE room_id = $2 AND student_no = $3 AND deleted_at IS NULL", status, target_room_id, student_no)
                    if res == "UPDATE 0": raise StudentNotFoundError("ไม่พบเลขที่นี้")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, entity_type="STUDENT",
                        entity_id=str(student_no), status="success", old_values=old_values,
                        new_values=new_values, endpoint_or_command="update_status", execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT",
                    entity_id=str(student_no), status="failed", error_detail=str(e),
                    old_values=old_values, new_values=new_values, endpoint_or_command="update_status", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def delete_student(cls, pool: asyncpg.Pool, student_no: int, user_name: str, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        old_values = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_STUDENTS")

                    old_row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2 AND s.deleted_at IS NULL", target_room_id, student_no)
                    if old_row: old_values = dict(old_row)

                    # 🛡️ กันการลบตัวเอง / ลบ admin อีกคน / ลบ owner (เลข 0) — ห้องต้องเหลือคนดูแลเสมอ
                    if old_row:
                        is_super_admin = settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID)
                        if not is_super_admin:
                            if int(old_row['user_id']) == int(user_id):
                                raise ForbiddenError("ไม่สามารถลบตนเองออกจากห้องได้")
                            if old_row['is_admin'] or student_no == 0:
                                raise ForbiddenError("ไม่สามารถลบผู้ดูแลห้องได้")

                    res = await conn.execute("UPDATE students SET deleted_at = NOW() WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", target_room_id, student_no)
                    if res == "UPDATE 0": raise StudentNotFoundError("ไม่พบข้อมูล หรือถูกลบไปแล้ว")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT", entity_id=str(student_no), status="success",
                        old_values=old_values, endpoint_or_command="delete_student", execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="DELETE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT", entity_id=str(student_no), status="failed", error_detail=str(e),
                    old_values=old_values, endpoint_or_command="delete_student", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def delete_student_permanent(cls, pool: asyncpg.Pool, student_no: int, user_name: str, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        old_values = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ กันการลบตัวเองถาวร (owner/เลข 0) — ห้องต้องเหลือคนดูแลเสมอ
                    old_row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2", target_room_id, student_no)
                    if old_row: old_values = dict(old_row)
                    if old_row:
                        is_super_admin = settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID)
                        if not is_super_admin:
                            if int(old_row['user_id']) == int(user_id):
                                raise ForbiddenError("ไม่สามารถลบตนเองออกจากห้องได้")

                    # 🛡️ RBAC: ตรวจสิทธิ์หลังเช็คว่ามีแถวจริง (กัน idempotency ทำ fail-log ซ้ำตอนลบซ้ำ)
                    await require_permission(conn, target_room_id, user_id, "HARD_DELETE_STUDENTS")

                    has_payments = await conn.fetchval(
                        "SELECT 1 FROM student_payments WHERE student_id = (SELECT id FROM students WHERE room_id = $1 AND student_no = $2) LIMIT 1",
                        target_room_id, student_no
                    )
                    if has_payments: raise ValidationError("ไม่สามารถลบข้อมูลถาวรได้ เนื่องจากมีประวัติการเงิน ให้ใช้ Soft Delete แทน")

                    res = await conn.execute("DELETE FROM students WHERE room_id = $1 AND student_no = $2", target_room_id, student_no)
                    if res == "DELETE 0": raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนเลขที่นี้")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT", entity_id=str(student_no), status="success",
                        old_values=old_values, endpoint_or_command="delete_student_permanent", execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="DELETE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT", entity_id=str(student_no), status="failed", error_detail=str(e),
                    old_values=old_values, endpoint_or_command="delete_student_permanent", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def sync_discord_account(
        cls,
        pool: asyncpg.Pool,
        room_code: str,
        student_no: int,
        discord_id: str,
        discord_username: str,
        client_source: str,
        actor_identifier: str,
        actor_user_id: Optional[int] = None,
    ) -> None:
        """ผูก Discord ID เข้ากับ student ที่ระบุ (room_code + student_no).

        🛡️ IDOR guard: ถ้ามี actor_user_id (ผู้ยิง request จาก get_current_user) ต้องเป็น
        เจ้าของ student เองเสมอ — กันคนอื่นส่ง X-Discord-Id/room_code ของคนอื่น
        แล้วมา "จี้" ผูกบัญชี Discord ของตัวเองทับบัญชีเพื่อน (privilege escalation).
        """
        start_time = time.time()
        target_room_id = None
        new_values = {"room_code": room_code, "student_no": student_no, "discord_id": discord_id, "discord_username": discord_username}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # find room by room_code
                    row = await conn.fetchrow(
                        "SELECT id FROM rooms WHERE room_code = $1 AND deleted_at IS NULL", room_code
                    )
                    if not row:
                        raise RoomNotFoundError("ไม่พบรหัสห้องนี้")
                    target_room_id = row["id"]

                    # find student in this room
                    student_row = await conn.fetchrow(
                        "SELECT user_id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
                        target_room_id, student_no
                    )
                    if not student_row:
                        raise StudentNotFoundError("ไม่พบเลขที่นักเรียนในห้องนี้")

                    user_id = student_row["user_id"]

                    # 🛡️ IDOR guard: ผู้ยิงต้องเป็นเจ้าของ student นี้ (หรือ Super Admin)
                    if actor_user_id is not None:
                        is_super_admin = settings.SUPER_ADMIN_ID and int(actor_user_id) == int(settings.SUPER_ADMIN_ID)
                        if not is_super_admin and int(actor_user_id) != int(user_id):
                            raise ForbiddenError("ไม่สามารถผูก Discord ให้กับเลขที่ของผู้อื่นได้")

                    # check if discord_id is already used by another user
                    existing = await conn.fetchval(
                        "SELECT id FROM users WHERE discord_id = $1 AND id != $2 AND deleted_at IS NULL",
                        discord_id, user_id
                    )
                    if existing:
                        raise ValidationError("Discord ID นี้ถูกผูกไว้กับบัญชีอื่นแล้ว")

                    # update user's discord_id and discord_username
                    await conn.execute(
                        "UPDATE users SET discord_id = $1, discord_username = $2, updated_at = NOW() WHERE id = $3",
                        discord_id, discord_username, user_id
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="SYNC_DISCORD", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT", entity_id=str(student_no), status="success",
                        new_values=new_values, endpoint_or_command="sync_discord_account", execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="SYNC_DISCORD", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="STUDENT", entity_id=str(student_no) if student_no else None,
                    status="failed", error_detail=str(e), new_values=new_values,
                    endpoint_or_command="sync_discord_account", execution_time_ms=exec_time
                )
            raise e
