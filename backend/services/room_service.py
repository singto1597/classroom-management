import asyncpg
import random
import string
import json
import time
from fastapi import HTTPException
from core.logger import AuditLogger
from core.rbac import require_permission
from core.name_utils import normalize_nfc, identity_pair, display_name
from services.finance_service import (
    DEFAULT_INCOME_CATEGORIES,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_FINANCE_ACCOUNTS,
)

service_logger = AuditLogger(service_name="ROOM_MANAGEMENT")

class RoomManagementService:
    
    @staticmethod
    def _generate_room_code(length: int = 6) -> str:
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(length))
        
    @classmethod
    async def create_room(cls, pool: asyncpg.Pool, room_name: str, user_id: int, client_source: str, actor_identifier: str, first_name: str = "", last_name: str = "", first_name_en: str = "", last_name_en: str = "") -> dict:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    old_values = {}
                    new_values = {"room_name": room_name, "first_name": first_name, "last_name": last_name}

                    # 🌟 NFC-normalize ชื่อไทยก่อนเขียน (แก้ อำ/อํา)
                    th_first = normalize_nfc(first_name)
                    th_last = normalize_nfc(last_name)
                    en_first = normalize_nfc(first_name_en)
                    en_last = normalize_nfc(last_name_en)

                    # อัปเดตข้อมูลผู้สร้างห้อง
                    if th_first or th_last or en_first or en_last:
                        old_user = await conn.fetchrow("SELECT first_name, last_name, first_name_en, last_name_en FROM users WHERE id = $1", user_id)
                        if old_user:
                            old_values["user_before_update"] = dict(old_user)

                        await conn.execute("""
                            UPDATE users SET first_name = COALESCE(NULLIF($1, ''), first_name),
                                             last_name = COALESCE(NULLIF($2, ''), last_name),
                                             first_name_en = COALESCE(NULLIF($3, ''), first_name_en),
                                             last_name_en = COALESCE(NULLIF($4, ''), last_name_en)
                            WHERE id = $5
                        """, th_first, th_last, en_first, en_last, user_id)
                    else:
                        user_record = await conn.fetchrow("SELECT first_name FROM users WHERE id = $1", user_id)
                        if not user_record or not user_record['first_name']:
                            old_values["user_before_update"] = dict(user_record) if user_record else {}
                            await conn.execute("UPDATE users SET first_name = 'Teacher', first_name_en = 'Teacher' WHERE id = $1", user_id)
                            new_values["first_name"] = "Teacher"
                            new_values["first_name_en"] = "Teacher"

                    while True:
                        code = cls._generate_room_code()
                        if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                            break

                    # 🚨 1. สร้างห้อง โดยบันทึก owner_id เป็นของคนสร้าง (เพื่อกันตาย กรณีแอดมินโดนปลดหมด)
                    room_id = await conn.fetchval("""
                        INSERT INTO rooms (room_name, room_code, owner_id) 
                        VALUES ($1, $2, $3) 
                        RETURNING id
                    """, room_name, code, user_id)
                    
                    # 🚨 2. บันทึกคนสร้างเข้าเป็นนักเรียนในห้อง (ให้เลขที่ 0 หรืออะไรก็ได้) 
                    # พร้อมเสก is_admin = TRUE และให้ permissions เป็น ["all"] หรือเผื่อเอาไว้
                    await conn.execute("""
                        INSERT INTO students (
                            room_id, user_id, student_no, class_role, status, is_admin, permissions
                        ) VALUES (
                            $1, $2, 0, 'president', 'active', TRUE, $3::jsonb
                        )
                    """, room_id, user_id, json.dumps(["all"]))

                    # 🎯 Seed หมวดหมู่รายรับ/รายจ่าย + บัญชีเงินสดค่าเริ่มต้น ให้ห้องใหม่ใช้เลย
                    # (อยู่ภายใน transaction เดียวกับ create_room → สร้างห้องสำเร็จ = มีของครบ)
                    await conn.executemany(
                        "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, 'income')",
                        [(room_id, name) for name in DEFAULT_INCOME_CATEGORIES],
                    )
                    await conn.executemany(
                        "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, 'expense')",
                        [(room_id, name) for name in DEFAULT_EXPENSE_CATEGORIES],
                    )
                    await conn.executemany(
                        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0.0)",
                        [(room_id, name) for name in DEFAULT_FINANCE_ACCOUNTS],
                    )
                    await service_logger.log(
                        conn=conn,
                        action="CREATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type="FINANCE_SEED",
                        entity_id=str(room_id),
                        status="success",
                        new_values={
                            "income_categories": DEFAULT_INCOME_CATEGORIES,
                            "expense_categories": DEFAULT_EXPENSE_CATEGORIES,
                            "accounts": DEFAULT_FINANCE_ACCOUNTS,
                        },
                        endpoint_or_command="create_room",
                        execution_time_ms=0,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn,
                        action="CREATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type="ROOM",
                        entity_id=str(room_id),
                        status="success",
                        old_values=old_values,
                        new_values=new_values,
                        endpoint_or_command="create_room",
                        execution_time_ms=exec_time
                    )
                    return {"room_id": room_id, "room_name": room_name, "room_code": code}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="CREATE",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=user_id,
                    entity_type="ROOM",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="create_room",
                    execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def join_room(cls, pool: asyncpg.Pool, payload, user_id: int, client_source: str, actor_identifier: str) -> dict:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    old_values = {}
                    new_values = {
                        "room_code": payload.room_code,
                        "student_no": payload.student_no,
                        "first_name": payload.first_name,
                        "last_name": payload.last_name,
                        "first_name_en": payload.first_name_en or None,
                        "last_name_en": payload.last_name_en or None,
                    }

                    room = await conn.fetchrow("SELECT id, room_name FROM rooms WHERE room_code = $1 AND deleted_at IS NULL", payload.room_code)
                    if not room: raise HTTPException(status_code=404, detail="ไม่พบรหัสห้องนี้")
                    room_id = room["id"]

                    if await conn.fetchval("SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL", room_id, user_id):
                        raise HTTPException(status_code=400, detail="คุณอยู่ในห้องเรียนนี้อยู่แล้ว หรือกำลังรอการอนุมัติ")

                    old_user = await conn.fetchrow("SELECT first_name, last_name, first_name_en, last_name_en FROM users WHERE id = $1", user_id)
                    if old_user:
                        old_values["user_before_update"] = dict(old_user)

                    await conn.execute("""
                        UPDATE users SET first_name = COALESCE(NULLIF($1, ''), first_name),
                                         last_name = COALESCE(NULLIF($2, ''), last_name),
                                         first_name_en = COALESCE(NULLIF($3, ''), first_name_en),
                                         last_name_en = COALESCE(NULLIF($4, ''), last_name_en)
                        WHERE id = $5
                    """, normalize_nfc(payload.first_name), normalize_nfc(payload.last_name),
                        payload.first_name_en or None, payload.last_name_en or None, user_id)

                    existing_student = await conn.fetchrow(
                        "SELECT id, user_id, status FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", room_id, payload.student_no
                    )

                    if existing_student:
                        ghost_user_id = existing_student['user_id']
                        ghost_user = await conn.fetchrow("SELECT first_name, last_name, first_name_en, last_name_en, email, google_id, discord_id, phone_number, birthday FROM users WHERE id = $1", ghost_user_id)

                        is_ghost = not ghost_user['google_id'] and not ghost_user['discord_id'] and not ghost_user['email']

                        if is_ghost:
                            old_values["ghost_user_deleted"] = dict(ghost_user)
                            # 🌟 identity: ชื่ออังกฤษเป็นกุญแจหลัก ถ้าไม่มีอังกฤษ fallback เป็นไทย NFC
                            # (เดิมใช้ concat + ลบช่องว่าง + lower เปราะ — ตอนนี้ normalize NFC แล้ว)
                            real_key = identity_pair(
                                payload.first_name_en, payload.last_name_en,
                                payload.first_name, payload.last_name,
                            )
                            ghost_key = identity_pair(
                                ghost_user.get('first_name_en'), ghost_user.get('last_name_en'),
                                ghost_user.get('first_name'), ghost_user.get('last_name'),
                            )

                            if real_key == ghost_key:
                                # 🚀 MERGE UPGRADE: ย้ายกรรมสิทธิ์ "ทุกห้อง" ที่บัญชีผีเคยมี มาให้บัญชีจริง!
                                ghost_rooms = await conn.fetch("SELECT id FROM students WHERE user_id = $1", ghost_user_id)
                                old_values["ghost_rooms_affected"] = [dict(gr) for gr in ghost_rooms]
                                
                                for gr in ghost_rooms:
                                    try:
                                        await conn.execute("UPDATE students SET user_id = $1, status = 'active' WHERE id = $2", user_id, gr['id'])
                                    except asyncpg.exceptions.UniqueViolationError:
                                        await conn.execute("DELETE FROM students WHERE id = $1", gr['id'])

                                await conn.execute("""
                                    UPDATE users SET phone_number = COALESCE(phone_number, $2), birthday = COALESCE(birthday, $3) WHERE id = $1
                                """, user_id, ghost_user.get('phone_number'), ghost_user.get('birthday'))

                                await conn.execute("DELETE FROM users WHERE id = $1", ghost_user_id)
                                
                                exec_time = int((time.time() - start_time) * 1000)
                                await service_logger.log(
                                    conn=conn,
                                    action="UPDATE",
                                    actor_identifier=actor_identifier,
                                    client_source=client_source,
                                    room_id=room_id,
                                    user_id=user_id,
                                    entity_type="ACCOUNT_CLAIM",
                                    entity_id=str(existing_student['id']),
                                    status="success",
                                    old_values=old_values,
                                    new_values=new_values,
                                    endpoint_or_command="join_room_claim",
                                    execution_time_ms=exec_time
                                )
                                return {"room_id": room_id, "student_id": existing_student['id'], "room_name": room["room_name"], "message": "ยืนยันตัวตน และรวบรวมข้อมูลทุกห้องสำเร็จ!"}
                            else:
                                raise HTTPException(status_code=400, detail=f"❌ ไม่สามารถสวมรอยได้! เลขที่ {payload.student_no} มีชื่อในระบบคือ '{display_name(ghost_user.get('first_name'), ghost_user.get('last_name'), ghost_user.get('first_name_en'), ghost_user.get('last_name_en'))}' โปรดแจ้งหัวหน้าห้องให้แก้ไขชื่อให้ตรงกันครับ")
                        else:
                            raise HTTPException(status_code=400, detail=f"❌ เลขที่ {payload.student_no} มีผู้ใช้งานตัวจริงผูกบัญชีไว้แล้ว")

                    student_id = await conn.fetchval(
                        "INSERT INTO students (room_id, user_id, student_no, class_role, status) VALUES ($1, $2, $3, 'student', 'pending') RETURNING id",
                        room_id, user_id, payload.student_no
                    )
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn,
                        action="CREATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type="JOIN_REQUEST",
                        entity_id=str(student_id),
                        status="success",
                        old_values=old_values,
                        new_values=new_values,
                        endpoint_or_command="join_room_request",
                        execution_time_ms=exec_time
                    )
                    return {"room_id": room_id, "student_id": student_id, "room_name": room["room_name"], "message": "ส่งคำขอเข้าร่วมห้องแล้ว รอการอนุมัติ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="CREATE_OR_UPDATE",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=user_id,
                    entity_type="ROOM_JOIN",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="join_room",
                    execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def get_pending_requests(cls, pool: asyncpg.Pool, room_id: int, user_id: int, client_source: str, actor_identifier: str) -> list:
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
                rows = await conn.fetch(
                    "SELECT s.student_no, u.first_name, u.last_name, u.first_name_en, u.last_name_en, s.created_at FROM students s LEFT JOIN users u ON s.user_id = u.id WHERE s.room_id = $1 AND s.status = 'pending' AND s.deleted_at IS NULL ORDER BY s.student_no ASC",
                    room_id
                )
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn,
                    action="VIEW",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="PENDING_REQUESTS",
                    status="success",
                    endpoint_or_command="get_pending_requests",
                    execution_time_ms=exec_time
                )
                return [dict(row) for row in rows]
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="VIEW",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="PENDING_REQUESTS",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="get_pending_requests",
                    execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def approve_join_request(cls, pool: asyncpg.Pool, room_id: int, student_no: int, user_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
                    
                    old_student = await conn.fetchrow("SELECT id, status FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL", room_id, student_no)
                    old_values = dict(old_student) if old_student else {}
                    new_values = {"status": "active"}

                    res = await conn.execute("UPDATE students SET status = 'active' WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL", room_id, student_no)
                    if res == "UPDATE 0": raise HTTPException(status_code=404, detail="ไม่พบคำขอ หรืออนุมัติไปแล้ว")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn,
                        action="UPDATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type="JOIN_REQUEST",
                        entity_id=str(old_student['id']) if old_student else None,
                        status="success",
                        old_values=old_values,
                        new_values=new_values,
                        endpoint_or_command="approve_join_request",
                        execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="UPDATE",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="JOIN_REQUEST",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="approve_join_request",
                    execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def reject_join_request(cls, pool: asyncpg.Pool, room_id: int, student_no: int, user_id: int, client_source: str, actor_identifier: str):
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await require_permission(conn, room_id, user_id, "MANAGE_STUDENTS")
                    
                    old_student = await conn.fetchrow("SELECT id, status FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL", room_id, student_no)
                    old_values = dict(old_student) if old_student else {}

                    res = await conn.execute("DELETE FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL", room_id, student_no)
                    if res == "DELETE 0": raise HTTPException(status_code=404, detail="ไม่พบคำขอ หรือถูกลบไปแล้ว")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn,
                        action="DELETE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type="JOIN_REQUEST",
                        entity_id=str(old_student['id']) if old_student else None,
                        status="success",
                        old_values=old_values,
                        endpoint_or_command="reject_join_request",
                        execution_time_ms=exec_time
                    )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="DELETE",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="JOIN_REQUEST",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="reject_join_request",
                    execution_time_ms=exec_time
                )
            raise e
