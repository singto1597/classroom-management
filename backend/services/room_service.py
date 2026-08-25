import asyncpg
import random
import string
import json
import time
from fastapi import HTTPException
from core.logger import AuditLogger
from core.rbac import require_permission
from core.name_utils import normalize_nfc, identity_pair
from services.finance_service import (
    DEFAULT_INCOME_CATEGORIES,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_FINANCE_ACCOUNTS,
)
from services.action_service import ActionService

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
                            room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed
                        ) VALUES (
                            $1, $2, 0, 'president', 'active', TRUE, $3::jsonb, TRUE
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
                        "SELECT id, user_id, status, added_by FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL", room_id, payload.student_no
                    )

                    if existing_student:
                        existing_user_id = existing_student['user_id']
                        if existing_user_id is None:
                            # แถวที่ user_id กลายเป็น NULL (user โดนลบ) → ถือเป็น ghost ให้อ้างสิทธิ์ผ่านแอดมินได้
                            ghost_user = None
                            is_ghost = True
                        else:
                            ghost_user = await conn.fetchrow(
                                "SELECT first_name, last_name, first_name_en, last_name_en, email, google_id, discord_id FROM users WHERE id = $1",
                                existing_user_id,
                            )
                            is_ghost = ghost_user and not ghost_user['google_id'] and not ghost_user['discord_id'] and not ghost_user['email']

                        if is_ghost:
                            # 🔒 Consent Model: ไม่สวมรอยทันทีอีกต่อไป — กลายเป็น "คำขออ้างสิทธิ์ (claim request)"
                            # ให้แอดมินอนุมัติ (เก็บชื่อเดิม vs ชื่อผู้ขอไว้ใน claim_meta ให้แอดมินตัดสิน
                            # — กรณีชื่อเพี้ยนเล็กน้อยก็ผ่านได้ ไม่ต้อง error 400 แบบเดิม)
                            real_key = identity_pair(
                                payload.first_name_en, payload.last_name_en,
                                payload.first_name, payload.last_name,
                            )
                            ghost_key = identity_pair(
                                (ghost_user or {}).get('first_name_en'), (ghost_user or {}).get('last_name_en'),
                                (ghost_user or {}).get('first_name'), (ghost_user or {}).get('last_name'),
                            )
                            claim_meta = {
                                "ghost_user_id": existing_user_id,
                                "ghost_first_name": (ghost_user or {}).get('first_name'),
                                "ghost_last_name": (ghost_user or {}).get('last_name'),
                                "ghost_first_name_en": (ghost_user or {}).get('first_name_en'),
                                "ghost_last_name_en": (ghost_user or {}).get('last_name_en'),
                                "ghost_status": existing_student['status'],
                                "name_match": bool(real_key) and bool(ghost_key) and real_key == ghost_key,
                            }
                            old_values["claim_request"] = dict(existing_student)
                            await conn.execute("""
                                UPDATE students
                                SET user_id = $1, status = 'pending', identity_claimed = FALSE,
                                    added_by = NULL, claim_meta = $2::jsonb, updated_at = CURRENT_TIMESTAMP
                                WHERE id = $3
                            """, user_id, json.dumps(claim_meta), existing_student['id'])

                            exec_time = int((time.time() - start_time) * 1000)
                            await service_logger.log(
                                conn=conn,
                                action="UPDATE",
                                actor_identifier=actor_identifier,
                                client_source=client_source,
                                room_id=room_id,
                                user_id=user_id,
                                entity_type="CLAIM_REQUEST",
                                entity_id=str(existing_student['id']),
                                status="success",
                                old_values=old_values,
                                new_values=new_values,
                                endpoint_or_command="join_room_claim_request",
                                execution_time_ms=exec_time
                            )
                            # ⚠️ Lobby.vue เช็ค substring "รอการอนุมัติ" ต้องมีใน message นี้
                            return {"room_id": room_id, "student_id": existing_student['id'], "room_name": room["room_name"], "message": "ส่งคำขอยืนยันตัวตนแล้ว รอการอนุมัติจากหัวหน้าห้อง"}
                        else:
                            raise HTTPException(status_code=400, detail=f"❌ เลขที่ {payload.student_no} มีผู้ใช้งานตัวจริงผูกบัญชีไว้แล้ว")

                    student_id = await conn.fetchval(
                        "INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by) VALUES ($1, $2, $3, 'student', 'pending', FALSE, NULL) RETURNING id",
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
                    "SELECT s.id, s.student_no, s.identity_claimed, s.added_by, s.claim_meta, "
                    "u.first_name, u.last_name, u.first_name_en, u.last_name_en, s.created_at "
                    "FROM students s LEFT JOIN users u ON s.user_id = u.id "
                    "WHERE s.room_id = $1 AND s.status = 'pending' AND s.deleted_at IS NULL ORDER BY s.student_no ASC",
                    room_id
                )
                results = []
                for row in rows:
                    d = dict(row)
                    claim_meta = d.get("claim_meta")
                    if isinstance(claim_meta, str):
                        try:
                            claim_meta = json.loads(claim_meta)
                        except json.JSONDecodeError:
                            claim_meta = {}
                    if d.get("added_by") is not None:
                        # แอดมินแอดให้ → รอเจ้าตัวกดรับ (invite) — แอดมินอนุมัติแทนไม่ได้
                        d["request_type"] = "invite_pending"
                    elif claim_meta and claim_meta.get("ghost_user_id"):
                        # ขออ้างสิทธิ์ ghost → แอดมินเห็นชื่อเดิม vs ชื่อผู้ขอ แล้วตัดสินอนุมัติ
                        d["request_type"] = "claim_request"
                        d["ghost_first_name"] = claim_meta.get("ghost_first_name")
                        d["ghost_last_name"] = claim_meta.get("ghost_last_name")
                        d["ghost_first_name_en"] = claim_meta.get("ghost_first_name_en")
                        d["ghost_last_name_en"] = claim_meta.get("ghost_last_name_en")
                        d["name_match"] = claim_meta.get("name_match")
                    else:
                        # ขอเข้าห้องเอง → รอแอดมินอนุมัติ
                        d["request_type"] = "join_request"
                    d.pop("claim_meta", None)
                    results.append(d)
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
                return results
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

                    old_student = await conn.fetchrow(
                        "SELECT id, status, added_by FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL",
                        room_id, student_no,
                    )
                    if not old_student:
                        raise HTTPException(status_code=404, detail="ไม่พบคำขอ หรืออนุมัติไปแล้ว")
                    old_values = dict(old_student)
                    new_values = {"status": "active", "identity_claimed": True}

                    # 🛡️ Consent Model: คำเชิญที่แอดมินแอดให้ (added_by IS NOT NULL) ต้องให้เจ้าตัวกดรับเอง
                    # — แอดมินอนุมัติแทนไม่ได้ ไม่งั้นแฮ็กเกอร์ก็แค่สร้างห้อง + แอดชื่อ + อนุมัติเอง
                    if old_student["added_by"] is not None:
                        raise HTTPException(status_code=400, detail="คำเชิญนี้รอการยืนยันจากนักเรียน (ให้นักเรียนกดรับคำเชิญก่อน)")

                    res = await conn.execute("""
                        UPDATE students SET status = 'active', identity_claimed = TRUE,
                               claim_meta = '{}'::jsonb, updated_at = CURRENT_TIMESTAMP
                        WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL
                    """, room_id, student_no)
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

                    old_student = await conn.fetchrow(
                        "SELECT id, status, added_by, claim_meta, user_id FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'pending' AND deleted_at IS NULL",
                        room_id, student_no,
                    )
                    if not old_student:
                        raise HTTPException(status_code=404, detail="ไม่พบคำขอ หรือถูกลบไปแล้ว")
                    old_values = dict(old_student)

                    claim_meta = old_student.get("claim_meta")
                    if isinstance(claim_meta, str):
                        try:
                            claim_meta = json.loads(claim_meta)
                        except json.JSONDecodeError:
                            claim_meta = {}

                    if old_student["added_by"] is not None:
                        # แอดมินถอนคำเชิญ (invite_pending) → ลบทิ้ง
                        await conn.execute("DELETE FROM students WHERE id = $1", old_student["id"])
                        audit_type = "REJECT_INVITE"
                    elif claim_meta and claim_meta.get("ghost_user_id"):
                        # ปฏิเสธคำขออ้างสิทธิ์ ghost → กู้คืนแถว ghost กลับ (ชื่อ/สถานะเดิม)
                        await conn.execute("""
                            UPDATE students SET user_id = $1, status = $2, identity_claimed = FALSE,
                                   added_by = NULL, claim_meta = '{}'::jsonb, updated_at = CURRENT_TIMESTAMP
                            WHERE id = $3
                        """, claim_meta.get("ghost_user_id"), claim_meta.get("ghost_status") or "active", old_student["id"])
                        audit_type = "REJECT_CLAIM"
                    else:
                        # ปฏิเสธคำขอเข้าห้องธรรมดา (join_request) → ลบทิ้ง
                        await conn.execute("DELETE FROM students WHERE id = $1", old_student["id"])
                        audit_type = "JOIN_REQUEST"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn,
                        action="DELETE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=room_id,
                        user_id=user_id,
                        entity_type=audit_type,
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

    @classmethod
    async def list_my_invites(cls, pool: asyncpg.Pool, user_id: int, client_source: str, actor_identifier: str) -> list:
        """รายการคำเชิญเข้าร่วมห้องของฉัน — แอดมินแอดชื่อฉันด้วยชื่อ (added_by IS NOT NULL) ที่ยัง pending.
        เจ้าตัวต้องกดรับ (accept_invite) ถึงจะกลายเป็นสมาชิก + เปิดข้อมูลส่วนตัวให้ห้องดู (Consent Model)."""
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT s.id AS invite_id, s.student_no, s.room_id, r.room_name, r.room_code, r.server_id,
                           au.first_name AS added_by_first, au.last_name AS added_by_last, s.created_at
                    FROM students s
                    JOIN rooms r ON s.room_id = r.id AND r.deleted_at IS NULL
                    LEFT JOIN users au ON s.added_by = au.id
                    WHERE s.user_id = $1 AND s.status = 'pending' AND s.identity_claimed = FALSE
                      AND s.added_by IS NOT NULL AND s.deleted_at IS NULL
                    ORDER BY s.created_at DESC
                """, user_id)
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=None, user_id=user_id,
                    entity_type="INVITES", status="success",
                    endpoint_or_command="list_my_invites", execution_time_ms=exec_time
                )
                return [dict(r) for r in rows]
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=None, user_id=user_id,
                    entity_type="INVITES", status="failed", error_detail=str(e),
                    endpoint_or_command="list_my_invites", execution_time_ms=exec_time
                )
            raise e

    @classmethod
    async def accept_invite(cls, pool: asyncpg.Pool, invite_id: int, user_id: int, client_source: str, actor_identifier: str) -> dict:
        """เจ้าตัวกดรับคำเชิญ → เป็นสมาชิก active + identity_claimed=TRUE (ข้อมูลส่วนตัวเปิดให้ห้องดูได้)."""
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow("""
                        SELECT s.id, s.room_id, s.user_id, s.student_no, s.added_by, s.status, s.identity_claimed,
                               u.first_name, u.last_name, u.first_name_en, u.last_name_en
                        FROM students s LEFT JOIN users u ON s.user_id = u.id
                        WHERE s.id = $1 AND s.deleted_at IS NULL
                    """, invite_id)
                    if not row:
                        raise HTTPException(status_code=404, detail="ไม่พบคำเชิญนี้")
                    if row["user_id"] != user_id:
                        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์รับคำเชิญนี้")
                    if row["added_by"] is None:
                        raise HTTPException(status_code=400, detail="รายการนี้ไม่ใช่คำเชิญที่รอคุณยืนยัน")
                    if row["status"] != "pending" or row["identity_claimed"]:
                        raise HTTPException(status_code=400, detail="คำเชิญนี้ถูกใช้ไปแล้วหรือถูกยกเลิก")

                    await conn.execute("""
                        UPDATE students SET status = 'active', identity_claimed = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                    """, invite_id)

                    old_values = {"status": row["status"], "identity_claimed": row["identity_claimed"]}
                    new_values = {"status": "active", "identity_claimed": True}
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=row["room_id"], user_id=user_id,
                        entity_type="INVITE_ACCEPTED", entity_id=str(invite_id), status="success",
                        old_values=old_values, new_values=new_values,
                        endpoint_or_command="accept_invite", execution_time_ms=exec_time
                    )

                    room_server_id = await conn.fetchval(
                        "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", row["room_id"]
                    )
                    if room_server_id:
                        await ActionService.notify_invite_accepted(
                            server_id=room_server_id,
                            student_no=row["student_no"],
                            first_name=row["first_name"],
                            last_name=row["last_name"],
                            first_name_en=row["first_name_en"] or "",
                            last_name_en=row["last_name_en"] or "",
                        )
                    return {"invite_id": invite_id, "room_id": row["room_id"], "message": "รับคำเชิญแล้ว ยินดีต้อนรับเข้าห้อง"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=None, user_id=user_id,
                    entity_type="INVITE_ACCEPTED", status="failed", error_detail=str(e),
                    endpoint_or_command="accept_invite", execution_time_ms=exec_time
                )
            raise e
