"""ตัวช่วยพื้นฐานที่ student service อื่นใช้ร่วมกัน (resolve room / parse permission / completion / find-or-create user)"""
import asyncpg
import io
import json
import time
from datetime import date, datetime
from typing import Any, Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.config import settings
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from core.logger import AuditLogger
from core.name_utils import normalize_nfc, normalize_en, identity_pair
from core.privacy import can_view_pii, mask_private_fields, is_real_claimed_account, PRIVATE_STUDENT_FIELDS
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import (
    STUDENT_PATCHABLE_COLUMNS, GLOBAL_FIELDS, NAME_NFC_FIELDS, LOCAL_FIELDS,
    THAI_TZ, THAI_MONTH_NAMES, EXPORT_HEADER_LABELS, ROLE_LABELS, STATUS_LABELS,
    DEFAULT_COL_WIDTH, EXPORT_COLUMN_WIDTHS, CENTER_FIELDS, WRAP_TEXT_FIELDS,
)

service_logger = AuditLogger(service_name="STUDENT")


class BaseMixin:
    # 🌟 SELECT ร่วมของ student (students JOIN users) — ใช้ทั้ง students และ export
    BASE_STUDENT_SELECT = """
        SELECT
            s.id, s.room_id, u.id as user_id, u.discord_id, s.student_no, s.student_id,
            u.prefix, u.first_name, u.last_name, u.nickname,
            u.first_name_en, u.last_name_en, u.nickname_en, u.birthday,
            s.class_role, s.cleaning_duty, s.olympic_camp, s.portfolio, s.target_faculty,
            u.blood_group, u.shirt_size, u.food_allergy, u.congenital_disease,
            u.phone_number, u.phone_number_parent, u.phone_number_parent_relation,
            u.line_id, u.ig_username, u.email,
            u.address_house_no, u.address_road, u.address_sub_district, u.address_district, u.address_province, u.address_post_code,
            s.status, s.is_admin, s.permissions, s.identity_claimed, s.added_by, s.created_at, s.updated_at
        FROM students s
        LEFT JOIN users u ON s.user_id = u.id
    """

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

    @staticmethod
    def _parse_permissions(perms: Any) -> List[str]:
        if not perms: return []
        if isinstance(perms, list): return perms
        if isinstance(perms, str):
            try: return json.loads(perms)
            except: return []
        return []

    @staticmethod
    def _calculate_completion(row: dict) -> dict:
        expected_fields = [
            'student_id', 'prefix', 'nickname', 'birthday',
            'cleaning_duty', 'olympic_camp', 'target_faculty',
            'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease',
            'phone_number', 'phone_number_parent', 'phone_number_parent_relation',
            'line_id', 'ig_username', 'email',
            'address_house_no', 'address_road', 'address_sub_district',
            'address_district', 'address_province', 'address_post_code'
        ]
        missing = [f for f in expected_fields if not row.get(f) or str(row.get(f)).strip() == ""]
        total = len(expected_fields)
        filled = total - len(missing)
        percent = int((filled / total) * 100)
        return {"percentage": percent, "missing_fields": missing}

    @staticmethod
    async def _find_or_create_user(
        conn: asyncpg.Connection,
        first_name: str,
        last_name: str,
        first_name_en: str = "",
        last_name_en: str = "",
        nickname: str = "",
        nickname_en: str = "",
    ) -> tuple[int, bool]:
        """หา user ตาม "กุญแจตัวตน" — ชื่ออังกฤษก่อน (English-primary) ถ้าไม่มีอังกฤษ
        หรือหาไม่เจอ → fallback เป็นชื่อไทยแบบ NFC-normalized (แก้ อำ/อํา match กันไม่เจอ).

        ทั้งชื่อไทยและอังกฤษถูก normalize ก่อนเก็บ (ดู core/name_utils) เพื่อให้
        exact-match ตรงกันเสมอ.

        คืน (user_id, is_real_claimed_account):
        - is_real=True → เจอบัญชีจริงที่เจ้าตัวยืนยันแล้ว (มี google/discord/email/phone)
          caller ต้องสร้าง "คำเชิญ pending" แทนการ link ตรง ๆ (Consent Model — core/privacy.py)
        - is_real=False → เจอ ghost ชื่อเท่านั้น หรือสร้าง ghost ใหม่ → สมาชิก active ได้ทันที (ไม่มี PII)
        """
        th_first = normalize_nfc(first_name)
        th_last = normalize_nfc(last_name)
        en_first = normalize_nfc(first_name_en)
        en_last = normalize_nfc(last_name_en)
        th_nickname = normalize_nfc(nickname)
        en_nickname = normalize_nfc(nickname_en)

        async def _match(sql: str, *params) -> tuple[int, bool] | None:
            row = await conn.fetchrow(sql, *params)
            if not row:
                return None
            return (row["id"], is_real_claimed_account(dict(row)))

        if en_first or en_last:
            # 1) ชื่ออังกฤษเป็นกุญแจหลัก — ค้นแบบไม่ไวตัวพิมพ์ (LOWER) สอดคล้องกับ identity_pair
            #    ที่ใช้ normalize_en (casefold) ใน bulk_add / join_room
            hit = await _match(
                "SELECT id, google_id, discord_id, email, phone_number FROM users WHERE LOWER(first_name_en) = $1 AND LOWER(last_name_en) = $2 AND deleted_at IS NULL",
                normalize_en(first_name_en), normalize_en(last_name_en),
            )
            if hit:
                return hit
            # 2) fallback: user เก่าที่มีแต่ชื่อไทย (อังกฤษยังว่าง) — กันสร้าง user ซ้ำตอนกรอกชื่ออังกฤษทีหลัง
            if th_first or th_last:
                hit = await _match(
                    "SELECT id, google_id, discord_id, email, phone_number FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL",
                    th_first, th_last,
                )
                if hit:
                    return hit
        else:
            hit = await _match(
                "SELECT id, google_id, discord_id, email, phone_number FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL",
                th_first, th_last,
            )
            if hit:
                return hit

        new_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, nickname, first_name_en, last_name_en, nickname_en) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            th_first or None, th_last or None, th_nickname or None,
            en_first or None, en_last or None, en_nickname or None,
        )
        return (new_id, False)
