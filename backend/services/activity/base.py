"""ตัวช่วยพื้นฐานที่ activity service อื่นใช้ร่วมกัน (resolve room / parse metadata / fetch + mask participants)"""
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

service_logger = AuditLogger(service_name="ACTIVITY")


class BaseMixin:
    # 🌟 SELECT ร่วมของ participant (อ่าน + JOIN students/users) — ใช้ทั้ง base และ export
    PARTICIPANT_SELECT = """
        SELECT
            ap.id, ap.activity_id, ap.student_id, ap.role_type, ap.role_detail,
            ap.earned_hours, ap.status, ap.metadata, ap.recorded_by,
            s.student_no, s.identity_claimed, u.id AS user_id,
            u.first_name, u.last_name, u.nickname,
            u.first_name_en, u.last_name_en, u.nickname_en,
            -- 🌟 Type A Profile Fields (READ ONLY จาก users) — JOIN มาพร้อมเสมอ ห้ามบันทึกซ้ำลง metadata
            u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
            u.phone_number, u.phone_number_parent
        FROM activity_participants ap
        JOIN students s ON ap.student_id = s.id
        LEFT JOIN users u ON s.user_id = u.id
    """

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

    @staticmethod
    def _validate_dynamic_fields(dynamic_fields: Any) -> None:
        """ตรวจโครงสร้างของ dynamic_fields (ต้องเป็น list ของ def ที่ key ต่างกัน ไม่มี label ว่าง)"""
        if dynamic_fields is None:
            return
        if not isinstance(dynamic_fields, list):
            raise ValidationError("dynamic_fields ต้องเป็น array")
        allowed_types = {"input", "dropdown", "boolean", "datetime"}
        seen = set()
        for item in dynamic_fields:
            if not isinstance(item, dict):
                raise ValidationError("dynamic_fields แต่ละรายการต้องเป็น object")
            key = item.get("key")
            label = item.get("label")
            ftype = item.get("type")
            if not isinstance(key, str) or not key.startswith("df_") or not key[3:].isdigit():
                raise ValidationError("dynamic_fields key ต้องอยู่ในรูปแบบ df_<number> (เช่น df_1)")
            if key in seen:
                raise ValidationError(f"dynamic_fields key '{key}' ซ้ำกันในรายการ")
            seen.add(key)
            if not isinstance(label, str) or not label.strip():
                raise ValidationError(f"dynamic_fields '{key}' ต้องมี label (หัวข้อ) ไม่เว้นว่าง")
            if ftype not in allowed_types:
                raise ValidationError(f"dynamic_fields '{key}' type ต้องเป็นหนึ่งใน {sorted(allowed_types)}")
            if ftype == "dropdown":
                options = item.get("options")
                if not isinstance(options, list) or not options:
                    raise ValidationError(f"dynamic_fields '{key}' type=dropdown ต้องมี options")
                for opt in options:
                    if not isinstance(opt, dict) or not str(opt.get("value", "")).strip() or not str(opt.get("label", "")).strip():
                        raise ValidationError(f"dynamic_fields '{key}' option ต้องมี value และ label")

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
    def _mask_participants_pii(cls, participants: List[dict], requester_user_id: Optional[int]) -> List[dict]:
        """🛡️ Consent Model: participant ที่ยังไม่ยืนยันตัวตน (identity_claimed=False) → Type A (PII)
        ถูก 🔒 mask — สมาชิกห้องเห็น PII ได้เฉพาะคนที่ยืนยันตัวตนแล้ว (หรือดูตัวเอง / super admin).
        ดู core/privacy.py"""
        is_super_admin = settings.SUPER_ADMIN_ID and requester_user_id and int(requester_user_id) == int(settings.SUPER_ADMIN_ID)
        for p in participants:
            can_view = can_view_activity_pii(
                requester_user_id=requester_user_id,
                target_user_id=p.get("user_id"),
                identity_claimed=p.get("identity_claimed"),
                is_super_admin=is_super_admin,
            )
            mask_private_fields(p, can_view, fields=PROFILE_TYPE_A_FIELDS)
        return participants

    @classmethod
    def _build_activity_response(cls, activity: dict, participants: Optional[List[dict]] = None) -> dict:
        resp = dict(activity)
        if participants is None:
            participants = activity.get("_participants") or []
        resp["participant_count"] = len(participants)
        resp["participants"] = participants
        resp.pop("_participants", None)
        return resp

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

    @classmethod
    async def _reconcile_participants(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        activity_id: int,
        participants: List[dict],
        user_name: str,
        actor_identifier: str,
        client_source: str,
        start_time: float,
    ) -> None:
        """
        🎯 แทนที่ผู้เข้าร่วมทั้งชุด (ใช้ในหน้าแก้ไขกิจกรรม — "แก้ได้ทุกอย่างเหมือนตอนสร้าง")

        รับ participant dicts ที่ถูกส่งมาจาก form (student_no + role_type + role_detail +
        earned_hours + status + metadata) แล้ว reconcile กับชุดปัจจุบันภายใน transaction เดียว:
        - มีอยู่แล้ว (student_id ตรง) → UPDATE (แทนที่ metadata เต็ม เพราะ form round-trip ทั้งชุด)
        - เคยถูก soft-delete → กู้คืน (revive) ให้ `deleted_at = NULL` (กันชน partial unique index)
        - เป็นสมาชิกใหม่ → INSERT
        - คนที่ไม่ถูกส่งมาอีกต่อไป → soft delete (deleted_at = NOW())
        เขียน audit log 1 รายการต่อ mutation (CREATE/UPDATE/DELETE) เหมือน batch_update_participants
        """
        validated = await cls._validate_participants(conn, room_id, participants)

        # อ่านชุดปัจจุบัน (id + student_id) เพื่อหาเป้าหมายการ UPDATE / DELETE
        current = await conn.fetch(
            "SELECT id, student_id FROM activity_participants WHERE activity_id = $1 AND deleted_at IS NULL",
            activity_id,
        )
        current_by_student: Dict[int, int] = {row["student_id"]: row["id"] for row in current}
        incoming_students: set = set()

        for (student_id, role_type, role_detail, earned_hours, p_status, p_meta) in validated:
            incoming_students.add(student_id)
            pid = current_by_student.get(student_id)

            if pid is not None:
                # 1) มีอยู่แล้ว → UPDATE (แทนที่ metadata เต็ม)
                old = await conn.fetchrow(
                    f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                    pid, activity_id,
                )
                old_meta = cls._parse_metadata(old["metadata"]) if old else {}
                await conn.execute(
                    """
                    UPDATE activity_participants
                    SET role_type = $1, role_detail = $2, earned_hours = $3, status = $4,
                        metadata = $5::jsonb, recorded_by = $6, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $7 AND activity_id = $8 AND deleted_at IS NULL
                    """,
                    role_type, role_detail, earned_hours, p_status, json.dumps(p_meta), user_name,
                    pid, activity_id,
                )
                new_vals = {"student_no": None, "role_type": role_type, "role_detail": role_detail,
                            "earned_hours": float(earned_hours), "status": p_status, "metadata": p_meta}
                if old:
                    new_vals["student_no"] = old["student_no"]
                await service_logger.log(
                    conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=room_id,
                    entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                    old_values={"metadata": old_meta, "role_detail": (old["role_detail"] if old else None)},
                    new_values={k: cls._serializable(v) for k, v in new_vals.items()},
                    endpoint_or_command="update_activity/reconcile", execution_time_ms=int((time.time() - start_time) * 1000),
                )
                continue

            # 2) ไม่มีในชุด active → ลองกู้คืน soft-deleted (กันชน partial unique index)
            revived = await conn.fetchrow(
                """
                UPDATE activity_participants
                SET deleted_at = NULL, role_type = $1, role_detail = $2, earned_hours = $3,
                    status = $4, metadata = $5::jsonb, recorded_by = $6, updated_at = CURRENT_TIMESTAMP
                WHERE activity_id = $7 AND student_id = $8 AND deleted_at IS NOT NULL
                RETURNING id
                """,
                role_type, role_detail, earned_hours, p_status, json.dumps(p_meta), user_name,
                activity_id, student_id,
            )
            if revived:
                pid = revived["id"]
                await service_logger.log(
                    conn=conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=room_id,
                    entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                    new_values={"action": "revived_soft_deleted", "role_type": role_type,
                                "role_detail": role_detail, "metadata": p_meta},
                    endpoint_or_command="update_activity/reconcile", execution_time_ms=int((time.time() - start_time) * 1000),
                )
                continue

            # 3) เป็นสมาชิกใหม่ → INSERT
            pid = await conn.fetchval(
                """
                INSERT INTO activity_participants
                    (activity_id, student_id, role_type, role_detail, earned_hours, status, metadata, recorded_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                RETURNING id
                """,
                activity_id, student_id, role_type, role_detail, earned_hours, p_status,
                json.dumps(p_meta), user_name,
            )
            await service_logger.log(
                conn=conn, action="CREATE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=room_id,
                entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                new_values={"role_type": role_type, "role_detail": role_detail,
                            "earned_hours": float(earned_hours), "status": p_status, "metadata": p_meta},
                endpoint_or_command="update_activity/reconcile", execution_time_ms=int((time.time() - start_time) * 1000),
            )

        # 4) ผู้เข้าร่วมที่ถูกถอดออกจากชุด → soft delete
        for student_id, pid in current_by_student.items():
            if student_id in incoming_students:
                continue
            old = await conn.fetchrow(
                f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                pid, activity_id,
            )
            await conn.execute(
                "UPDATE activity_participants SET deleted_at = NOW() WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                pid, activity_id,
            )
            old_meta = cls._parse_metadata(old["metadata"]) if old else {}
            await service_logger.log(
                conn=conn, action="DELETE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=room_id,
                entity_type="ACTIVITY_PARTICIPANT", entity_id=str(pid), status="success",
                old_values={"metadata": old_meta, "role_detail": (old["role_detail"] if old else None)},
                new_values={"deleted_at": "soft-deleted"},
                endpoint_or_command="update_activity/reconcile", execution_time_ms=int((time.time() - start_time) * 1000),
            )

    @classmethod
    async def _get_activity_room(cls, conn: asyncpg.Connection, activity_id: int) -> Optional[int]:
        """คืน room_id ของกิจกรรม (เพื่อเช็คว่าอยู่ใน target room เดียวกัน)"""
        return await conn.fetchval(
            "SELECT room_id FROM activities WHERE id = $1 AND deleted_at IS NULL", activity_id
        )
