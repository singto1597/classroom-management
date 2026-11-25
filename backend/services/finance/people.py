"""👥 [FIN-V2 / P1.2] ทะเบียนผู้เกี่ยวข้องทางการเงิน + ตั้งค่าการเงินของห้อง

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี "person" แทนข้อความอิสระ
═══════════════════════════════════════════════════════════════════════════════
วันนี้ชื่อผู้รับเงิน/ผู้จ่ายถูกเก็บเป็น **ข้อความ** ใน `recorded_by`,
`finance_receipts.issued_by_name`, … ⇒ สะกดต่างกันนิดเดียวก็กลายเป็นคนละคน,
ตอบไม่ได้ว่า "ครูคนนี้รับเงินไปเท่าไรเดือนนี้", และใบสำคัญจ่ายไม่มีทางเลือก
ผู้รับเงินจากรายชื่อจริงได้

ตาราง `finance_people` (P1.1) เก็บ**ตัวจริง** 1 แถวต่อคนต่อห้อง พร้อมบทบาท
`receive`/`pay`/`approve` — ชื่อบนเอกสารยังเป็น **snapshot** (เอกสารที่พิมพ์แล้ว
ต้องไม่เปลี่ยนตามชื่อในทะเบียน) แต่ต้นทางของ snapshot คือแถวนี้

📌 ขอบเขตของ package นี้:
   - CRUD ผู้เกี่ยวข้อง (นักเรียน/ครู/บุคคลภายนอก) + soft delete
   - ซิงก์รายชื่อนักเรียนแบบ idempotent (ไม่ทับชื่อที่ครูแก้)
   - `finance_settings` (ผู้รับเงินเริ่มต้น / กระเป๋าเริ่มต้น / บังคับเลือกผู้รับ)
   ⛔ ไม่ทำ custody (P3.1) · ไม่แก้ `recorded_by` เดิม · ไม่ migrate ข้อความเก่า

⚠️ กติกา MRO: ทุกเมธอดใช้ชื่อเฉพาะ (`list_people`, `create_person`, …) และ
   `FinanceService` วาง `PeopleMixin` **ก่อน** mixin ที่พึ่งชื่อซ้ำไม่ได้
   (P1.1: ตาราง · P2.1+: อ่าน `default_receiver_person_id` ผ่าน API นี้)
"""
import time
from typing import List, Optional

import asyncpg

from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger

# 🎭 บทบาทที่ประกาศใน DB (`chk_finance_people_roles`) — ต้องตรงกันทั้งสองฝั่ง
VALID_PERSON_TYPES = ("student", "teacher", "external")
VALID_ROLES = ("receive", "pay", "approve")

# 📊 ค่าเริ่มต้นเมื่อห้องยังไม่เคยส่ง PATCH settings — GET ต้องไม่ 404
_SETTINGS_DEFAULTS = {
    "default_receiver_person_id": None,
    "default_wallet_account_id": None,
    "require_receiver": True,
    "receipt_note": None,
}


class PeopleMixin:
    """ทะเบียนผู้เกี่ยวข้องทางการเงิน (`finance_people`) + ตั้งค่าห้อง (`finance_settings`)"""

    # ─────────────────────────────────────────────────────────────────────
    # ตัวช่วยภายใน
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _shape_person(row) -> dict:
        """แถว `finance_people` → dict สำหรับ response

        ⚠️ `roles` มาจาก asyncpg เป็น `list[str]` อยู่แล้ว แต่ถ้าแถวถูกก๊อปปี้เป็น
           JSON ระหว่างทาง มันอาจกลายเป็นสตริง `'["receive"]'` — normalize ให้ชัด
           (Pydantic จะปฏิเสธสตริงที่ประกาศเป็น `List[str]` และผู้ใช้จะเห็น 500)
        """
        roles = row["roles"] or []
        if isinstance(roles, str):
            roles = [roles]
        return {
            "person_id": row["id"],
            "person_type": row["person_type"],
            "student_id": row["student_id"],
            "display_name": row["display_name"],
            "phone": row["phone"],
            "roles": list(roles),
            "is_active": row["is_active"],
            "note": row["note"],
        }

    @staticmethod
    def _validate_person_link(person_type: str, student_id: Optional[int]) -> None:
        """ตรวจกฎเดียวกับ `chk_finance_people_student_link` **ก่อน** ถึง DB

        ⚠️ ถ้าปล่อยให้ CHECK ของ DB โยน `CheckViolationError` ผู้ใช้จะได้ 500 —
           ที่นี่ตอบ 400 พร้อมข้อความที่บอกว่าต้องแก้ตรงไหน
        """
        if person_type not in VALID_PERSON_TYPES:
            raise ValueError("ประเภทผู้เกี่ยวข้องไม่ถูกต้อง (student / teacher / external)")
        if person_type == "student" and not student_id:
            raise ValueError("ผู้เกี่ยวข้องประเภทนักเรียนต้องระบุรหัสนักเรียน")
        if person_type != "student" and student_id is not None:
            raise ValueError("ผู้เกี่ยวข้องที่ไม่ใช่นักเรียนต้องไม่ผูกกับรหัสนักเรียน")

    @staticmethod
    def _normalize_roles(roles: List[str]) -> List[str]:
        """ลบบทบาทซ้ำโดยคงลำดับเดิม + กันรายการว่าง (DB ยอม `\\{}` แต่ไม่มีความหมาย)"""
        cleaned = list(dict.fromkeys(roles or []))
        invalid = [r for r in cleaned if r not in VALID_ROLES]
        if invalid:
            raise ValueError(f"บทบาทไม่ถูกต้อง: {', '.join(invalid)}")
        if not cleaned:
            raise ValueError("ต้องมีบทบาทอย่างน้อย 1 อย่าง (receive / pay / approve)")
        return cleaned

    @classmethod
    async def _assert_student_in_room(
        cls, conn: asyncpg.Connection, room_id: int, student_id: int
    ) -> None:
        """นักเรียนต้องอยู่ในห้องนี้และยังไม่ถูกลบ — กันการผูกข้ามห้องผ่าน API"""
        found = await conn.fetchval(
            "SELECT 1 FROM students WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
            student_id, room_id,
        )
        if not found:
            raise ValueError("ไม่พบนักเรียนคนนี้ในห้องเรียน")

    # ─────────────────────────────────────────────────────────────────────
    # อ่าน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def list_people(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
        person_type: Optional[str] = None,
        active: Optional[bool] = None,
        q: Optional[str] = None,
    ) -> List[dict]:
        """รายชื่อผู้เกี่ยวข้องของห้อง (ซ่อนแถว soft-deleted เสมอ)

        📖 สมาชิกห้องอ่านได้ (transparency ตาม pattern `get_active_students`)
           แต่ต้องเป็นสมาชิกของห้องนี้ — `require_member` กันการอ่านข้ามห้อง
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if person_type is not None and person_type not in VALID_PERSON_TYPES:
                    raise ValueError("ประเภทผู้เกี่ยวข้องไม่ถูกต้อง (student / teacher / external)")

                # 🔍 สร้าง WHERE จากค่าที่ส่งมา — ใช้พารามิเตอร์จริง ไม่ต่อสตริงค่าผู้ใช้
                where = ["room_id = $1", "deleted_at IS NULL"]
                params: list = [target_room_id]
                if person_type is not None:
                    params.append(person_type)
                    where.append(f"person_type = ${len(params)}")
                if active is not None:
                    params.append(active)
                    where.append(f"is_active = ${len(params)}")
                if q and q.strip():
                    params.append(f"%{q.strip()}%")
                    where.append(
                        f"(display_name ILIKE ${len(params)} OR phone ILIKE ${len(params)})"
                    )

                rows = await conn.fetch(
                    f"""SELECT id, person_type, student_id, display_name, phone,
                               roles, is_active, note
                        FROM finance_people
                        WHERE {' AND '.join(where)}
                        ORDER BY display_name ASC, id ASC""",
                    *params,
                )
                result = [cls._shape_person(r) for r in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_PERSON", status="success",
                    endpoint_or_command="FinanceService.list_people",
                    execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.list_people",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # เขียน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def create_person(
        cls,
        pool: asyncpg.Pool,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """เพิ่มผู้เกี่ยวข้อง 1 คน — คืนแถวที่สร้างใหม่

        🔁 นักเรียน 1 คนมี person ได้ 1 แถวต่อห้อง (partial unique) ⇒ เพิ่มซ้ำ
           ได้ `ValueError` ภาษาไทย (ไม่ใช่ 500 จาก DB)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                cls._validate_person_link(req.person_type, req.student_id)
                if req.person_type == "student":
                    await cls._assert_student_in_room(conn, target_room_id, req.student_id)
                roles = cls._normalize_roles(req.roles)
                display_name = (req.display_name or "").strip()
                if not display_name:
                    raise ValueError("ชื่อผู้เกี่ยวข้องต้องไม่ว่าง")

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนแตะข้อมูลใด ๆ — ทะเบียนผู้เกี่ยวข้องเป็นต้นทางของ
                    #    ชื่อผู้รับเงินบนเอกสาร ⇒ ต้องเรียงกับเส้นทางเงินอื่นเหมือนกัน
                    await _lock_room_money(conn, target_room_id)

                    existing = await conn.fetchval(
                        """SELECT id FROM finance_people
                           WHERE room_id = $1 AND student_id = $2 AND deleted_at IS NULL""",
                        target_room_id, req.student_id,
                    )
                    if existing:
                        raise ValueError("นักเรียนคนนี้มีรายชื่อในทะเบียนผู้เกี่ยวข้องแล้ว")

                    row = await conn.fetchrow(
                        """INSERT INTO finance_people
                               (room_id, person_type, student_id, display_name, phone,
                                roles, is_active, note)
                           VALUES ($1, $2, $3, $4, $5, $6::TEXT[], $7, $8)
                           RETURNING id, person_type, student_id, display_name, phone,
                                     roles, is_active, note""",
                        target_room_id, req.person_type, req.student_id,
                        display_name, req.phone, roles,
                        req.is_active, req.note,
                    )

                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", entity_id=str(row["id"]),
                        status="success", new_values=cls._shape_person(row),
                        endpoint_or_command="FinanceService.create_person",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return cls._shape_person(row)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_person",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_person(
        cls,
        pool: asyncpg.Pool,
        person_id: int,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """แก้ไขผู้เกี่ยวข้อง — PATCH เฉพาะฟิลด์ที่ส่งมา

        ⚠️ เปลี่ยน `person_type` ข้าม student ↔ อื่นได้ในpackage นี้ (ยังไม่มีตาราง
           อ้างถึง person) แต่ **บันทึก audit** ไว้เสมอ เพื่อให้ย้อนรอยได้เมื่อ
           P2+ เริ่มผูก event กับ person
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                updates = req.model_dump(exclude_unset=True)
                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนอ่าน-แก้แถว (เหมือนทุกเส้นทางที่เขียนข้อมูลการเงิน)
                    await _lock_room_money(conn, target_room_id)

                    current = await conn.fetchrow(
                        """SELECT id, person_type, student_id, display_name, phone,
                                  roles, is_active, note
                           FROM finance_people
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                           FOR UPDATE""",
                        person_id, target_room_id,
                    )
                    if not current:
                        raise ValueError("ไม่พบผู้เกี่ยวข้องทางการเงินรายนี้")

                    new_type = updates.get("person_type", current["person_type"])
                    new_student = updates.get("student_id", current["student_id"])
                    cls._validate_person_link(new_type, new_student)
                    if new_type == "student":
                        await cls._assert_student_in_room(conn, target_room_id, new_student)

                    if "roles" in updates:
                        updates["roles"] = cls._normalize_roles(updates["roles"])

                    # ลบคีย์ที่ไม่ได้แก้จริงเพื่อไม่ให้เขียนทับด้วยค่าเดิมซ้ำ ๆ
                    fields = {
                        k: v for k, v in updates.items()
                        if k in ("person_type", "student_id", "display_name", "phone",
                                 "roles", "is_active", "note")
                    }
                    if "display_name" in fields:
                        fields["display_name"] = fields["display_name"].strip()
                        if not fields["display_name"]:
                            raise ValueError("ชื่อผู้เกี่ยวข้องต้องไม่ว่าง")

                    if fields:
                        set_sql = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
                        values = list(fields.values())
                        row = await conn.fetchrow(
                            f"""UPDATE finance_people
                                SET {set_sql}, updated_at = NOW()
                                WHERE id = $1
                                RETURNING id, person_type, student_id, display_name, phone,
                                          roles, is_active, note""",
                            person_id, *values,
                        )
                    else:
                        row = current

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", entity_id=str(person_id),
                        status="success",
                        old_values=cls._shape_person(current),
                        new_values=cls._shape_person(row),
                        endpoint_or_command="FinanceService.update_person",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return cls._shape_person(row)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", entity_id=str(person_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_person",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_person(
        cls,
        pool: asyncpg.Pool,
        person_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ปิดใช้งานผู้เกี่ยวข้อง = **soft delete** เท่านั้น

        🔒 FK ของ `finance_settings.default_receiver_person_id` เป็น ON DELETE
           SET NULL แต่ *soft delete ไม่ trigger FK* ⇒ ต้องเคลียร์ค่าเริ่มต้นเอง
           ไม่งั้นหน้าจอรับเงินจะอ้าง person ที่หายไปจากทะเบียน
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนอ่าน-แก้แถว (เหมือนทุกเส้นทางที่เขียนข้อมูลการเงิน)
                    await _lock_room_money(conn, target_room_id)

                    current = await conn.fetchrow(
                        """SELECT id, person_type, student_id, display_name, phone,
                                  roles, is_active, note
                           FROM finance_people
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                           FOR UPDATE""",
                        person_id, target_room_id,
                    )
                    if not current:
                        raise ValueError("ไม่พบผู้เกี่ยวข้องทางการเงินรายนี้")

                    await conn.execute(
                        """UPDATE finance_people
                           SET deleted_at = NOW(), is_active = FALSE, updated_at = NOW()
                           WHERE id = $1""",
                        person_id,
                    )
                    await conn.execute(
                        """UPDATE finance_settings
                           SET default_receiver_person_id = NULL, updated_at = NOW()
                           WHERE room_id = $1 AND default_receiver_person_id = $2""",
                        target_room_id, person_id,
                    )

                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", entity_id=str(person_id),
                        status="success", old_values=cls._shape_person(current),
                        endpoint_or_command="FinanceService.delete_person",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return {"status": "success", "message": "ปิดใช้งานผู้เกี่ยวข้องแล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", entity_id=str(person_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_person",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # ซิงก์รายชื่อนักเรียน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def sync_students(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """สร้างแถว person ให้นักเรียน active ทุกคน — **idempotent**

        🔴 กฎที่ห้ามพลาด:
           1. `DO UPDATE SET updated_at = NOW()` เท่านั้น — **ห้ามทับ `display_name`**
              เพราะครูอาจตั้งชื่อเล่นที่ต้องการแล้ว (ซิงก์เป็นเรื่อง "มีครบไหม"
              ไม่ใช่ "รีเซ็ตชื่อ")
           2. `ON CONFLICT` ต้องระบุ predicate ให้ตรงกับ partial unique เป๊ะ
              (`WHERE student_id IS NOT NULL AND deleted_at IS NULL`) ไม่งั้น
              Postgres ฟ้อง "no unique or exclusion constraint matching"
           3. นับ created จาก `xmax = 0` ของแถวที่ RETURNING — **ห้ามใช้ MAX(id)**
              เพราะแถวเก่าที่ถูกอัปเดตไม่เพิ่ม id และคำขอซ้อนกันทำให้ตัวเลขนอน
           4. แถวที่ soft-deleted อยู่แล้ว **ไม่ถูกนับ** เป็น conflict ⇒ ซิงก์จะสร้าง
              แถวใหม่ของนักเรียนคนเดิม (พฤติกรรมที่ต้องการ: ครูเปิดใช้งานคนนั้นใหม่)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนเขียนทะเบียน (idempotent sync ก็ยังเขียนแถว)
                    await _lock_room_money(conn, target_room_id)

                    rows = await conn.fetch(
                        """
                        INSERT INTO finance_people
                            (room_id, person_type, student_id, display_name, roles)
                        SELECT $1, 'student', S.id,
                               -- 🔴 ชื่อ-นามสกุลเต็ม (ไม่ต่อชื่อเล่น) — ใช้บนบิล/เอกสารการเงิน
                               COALESCE(
                                   NULLIF(BTRIM(CONCAT_WS(
                                       ' ',
                                       NULLIF(BTRIM(P.prefix), ''),
                                       NULLIF(BTRIM(P.first_name), ''),
                                       NULLIF(BTRIM(P.last_name), '')
                                   )), ''),
                                   NULLIF(BTRIM(CONCAT_WS(
                                       ' ',
                                       NULLIF(BTRIM(P.first_name_en), ''),
                                       NULLIF(BTRIM(P.last_name_en), '')
                                   )), ''),
                                   'นักเรียน #' || S.student_no
                               ),
                               ARRAY['receive']::TEXT[]
                        FROM students S
                        LEFT JOIN v_student_profiles P ON P.student_id = S.id
                        WHERE S.room_id = $1
                          AND S.status = 'active'
                          AND S.deleted_at IS NULL
                        ON CONFLICT (room_id, student_id)
                            WHERE student_id IS NOT NULL AND deleted_at IS NULL
                        DO UPDATE SET updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """,
                        target_room_id,
                    )
                    created = sum(1 for r in rows if r["inserted"])
                    updated = len(rows) - created

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", status="success",
                        new_values={"sync_students": {"created": created, "updated": updated}},
                        endpoint_or_command="FinanceService.sync_students",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return {"created": created, "updated": updated, "skipped": 0}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PERSON", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.sync_students",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # ตั้งค่าการเงินของห้อง
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def get_settings(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ค่าเริ่มต้นของหน้าจอรับเงิน — **ไม่มีแถว = คืนค่า default ไม่สร้างแถว**

        การสร้างแถวเป็นหน้าที่ของ PATCH เท่านั้น (GET ต้องไม่มี side effect)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)
                row = await conn.fetchrow(
                    """SELECT default_receiver_person_id, default_wallet_account_id,
                              require_receiver, receipt_note
                       FROM finance_settings WHERE room_id = $1""",
                    target_room_id,
                )
                result = dict(row) if row else dict(_SETTINGS_DEFAULTS)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_SETTINGS", status="success",
                    endpoint_or_command="FinanceService.get_settings",
                    execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_SETTINGS", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_settings",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_settings(
        cls,
        pool: asyncpg.Pool,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """PATCH ตั้งค่าการเงิน — upsert (แถวเดียวต่อห้อง)

        📌 PATCH semantics: ส่งมาเฉพาะฟิลด์ที่จะเปลี่ยน → รวมกับค่าเดิม (หรือ
           default เมื่อยังไม่มีแถว) แล้วเขียนทั้งชุด ⇒ `"receipt_note": null`
           ล้างค่าได้จริง ไม่ใช่ "ไม่ส่งมา"
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                updates = req.model_dump(exclude_unset=True)
                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อน upsert ค่าเริ่มต้น (หน้าจอรับเงินอ่านค่าที่นี่)
                    await _lock_room_money(conn, target_room_id)

                    current = await conn.fetchrow(
                        """SELECT default_receiver_person_id, default_wallet_account_id,
                                  require_receiver, receipt_note
                           FROM finance_settings WHERE room_id = $1 FOR UPDATE""",
                        target_room_id,
                    )
                    merged = dict(current) if current else dict(_SETTINGS_DEFAULTS)
                    merged.update({k: v for k, v in updates.items() if k in merged})

                    # 🔎 ตรวจ FK ด้วยข้อความไทยก่อนปล่อยให้ DB โยน FK violation (500)
                    receiver_id = merged["default_receiver_person_id"]
                    if receiver_id is not None:
                        ok = await conn.fetchval(
                            """SELECT 1 FROM finance_people
                               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            receiver_id, target_room_id,
                        )
                        if not ok:
                            raise ValueError("ไม่พบผู้รับเงินคนนี้ในทะเบียนของห้อง")

                    wallet_id = merged["default_wallet_account_id"]
                    if wallet_id is not None:
                        ok = await conn.fetchval(
                            """SELECT 1 FROM finance_accounts
                               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            wallet_id, target_room_id,
                        )
                        if not ok:
                            raise ValueError("ไม่พบกระเป๋าเงินนี้ในห้อง")

                    row = await conn.fetchrow(
                        """INSERT INTO finance_settings
                               (room_id, default_receiver_person_id, default_wallet_account_id,
                                require_receiver, receipt_note, updated_at)
                           VALUES ($1, $2, $3, $4, $5, NOW())
                           ON CONFLICT (room_id) DO UPDATE SET
                               default_receiver_person_id = EXCLUDED.default_receiver_person_id,
                               default_wallet_account_id = EXCLUDED.default_wallet_account_id,
                               require_receiver = EXCLUDED.require_receiver,
                               receipt_note = EXCLUDED.receipt_note,
                               updated_at = NOW()
                           RETURNING default_receiver_person_id, default_wallet_account_id,
                                     require_receiver, receipt_note""",
                        target_room_id, merged["default_receiver_person_id"],
                        merged["default_wallet_account_id"], merged["require_receiver"],
                        merged["receipt_note"],
                    )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_SETTINGS", entity_id=str(target_room_id),
                        status="success",
                        old_values=dict(current) if current else None,
                        new_values=dict(row),
                        endpoint_or_command="FinanceService.update_settings",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return dict(row)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_SETTINGS", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_settings",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
