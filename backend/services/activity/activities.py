"""CRUD กิจกรรม (activities) + บทบาท/รายชื่อที่ใช้ได้"""
import io
import json
import time
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, List, Optional

import asyncpg

from core.config import settings
from core.exceptions import (
    ActivityNotFoundError,
    CheckinSheetNotFoundError,
    ForbiddenError,
    ParticipantNotFoundError,
    RoomNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from core.logger import AuditLogger
from core.rbac import require_member, require_permission
from core.privacy import can_view_activity_pii, mask_private_fields, PROFILE_TYPE_A_FIELDS
from services.action_service import ActionService
from .base import service_logger


class ActivitiesMixin:
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
                    # 🌟 validate dynamic_fields (ถ้ามีใน metadata) — กัน def ผิดโครงสร้างตอนสร้าง
                    if "dynamic_fields" in meta:
                        cls._validate_dynamic_fields(meta.get("dynamic_fields"))

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
                        cls._mask_participants_pii(data["_participants"], user_id)
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
                cls._mask_participants_pii(participants, user_id)

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
        participants: Optional[List[dict]] = None,
    ) -> dict:
        """
        PATCH กิจกรรม — อัปเดตเฉพาะฟิลด์ที่ส่งมา (exclude_unset=True จาก router)
        metadata ถ้าส่งมา จะ merge กับของเดิม (deep-merge 1 ระดับ) — กันทำหายคีย์เก่า
        participants ถ้าส่งมา (ไม่ใช่ None) → reconcile ผู้เข้าร่วมทั้งชุดใน transaction เดียว
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
                    # 📌 delete-on-null: คีย์ที่ส่งค่า None มา → ลบออก (ใช้ตอน dual-write คีย์เก่า
                    # location_name/url, agenda, tags ถูกถอดออกจากข้อมูลเพิ่มเติม) — กัน ghost key ค้าง
                    if "metadata" in clean and isinstance(clean["metadata"], dict):
                        merged = dict(old["metadata"])
                        for k, v in clean["metadata"].items():
                            if v is None:
                                merged.pop(k, None)
                            else:
                                merged[k] = v
                        clean["metadata"] = merged
                        # 🌟 validate dynamic_fields หลัง merge (เฉพาะเมื่อมีและไม่ใช่ None) — ลบ (null) ไม่ต้อง validate
                        if merged.get("dynamic_fields") is not None:
                            cls._validate_dynamic_fields(merged.get("dynamic_fields"))

                    allowed = {"title", "description", "activity_date", "base_hours", "status", "metadata"}
                    fields = {k: v for k, v in clean.items() if k in allowed}
                    if not fields and participants is None:
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

                    # 👥 ถ้าส่ง participants มาด้วย → reconcile ทั้งชุด (เพิ่ม/แก้/ลบ/กู้คืน) ใน transaction เดียว
                    if participants is not None:
                        await cls._reconcile_participants(
                            conn=conn,
                            room_id=target_room_id,
                            activity_id=activity_id,
                            participants=participants,
                            user_name=user_name,
                            actor_identifier=actor_identifier,
                            client_source=client_source,
                            start_time=start_time,
                        )

                    activity = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                    participants = await cls._fetch_participants(conn, activity_id)
                    cls._mask_participants_pii(participants, actor_user_id)
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

    @classmethod
    async def list_available_students(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[dict]:
        """นักเรียน active ในห้องที่ยังไม่ได้เป็นผู้เข้าร่วม active ของกิจกรรมนี้
        (soft-deleted participant = re-addable → รวมด้วย เพราะ batch-add จะ revive คืน)"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)
                if await cls._get_activity_room(conn, activity_id) != target_room_id:
                    raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                rows = await conn.fetch(
                    """
                    SELECT s.id AS student_id, s.student_no,
                           u.first_name, u.last_name, u.nickname,
                           u.first_name_en, u.last_name_en, u.nickname_en,
                           u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
                           u.phone_number, u.phone_number_parent
                    FROM students s
                    LEFT JOIN users u ON s.user_id = u.id
                    WHERE s.room_id = $1 AND s.status = 'active' AND s.deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM activity_participants ap
                          WHERE ap.activity_id = $2 AND ap.student_id = s.id AND ap.deleted_at IS NULL
                      )
                    ORDER BY s.student_no ASC
                    """,
                    target_room_id, activity_id,
                )
                result = [dict(r) for r in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY_AVAILABLE_STUDENTS", entity_id=str(activity_id), status="success",
                    new_values={"available_count": len(result)},
                    endpoint_or_command="list_available_students", execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_AVAILABLE_STUDENTS", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="list_available_students", execution_time_ms=exec_time,
                )
            raise e

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
