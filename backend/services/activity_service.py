import json
import time
import io
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo

import asyncpg
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.config import settings
from core.exceptions import (
    ActivityNotFoundError,
    ForbiddenError,
    ParticipantNotFoundError,
    RoomNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from core.logger import AuditLogger
from core.rbac import require_member, require_permission
from services.action_service import ActionService

THAI_TZ = ZoneInfo("Asia/Bangkok")

service_logger = AuditLogger(service_name="ACTIVITY")

THAI_MONTH_NAMES: List[str] = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

# 🌟 คอลัมน์มาตรฐานใน Excel export — แผนที่ชื่อคอลัมน์ → ภาษาไทย
# ครอบคลุมทั้ง base fields, Type A (profile), และ Type B (metadata เฉพาะกิจกรรม)
EXPORT_HEADER_LABELS: Dict[str, str] = {
    "student_no": "เลขที่",
    "first_name": "ชื่อจริง",
    "last_name": "นามสกุล",
    "nickname": "ชื่อเล่น",
    "role_type": "หน้าที่ (ประเภท)",
    "role_detail": "รายละเอียดหน้าที่",
    "earned_hours": "ชั่วโมงจิตอาสา",
    "status": "สถานะเข้าร่วม",
    # Type A — จากโปรไฟล์ users
    "blood_group": "กรุ๊ปเลือด",
    "shirt_size": "ไซส์เสื้อ",
    "food_allergy": "อาหารที่แพ้",
    "congenital_disease": "โรคประจำตัว",
    "phone_number": "เบอร์โทรศัพท์นักเรียน",
    "phone_number_parent": "เบอร์โทรศัพท์ผู้ปกครอง",
    # Type B — metadata เฉพาะกิจกรรม (หมวดการเดินทาง)
    "bus_number": "หมายเลขรถบัส",
    "van_number": "หมายเลขรถตู้",
    "seat_number": "เลขที่นั่ง",
    "travel_method": "วิธีการเดินทาง",
    # Type B — ที่พักและการจัดกลุ่ม
    "room_number": "หมายเลขห้องพัก",
    "building_name": "ชื่ออาคาร/ตึกพัก",
    "group_name": "ชื่อกลุ่ม/สี/ค่าย/บ้าน",
    "team_role": "บทบาทในทีม",
    # Type B — การจัดการหน้างาน
    "consent_status": "ใบขออนุญาตผู้ปกครอง",
    "is_paid": "สถานะจ่ายเงินค่าค่าย",
    "check_in_time": "เวลาเช็คอิน",
}

# 🌟 Type A — Profile Fields: ดึงจากตาราง users (READ ONLY ในบริบทกิจกรรม) — ห้ามเก็บซ้ำลง JSONB
# ตอน GET participants จะ JOIN กลับมาพร้อมเสมอ และตอน Export จะอ่านจาก record ตรง ๆ
PROFILE_FIELDS: FrozenSet[str] = frozenset({
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
    "phone_number", "phone_number_parent",
})
PROFILE_FIELD_LABELS: Dict[str, str] = {
    "blood_group": "กรุ๊ปเลือด",
    "shirt_size": "ไซส์เสื้อ",
    "food_allergy": "อาหารที่แพ้",
    "congenital_disease": "โรคประจำตัว",
    "phone_number": "เบอร์โทรศัพท์นักเรียน",
    "phone_number_parent": "เบอร์โทรศัพท์ผู้ปกครอง",
}

ROLE_TYPE_LABELS: Dict[str, str] = {
    "participant": "ผู้เข้าร่วม",
    "staff": "ทีมงาน",
    "leader": "หัวหน้ากลุ่ม",
}

PARTICIPANT_STATUS_LABELS: Dict[str, str] = {
    "confirmed": "ยืนยันแล้ว",
    "cancelled": "ยกเลิก",
    "attended": "มาแล้ว",
}


class ActivityService:

    # ================================================================
    # 🌟 JSONB Parsing Helper (ดึงจาก docs/skills.md)
    # asyncpg คืน JSONB เป็น str หรือ dict ขึ้นกับเวอร์ชัน → normalize เสมอ
    # ================================================================
    @staticmethod
    def _parse_metadata(raw: Any) -> dict:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @staticmethod
    async def _resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
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

    @staticmethod
    def _serializable(obj: Any) -> Any:
        """แปลง object ที่ Pydantic/JSON รับไม่ได้ (Decimal, date) ให้เป็นค่าเซฟสำหรับ audit log"""
        if isinstance(obj, (date, datetime)):
            return str(obj)
        if hasattr(obj, "item"):  # numpy-ish fallback (Decimal → float ได้ผ่าน float())
            return float(obj)
        return obj

    # ================================================================
    # 📖 Read helpers
    # ================================================================
    PARTICIPANT_SELECT = """
        SELECT
            ap.id, ap.activity_id, ap.student_id, ap.role_type, ap.role_detail,
            ap.earned_hours, ap.status, ap.metadata, ap.recorded_by,
            s.student_no,
            u.first_name, u.last_name, u.nickname,
            -- 🌟 Type A Profile Fields (READ ONLY จาก users) — JOIN มาพร้อมเสมอ ห้ามบันทึกซ้ำลง metadata
            u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
            u.phone_number, u.phone_number_parent
        FROM activity_participants ap
        JOIN students s ON ap.student_id = s.id
        LEFT JOIN users u ON s.user_id = u.id
    """

    @classmethod
    async def _fetch_activity_row(cls, conn: asyncpg.Connection, room_id: int, activity_id: int) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT id, room_id, title, description, activity_date, base_hours, status, metadata, created_by, created_at, updated_at "
            "FROM activities WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
            activity_id, room_id,
        )
        if not row:
            return None
        data = dict(row)
        data["metadata"] = cls._parse_metadata(data["metadata"])
        data["base_hours"] = float(data["base_hours"] or 0)
        return data

    @classmethod
    async def _fetch_participants(cls, conn: asyncpg.Connection, activity_id: int) -> List[dict]:
        rows = await conn.fetch(
            f"{cls.PARTICIPANT_SELECT} WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL ORDER BY s.student_no ASC",
            activity_id,
        )
        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = cls._parse_metadata(d["metadata"])
            d["earned_hours"] = float(d["earned_hours"] or 0)
            result.append(d)
        return result

    @classmethod
    def _build_activity_response(cls, activity: dict, participants: Optional[List[dict]] = None) -> dict:
        resp = dict(activity)
        if participants is None:
            participants = activity.get("_participants") or []
        resp["participant_count"] = len(participants)
        resp["participants"] = participants
        resp.pop("_participants", None)
        return resp

    # ================================================================
    # 📥 ตรวจผู้เข้าร่วมก่อน insert (ต้องเป็นสมาชิก active ของห้อง)
    # ================================================================
    @classmethod
    async def _validate_participants(cls, conn: asyncpg.Connection, room_id: int, participants: List[dict]) -> List[tuple]:
        """คืน list ของ (student_id, role_type, role_detail, earned_hours, status, metadata) ตามลำดับ participants"""
        validated = []
        seen = set()
        for p in participants:
            student_no = p["student_no"]
            if student_no in seen:
                raise ValidationError(f"เลขที่ {student_no} ถูกเลือกซ้ำในรายชื่อผู้เข้าร่วม")
            seen.add(student_no)

            student_id = await conn.fetchval(
                "SELECT id FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'active' AND deleted_at IS NULL",
                room_id, student_no,
            )
            if not student_id:
                raise StudentNotFoundError(f"ไม่พบเลขที่ {student_no} ในห้องนี้ (หรือยังไม่ active)")

            # 🌟 metadata ต้องเป็น dict เสมอ (กันยัด list/str เข้า JSONB)
            metadata = p.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ValidationError(f"metadata ของเลขที่ {student_no} ต้องเป็น object")

            validated.append((
                student_id,
                p.get("role_type", "participant"),
                p.get("role_detail"),
                p.get("earned_hours", 0.0),
                p.get("status", "confirmed"),
                metadata,
            ))
        return validated

    # ================================================================
    # ✏️ CRUD: Activities
    # ================================================================
    @classmethod
    async def create_activity(
        cls,
        pool: asyncpg.Pool,
        title: str,
        activity_date: date,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        description: Optional[str] = None,
        base_hours: float = 0.0,
        status: str = "upcoming",
        metadata: Optional[dict] = None,
        participants: Optional[List[dict]] = None,
    ) -> dict:
        """
        สร้างกิจกรรม + ผู้เข้าร่วมหลายคนพร้อมกัน (executemany ภายใน transaction เดียว)
        - RBAC: ต้องมี MANAGE_ACTIVITIES
        - Audit: CREATE กิจกรรม + CREATE participant (ใน transaction เดียวกัน)
        - Notification: publish NEW_ACTIVITY หลัง commit (ถ้าห้องผูก Discord แล้ว)
        """
        start_time = time.time()
        target_room_id = None
        new_values: dict = {}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    meta = metadata or {}
                    if not isinstance(meta, dict):
                        raise ValidationError("metadata ต้องเป็น object")

                    activity_id = await conn.fetchval(
                        """
                        INSERT INTO activities (room_id, title, description, activity_date, base_hours, status, metadata, created_by)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                        RETURNING id
                        """,
                        target_room_id, title, description, activity_date, base_hours, status,
                        json.dumps(meta), user_name,
                    )

                    new_values = {
                        "title": title,
                        "description": description,
                        "activity_date": str(activity_date),
                        "base_hours": float(base_hours),
                        "status": status,
                        "metadata": meta,
                        "created_by": user_name,
                    }

                    # 👥 แทรกผู้เข้าร่วมแบบ executemany (atomic กับ activity)
                    participant_records = participants or []
                    if participant_records:
                        validated = await cls._validate_participants(conn, target_room_id, participant_records)
                        await conn.executemany(
                            """
                            INSERT INTO activity_participants
                                (activity_id, student_id, role_type, role_detail, earned_hours, status, metadata, recorded_by)
                            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                            """,
                            [
                                (
                                    activity_id, student_id, role_type, role_detail,
                                    earned_hours, p_status, json.dumps(p_meta), user_name,
                                )
                                for (student_id, role_type, role_detail, earned_hours, p_status, p_meta) in validated
                            ],
                        )
                        new_values["participants"] = [
                            {"student_no": p["student_no"], "role_type": p.get("role_type", "participant"),
                             "role_detail": p.get("role_detail"), "earned_hours": float(p.get("earned_hours", 0))}
                            for p in participant_records
                        ]

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        new_values=new_values, endpoint_or_command="create_activity", execution_time_ms=exec_time,
                    )

            # 📢 แจ้งเตือน Discord (หลัง commit transaction สำเร็จ)
            room_server_id = None
            async with pool.acquire() as conn:
                room_server_id = await conn.fetchval(
                    "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL", target_room_id
                )
            if room_server_id:
                await ActionService.notify_new_activity(
                    server_id=room_server_id,
                    title=title,
                    activity_date=activity_date,
                    base_hours=float(base_hours),
                    metadata=meta,
                    participant_count=len(participant_records),
                    user_name=user_name,
                    activity_id=activity_id,
                )

            return {"activity_id": activity_id, "status": "success"}

        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY", status="failed", error_detail=str(e),
                    new_values=new_values or {"title": title}, endpoint_or_command="create_activity", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def list_activities(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        include_participants: bool = False,
    ) -> List[dict]:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)

                base_sql = (
                    "SELECT id, room_id, title, description, activity_date, base_hours, status, metadata, created_by, created_at, updated_at "
                    "FROM activities WHERE room_id = $1 AND deleted_at IS NULL"
                )
                params: List[Any] = [target_room_id]
                if status:
                    base_sql += " AND status = $" + str(len(params) + 1)
                    params.append(status)
                base_sql += " ORDER BY activity_date ASC, id DESC"

                rows = await conn.fetch(base_sql, *params)
                activities = []
                for row in rows:
                    data = dict(row)
                    data["metadata"] = cls._parse_metadata(data["metadata"])
                    data["base_hours"] = float(data["base_hours"] or 0)
                    data["_participants"] = []
                    if include_participants:
                        data["_participants"] = await cls._fetch_participants(conn, data["id"])
                    activities.append(cls._build_activity_response(data))

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY_LIST", status="success",
                    new_values={"status": status}, endpoint_or_command="list_activities", execution_time_ms=exec_time,
                )
                return activities
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_LIST", status="failed", error_detail=str(e),
                    endpoint_or_command="list_activities", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def get_activity(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)

                activity = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                if not activity:
                    raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")
                participants = await cls._fetch_participants(conn, activity_id)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                    endpoint_or_command="get_activity", execution_time_ms=exec_time,
                )
                return cls._build_activity_response(activity, participants)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="get_activity", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def update_activity(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        update_data: dict,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """
        PATCH กิจกรรม — อัปเดตเฉพาะฟิลด์ที่ส่งมา (exclude_unset=True จาก router)
        metadata ถ้าส่งมา จะ merge กับของเดิม (deep-merge 1 ระดับ) — กันทำหายคีย์เก่า
        """
        start_time = time.time()
        target_room_id = None
        old_values: dict = {}
        try:
            clean = {k: v for k, v in update_data.items() if v is not None}
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    old = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                    if not old:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")
                    old_values = old

                    # 🌟 merge metadata (deep 1 ระดับ): คีย์ที่ผู้ใช้ไม่ส่งยังอยู่ครบ
                    if "metadata" in clean and isinstance(clean["metadata"], dict):
                        merged = dict(old["metadata"])
                        for k, v in clean["metadata"].items():
                            merged[k] = v
                        clean["metadata"] = merged

                    allowed = {"title", "description", "activity_date", "base_hours", "status", "metadata"}
                    fields = {k: v for k, v in clean.items() if k in allowed}
                    if not fields:
                        raise ValidationError("ไม่มีฟิลด์ที่แก้ไขได้ถูกส่งมา")

                    keys = sorted(fields.keys())
                    set_clauses = []
                    values: List[Any] = []
                    for i, key in enumerate(keys, start=1):
                        if key == "metadata":
                            set_clauses.append(f"{key} = ${i}::jsonb")
                            values.append(json.dumps(fields[key]))
                        elif key == "base_hours":
                            set_clauses.append(f"{key} = ${i}")
                            values.append(fields[key])
                        else:
                            set_clauses.append(f"{key} = ${i}")
                            values.append(fields[key])
                    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                    values.extend([activity_id, target_room_id])
                    sql = (
                        f"UPDATE activities SET {', '.join(set_clauses)} "
                        f"WHERE id = ${len(values)-1} AND room_id = ${len(values)} AND deleted_at IS NULL"
                    )
                    res = await conn.execute(sql, *values)
                    if res == "UPDATE 0":
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    new_values = {k: cls._serializable(v) for k, v in fields.items()}

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        old_values=old_values, new_values=new_values,
                        endpoint_or_command="update_activity", execution_time_ms=exec_time,
                    )

                    activity = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                    participants = await cls._fetch_participants(conn, activity_id)
                    return cls._build_activity_response(activity, participants)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="update_activity", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def delete_activity(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        user_name: str,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """Soft delete กิจกรรม — ผู้เข้าร่วมยังอยู่ (soft delete ด้วย) เผื่อกู้คืนได้"""
        start_time = time.time()
        target_room_id = None
        old_values: dict = {}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_ACTIVITIES")

                    old = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                    if not old:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")
                    old_values = old

                    # soft-delete กิจกรรม + ผู้เข้าร่วมทั้งหมด (กันข้อมูลฟ้องว่ายังมีคน)
                    await conn.execute(
                        "UPDATE activities SET deleted_at = NOW() WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        activity_id, target_room_id,
                    )
                    await conn.execute(
                        "UPDATE activity_participants SET deleted_at = NOW() WHERE activity_id = $1 AND deleted_at IS NULL",
                        activity_id,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        old_values=old_values, new_values={"deleted_at": "soft-deleted"},
                        endpoint_or_command="delete_activity", execution_time_ms=exec_time,
                    )
                    return {"activity_id": activity_id, "deleted_at": "soft-deleted"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="DELETE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="delete_activity", execution_time_ms=exec_time,
                )
            raise e

    # ================================================================
    # 👥 CRUD: Participants (standalone)
    # ================================================================
    @classmethod
    async def _get_activity_room(cls, conn: asyncpg.Connection, activity_id: int) -> Optional[int]:
        """คืน room_id ของกิจกรรม (เพื่อเช็คว่าอยู่ใน target room เดียวกัน)"""
        return await conn.fetchval(
            "SELECT room_id FROM activities WHERE id = $1 AND deleted_at IS NULL", activity_id
        )

    @classmethod
    async def add_participant(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        student_no: int,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        role_type: str = "participant",
        role_detail: Optional[str] = None,
        earned_hours: float = 0.0,
        status: str = "confirmed",
        metadata: Optional[dict] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    student_id = await conn.fetchval(
                        "SELECT id FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'active' AND deleted_at IS NULL",
                        target_room_id, student_no,
                    )
                    if not student_id:
                        raise StudentNotFoundError(f"ไม่พบเลขที่ {student_no} ในห้องนี้")

                    meta = metadata or {}
                    if not isinstance(meta, dict):
                        raise ValidationError("metadata ต้องเป็น object")

                    # ถ้าเคย soft-delete ไว้ → กู้กลับมา (กันชน UNIQUE partial index)
                    revived = await conn.fetchrow(
                        """
                        UPDATE activity_participants
                        SET deleted_at = NULL, role_type = $1, role_detail = $2, earned_hours = $3,
                            status = $4, metadata = $5::jsonb, recorded_by = $6, updated_at = CURRENT_TIMESTAMP
                        WHERE activity_id = $7 AND student_id = $8 AND deleted_at IS NOT NULL
                        RETURNING id
                        """,
                        role_type, role_detail, earned_hours, status, json.dumps(meta), user_name,
                        activity_id, student_id,
                    )
                    if revived:
                        participant_id = revived["id"]
                    else:
                        participant_id = await conn.fetchval(
                            """
                            INSERT INTO activity_participants
                                (activity_id, student_id, role_type, role_detail, earned_hours, status, metadata, recorded_by)
                            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                            RETURNING id
                            """,
                            activity_id, student_id, role_type, role_detail, earned_hours, status,
                            json.dumps(meta), user_name,
                        )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="success",
                        new_values={
                            "activity_id": activity_id, "student_no": student_no,
                            "role_type": role_type, "role_detail": role_detail,
                            "earned_hours": float(earned_hours), "status": status, "metadata": meta,
                        },
                        endpoint_or_command="add_participant", execution_time_ms=exec_time,
                    )
                    return {"participant_id": participant_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_PARTICIPANT", status="failed", error_detail=str(e),
                    endpoint_or_command="add_participant", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def update_participant(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        participant_id: int,
        update_data: dict,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """PATCH participant — อัปเดตเฉพาะฟิลด์ที่ส่งมา; metadata merge กับของเดิม"""
        start_time = time.time()
        target_room_id = None
        old_values: dict = {}
        try:
            clean = {k: v for k, v in update_data.items() if v is not None}
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    old = await conn.fetchrow(
                        f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                        participant_id, activity_id,
                    )
                    if not old:
                        raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {participant_id}")
                    old_values = dict(old)
                    old_values["metadata"] = cls._parse_metadata(old_values["metadata"])

                    if "metadata" in clean and isinstance(clean["metadata"], dict):
                        merged = dict(old_values["metadata"])
                        merged.update(clean["metadata"])
                        clean["metadata"] = merged

                    allowed = {"role_type", "role_detail", "earned_hours", "status", "metadata"}
                    fields = {k: v for k, v in clean.items() if k in allowed}
                    if not fields:
                        raise ValidationError("ไม่มีฟิลด์ที่แก้ไขได้ถูกส่งมา")

                    keys = sorted(fields.keys())
                    set_clauses = []
                    values: List[Any] = []
                    for i, key in enumerate(keys, start=1):
                        if key == "metadata":
                            set_clauses.append(f"{key} = ${i}::jsonb")
                            values.append(json.dumps(fields[key]))
                        else:
                            set_clauses.append(f"{key} = ${i}")
                            values.append(fields[key])
                    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                    values.extend([participant_id, activity_id])
                    sql = (
                        f"UPDATE activity_participants SET {', '.join(set_clauses)} "
                        f"WHERE id = ${len(values)-1} AND activity_id = ${len(values)} AND deleted_at IS NULL"
                    )
                    res = await conn.execute(sql, *values)
                    if res == "UPDATE 0":
                        raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {participant_id}")

                    new_values = {k: cls._serializable(v) for k, v in fields.items()}

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="success",
                        old_values=old_values, new_values=new_values,
                        endpoint_or_command="update_participant", execution_time_ms=exec_time,
                    )
                    return {"participant_id": participant_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="update_participant", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def remove_participant(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        participant_id: int,
        user_name: str,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """Soft delete participant"""
        start_time = time.time()
        target_room_id = None
        old_values: dict = {}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_ACTIVITIES")

                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    old = await conn.fetchrow(
                        f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                        participant_id, activity_id,
                    )
                    if not old:
                        raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {participant_id}")
                    old_values = dict(old)
                    old_values["metadata"] = cls._parse_metadata(old_values["metadata"])

                    await conn.execute(
                        "UPDATE activity_participants SET deleted_at = NOW() WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                        participant_id, activity_id,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="success",
                        old_values=old_values, new_values={"deleted_at": "soft-deleted"},
                        endpoint_or_command="remove_participant", execution_time_ms=exec_time,
                    )
                    return {"participant_id": participant_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="DELETE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="remove_participant", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def update_participant_status(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        participant_id: int,
        status: str,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """เปลี่ยนสถานะผู้เข้าร่วม (confirmed/cancelled/attended) — ใช้ตอนเช็คอิน / ยกเลิก"""
        return await cls.update_participant(
            pool=pool,
            activity_id=activity_id,
            participant_id=participant_id,
            update_data={"status": status},
            user_name=user_name,
            client_source=client_source,
            actor_identifier=actor_identifier,
            server_id=server_id,
            room_id=room_id,
            actor_user_id=actor_user_id,
        )

    @classmethod
    async def batch_update_participants(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        items: List[dict],
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """
        🎯 Batch Apply (คลุมดำตั้งค่า) — อัปเดต metadata ของผู้เข้าร่วมหลายคนภายใน transaction เดียว
        - รายการไหน error (participant ไม่ใช่ของกิจกรรม / soft-delete) → rollback ทั้งก้อน (atomic)
        - metadata ถูก merge กับของเดิม (ไม่ทับคีย์ที่ไม่ได้ส่ง)
        - เขียน audit log 1 รายการต่อ participant ที่ถูกอัปเดต
        """
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    # 🧹 Dedupe participant_id (กันอัปเดตซ้ำในชุดเดียว) — ตาม lesson batch finance
                    seen = set()
                    unique_items: List[dict] = []
                    for item in items:
                        pid = int(item["participant_id"])
                        if pid in seen:
                            raise ValidationError(f"participant_id {pid} ถูกส่งซ้ำใน batch")
                        seen.add(pid)
                        meta = item.get("metadata") or {}
                        if not isinstance(meta, dict):
                            raise ValidationError(f"metadata ของ participant {pid} ต้องเป็น object")
                        unique_items.append({"participant_id": pid, "metadata": meta})

                    updated = []
                    for item in unique_items:
                        pid = item["participant_id"]
                        new_meta = item["metadata"]
                        old = await conn.fetchrow(
                            f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                            pid, activity_id,
                        )
                        if not old:
                            raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {pid}")
                        old_meta = cls._parse_metadata(old["metadata"])
                        merged = dict(old_meta)
                        merged.update(new_meta)

                        await conn.execute(
                            "UPDATE activity_participants SET metadata = $1::jsonb, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = $2 AND activity_id = $3 AND deleted_at IS NULL",
                            json.dumps(merged), pid, activity_id,
                        )
                        updated.append({"participant_id": pid, "student_no": old["student_no"], "metadata": merged})

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id,
                            entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                            old_values={"metadata": old_meta}, new_values={"metadata": merged},
                            endpoint_or_command="batch_update_participants", execution_time_ms=exec_time,
                        )

                    return {"status": "success", "updated_count": len(updated), "updated": updated}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_PARTICIPANT", status="failed", error_detail=str(e),
                    endpoint_or_command="batch_update_participants", execution_time_ms=exec_time,
                )
            raise e

    # ================================================================
    # 👤 ดูสิทธิ์/กิจกรรมของนักเรียนคนเดียว (สำหรับบอท /my_roles และหน้าโปรไฟล์)
    # ================================================================
    @classmethod
    async def get_student_activity_roles(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> List[dict]:
        """
        คืนรายการกิจกรรม + หน้าที่ของ student คนนี้ (ผูกผ่าน users.user_id → students.student_id)
        ใช้กับบอท /my_roles: ดึง role_detail, bus_number (metadata), earned_hours ของกิจกรรมที่กำลังจะมา
        """
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                student_id = await conn.fetchval(
                    "SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL",
                    target_room_id, user_id,
                )
                if not student_id:
                    return []

                rows = await conn.fetch(
                    """
                    SELECT
                        a.id AS activity_id, a.title, a.activity_date, a.base_hours, a.status,
                        a.metadata AS activity_metadata,
                        ap.role_type, ap.role_detail, ap.earned_hours, ap.status AS participant_status,
                        ap.metadata AS participant_metadata,
                        u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
                        u.phone_number, u.phone_number_parent
                    FROM activity_participants ap
                    JOIN activities a ON ap.activity_id = a.id
                    JOIN students s ON ap.student_id = s.id
                    LEFT JOIN users u ON s.user_id = u.id
                    WHERE ap.student_id = $1 AND ap.deleted_at IS NULL
                      AND a.deleted_at IS NULL AND a.room_id = $2
                    ORDER BY a.activity_date ASC
                    """,
                    student_id, target_room_id,
                )
                result = []
                for row in rows:
                    d = dict(row)
                    d["activity_metadata"] = cls._parse_metadata(d["activity_metadata"])
                    d["participant_metadata"] = cls._parse_metadata(d["participant_metadata"])
                    d["base_hours"] = float(d["base_hours"] or 0)
                    d["earned_hours"] = float(d["earned_hours"] or 0)
                    result.append(d)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="ACTIVITY_MY_ROLES", status="success",
                    endpoint_or_command="get_student_activity_roles", execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ACTIVITY_MY_ROLES", status="failed", error_detail=str(e),
                    endpoint_or_command="get_student_activity_roles", execution_time_ms=exec_time,
                )
            raise e

    # ================================================================
    # 📄 Excel Export (openpyxl) — ดึง metadata คีย์สำคัญเป็นคอลัมน์
    # ================================================================
    @staticmethod
    def _format_buddhist_date(value: Any) -> str:
        """'15 ตุลาคม 2569' (พ.ศ. = ค.ศ. + 543)"""
        if value is None:
            return ""
        if isinstance(value, datetime):
            value = value.date()
        if not isinstance(value, date):
            return str(value)
        return f"{value.day} {THAI_MONTH_NAMES[value.month - 1]} {value.year + 543}"

    @staticmethod
    def _translate_label(field: str, value: Any) -> Any:
        if value is None:
            return ""
        if field == "role_type":
            return ROLE_TYPE_LABELS.get(str(value), value)
        if field == "status":
            return PARTICIPANT_STATUS_LABELS.get(str(value), value)
        if field == "activity_date":
            return ActivityService._format_buddhist_date(value)
        if field == "is_paid":
            # Boolean Checkbox → ไทย
            if isinstance(value, bool):
                return "✅ จ่ายแล้ว" if value else "⏳ ยังไม่จ่าย"
            if isinstance(value, str):
                return "✅ จ่ายแล้ว" if value.lower() in ("true", "1", "yes", "y") else "⏳ ยังไม่จ่าย"
            return str(value)
        return value

    # ตัวอ่านค่าของแต่ละคอลัมน์ — Type A อ่านจาก profile record, Type B อ่านจาก participant metadata
    # DRY: export + (อนาคต) GET ใช้ตัวนี้อ่านค่าเดียวกัน ไม่ต้องแก้สองที่
    @staticmethod
    def _field_reader(field: str) -> Any:
        if field in PROFILE_FIELDS:
            # Type A — จาก JOIN users (record), ไม่มี value → ""
            return lambda p: p.get(field)
        return lambda p: (p.get("metadata") or {}).get(field)  # Type B — จาก metadata

    @classmethod
    async def export_activity_excel(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        metadata_keys: List[str],
        user_name: str,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> io.BytesIO:
        """Export ผู้เข้าร่วมกิจกรรมเป็น .xlsx — Dynamic Smart Columns

        คอลัมน์มาจาก activities.metadata.required_fields (Array คีย์ที่ผู้สร้างกิจกรรมเลือกไว้ใน Field Selector)
        - คีย์ในกลุ่ม Type A (profile) → อ่านจาก record (JOIN users) โดยตรง
        - คีย์ในกลุ่ม Type B (metadata) → อ่านจาก participant.metadata
        ถ้า metadata_keys ส่งมา (backward compat) จะใช้ตัวนั้นแทน — ลดคอลัมน์ขยะว่างเปล่า
        """
        start_time = time.time()
        target_room_id = None
        # 🌟 export_keys = required_fields (จาก Field Selector) หรือ fallback metadata_keys — init ก่อน try
        # กัน audit fallback เจอ unbound variable ตอน error เกิดก่อนกำหนดค่า (ตาม lesson "AuditLogger Fallback")
        export_keys: List[str] = [str(k).strip() for k in metadata_keys if str(k).strip()]
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_ACTIVITIES")

                    activity = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                    if not activity:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")
                    participants = await cls._fetch_participants(conn, activity_id)
                    if not participants:
                        raise ValidationError("ยังไม่มีผู้เข้าร่วมในกิจกรรมนี้")

                    # 🌟 Dynamic: เอา required_fields จาก metadata กิจกรรม (Field Selector)
                    # ถ้าไม่มี (กิจกรรมเก่า) → ใช้ metadata_keys ที่ frontend ส่งมา (backward compat)
                    required_fields = activity.get("metadata", {}).get("required_fields") or []
                    if not isinstance(required_fields, list):
                        required_fields = []
                    if required_fields:
                        export_keys = [str(k).strip() for k in required_fields if str(k).strip()]
                    else:
                        export_keys = [str(k).strip() for k in metadata_keys if str(k).strip()]

                    # คอลัมน์พื้นฐาน (English keys) + คอลัมน์ที่ผู้สร้างเลือก (ลำดับตามที่เลือก)
                    base_fields = ["student_no", "first_name", "last_name", "role_type", "role_detail", "earned_hours", "status"]
                    seen = set()
                    fields = [f for f in base_fields if not (f in seen or seen.add(f))]
                    for key in export_keys:
                        if key not in fields:
                            fields.append(key)

                    room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", target_room_id)
                    room_name = room["room_name"] if room else f"ห้อง #{target_room_id}"

                    wb = Workbook()
                    # ---- Sheet 1: สรุป ----
                    ws_summary = wb.active
                    ws_summary.title = "สรุป"
                    ws_summary.sheet_view.showGridLines = False
                    ws_summary.column_dimensions["A"].width = 30
                    ws_summary.column_dimensions["B"].width = 26

                    HEADER_FILL = PatternFill("solid", fgColor="8B5CF6")   # ม่วง (ธีมกิจกรรม)
                    TOTAL_FILL = PatternFill("solid", fgColor="D1D5DB")
                    SECTION_FILL = PatternFill("solid", fgColor="F5F3FF")
                    white_bold = Font(bold=True, color="FFFFFF")
                    title_font = Font(bold=True, size=16, color="0F172A")

                    ws_summary["A1"] = f"สรุปกิจกรรม — {room_name}"
                    ws_summary["A1"].font = title_font
                    ws_summary["A2"] = f"สร้างเมื่อ {datetime.now(THAI_TZ).strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)"
                    ws_summary["A2"].font = Font(color="64748B", size=10)

                    def _section(row, label):
                        ws_summary.cell(row=row, column=1, value=label).font = Font(bold=True, size=12)
                        for col in (1, 2):
                            ws_summary.cell(row=row, column=col).fill = SECTION_FILL

                    def _row(row, label, value):
                        ws_summary.cell(row=row, column=1, value=label).font = Font(bold=True)
                        ws_summary.cell(row=row, column=2, value=value)

                    _section(4, "ข้อมูลกิจกรรม")
                    _row(5, "ชื่อกิจกรรม", activity["title"])
                    _row(6, "วันที่", cls._format_buddhist_date(activity["activity_date"]))
                    _row(7, "ชั่วโมงฐาน", float(activity["base_hours"] or 0))
                    _row(8, "สถานะ", PARTICIPANT_STATUS_LABELS.get(activity["status"], activity["status"]))
                    _row(9, "จำนวนผู้เข้าร่วม", len(participants))

                    _section(11, "รายละเอียด")
                    _row(12, "คำอธิบาย", activity.get("description") or "—")

                    _section(14, "Metadata กิจกรรม")
                    meta_lines = "\n".join(f"{k}: {v}" for k, v in activity["metadata"].items()) or "—"
                    ws_summary.cell(row=15, column=1, value=meta_lines)
                    ws_summary.merge_cells(start_row=15, start_column=1, end_row=15, end_column=2)

                    # ---- Sheet 2: รายชื่อผู้เข้าร่วม ----
                    ws_data = wb.create_sheet("รายชื่อผู้เข้าร่วม")
                    ws_data.sheet_view.showGridLines = False
                    ws_data.append([EXPORT_HEADER_LABELS.get(f, f) for f in fields])
                    for idx, field in enumerate(fields, start=1):
                        ws_data.column_dimensions[get_column_letter(idx)].width = 20
                        cell = ws_data.cell(row=1, column=idx)
                        cell.fill = HEADER_FILL
                        cell.font = white_bold
                        cell.alignment = Alignment(horizontal="center", vertical="center")

                    # แหล่งข้อมูลของแต่ละคอลัมน์ (DRY ผ่าน _field_reader):
                    # - base fields (student_no/ชื่อ/role) → อ่านจาก record + แปลง label
                    # - Type A (profile) → อ่านจาก record ตรง ๆ (JOIN users)
                    # - Type B (metadata) → อ่านจาก participant.metadata
                    BASE_READERS: Dict[str, Any] = {
                        "student_no": lambda p: p["student_no"],
                        "first_name": lambda p: p["first_name"],
                        "last_name": lambda p: p["last_name"],
                        "role_type": lambda p: cls._translate_label("role_type", p["role_type"]),
                        "role_detail": lambda p: p["role_detail"],
                        "earned_hours": lambda p: float(p["earned_hours"] or 0),
                        "status": lambda p: cls._translate_label("status", p["status"]),
                    }
                    for i, p in enumerate(participants, start=2):
                        final = []
                        for field in fields:
                            if field in BASE_READERS:
                                final.append(BASE_READERS[field](p))
                            else:
                                reader = cls._field_reader(field)
                                val = reader(p)
                                if val is None or (isinstance(val, str) and not val.strip()):
                                    final.append("")
                                else:
                                    final.append(cls._translate_label(field, val))
                        ws_data.append(final)
                        if i % 2 == 0:
                            for col_idx in range(1, len(fields) + 1):
                                ws_data.cell(row=i, column=col_idx).fill = PatternFill("solid", fgColor="F5F3FF")
                    ws_data.freeze_panes = "A2"

                    output = io.BytesIO()
                    wb.save(output)
                    output.seek(0)

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="EXPORT", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        new_values={"required_fields": export_keys, "metadata_keys": metadata_keys, "columns": fields},
                        endpoint_or_command="export_activity_excel", execution_time_ms=exec_time,
                    )
                    return output
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="EXPORT", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), new_values={"required_fields": export_keys, "metadata_keys": metadata_keys},
                    endpoint_or_command="export_activity_excel", execution_time_ms=exec_time,
                )
            raise e
