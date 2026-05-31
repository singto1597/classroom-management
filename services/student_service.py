import asyncpg
from datetime import datetime
from typing import List, Dict, Any, FrozenSet
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import io

from core.audit import log_action
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from core.rbac import require_permission
from models.student_schemas import StudentUpdateRequest

# อนุญาตเฉพาะคอลัมน์ที่นิยามใน Pydantic — กันชื่อคอลัมน์แปลกปลอมจาก client
STUDENT_PATCHABLE_COLUMNS: FrozenSet[str] = frozenset(StudentUpdateRequest.model_fields.keys())

class StudentService:
    
    @staticmethod
    async def _get_room_id(conn: asyncpg.Connection, server_id: int) -> int:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
        if not room_id: raise RoomNotFoundError(f"Room for server {server_id} not found.")
        return room_id

    @staticmethod
    def _calculate_completion(row: dict) -> dict:
        """คำนวณ % ว่ากรอกข้อมูลครบหรือยัง"""
        # ระบุฟิลด์ที่คาดหวังว่าควรมี
        expected_fields = [
            # ข้อมูลส่วนตัว
            'student_id', 'prefix', 'nickname', 'birthday',
            
            # วิชาการและหน้าที่
            'cleaning_duty', 'olympic_camp', 'target_faculty',
            
            # สุขภาพ (ถ้าไม่มีโรค ให้พิมพ์ "-" ถือว่ากรอกแล้ว)
            'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease',
            
            # ช่องทางติดต่อ
            'phone_number', 'phone_number_parent', 'phone_number_parent_relation',
            'line_id', 'ig_username', 'email',
            
            # ที่อยู่ (ต้องมีให้ครบถึงจะส่งจดหมาย/เอกสารได้)
            'address_house_no', 'address_road', 'address_sub_district',
            'address_district', 'address_province', 'address_post_code'
        ]
        missing = [f for f in expected_fields if not row.get(f) or str(row.get(f)).strip() == ""]
        total = len(expected_fields)
        filled = total - len(missing)
        percent = int((filled / total) * 100)
        return {"percentage": percent, "missing_fields": missing}

    # ==========================================
    # 1. สร้างนักเรียน (Quick Add & Bulk Add)
    # ==========================================
    @classmethod
    async def add_student(cls, pool: asyncpg.Pool, server_id: int, student_no: int, first_name: str, last_name: str, user_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                await conn.execute(
                    """INSERT INTO students (room_id, student_no, first_name, last_name) 
                       VALUES ($1, $2, $3, $4) ON CONFLICT (room_id, student_no) DO NOTHING""",
                    room_id, student_no, first_name, last_name
                )
                await log_action(conn, room_id, user_name, "Add Student", f"เพิ่มเลขที่ {student_no}")

    @classmethod
    async def bulk_add_students(cls, pool: asyncpg.Pool, server_id: int, students: List[dict], user_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                # ใช้ executemany เพื่อ Insert ทีละหลายร้อยแถวได้อย่างรวดเร็ว
                tuples = [(room_id, s['student_no'], s['first_name'], s['last_name']) for s in students]
                await conn.executemany(
                    """INSERT INTO students (room_id, student_no, first_name, last_name) 
                       VALUES ($1, $2, $3, $4) ON CONFLICT (room_id, student_no) DO NOTHING""",
                    tuples
                )
                await log_action(conn, room_id, user_name, "Bulk Add", f"เพิ่มนักเรียน {len(students)} คน")

    # ==========================================
    # 2. เชื่อมบัญชี Discord (Sync)
    # ==========================================
    @classmethod
    async def sync_discord(cls, pool: asyncpg.Pool, server_id: int, student_no: int, discord_id: int, user_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                res = await conn.execute(
                    "UPDATE students SET discord_id = $1 WHERE room_id = $2 AND student_no = $3 AND deleted_at IS NULL",
                    discord_id, room_id, student_no
                )
                if res == "UPDATE 0": raise StudentNotFoundError("ไม่พบเลขที่นี้ในระบบ")
                await log_action(conn, room_id, user_name, "Sync Discord", f"ผูกดิสคอร์ดเข้ากับเลขที่ {student_no}")

    # ==========================================
    # 3. อัปเดตข้อมูล (Dynamic Update)
    # ==========================================
    @classmethod
    async def update_student(cls, pool: asyncpg.Pool, server_id: int, student_no: int, update_data: dict, updater_discord_id: int):
        clean_data = {k: v for k, v in update_data.items() if v is not None}
        clean_data = {k: v for k, v in clean_data.items() if k in STUDENT_PATCHABLE_COLUMNS}
        if not clean_data:
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)

                target_discord_id = await conn.fetchval(
                    "SELECT discord_id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", room_id, student_no
                )
                if target_discord_id != updater_discord_id:
                    await require_permission(conn, room_id, updater_discord_id, "MANAGE_STUDENTS")

                keys = sorted(clean_data.keys())
                set_clauses = []
                values: List[Any] = [room_id, student_no]
                idx = 3
                for key in keys:
                    set_clauses.append(f"{key} = ${idx}")
                    values.append(clean_data[key])
                    idx += 1

                set_query = ", ".join(set_clauses)
                query = (
                    f"UPDATE students SET {set_query}, updated_at = CURRENT_TIMESTAMP "
                    "WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL"
                )
                await conn.execute(query, *values)

                actor_row = await conn.fetchrow(
                    "SELECT first_name, last_name FROM students WHERE room_id = $1 AND discord_id = $2 AND deleted_at IS NULL",
                    room_id,
                    updater_discord_id,
                )
                if actor_row:
                    actor_name = f"{actor_row['first_name'] or ''} {actor_row['last_name'] or ''}".strip()
                else:
                    actor_name = f"discord:{updater_discord_id}"
                if not actor_name:
                    actor_name = f"discord:{updater_discord_id}"

                fields_desc = ", ".join(keys)
                await log_action(
                    conn,
                    room_id,
                    actor_name,
                    "Update Student",
                    f"แก้ไขเลขที่ {student_no} ฟิลด์: {fields_desc}",
                )

    # ==========================================
    # 4. ดูข้อมูลตัวเอง (Profile) / ดูทั้งหมด (All)
    # ==========================================
    @classmethod
    async def get_student_by_discord(cls, pool: asyncpg.Pool, server_id: int, discord_id: int) -> dict:
        async with pool.acquire() as conn:
            room_id = await cls._get_room_id(conn, server_id)
            row = await conn.fetchrow("SELECT * FROM students WHERE room_id = $1 AND discord_id = $2 AND deleted_at IS NULL", room_id, discord_id)
            if not row: raise StudentNotFoundError("ยังไม่ได้ Sync ข้อมูล")
            
            data = dict(row)
            data['data_completion'] = cls._calculate_completion(data)
            return data

    @classmethod
    async def get_all_students(cls, pool: asyncpg.Pool, server_id: int, requester_discord_id: int) -> List[dict]:
        async with pool.acquire() as conn:
            room_id = await cls._get_room_id(conn, server_id)
            
            # 🔴 ลบทิ้ง: การเช็คสิทธิ์ระดับสูง
            # await require_permission(conn, room_id, requester_discord_id, "VIEW_ALL_STUDENTS")

            # 🟢 เพิ่มใหม่: เช็คแค่ว่า "Discord ID นี้ เป็นนักเรียนที่มีชื่ออยู่ในห้องนี้จริงๆ ใช่ไหม?"
            is_member = await conn.fetchval(
                "SELECT 1 FROM students WHERE room_id = $1 AND discord_id = $2 AND deleted_at IS NULL",
                room_id, requester_discord_id
            )
            if not is_member:
                raise ForbiddenError("คุณไม่มีสิทธิ์ดูรายชื่อ เพราะคุณไม่ได้อยู่ในห้องเรียนนี้")

            # ดึงมาทั้งหมดเพื่อคำนวณ %
            rows = await conn.fetch("SELECT * FROM students WHERE room_id = $1 AND deleted_at IS NULL ORDER BY student_no ASC", room_id)
            
            results = []
            for row in rows:
                full_data = dict(row)
                completion_status = cls._calculate_completion(full_data)
                
                # กรองเอาเฉพาะข้อมูลปลอดภัย
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
    async def export_students_excel(cls, pool, server_id: int, fields: List[str], user_name: str, discord_id: int):
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                
                # เช็คสิทธิ์ด้วย RBAC
                await require_permission(conn, room_id, discord_id, "EXPORT_STUDENTS")

                # ดึงข้อมูลทั้งหมดของห้อง
                rows = await conn.fetch("SELECT * FROM students WHERE room_id = $1 AND deleted_at IS NULL ORDER BY student_no ASC", room_id)
                
                if not rows:
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนในห้องนี้")

                # แปลงเป็น List ของ Dict และเลือกเฉพาะฟิลด์ที่ต้องการ
                data = []
                for r in rows:
                    row_dict = dict(r)
                    # กรองเอาเฉพาะ key ที่ user สั่ง
                    filtered_row = {f: row_dict.get(f) for f in fields}
                    data.append(filtered_row)

                # ใช้ Pandas สร้าง DataFrame
                df = pd.DataFrame(data)
                
                # สร้าง Buffer ในหน่วยความจำ (BytesIO) ไม่ต้องเขียนลง Disk จริง
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Students_List')
                
                output.seek(0) # เลื่อน pointer ไปจุดเริ่มต้นไฟล์

                # 🛡️ Audit Log: บันทึกว่าใครแอบก๊อปข้อมูลเพื่อน!
                await log_action(conn, room_id, user_name, "Export Data", f"Exported fields: {', '.join(fields)}")
                
                return output

    # ระบบค้นหา (Search Logic)
    @classmethod
    async def search_students(cls, pool, server_id: int, query: str):
        async with pool.acquire() as conn:
            room_id = await cls._get_room_id(conn, server_id)
            
            # ค้นหาแบบ Flexible: ค้นได้ทั้งเลขที่ และ ชื่อ (ILIKE คือ Case-insensitive search)
            # ถ้า query เป็นตัวเลข ให้เช็คที่ student_no ด้วย
            sql_query = """
                SELECT * FROM students 
                WHERE room_id = $1 
                AND (
                    first_name ILIKE $2 OR 
                    last_name ILIKE $2 OR 
                    nickname ILIKE $2 OR 
                    CAST(student_no AS TEXT) = $3
                )
                AND status = 'active'
                AND deleted_at IS NULL
                LIMIT 5
            """
            search_pattern = f"%{query}%"
            rows = await conn.fetch(sql_query, room_id, search_pattern, query)
            
            return [dict(r) for r in rows]

    # ระบบ Deactivate (เปลี่ยน Status)

    @classmethod
    async def update_status(cls, pool, server_id: int, student_no: int, status: str, user_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                res = await conn.execute(
                    "UPDATE students SET status = $1 WHERE room_id = $2 AND student_no = $3 AND deleted_at IS NULL",
                    status, room_id, student_no
                )
                if res == "UPDATE 0": raise StudentNotFoundError("ไม่พบเลขที่นี้")
                
                await log_action(conn, room_id, user_name, "Status Change", f"เปลี่ยนสถานะเลขที่ {student_no} เป็น {status}")
    
    @classmethod
    async def delete_student(cls, pool: asyncpg.Pool, server_id: int, student_no: int, user_name: str, requester_discord_id: int):
        """ลบข้อมูลนักเรียนแบบ Soft Delete (เก็บประวัติไว้)"""
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                
                # 🛡️ เช็คสิทธิ์ด้วย RBAC
                await require_permission(conn, room_id, requester_discord_id, "MANAGE_STUDENTS")
                
                # 🗑️ อัปเดต deleted_at (Soft Delete)
                res = await conn.execute(
                    "UPDATE students SET deleted_at = NOW() WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
                    room_id, student_no
                )
                
                if res == "UPDATE 0":
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนเลขที่นี้ หรืออาจจะถูกลบไปแล้ว")
                    
                # 📜 บันทึก Log
                await log_action(conn, room_id, user_name, "Soft Delete", f"ลบข้อมูลนักเรียนเลขที่ {student_no} (Soft Delete)")

    @classmethod
    async def delete_student_permanent(cls, pool: asyncpg.Pool, server_id: int, student_no: int, user_name: str, requester_discord_id: int):
        """ลบข้อมูลออกจาก Database ถาวร (Hard Delete) - ใช้กรณีต้องการล้างข้อมูลเพื่อเปลี่ยนเลขที่/ย้ายห้อง"""
        async with pool.acquire() as conn:
            async with conn.transaction():
                room_id = await cls._get_room_id(conn, server_id)
                # 🛡️ เช็คสิทธิ์ด้วย RBAC
                await require_permission(conn, room_id, requester_discord_id, "HARD_DELETE_STUDENTS")
                
                # 🛡️ เช็ค Dependency ก่อนลบ (กฎข้อ 9: ป้องกันข้อมูลกำพร้า)
                # เช็คว่ามีประวัติการเงิน (student_payments) ผูกอยู่ไหม
                has_payments = await conn.fetchval(
                    "SELECT 1 FROM student_payments WHERE student_id = (SELECT id FROM students WHERE room_id = $1 AND student_no = $2) LIMIT 1",
                    room_id, student_no
                )
                if has_payments:
                    raise ValidationError("ไม่สามารถลบข้อมูลถาวรได้ เนื่องจากนักเรียนคนนี้มีประวัติการเงินในระบบ ให้ใช้ Soft Delete แทน")

                res = await conn.execute(
                    "DELETE FROM students WHERE room_id = $1 AND student_no = $2",
                    room_id, student_no
                )
                
                if res == "DELETE 0":
                    raise StudentNotFoundError("ไม่พบข้อมูลนักเรียนเลขที่นี้")
                    
                await log_action(conn, room_id, user_name, "Hard Delete", f"ลบข้อมูลนักเรียนเลขที่ {student_no} ออกจากฐานข้อมูลถาวร (Hard Delete)")

    @classmethod
    async def get_user_rooms(cls, pool, discord_id: int):
        async with pool.acquire() as conn:
            query = """
                SELECT 
                    r.server_id, 
                    r.room_name, 
                    s.class_role as role
                FROM students s
                JOIN rooms r ON s.room_id = r.id 
                WHERE s.discord_id = $1
                AND s.deleted_at IS NULL
                AND r.deleted_at IS NULL
            """
            rows = await conn.fetch(query, discord_id)
            return [dict(row) for row in rows]