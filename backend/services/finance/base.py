"""ตัวช่วยพื้นฐานที่ Finance service อื่นใช้ร่วมกัน (resolve room / actor / server_id)"""
import asyncpg
import io
import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import (
    THAI_TZ, CUTOFF_DATE, MONEY_NUM_FMT, PCT_NUM_FMT, ACCOUNT_TYPE_LABELS,
    COLLECTION_STATUS_LABELS, REFERENCE_TYPE_LABELS, MANAGEMENT_TAB_COLORS,
    ACCOUNTING_TAB_COLORS, RECONCILE_REFERENCE_TYPE, RECONCILE_EQUITY_CODE,
    RECONCILE_EQUITY_NAME, _CLAMP_START_NOTE, _CLAMP_EMPTY_NOTE,
)
from .helpers import (
    _naive_thai_dt, _clamp_to_cutoff, _ExportPeriodView, _resolve_inclusive_period,
    _legacy_id_from_journal,
)

service_logger = AuditLogger(service_name="FINANCE")


class BaseMixin:
    @staticmethod
    def _extract_req_data(req) -> dict:
        if isinstance(req, dict):
            return req
        # 🚀 Pydantic v2 ต้องใช้ model_dump() (dict() ถูกลบใน v3) — ตรงตามกฎ CLAUDE.md
        if hasattr(req, 'model_dump') and callable(req.model_dump):
            return req.model_dump()
        if hasattr(req, 'dict') and callable(req.dict):
            return req.dict()
        try:
            return vars(req)
        except Exception:
            return {"raw_data": str(req)}

    @staticmethod
    def _finance_actor(req) -> str:
        n = getattr(req, "user_name", None)
        if n is not None and str(n).strip():
            return str(n).strip()[:200]
        return "—"

    @staticmethod
    async def _get_room_server_id(conn: asyncpg.Connection, room_id: int) -> Optional[int]:
        """ดึง server_id ของห้อง (ใช้ publish ไป Discord) — คืน None ถ้าห้องยังไม่ผูก Discord"""
        return await conn.fetchval(
            "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL",
            room_id,
        )

    @staticmethod
    def _period_start(
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
    ) -> Optional[date]:
        """จุดเริ่มต้นของช่วงเวลาที่ถูกขอ → ใช้ตัดสินใจ Route ไป legacy หรือ v2.

        - month/year: วันที่ 1 ของเดือน
        - start_date: ตัวมันเอง (หรือจุดเริ่มต้นของช่วง)
        - ไม่ระบุเลย: ใช้จุดเริ่มต้นของเดือนปัจจุบัน (ทำนองเดียวกับ legacy fallback)
        คืน None ไม่มีทางเกิดขึ้นจริง (เดือนปัจจุบันมีจุดเริ่มเสมอ) แต่ใส่เผื่อ type safety.
        """
        if month is not None and year is not None:
            return date(year, month, 1)
        if start_date is not None:
            return start_date
        # ไม่มีตัวกรองช่วงเวลา → default เป็นเดือนปัจจุบัน (ตรงกับ logic เดิมของ get_summary)
        today = datetime.now(THAI_TZ).date()
        return date(today.year, today.month, 1)

    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
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

    @classmethod
    async def get_active_students(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id, S.student_no, U.first_name, U.last_name, U.nickname,
                           U.first_name_en, U.last_name_en, U.nickname_en
                    FROM students S
                    LEFT JOIN users U ON S.user_id = U.id
                    WHERE S.room_id = $1 AND S.status = 'active' AND S.deleted_at IS NULL
                    ORDER BY S.student_no ASC
                """, target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="success",
                    endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
