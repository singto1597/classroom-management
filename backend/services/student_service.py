import asyncpg
import json
import time
from datetime import datetime
from typing import List, Dict, Any, FrozenSet, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import io

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from core.rbac import require_permission
from models.student_schemas import StudentUpdateRequest

service_logger = AuditLogger(service_name="STUDENT")

STUDENT_PATCHABLE_COLUMNS: FrozenSet[str] = frozenset(StudentUpdateRequest.model_fields.keys())

GLOBAL_FIELDS: FrozenSet[str] = frozenset([
    'prefix', 'first_name', 'last_name', 'nickname', 'birthday',
    'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease',
    'phone_number', 'phone_number_parent', 'phone_number_parent_relation',
    'line_id', 'ig_username', 'email',
    'address_house_no', 'address_road', 'address_sub_district',
    'address_district', 'address_province', 'address_post_code'
])

LOCAL_FIELDS: FrozenSet[str] = frozenset([
    'student_id', 'class_role', 'cleaning_duty', 'olympic_camp',
    'portfolio', 'target_faculty', 'is_admin', 'permissions', 'status'
])

class StudentService:

    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: 
                raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id")

    BASE_STUDENT_SELECT = """
        SELECT 
            s.id, s.room_id, u.id as user_id, u.discord_id, s.student_no, s.student_id,
            u.prefix, u.first_name, u.last_name, u.nickname, u.birthday,
            s.class_role, s.cleaning_duty, s.olympic_camp, s.portfolio, s.target_faculty,
            u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
            u.phone_number, u.phone_number_parent, u.phone_number_parent_relation,
            u.line_id, u.ig_username, u.email,
            u.address_house_no, u.address_road, u.address_sub_district, u.address_district, u.address_province, u.address_post_code,
            s.status, s.is_admin, s.permissions, s.created_at, s.updated_at
        FROM students s
        LEFT JOIN users u ON s.user_id = u.id
    """

    @staticmethod
    def _parse_permissions(perms: Any) -> List[str]:
        if not perms: return []
        if isinstance(perms, list): return perms
        if isinstance(perms, str):
            try: return json.loads(perms)
            except: return []
        return []

    @staticmethod
    def _calculate_completion(row: dict) -> dict:
        expected_fields = [
            'student_id', 'prefix', 'nickname', 'birthday',
            'cleaning_duty', 'olympic_camp', 'target_faculty',
            'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease',
            'phone_number', 'phone_number_parent', 'phone_number_parent_relation',
            'line_id', 'ig_username', 'email',
            'address_house_no', 'address_road', 'address_sub_district',
            'address_district', 'address_province', 'address_post_code'
        ]
        missing = [f for f in expected_fields if not row.get(f) or str(row.get(f)).strip() == ""]
        total = len(expected_fields)
        filled = total - len(missing)
        percent = int((filled / total) * 100)
        return {"percentage": percent, "missing_fields": missing}

    @classmethod
    async def add_student(cls, pool: asyncpg.Pool, student_no: int, first_name: str, last_name: str, user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        new_values = {"student_no": student_no, "first_name": first_name, "last_name": last_name, "user_name": user_name}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    user_id = await conn.fetchval("SELECT id FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL", first_name, last_name)
                    if not user_id:
                        user_id = await conn.fetchval("INSERT INTO users (first_name, last_name) VALUES ($1, $2) RETURNING id", first_name, last_name)

                    res = await conn.execute("""
                        INSERT INTO students (room_id, student_no, user_id, status) 
                        SELECT $1, $2, $3, 'active' WHERE NOT EXISTS (
                            SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                        )
                    """, target_room_id, student_no, user_id)
                    
                    if res == "INSERT 0 1":
                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="CREATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id, user_id=user_id,
                            entity_type="STUDENT", entity_id=str(student_no), status="success",
                            new_values=new_values, endpoint_or_command="add_student", execution_time_ms=exec_time
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
    async def bulk_add_students(cls, pool: asyncpg.Pool, students: List[dict], user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        new_values = {"students": students, "user_name": user_name}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    first_names = [s['first_name'] for s in students]
                    last_names = [s['last_name'] for s in students]
                    
                    existing_users = await conn.fetch(
                        "SELECT id, first_name, last_name FROM users WHERE (first_name, last_name) IN (SELECT * FROM UNNEST($1::text[], $2::text[])) AND deleted_at IS NULL",
                        first_names, last_names
                    )
                    
                    user_map = {(row['first_name'], row['last_name']): row['id'] for row in existing_users}
                    new_users = [s for s in students if (s['first_name'], s['last_name']) not in user_map]
                    
                    if new_users:
                        new_firsts = [s['first_name'] for s in new_users]
                        new_lasts = [s['last_name'] for s in new_users]
                        inserted_users = await conn.fetch(
                            "INSERT INTO users (first_name, last_name) SELECT * FROM UNNEST($1::text[], $2::text[]) RETURNING id, first_name, last_name",
                            new_firsts, new_lasts
                        )
                        for row in inserted_users:
                            user_map[(row['first_name'], row['last_name'])] = row['id']
                    
                    student_tuples = [(target_room_id, s['student_no'], user_map[(s['first_name'], s['last_name'])]) for s in students]
                    await conn.executemany("""
                        INSERT INTO students (room_id, student_no, user_id, status) 
                        SELECT $1, $2, $3, 'active' WHERE NOT EXISTS (
                            SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL
                        )
                    """, student_tuples)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, entity_type="STUDENT_BULK",
                        status="success", new_values=new_values, endpoint_or_command="bulk_add_students", execution_time_ms=exec_time
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
                        "class_role": full_data["class_role"],
                        "status": full_data["status"],
                        "is_admin": full_data.get("is_admin", False),
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
    async def export_students_excel(cls, pool, fields: List[str], user_name: str, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "EXPORT_STUDENTS")

                    rows = await conn.fetch(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.deleted_at IS NULL ORDER BY s.student_no ASC", target_room_id)
                    if not rows: raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนในห้องนี้")

                    data = []
                    for r in rows:
                        row_dict = dict(r)
                        filtered_row = {f: row_dict.get(f) for f in fields}
                        data.append(filtered_row)

                    df = pd.DataFrame(data)
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Students_List')
                    
                    output.seek(0)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="EXPORT", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_LIST", status="success", new_values={"fields": fields}, 
                        endpoint_or_command="export_students_excel", execution_time_ms=exec_time
                    )
                    
                    return output
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="EXPORT", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="STUDENT_LIST", status="failed", error_detail=str(e), 
                    new_values={"fields": fields}, endpoint_or_command="export_students_excel", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def search_students(cls, pool, query: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                sql_query = f"""
                    {cls.BASE_STUDENT_SELECT}
                    WHERE s.room_id = $1 
                    AND (
                        u.first_name ILIKE $2 OR 
                        u.last_name ILIKE $2 OR 
                        u.nickname ILIKE $2 OR 
                        CAST(s.student_no AS TEXT) = $3
                    )
                    AND s.status = 'active'
                    AND s.deleted_at IS NULL
                    LIMIT 5
                """
                search_pattern = f"%{query}%"
                rows = await conn.fetch(sql_query, target_room_id, search_pattern, query)
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, entity_type="STUDENT_SEARCH",
                    status="success", new_values={"query": query}, endpoint_or_command="search_students", execution_time_ms=exec_time
                )
                return [dict(r) for r in rows]
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
                
                from core.config import settings
                is_super_admin = settings.SUPER_ADMIN_ID and int(requester_user_id) == int(settings.SUPER_ADMIN_ID)
                
                is_self = (target_user_id == requester_user_id)
                has_permission = False
                
                if not is_super_admin:
                    try:
                        await require_permission(conn, target_room_id, requester_user_id, "VIEW_ALL_STUDENTS")
                        has_permission = True
                    except ForbiddenError:
                        has_permission = False
                
                if not (is_super_admin or is_self or has_permission):
                    private_fields = ['phone_number_parent', 'phone_number_parent_relation', 'address_house_no', 'address_road', 'address_sub_district', 'address_district', 'address_province', 'address_post_code', 'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease']
                    for field in private_fields:
                        if field in target_data: target_data[field] = "🔒 ไม่มีสิทธิ์เข้าถึง"
                
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
    async def update_status(cls, pool, student_no: int, status: str, user_name: str, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        start_time = time.time()
        target_room_id = None
        old_values = None
        new_values = {"status": status}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    old_row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", target_room_id, student_no)
                    if old_row: old_values = dict(old_row)
                    
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
                    await require_permission(conn, target_room_id, user_id, "HARD_DELETE_STUDENTS")
                    
                    old_row = await conn.fetchrow(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2", target_room_id, student_no)
                    if old_row: old_values = dict(old_row)

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
    ) -> None:
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
