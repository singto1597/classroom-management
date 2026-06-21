import asyncpg
from datetime import datetime
from typing import List, Dict, Any, FrozenSet, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import io

from core.audit import log_action
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from core.rbac import require_permission
from core.rbac import RBACManager
from models.student_schemas import StudentUpdateRequest

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
    'portfolio', 'target_faculty'
])

class StudentService:

    BASE_STUDENT_SELECT = """
        SELECT 
            s.id, s.room_id, u.discord_id, s.student_no, s.student_id,
            u.prefix, u.first_name, u.last_name, u.nickname, u.birthday,
            s.class_role, s.cleaning_duty, s.olympic_camp, s.portfolio, s.target_faculty,
            u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
            u.phone_number, u.phone_number_parent, u.phone_number_parent_relation,
            u.line_id, u.ig_username, u.email,
            u.address_house_no, u.address_road, u.address_sub_district, u.address_district, u.address_province, u.address_post_code,
            s.status, s.created_at, s.updated_at
        FROM students s
        LEFT JOIN users u ON s.user_id = u.id
    """

    # 🔥 เพิ่มฟังก์ชันผู้ช่วยตรงนี้ เพื่อแกะ ID ออกมาอย่างปลอดภัย
    @staticmethod
    def _extract_id(user_data: Any) -> int:
        if isinstance(user_data, dict):
            # พยายามดึง discord_id ก่อน (สำหรับคนล็อกอินผ่าน Discord) 
            # ถ้าไม่มี ให้ดึง user_id (สำหรับคนล็อกอินผ่าน Google)
            raw_id = user_data.get('discord_id') or user_data.get('user_id')
            if not raw_id:
                raise ForbiddenError("Token ปัจจุบันไม่มีข้อมูล User ID หรือ Discord ID ที่ถูกต้อง")
            return int(raw_id)
        # ถ้าส่งมาเป็นตัวเลขหรือ String เดี่ยวๆ ก็ Cast ได้เลย
        return int(user_data)
    
    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id")

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
    async def add_student(cls, pool: asyncpg.Pool, student_no: int, first_name: str, last_name: str, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                
                user_id = await conn.fetchval(
                    "SELECT id FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL", 
                    first_name, last_name
                )
                
                if not user_id:
                    user_id = await conn.fetchval(
                        "INSERT INTO users (first_name, last_name) VALUES ($1, $2) RETURNING id", 
                        first_name, last_name
                    )

                await conn.execute(
                    """INSERT INTO students (room_id, student_no, user_id) 
                       VALUES ($1, $2, $3) ON CONFLICT (room_id, student_no) DO NOTHING""",
                    resolved_room_id, student_no, user_id
                )
                await log_action(conn, resolved_room_id, user_name, "Add Student", f"เพิ่มเลขที่ {student_no}")

    @classmethod
    async def bulk_add_students(cls, pool: asyncpg.Pool, students: List[dict], user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                
                first_names = [s['first_name'] for s in students]
                last_names = [s['last_name'] for s in students]
                
                existing_users = await conn.fetch(
                    """
                    SELECT id, first_name, last_name FROM users 
                    WHERE (first_name, last_name) IN (
                        SELECT * FROM UNNEST($1::text[], $2::text[])
                    ) AND deleted_at IS NULL
                    """,
                    first_names, last_names
                )
                
                user_map = {(row['first_name'], row['last_name']): row['id'] for row in existing_users}
                
                new_users = [s for s in students if (s['first_name'], s['last_name']) not in user_map]
                
                if new_users:
                    new_firsts = [s['first_name'] for s in new_users]
                    new_lasts = [s['last_name'] for s in new_users]
                    
                    inserted_users = await conn.fetch(
                        """
                        INSERT INTO users (first_name, last_name) 
                        SELECT * FROM UNNEST($1::text[], $2::text[]) 
                        RETURNING id, first_name, last_name
                        """,
                        new_firsts, new_lasts
                    )
                    for row in inserted_users:
                        user_map[(row['first_name'], row['last_name'])] = row['id']
                
                student_tuples = [
                    (resolved_room_id, s['student_no'], user_map[(s['first_name'], s['last_name'])]) 
                    for s in students
                ]
                
                await conn.executemany(
                    """
                    INSERT INTO students (room_id, student_no, user_id) 
                    VALUES ($1, $2, $3) 
                    ON CONFLICT (room_id, student_no) DO NOTHING
                    """,
                    student_tuples
                )
                
                await log_action(conn, resolved_room_id, user_name, "Bulk Add", f"เพิ่มนักเรียน {len(students)} คน")
    
    @classmethod
    async def sync_discord(cls, pool: asyncpg.Pool, student_no: int, discord_id: Any, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        safe_discord_id = cls._extract_id(discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                
                user_id = await conn.fetchval(
                    "SELECT user_id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
                    resolved_room_id, student_no
                )
                if not user_id: raise StudentNotFoundError("ไม่พบเลขที่นี้ในระบบ")
                
                try:
                    await conn.execute("UPDATE users SET discord_id = $1 WHERE id = $2", safe_discord_id, user_id)
                except asyncpg.exceptions.UniqueViolationError:
                    raise ValidationError("บัญชี Discord นี้ถูกผูกกับนักเรียนคนอื่นในระบบไปแล้วครับ")
                
                await log_action(conn, resolved_room_id, user_name, "Sync Discord", f"ผูกดิสคอร์ดเข้ากับเลขที่ {student_no}")

    @classmethod
    async def update_student(cls, pool: asyncpg.Pool, student_no: int, update_data: dict, updater_discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None):
        safe_updater_discord_id = cls._extract_id(updater_discord_id) # 🛡️ เรียกใช้ _extract_id

        clean_data = {k: v for k, v in update_data.items() if v is not None and k in STUDENT_PATCHABLE_COLUMNS}
        if not clean_data: return

        global_updates = {k: v for k, v in clean_data.items() if k in GLOBAL_FIELDS}
        local_updates = {k: v for k, v in clean_data.items() if k in LOCAL_FIELDS}

        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)

                target_info = await conn.fetchrow(
                    """SELECT u.discord_id, s.user_id 
                       FROM students s 
                       LEFT JOIN users u ON s.user_id = u.id 
                       WHERE s.room_id = $1 AND s.student_no = $2 AND s.deleted_at IS NULL""", 
                    resolved_room_id, student_no
                )
                
                if not target_info:
                    raise StudentNotFoundError("ไม่พบเลขที่นี้")
                
                target_discord_id = target_info['discord_id']
                user_id = target_info['user_id']

                if target_discord_id != safe_updater_discord_id:
                    await require_permission(conn, resolved_room_id, safe_updater_discord_id, "MANAGE_STUDENTS")

                if global_updates and user_id:
                    keys = sorted(global_updates.keys())
                    set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(keys)]
                    values = [user_id] + [global_updates[k] for k in keys]
                    await conn.execute(
                        f"UPDATE users SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE id = $1", 
                        *values
                    )

                if local_updates:
                    keys = sorted(local_updates.keys())
                    set_clauses = [f"{key} = ${i+3}" for i, key in enumerate(keys)]
                    values = [resolved_room_id, student_no] + [local_updates[k] for k in keys]
                    await conn.execute(
                        f"UPDATE students SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE room_id = $1 AND student_no = $2", 
                        *values
                    )

                actor_row = await conn.fetchrow(
                    """SELECT u.first_name, u.last_name 
                       FROM students s 
                       JOIN users u ON s.user_id = u.id 
                       WHERE s.room_id = $1 AND (u.discord_id = $2 OR u.id = $2) AND s.deleted_at IS NULL""",
                    resolved_room_id, safe_updater_discord_id
                )
                
                actor_name = f"{actor_row['first_name'] or ''} {actor_row['last_name'] or ''}".strip() if actor_row else f"discord:{safe_updater_discord_id}"
                
                fields_desc = ", ".join(sorted(clean_data.keys()))
                await log_action(conn, resolved_room_id, actor_name, "Update Student", f"แก้ไขเลขที่ {student_no} ฟิลด์: {fields_desc}")

    @classmethod
    async def get_student_by_discord(cls, pool: asyncpg.Pool, discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        safe_discord_id = cls._extract_id(discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
            row = await conn.fetchrow(
                f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND (u.discord_id = $2 OR u.id = $2) AND s.deleted_at IS NULL", 
                resolved_room_id, safe_discord_id
            )
            if not row: raise StudentNotFoundError("ยังไม่ได้ Sync ข้อมูล")
            
            data = dict(row)
            data['data_completion'] = cls._calculate_completion(data)
            return data

    @classmethod
    async def get_all_students(cls, pool: asyncpg.Pool, requester_discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None) -> List[dict]:
        safe_requester_id = cls._extract_id(requester_discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
            
            is_member = await conn.fetchval(
                """SELECT 1 FROM students s 
                   JOIN users u ON s.user_id = u.id 
                   WHERE s.room_id = $1 AND (u.discord_id = $2 OR u.id = $2) AND s.deleted_at IS NULL""",
                resolved_room_id, safe_requester_id
            )
            if not is_member:
                raise ForbiddenError("คุณไม่มีสิทธิ์ดูรายชื่อ เพราะคุณไม่ได้อยู่ในห้องเรียนนี้")

            rows = await conn.fetch(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.deleted_at IS NULL ORDER BY s.student_no ASC", resolved_room_id)
            
            results = []
            for row in rows:
                full_data = dict(row)
                completion_status = cls._calculate_completion(full_data)
                
                safe_data = {
                    "id": full_data["id"],
                    "student_no": full_data["student_no"],
                    "student_id": full_data.get("student_id"),
                    "first_name": full_data["first_name"],
                    "last_name": full_data["last_name"],
                    "nickname": full_data.get("nickname"),
                    "class_role": full_data["class_role"],
                    "status": full_data["status"],
                    "discord_id_str": str(full_data['discord_id']) if full_data.get('discord_id') else None,
                    "data_completion": completion_status
                }
                results.append(safe_data)
                
            return results

    @classmethod
    async def export_students_excel(cls, pool, fields: List[str], user_name: str, discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None):
        safe_discord_id = cls._extract_id(discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                await require_permission(conn, resolved_room_id, safe_discord_id, "EXPORT_STUDENTS")

                rows = await conn.fetch(f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.deleted_at IS NULL ORDER BY s.student_no ASC", resolved_room_id)
                
                if not rows:
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนในห้องนี้")

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
                await log_action(conn, resolved_room_id, user_name, "Export Data", f"Exported fields: {', '.join(fields)}")
                
                return output

    @classmethod
    async def search_students(cls, pool, query: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
            
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
            rows = await conn.fetch(sql_query, resolved_room_id, search_pattern, query)
            
            return [dict(r) for r in rows]
    
    @classmethod
    async def get_student_profile(cls, pool: asyncpg.Pool, student_no: int, requester_discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        safe_requester_id = cls._extract_id(requester_discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
            
            target_row = await conn.fetchrow(
                f"{cls.BASE_STUDENT_SELECT} WHERE s.room_id = $1 AND s.student_no = $2 AND s.deleted_at IS NULL", 
                resolved_room_id, student_no
            )
            if not target_row: 
                raise StudentNotFoundError("ไม่พบข้อมูลนักเรียน")
            
            target_data = dict(target_row)
            target_discord = target_data.get('discord_id')
            
            from core.config import settings
            is_super_admin = settings.SUPER_ADMIN_ID and safe_requester_id == int(settings.SUPER_ADMIN_ID)
            
            requester_role = None
            if not is_super_admin:
                requester_row = await conn.fetchrow(
                    """SELECT s.class_role 
                       FROM students s 
                       JOIN users u ON s.user_id = u.id 
                       WHERE s.room_id = $1 AND (u.discord_id = $2 OR u.id = $2) AND s.status = 'active' AND s.deleted_at IS NULL""",
                    resolved_room_id, safe_requester_id
                )
                if not requester_row:
                    raise ForbiddenError("คุณไม่ได้อยู่ในห้องเรียนนี้")
                requester_role = requester_row['class_role']

            is_self = (target_discord is not None and int(target_discord) == safe_requester_id)
            
            has_permission = False
            if requester_role:
                has_permission = RBACManager.has_permission(requester_role, "VIEW_ALL_STUDENTS")
            
            has_full_access = is_super_admin or is_self or has_permission

            if not has_full_access:
                private_fields = [
                    'phone_number_parent', 'phone_number_parent_relation', 
                    'address_house_no', 'address_road', 'address_sub_district', 
                    'address_district', 'address_province', 'address_post_code', 
                    'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease'
                ]
                
                mask_text = "🔒 ไม่มีสิทธิ์เข้าถึง"
                for field in private_fields:
                    if field in target_data:
                        target_data[field] = mask_text
            
            target_data['data_completion'] = cls._calculate_completion(dict(target_row))
            return target_data

    @classmethod
    async def get_user_rooms(cls, pool, discord_id: Any):
        safe_discord_id = cls._extract_id(discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            query = """
                SELECT 
                    r.id as room_id,
                    r.server_id, 
                    r.room_code,
                    r.room_name, 
                    s.class_role as role
                FROM students s
                JOIN rooms r ON s.room_id = r.id
                JOIN users u ON s.user_id = u.id
                WHERE (u.discord_id = $1 OR u.id = $1)  
                AND s.deleted_at IS NULL
                AND r.deleted_at IS NULL
            """
            rows = await conn.fetch(query, safe_discord_id)
            return [dict(row) for row in rows]

    @classmethod
    async def update_status(cls, pool, student_no: int, status: str, user_name: str, server_id: Optional[int] = None, room_id: Optional[int] = None):
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                res = await conn.execute(
                    "UPDATE students SET status = $1 WHERE room_id = $2 AND student_no = $3 AND deleted_at IS NULL",
                    status, resolved_room_id, student_no
                )
                if res == "UPDATE 0": raise StudentNotFoundError("ไม่พบเลขที่นี้")
                
                await log_action(conn, resolved_room_id, user_name, "Status Change", f"เปลี่ยนสถานะเลขที่ {student_no} เป็น {status}")
    
    @classmethod
    async def delete_student(cls, pool: asyncpg.Pool, student_no: int, user_name: str, requester_discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None):
        safe_requester_id = cls._extract_id(requester_discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                await require_permission(conn, resolved_room_id, safe_requester_id, "MANAGE_STUDENTS")
                
                res = await conn.execute(
                    "UPDATE students SET deleted_at = NOW() WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
                    resolved_room_id, student_no
                )
                
                if res == "UPDATE 0":
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนเลขที่นี้ หรืออาจจะถูกลบไปแล้ว")
                    
                await log_action(conn, resolved_room_id, user_name, "Soft Delete", f"ลบข้อมูลนักเรียนเลขที่ {student_no} (Soft Delete)")

    @classmethod
    async def delete_student_permanent(cls, pool: asyncpg.Pool, student_no: int, user_name: str, requester_discord_id: Any, server_id: Optional[int] = None, room_id: Optional[int] = None):
        safe_requester_id = cls._extract_id(requester_discord_id) # 🛡️ เรียกใช้ _extract_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_room_id = await cls.resolve_room_id(conn, server_id=server_id, room_id=room_id)
                await require_permission(conn, resolved_room_id, safe_requester_id, "HARD_DELETE_STUDENTS")
                
                has_payments = await conn.fetchval(
                    "SELECT 1 FROM student_payments WHERE student_id = (SELECT id FROM students WHERE room_id = $1 AND student_no = $2) LIMIT 1",
                    resolved_room_id, student_no
                )
                if has_payments:
                    raise ValidationError("ไม่สามารถลบข้อมูลถาวรได้ เนื่องจากนักเรียนคนนี้มีประวัติการเงินในระบบ ให้ใช้ Soft Delete แทน")

                res = await conn.execute(
                    "DELETE FROM students WHERE room_id = $1 AND student_no = $2",
                    resolved_room_id, student_no
                )
                
                if res == "DELETE 0":
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนเลขที่นี้")
                    
                await log_action(conn, resolved_room_id, user_name, "Hard Delete", f"ลบข้อมูลนักเรียนเลขที่ {student_no} ออกจากฐานข้อมูลถาวร (Hard Delete)")