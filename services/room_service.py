import asyncpg
import random
import string
from fastapi import HTTPException
from core.audit import log_action

class RoomManagementService:
    
    @staticmethod
    def _generate_room_code(length: int = 6) -> str:
        """สุ่มรหัสเข้าห้อง A-Z, 0-9"""
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    @classmethod
    async def create_room(cls, pool: asyncpg.Pool, room_name: str, user_id: int) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. สุ่มรหัสห้อง
                while True:
                    code = cls._generate_room_code()
                    if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                        break

                # 2. สร้างห้อง
                room_id = await conn.fetchval(
                    "INSERT INTO rooms (room_name, room_code) VALUES ($1, $2) RETURNING id",
                    room_name, code
                )

                # 3. ให้คนสร้างห้องเป็น teacher ทันที (เลขที่ 0 หรือ 99 ก็ได้)
                await conn.execute(
                    """INSERT INTO students (room_id, user_id, student_no, class_role, status) 
                       VALUES ($1, $2, 0, 'teacher', 'active')""",
                    room_id, user_id
                )
                await log_action(conn, room_id, "System/WebUser", "Create Room", f"สร้างห้อง {room_name} รหัส {code}")
                return {"room_id": room_id, "room_name": room_name, "room_code": code}

    @classmethod
    async def join_room(cls, pool: asyncpg.Pool, payload, user_id: int) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                room = await conn.fetchrow("SELECT id, room_name FROM rooms WHERE room_code = $1 AND deleted_at IS NULL", payload.room_code)
                if not room: raise HTTPException(status_code=404, detail="ไม่พบรหัสห้องนี้")
                room_id = room["id"]

                if await conn.fetchval("SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL", room_id, user_id):
                    raise HTTPException(status_code=400, detail="คุณอยู่ในห้องเรียนนี้อยู่แล้ว")

                if await conn.fetchval("SELECT id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", room_id, payload.student_no):
                    raise HTTPException(status_code=400, detail=f"เลขที่ {payload.student_no} มีคนใช้แล้ว")

                # ไม่ต้อง Insert ชื่อแล้ว เพราะชื่ออยู่ที่ตาราง users แล้ว
                student_id = await conn.fetchval(
                    "INSERT INTO students (room_id, user_id, student_no, class_role, status) VALUES ($1, $2, $3, 'student', 'active') RETURNING id",
                    room_id, user_id, payload.student_no
                )
                await log_action(conn, room_id, f"User:{user_id}", "Join Room", f"เข้าห้องเลขที่ {payload.student_no}")
                return {"room_id": room_id, "student_id": student_id, "room_name": room["room_name"]}