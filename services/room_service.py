import asyncpg
import random
import string
from fastapi import HTTPException
from core.audit import log_action
from core.rbac import require_permission

class RoomManagementService:
    
    @staticmethod
    def _generate_room_code(length: int = 6) -> str:
        """สุ่มรหัสเข้าห้อง A-Z, 0-9"""
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    @classmethod
    async def create_room(cls, pool: asyncpg.Pool, room_name: str, user_id: int, first_name: str = "", last_name: str = "") -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                while True:
                    code = cls._generate_room_code()
                    if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                        break

                room_id = await conn.fetchval(
                    "INSERT INTO rooms (room_name, room_code) VALUES ($1, $2) RETURNING id",
                    room_name, code
                )

                if not first_name or not last_name:
                    user = await conn.fetchrow("SELECT first_name, last_name FROM users WHERE id = $1", user_id)
                    if user:
                        first_name = user['first_name'] or "Teacher"
                        last_name = user['last_name'] or ""

                await conn.execute(
                    """INSERT INTO students (room_id, user_id, student_no, class_role, status, first_name, last_name) 
                       VALUES ($1, $2, 0, 'president', 'active', $3, $4)""",
                    room_id, user_id, first_name, last_name
                )
                await log_action(conn, room_id, "System/WebUser", "Create Room", f"สร้างห้อง {room_name} รหัส {code}")
                return {"room_id": room_id, "room_name": room_name, "room_code": code}

    @classmethod
    async def join_room(cls, pool: asyncpg.Pool, payload, user_id: int) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                room = await conn.fetchrow("SELECT id, room_name FROM rooms WHERE room_code = $1 AND deleted_at IS NULL", payload.room_code)
                if not room: 
                    raise HTTPException(status_code=404, detail="ไม่พบรหัสห้องนี้")
                room_id = room["id"]

                if await conn.fetchval("SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL", room_id, user_id):
                    raise HTTPException(status_code=400, detail="คุณอยู่ในห้องเรียนนี้อยู่แล้ว หรือกำลังรอการอนุมัติ")

                if await conn.fetchval("SELECT id FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", room_id, payload.student_no):
                    raise HTTPException(status_code=400, detail=f"เลขที่ {payload.student_no} มีคนใช้งานแล้ว หรือกำลังรออนุมัติ")

                student_id = await conn.fetchval(
                    """INSERT INTO students (room_id, user_id, student_no, class_role, status, first_name, last_name) 
                       VALUES ($1, $2, $3, 'student', 'pending', $4, $5) RETURNING id""",
                    room_id, user_id, payload.student_no, payload.first_name, payload.last_name
                )
                await log_action(conn, room_id, f"User:{user_id}", "Join Request", f"ส่งคำขอเข้าห้องเลขที่ {payload.student_no}")
                return {"room_id": room_id, "student_id": student_id, "room_name": room["room_name"]}

    @classmethod
    async def get_pending_requests(cls, pool: asyncpg.Pool, room_id: int, user_id: int) -> list:
        async with pool.acquire() as conn:
            # 🚨 จุดนี้เปลี่ยน requester_id -> user_id
            await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
            rows = await conn.fetch(
                """SELECT student_no, first_name, last_name, created_at
                   FROM students
                   WHERE room_id = $1 AND status = 'pending' AND deleted_at IS NULL
                   ORDER BY student_no ASC""",
                room_id
            )
            return [dict(row) for row in rows]

    @classmethod
    async def approve_join_request(cls, pool: asyncpg.Pool, room_id: int, student_no: int, user_id: int, approver_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 🚨 เปลี่ยน requester_id -> user_id
                await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
                res = await conn.execute(
                    "UPDATE students SET status = 'active' WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL",
                    room_id, student_no
                )
                if res == "UPDATE 0":
                    raise HTTPException(status_code=404, detail="ไม่พบคำขอเข้าร่วม หรืออนุมัติไปแล้ว")
                await log_action(conn, room_id, approver_name, "Approve Join", f"อนุมัติคำขอเข้าร่วมของเลขที่ {student_no}")

    @classmethod
    async def reject_join_request(cls, pool: asyncpg.Pool, room_id: int, student_no: int, user_id: int, rejector_name: str):
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 🚨 เปลี่ยน requester_id -> user_id
                await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
                res = await conn.execute(
                    "DELETE FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending'",
                    room_id, student_no
                )
                if res == "DELETE 0":
                    raise HTTPException(status_code=404, detail="ไม่พบคำขอเข้าร่วม หรือถูกลบไปแล้ว")
                await log_action(conn, room_id, rejector_name, "Reject Join", f"ปฏิเสธและลบคำขอของเลขที่ {student_no}")