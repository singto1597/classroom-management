"""แผ่นเช็คชื่อ (activity_checkin_sheets) + บันทึกเช็คอิน"""
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


class CheckinsMixin:
    @classmethod
    async def list_checkin_sheets(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[dict]:
        """รายการแผ่นเช็คชื่อของกิจกรรม + สรุป checked/total"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)
                if await cls._get_activity_room(conn, activity_id) != target_room_id:
                    raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                total_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM activity_participants WHERE activity_id = $1 AND deleted_at IS NULL",
                    activity_id,
                ) or 0

                rows = await conn.fetch(
                    """
                    SELECT s.id, s.activity_id, s.title, s.event_date, s.created_by, s.created_at, s.updated_at,
                           COUNT(r.id) FILTER (WHERE r.is_present = TRUE AND r.deleted_at IS NULL) AS checked_count
                    FROM activity_checkin_sheets s
                    LEFT JOIN activity_checkin_records r ON r.sheet_id = s.id
                    WHERE s.activity_id = $1 AND s.deleted_at IS NULL
                    GROUP BY s.id
                    ORDER BY s.created_at ASC, s.id ASC
                    """,
                    activity_id,
                )
                sheets = []
                for row in rows:
                    d = dict(row)
                    d["checked_count"] = int(d["checked_count"] or 0)
                    d["total_count"] = int(total_count)
                    sheets.append(d)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET_LIST", entity_id=str(activity_id), status="success",
                    endpoint_or_command="list_checkin_sheets", execution_time_ms=exec_time,
                )
                return sheets
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET_LIST", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="list_checkin_sheets", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def create_checkin_sheet(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        title: str,
        event_date: Optional[date],
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """สร้างแผ่นเช็คชื่อใหม่ เช่น 'เช็คขึ้นรถ'"""
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

                    sheet_id = await conn.fetchval(
                        """
                        INSERT INTO activity_checkin_sheets (activity_id, title, event_date, created_by)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                        """,
                        activity_id, title, event_date, user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="success",
                        new_values={"activity_id": activity_id, "title": title,
                                    "event_date": str(event_date) if event_date else None},
                        endpoint_or_command="create_checkin_sheet", execution_time_ms=exec_time,
                    )
                    return {"sheet_id": sheet_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET", status="failed", error_detail=str(e),
                    new_values={"activity_id": activity_id, "title": title},
                    endpoint_or_command="create_checkin_sheet", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def update_checkin_sheet(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        sheet_id: int,
        update_data: dict,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """PATCH แผ่นเช็คชื่อ — event_date: null = เคลียร์วันที่"""
        start_time = time.time()
        target_room_id = None
        old_values: dict = {}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")
                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    old = await conn.fetchrow(
                        "SELECT id, activity_id, title, event_date, created_by FROM activity_checkin_sheets "
                        "WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                        sheet_id, activity_id,
                    )
                    if not old:
                        raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")
                    old_values = dict(old)

                    # title: None ข้าม; event_date: key มีอยู่ (แม้ None) → เซ็ต (null = เคลียร์)
                    fields: dict = {}
                    if "title" in update_data and update_data["title"] is not None:
                        fields["title"] = update_data["title"]
                    if "event_date" in update_data:
                        fields["event_date"] = update_data["event_date"]
                    if not fields:
                        raise ValidationError("ไม่มีฟิลด์ที่แก้ไขได้ถูกส่งมา")

                    keys = sorted(fields.keys())
                    set_clauses = []
                    values: List[Any] = []
                    for i, key in enumerate(keys, start=1):
                        set_clauses.append(f"{key} = ${i}")
                        values.append(fields[key])
                    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                    values.extend([sheet_id, activity_id])
                    sql = (
                        f"UPDATE activity_checkin_sheets SET {', '.join(set_clauses)} "
                        f"WHERE id = ${len(values)-1} AND activity_id = ${len(values)} AND deleted_at IS NULL"
                    )
                    res = await conn.execute(sql, *values)
                    if res == "UPDATE 0":
                        raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")

                    new_values = {k: cls._serializable(v) for k, v in fields.items()}
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="success",
                        old_values=old_values, new_values=new_values,
                        endpoint_or_command="update_checkin_sheet", execution_time_ms=exec_time,
                    )
                    return {"sheet_id": sheet_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="update_checkin_sheet", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def delete_checkin_sheet(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        sheet_id: int,
        user_name: str,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """Soft delete แผ่นเช็คชื่อ + บันทึกเช็คทั้งหมดในแผ่น"""
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
                        "SELECT id, activity_id, title, event_date, created_by FROM activity_checkin_sheets "
                        "WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                        sheet_id, activity_id,
                    )
                    if not old:
                        raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")
                    old_values = dict(old)

                    await conn.execute(
                        "UPDATE activity_checkin_sheets SET deleted_at = NOW() WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                        sheet_id, activity_id,
                    )
                    await conn.execute(
                        "UPDATE activity_checkin_records SET deleted_at = NOW() WHERE sheet_id = $1 AND deleted_at IS NULL",
                        sheet_id,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="success",
                        old_values=old_values, new_values={"deleted_at": "soft-deleted"},
                        endpoint_or_command="delete_checkin_sheet", execution_time_ms=exec_time,
                    )
                    return {"sheet_id": sheet_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="DELETE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, user_id=user_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="failed",
                    error_detail=str(e), old_values=old_values,
                    endpoint_or_command="delete_checkin_sheet", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def get_checkin_sheet(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        sheet_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ดูแผ่นเช็คชื่อ + ผู้เข้าร่วมทุกคนพร้อมเครื่องหมาย (is_present/checked_at/recorded_by)"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if user_id is not None:
                    await require_member(conn, target_room_id, user_id)
                if await cls._get_activity_room(conn, activity_id) != target_room_id:
                    raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                sheet = await conn.fetchrow(
                    "SELECT id, activity_id, title, event_date, created_by, created_at, updated_at "
                    "FROM activity_checkin_sheets WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
                    sheet_id, activity_id,
                )
                if not sheet:
                    raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")

                participants = await cls._fetch_participants(conn, activity_id)
                cls._mask_participants_pii(participants, user_id)
                records = await conn.fetch(
                    "SELECT participant_id, is_present, checked_at, recorded_by "
                    "FROM activity_checkin_records WHERE sheet_id = $1 AND deleted_at IS NULL",
                    sheet_id,
                )
                marks = {r["participant_id"]: r for r in records}
                for p in participants:
                    mark = marks.get(p["id"])
                    p["is_present"] = bool(mark["is_present"]) if mark else False
                    p["checked_at"] = mark["checked_at"] if mark else None
                    p["recorded_by"] = mark["recorded_by"] if mark else None

                sheet_dict = dict(sheet)
                sheet_dict["checked_count"] = sum(1 for p in participants if p["is_present"])
                sheet_dict["total_count"] = len(participants)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="success",
                    endpoint_or_command="get_checkin_sheet", execution_time_ms=exec_time,
                )
                return {"sheet": sheet_dict, "participants": participants}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_SHEET", entity_id=str(sheet_id), status="failed",
                    error_detail=str(e), endpoint_or_command="get_checkin_sheet", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def _checkin_sheet_exists(cls, conn: asyncpg.Connection, activity_id: int, sheet_id: int) -> bool:
        return await conn.fetchval(
            "SELECT 1 FROM activity_checkin_sheets WHERE id = $1 AND activity_id = $2 AND deleted_at IS NULL",
            sheet_id, activity_id,
        )

    @classmethod
    async def upsert_checkin_record(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        sheet_id: int,
        participant_id: int,
        is_present: bool,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """เช็คชื่อ/แก้การเช็คของ participant 1 คนในแผ่น (upsert — 1 active row ต่อ (sheet, participant))"""
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
                    if not await cls._checkin_sheet_exists(conn, activity_id, sheet_id):
                        raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")

                    participant = await conn.fetchrow(
                        f"{cls.PARTICIPANT_SELECT} WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL",
                        participant_id, activity_id,
                    )
                    if not participant:
                        raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {participant_id}")

                    existing = await conn.fetchval(
                        "SELECT id FROM activity_checkin_records WHERE sheet_id = $1 AND participant_id = $2 AND deleted_at IS NULL",
                        sheet_id, participant_id,
                    )
                    action = "UPDATE" if existing else "CREATE"

                    record_id = await conn.fetchval(
                        """
                        INSERT INTO activity_checkin_records (sheet_id, participant_id, is_present, checked_at, recorded_by)
                        VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4)
                        ON CONFLICT (sheet_id, participant_id) WHERE deleted_at IS NULL
                        DO UPDATE SET is_present = EXCLUDED.is_present, checked_at = CURRENT_TIMESTAMP,
                                      recorded_by = EXCLUDED.recorded_by, updated_at = CURRENT_TIMESTAMP
                        RETURNING id
                        """,
                        sheet_id, participant_id, is_present, user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action=action, actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_CHECKIN_RECORD", entity_id=str(record_id), status="success",
                        new_values={"sheet_id": sheet_id, "participant_id": participant_id,
                                    "student_no": participant["student_no"], "is_present": is_present},
                        endpoint_or_command="upsert_checkin_record", execution_time_ms=exec_time,
                    )
                    return {"record_id": record_id, "status": "success"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPSERT", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_RECORD", status="failed", error_detail=str(e),
                    new_values={"sheet_id": sheet_id, "participant_id": participant_id, "is_present": is_present},
                    endpoint_or_command="upsert_checkin_record", execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def batch_update_checkin_records(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        sheet_id: int,
        records: List[dict],
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """เช็คชื่อหลายคนในแผ่นเดียวพร้อมกัน (atomic — ตัวไหน error rollback ทั้งก้อน)"""
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
                    if not await cls._checkin_sheet_exists(conn, activity_id, sheet_id):
                        raise CheckinSheetNotFoundError(f"ไม่พบแผ่นเช็คชื่อ ID: {sheet_id}")

                    seen = set()
                    unique_records: List[dict] = []
                    for r in records:
                        pid = int(r["participant_id"])
                        if pid in seen:
                            raise ValidationError(f"participant_id {pid} ถูกส่งซ้ำในชุดเช็คชื่อ")
                        seen.add(pid)
                        unique_records.append({"participant_id": pid, "is_present": bool(r["is_present"])})

                    active_ids = {
                        row["id"] for row in await conn.fetch(
                            "SELECT id FROM activity_participants WHERE activity_id = $1 AND deleted_at IS NULL",
                            activity_id,
                        )
                    }
                    for r in unique_records:
                        if r["participant_id"] not in active_ids:
                            raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {r['participant_id']} ในกิจกรรมนี้")

                    updated = 0
                    for r in unique_records:
                        await conn.fetchval(
                            """
                            INSERT INTO activity_checkin_records (sheet_id, participant_id, is_present, checked_at, recorded_by)
                            VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4)
                            ON CONFLICT (sheet_id, participant_id) WHERE deleted_at IS NULL
                            DO UPDATE SET is_present = EXCLUDED.is_present, checked_at = CURRENT_TIMESTAMP,
                                          recorded_by = EXCLUDED.recorded_by, updated_at = CURRENT_TIMESTAMP
                            RETURNING id
                            """,
                            sheet_id, r["participant_id"], r["is_present"], user_name,
                        )
                        updated += 1
                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id,
                            entity_type="ACTIVITY_CHECKIN_RECORD", entity_id=str(r["participant_id"]), status="success",
                            new_values={"sheet_id": sheet_id, "participant_id": r["participant_id"],
                                        "is_present": r["is_present"]},
                            endpoint_or_command="batch_update_checkin_records", execution_time_ms=exec_time,
                        )

                    return {"status": "success", "updated_count": updated}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            safe_room_id = None if isinstance(e, RoomNotFoundError) else target_room_id
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id,
                    entity_type="ACTIVITY_CHECKIN_RECORD", status="failed", error_detail=str(e),
                    new_values={"sheet_id": sheet_id},
                    endpoint_or_command="batch_update_checkin_records", execution_time_ms=exec_time,
                )
            raise e
