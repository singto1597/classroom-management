"""ผู้เข้าร่วมกิจกรรม (activity_participants) — เพิ่ม/แก้/ลบ/สถานะ/batch"""
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


class ParticipantsMixin:
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
                        # 🎖️ พก role_detail ต่อ (batch ตั้งหน้าที่) — ไม่ส่ง = None = ไม่แตะของเดิม
                        role_detail = item.get("role_detail")
                        if role_detail is not None and not isinstance(role_detail, str):
                            raise ValidationError(f"role_detail ของ participant {pid} ต้องเป็น string")
                        # 🌟 role_type / status / earned_hours — optional; ไม่ส่ง = None = ไม่แตะของเดิม
                        role_type = item.get("role_type")
                        if role_type is not None and role_type not in ("participant", "staff", "leader"):
                            raise ValidationError(f"role_type ของ participant {pid} ต้องเป็น participant/staff/leader")
                        p_status = item.get("status")
                        if p_status is not None and p_status not in ("confirmed", "cancelled", "attended"):
                            raise ValidationError(f"status ของ participant {pid} ต้องเป็น confirmed/cancelled/attended")
                        earned_hours = item.get("earned_hours")
                        if earned_hours is not None:
                            try:
                                earned_hours = float(earned_hours)
                            except (TypeError, ValueError):
                                raise ValidationError(f"earned_hours ของ participant {pid} ต้องเป็นตัวเลข")
                            if earned_hours < 0:
                                raise ValidationError(f"earned_hours ของ participant {pid} ต้องไม่ติดลบ")
                        unique_items.append({
                            "participant_id": pid,
                            "role_detail": role_detail,
                            "role_type": role_type,
                            "status": p_status,
                            "earned_hours": earned_hours,
                            "metadata": meta,
                        })

                    updated = []
                    for item in unique_items:
                        pid = item["participant_id"]
                        new_meta = item["metadata"]
                        new_role_detail = item["role_detail"]
                        new_role_type = item["role_type"]
                        new_status = item["status"]
                        new_earned_hours = item["earned_hours"]
                        old = await conn.fetchrow(
                            f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                            pid, activity_id,
                        )
                        if not old:
                            raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {pid}")
                        old_meta = cls._parse_metadata(old["metadata"])
                        merged = dict(old_meta)
                        merged.update(new_meta)

                        # Dynamic SET — ถ้าส่ง field ไหนมา (ไม่ใช่ None) → ตั้งค่าให้
                        # role_detail: ("" = เคลียร์หน้าที่) — pattern เดียวกับ update_participant
                        set_clauses = ["metadata = $1::jsonb"]
                        values: List[Any] = [json.dumps(merged)]
                        if new_role_detail is not None:
                            set_clauses.append(f"role_detail = ${len(values) + 1}")
                            values.append(new_role_detail)
                        if new_role_type is not None:
                            set_clauses.append(f"role_type = ${len(values) + 1}")
                            values.append(new_role_type)
                        if new_status is not None:
                            set_clauses.append(f"status = ${len(values) + 1}")
                            values.append(new_status)
                        if new_earned_hours is not None:
                            set_clauses.append(f"earned_hours = ${len(values) + 1}")
                            values.append(new_earned_hours)
                        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                        values.extend([pid, activity_id])
                        sql = (
                            f"UPDATE activity_participants SET {', '.join(set_clauses)} "
                            f"WHERE id = ${len(values)-1} AND activity_id = ${len(values)} AND deleted_at IS NULL"
                        )
                        await conn.execute(sql, *values)

                        new_vals: dict = {"metadata": merged}
                        if new_role_detail is not None:
                            new_vals["role_detail"] = new_role_detail
                        if new_role_type is not None:
                            new_vals["role_type"] = new_role_type
                        if new_status is not None:
                            new_vals["status"] = new_status
                        if new_earned_hours is not None:
                            new_vals["earned_hours"] = float(new_earned_hours)
                        updated.append({
                            "participant_id": pid,
                            "student_no": old["student_no"],
                            "role_detail": new_role_detail if new_role_detail is not None else old["role_detail"],
                            "role_type": new_role_type if new_role_type is not None else old["role_type"],
                            "status": new_status if new_status is not None else old["status"],
                            "earned_hours": float(new_earned_hours) if new_earned_hours is not None else float(old["earned_hours"] or 0),
                            "metadata": merged,
                        })

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id,
                            entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                            old_values={"metadata": old_meta, "role_detail": old["role_detail"]},
                            new_values={k: cls._serializable(v) for k, v in new_vals.items()},
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

    @classmethod
    async def batch_add_participants(
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
        """เพิ่มผู้เข้าร่วมหลายคนพร้อมกัน (atomic) — revive-or-insert ต่อคน (กันชน full UNIQUE)
        เขียน audit log 1 รายการต่อคนที่เพิ่ม"""
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

                    seen = set()
                    unique_items: List[dict] = []
                    for item in items:
                        no = int(item["student_no"])
                        if no in seen:
                            raise ValidationError(f"เลขที่ {no} ถูกส่งซ้ำในชุดเพิ่มผู้เข้าร่วม")
                        seen.add(no)
                        meta = item.get("metadata") or {}
                        if not isinstance(meta, dict):
                            raise ValidationError(f"metadata ของเลขที่ {no} ต้องเป็น object")
                        unique_items.append(item)

                    added: List[dict] = []
                    for item in unique_items:
                        no = int(item["student_no"])
                        role_type = item.get("role_type", "participant")
                        role_detail = item.get("role_detail")
                        earned_hours = float(item.get("earned_hours", 0.0) or 0.0)
                        status = item.get("status", "confirmed")
                        meta = item.get("metadata") or {}

                        student_id = await conn.fetchval(
                            "SELECT id FROM students WHERE room_id = $1 AND student_no = $2 AND status = 'active' AND deleted_at IS NULL",
                            target_room_id, no,
                        )
                        if not student_id:
                            raise StudentNotFoundError(f"ไม่พบเลขที่ {no} ในห้องนี้ (หรือยังไม่ active)")

                        # revive-or-insert (pattern เดียวกับ add_participant) — กันชน UNIQUE(activity_id, student_id)
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
                            log_action = "CREATE"
                            audit_extra = {"action": "revived_soft_deleted"}
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
                            log_action = "CREATE"
                            audit_extra = {}

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action=log_action, actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id,
                            entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant_id), status="success",
                            new_values={"activity_id": activity_id, "student_no": no,
                                        "role_type": role_type, "role_detail": role_detail,
                                        "earned_hours": earned_hours, "status": status, "metadata": meta,
                                        **audit_extra},
                            endpoint_or_command="batch_add_participants", execution_time_ms=exec_time,
                        )
                        added.append({"participant_id": participant_id, "student_no": no})

                    return {"status": "success", "added": added, "updated_count": len(added)}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_PARTICIPANT", status="failed", error_detail=str(e),
                    new_values={"activity_id": activity_id, "items": items},
                    endpoint_or_command="batch_add_participants", execution_time_ms=exec_time,
                )
            raise e
