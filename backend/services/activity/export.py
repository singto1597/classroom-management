"""Excel export รายชื่อกิจกรรม (openpyxl)"""
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
import math
import re
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from .constants import (
    THAI_TZ, THAI_MONTH_NAMES, EXPORT_HEADER_LABELS, ACTIVITY_META_LABELS,
    PROFILE_FIELDS, PROFILE_FIELD_LABELS, ROLE_TYPE_LABELS, PARTICIPANT_STATUS_LABELS,
    ACTIVITY_STATUS_LABELS, ACTIVITY_STATUS_COLORS, PARTICIPANT_STATUS_COLORS,
    EXPORT_FIELD_WIDTHS, DEFAULT_EXPORT_COL_WIDTH,
)


class ExportMixin:
    @staticmethod
    def _sanitize_filename(title: Any) -> str:
        """แปลงชื่อกิจกรรมเป็นชื่อไฟล์ที่ปลอดภัย: ตัดอักขระต้องห้าม + กันยาวเกิน 80 ตัว
        (ใช้ตั้งชื่อไฟล์ Excel export แทน activity_<id>_participants.xlsx)"""
        cleaned = re.sub(r'[\\/:*?"<>|]', "_", str(title or ""))
        cleaned = re.sub(r"\s+", "_", cleaned.strip(" _"))
        return cleaned[:80] or "กิจกรรม"

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

    @staticmethod
    def _format_custom_fields(custom_fields: Any) -> str:
        """participant.metadata.custom_fields = [{label, value}] → 'หัวข้อ: ค่า' ต่อบรรทัด
        (กัน value ที่เป็น dict/list หลุดเป็น raw)"""
        if not isinstance(custom_fields, list):
            return ""
        lines = []
        for entry in custom_fields:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "")).strip()
            value = entry.get("value")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            value_str = str(value).strip() if value is not None else ""
            if label and value_str:
                lines.append(f"{label}: {value_str}")
        return "\n".join(lines)

    @staticmethod
    def _format_list_value(value: Any) -> str:
        """list → คั่นด้วย ' / ' (ใช้กับ positions, tags, required_fields)"""
        if isinstance(value, (list, tuple)):
            items = [str(v).strip() for v in value if str(v).strip()]
            return " / ".join(items) if items else ""
        return str(value) if value is not None else ""

    @classmethod
    def _format_activity_meta_lines(cls, meta: dict) -> str:
        """
        สรุป 'ข้อมูลเพิ่มเติม' ของกิจกรรมแบบ readable (ไม่แสดงคีย์ดิบ)
        - custom_fields → 'หัวข้อ: ค่า' ต่อบรรทัด
        - คีย์เก่าที่รู้จัก (location_name/url, agenda, tags) + positions/required_fields → label ไทย
        - คีย์อื่น ๆ → เก็บไว้ในกลุ่ม 'อื่นๆ' (กันข้อมูลเก่าหาย แต่ไม่ dump คีย์ดิบเดี่ยว ๆ)
        """
        if not meta:
            return "—"

        lines: List[str] = []

        # 1) custom_fields (ข้อมูลเพิ่มเติมแบบ friendly) — มาก่อนเสมอ
        custom_lines = cls._format_custom_fields(meta.get("custom_fields"))
        if custom_lines:
            lines.append(custom_lines)

        # 2) คีย์เก่า/คีย์ภายในที่รู้จัก → label ไทย (กันซ้ำกับ custom_fields ที่ mapping แล้ว)
        known_keys = ["location_name", "location_url", "agenda", "tags", "positions", "required_fields", "dynamic_fields"]
        seen_labels = set()
        for key in known_keys:
            if key not in meta:
                continue
            value = meta.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            # ถ้า key นี้ถูก dual-write จาก custom_fields แล้ว ให้ข้าม (ป้องกันซ้ำ)
            label = ACTIVITY_META_LABELS.get(key, key)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            if key in ("tags", "positions", "required_fields"):
                formatted = cls._format_list_value(value)
                if key == "required_fields":
                    # แปลงเป็นชื่อไทยของฟิลด์ที่เก็บต่อคน (รวม dynamic fields: df_<n> → label ที่ผู้ใช้ตั้ง)
                    dyn_labels = {}
                    for d in meta.get("dynamic_fields") or []:
                        if isinstance(d, dict):
                            dk = str(d.get("key", "")).strip()
                            dl = str(d.get("label", "")).strip()
                            if dk and dl:
                                dyn_labels[dk] = dl
                    labels = []
                    for item in value if isinstance(value, (list, tuple)) else []:
                        item_str = str(item).strip()
                        if not item_str:
                            continue
                        labels.append(EXPORT_HEADER_LABELS.get(item_str, dyn_labels.get(item_str, item_str)))
                    formatted = " / ".join(labels)
                if formatted:
                    lines.append(f"{label}: {formatted}")
            elif key == "dynamic_fields":
                # 🌟 Dynamic Fields (ฟิลด์ที่ผู้จัดการกิจกรรมสร้างเอง) → แสดง label ไทย ไม่ใช่คีย์ df_<n>
                labels = []
                for d in value if isinstance(value, list) else []:
                    if not isinstance(d, dict):
                        continue
                    lbl = str(d.get("label", "")).strip()
                    if lbl:
                        labels.append(lbl)
                formatted = " / ".join(labels)
                if formatted:
                    lines.append(f"{label}: {formatted}")
            elif key == "location_url":
                lines.append(f"{label}: {value}")
            else:
                lines.append(f"{label}: {value}")

        # 3) คีย์อื่น ๆ ที่เหลือ (กิจกรรมเก่า) → รวมเป็น 'อื่นๆ' ไม่ dump คีย์ดิบทีละตัว
        remaining = {}
        for k, v in meta.items():
            if k == "custom_fields" or k in ACTIVITY_META_LABELS:
                continue
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            remaining[k] = v
        if remaining:
            parts = []
            for k, v in remaining.items():
                if isinstance(v, (dict, list)):
                    v_str = json.dumps(v, ensure_ascii=False, default=str)
                else:
                    v_str = str(v)
                parts.append(f"{k}: {v_str}")
            lines.append(f"อื่นๆ: {' ; '.join(parts)}")

        return "\n".join(lines) if lines else "—"

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
                    # 🌟 เพิ่มคอลัมน์ 'ข้อมูลเพิ่มเติม' (custom_fields ต่อคน) เฉพาะเมื่อมีใครสักคนกรอกแล้ว
                    # (กันคอลัมน์ว่างเปล่าเข้าไปขยาย header — เทสเดิมไม่มี custom_fields → ไม่กระทบ)
                    has_custom_fields = any(
                        cls._format_custom_fields((p.get("metadata") or {}).get("custom_fields"))
                        for p in participants
                    )
                    if has_custom_fields and "custom_fields" not in fields:
                        fields.append("custom_fields")

                    # 🌟 คอลัมน์ Dynamic Fields — ฟิลด์ที่ผู้จัดการกิจกรรมสร้างเอง (activities.metadata.dynamic_fields)
                    # header = label ที่ผู้ใช้ตั้ง (ไม่ใช่คีย์ df_<n>); ค่าอ่านจาก participant.metadata[df_<n>]
                    # เฉพาะเมื่อ activity มี defs — activity เก่าไม่มี → ไม่เพิ่มคอลัมน์ ไม่แตกเทสเดิม
                    dynamic_labels: Dict[str, str] = {}
                    dynamic_fields_defs = activity.get("metadata", {}).get("dynamic_fields") or []
                    if isinstance(dynamic_fields_defs, list):
                        for d in dynamic_fields_defs:
                            if not isinstance(d, dict):
                                continue
                            k = str(d.get("key", "")).strip()
                            lbl = str(d.get("label", "")).strip()
                            if k and lbl:
                                dynamic_labels[k] = lbl
                        for k in dynamic_labels:
                            if k not in fields:
                                fields.append(k)

                    room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", target_room_id)
                    room_name = room["room_name"] if room else f"ห้อง #{target_room_id}"

                    wb = Workbook()
                    # ---- Sheet 1: สรุป ----
                    ws_summary = wb.active
                    ws_summary.title = "สรุป"
                    ws_summary.sheet_view.showGridLines = False
                    ws_summary.column_dimensions["A"].width = 30
                    ws_summary.column_dimensions["B"].width = 34

                    HEADER_FILL = PatternFill("solid", fgColor="8B5CF6")   # ม่วง (ธีมกิจกรรม)
                    TOTAL_FILL = PatternFill("solid", fgColor="EDE9FE")    # ม่วงอ่อน (แถวรวม)
                    SECTION_FILL = PatternFill("solid", fgColor="F5F3FF")
                    white_bold = Font(bold=True, color="FFFFFF")
                    title_font = Font(bold=True, size=18, color="0F172A")
                    THIN_BORDER = Border(
                        left=Side(style="thin", color="E2E8F0"),
                        right=Side(style="thin", color="E2E8F0"),
                        top=Side(style="thin", color="E2E8F0"),
                        bottom=Side(style="thin", color="E2E8F0"),
                    )

                    # หัวข้อ + วันที่ (merge กลางหน้า)
                    ws_summary.merge_cells("A1:B1")
                    ws_summary["A1"] = f"สรุปกิจกรรม — {room_name}"
                    ws_summary["A1"].font = title_font
                    ws_summary["A1"].alignment = Alignment(horizontal="center", vertical="center")
                    ws_summary.row_dimensions[1].height = 34

                    ws_summary.merge_cells("A2:B2")
                    ws_summary["A2"] = f"สร้างเมื่อ {datetime.now(THAI_TZ).strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)"
                    ws_summary["A2"].font = Font(color="64748B", size=10)
                    ws_summary["A2"].alignment = Alignment(horizontal="center", vertical="center")

                    def _section(row, label):
                        ws_summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
                        cell = ws_summary.cell(row=row, column=1, value=label)
                        cell.font = Font(bold=True, size=12, color="FFFFFF")
                        cell.fill = HEADER_FILL
                        cell.alignment = Alignment(vertical="center")
                        ws_summary.row_dimensions[row].height = 24
                        ws_summary.cell(row=row, column=2).fill = HEADER_FILL
                        for col in (1, 2):
                            ws_summary.cell(row=row, column=col).border = THIN_BORDER

                    def _row(row, label, value):
                        c1 = ws_summary.cell(row=row, column=1, value=label)
                        c1.font = Font(bold=True, color="0F172A")
                        c1.alignment = Alignment(vertical="center")
                        c2 = ws_summary.cell(row=row, column=2, value=value)
                        c2.alignment = Alignment(vertical="center")
                        ws_summary.row_dimensions[row].height = 22
                        for col in (1, 2):
                            ws_summary.cell(row=row, column=col).border = THIN_BORDER

                    _section(4, "ข้อมูลกิจกรรม")
                    _row(5, "ชื่อกิจกรรม", activity["title"])
                    _row(6, "วันที่", cls._format_buddhist_date(activity["activity_date"]))
                    _row(7, "ชั่วโมงฐาน", float(activity["base_hours"] or 0))
                    # 🌟 สถานะกิจกรรม → ภาษาไทย (ACTIVITY_STATUS_LABELS) ไม่ใช่สถานะ participant
                    act_status = str(activity["status"] or "")
                    _row(8, "สถานะ", ACTIVITY_STATUS_LABELS.get(act_status, act_status))
                    act_status_color = ACTIVITY_STATUS_COLORS.get(act_status)
                    if act_status_color:
                        ws_summary.cell(row=8, column=2).font = Font(bold=True, color=act_status_color)
                    _row(9, "จำนวนผู้เข้าร่วม", len(participants))

                    _section(11, "รายละเอียด")
                    desc_text = str(activity.get("description") or "—")
                    _row(12, "คำอธิบาย", desc_text)
                    ws_summary.cell(row=12, column=2).alignment = Alignment(vertical="top", wrap_text=True)
                    # merged ไม่ auto-fit → คำนวณความสูงคร่าว ๆ (อักษรไทย ≈ 1.2 จุด/ตัว, ความกว้าง B = 34)
                    ws_summary.row_dimensions[12].height = max(22, math.ceil(len(desc_text) / 30) * 15)

                    _section(14, "ข้อมูลเพิ่มเติมของกิจกรรม")
                    # 🌟 แสดงเป็น readable label ไทย (ไม่ dump คีย์ดิบ) — custom_fields / คีย์เก่า / positions / required_fields
                    meta_lines = cls._format_activity_meta_lines(activity.get("metadata") or {})
                    ws_summary.cell(row=15, column=1, value=meta_lines)
                    ws_summary.merge_cells(start_row=15, start_column=1, end_row=15, end_column=2)
                    ws_summary.cell(row=15, column=1).alignment = Alignment(vertical="top", wrap_text=True)
                    # merged cell ต้องตั้งความสูงเอง (Excel ไม่ auto-fit บน merged)
                    ws_summary.row_dimensions[15].height = max(22, (meta_lines.count("\n") + 1) * 15)

                    # ---- Sheet 2: รายชื่อผู้เข้าร่วม ----
                    ws_data = wb.create_sheet("รายชื่อผู้เข้าร่วม")
                    ws_data.sheet_view.showGridLines = False
                    # header: dynamic field ใช้ label ที่ผู้ใช้ตั้ง (dynamic_labels) — ไม่ใช่คีย์ df_<n>
                    ws_data.append([EXPORT_HEADER_LABELS.get(f, dynamic_labels.get(f, f)) for f in fields])
                    for idx, field in enumerate(fields, start=1):
                        # 🌟 ความกว้างต่อคอลัมน์ (เลขที่แคบ, custom_fields กว้าง) — ไม่กว้างเท่ากันหมดแล้ว
                        ws_data.column_dimensions[get_column_letter(idx)].width = EXPORT_FIELD_WIDTHS.get(
                            field, DEFAULT_EXPORT_COL_WIDTH
                        )
                        cell = ws_data.cell(row=1, column=idx)
                        cell.fill = HEADER_FILL
                        cell.font = white_bold
                        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                        cell.border = Border(
                            bottom=Side(style="medium", color="8B5CF6"),
                            top=Side(style="thin", color="E2E8F0"),
                            left=Side(style="thin", color="E2E8F0"),
                            right=Side(style="thin", color="E2E8F0"),
                        )
                    ws_data.row_dimensions[1].height = 32

                    # แหล่งข้อมูลของแต่ละคอลัมน์ (DRY ผ่าน _field_reader):
                    # - base fields (student_no/ชื่อ/role) → อ่านจาก record + แปลง label
                    # - Type A (profile) → อ่านจาก record ตรง ๆ (JOIN users)
                    # - Type B (metadata) → อ่านจาก participant.metadata
                    BASE_READERS: Dict[str, Any] = {
                        "student_no": lambda p: p["student_no"],
                        "first_name": lambda p: p["first_name"],
                        "last_name": lambda p: p["last_name"],
                        "first_name_en": lambda p: p.get("first_name_en"),
                        "last_name_en": lambda p: p.get("last_name_en"),
                        "nickname_en": lambda p: p.get("nickname_en"),
                        "role_type": lambda p: cls._translate_label("role_type", p["role_type"]),
                        "role_detail": lambda p: p["role_detail"],
                        "earned_hours": lambda p: float(p["earned_hours"] or 0),
                        "status": lambda p: cls._translate_label("status", p["status"]),
                    }
                    ZEBRA_FILL = PatternFill("solid", fgColor="F5F3FF")
                    WRAP_FIELDS = {"custom_fields", "role_detail"}  # ฟิลด์ที่เนื้อหายาว → ตัดบรรทัด
                    is_super_admin = settings.SUPER_ADMIN_ID and user_id and int(user_id) == int(settings.SUPER_ADMIN_ID)
                    for i, p in enumerate(participants, start=2):
                        final = []
                        # 🛡️ Consent Model: participant ที่ยังไม่ยืนยันตัวตน → Type A (profile PII) เป็น ""
                        p_can_view_type_a = can_view_activity_pii(
                            requester_user_id=user_id,
                            target_user_id=p.get("user_id"),
                            identity_claimed=p.get("identity_claimed"),
                            is_super_admin=is_super_admin,
                        )
                        for field in fields:
                            if field in BASE_READERS:
                                final.append(BASE_READERS[field](p))
                            elif field == "custom_fields":
                                # 🌟 ข้อมูลเพิ่มเติมต่อคน → 'หัวข้อ: ค่า' (ไม่ใช่ raw array)
                                final.append(cls._format_custom_fields((p.get("metadata") or {}).get("custom_fields")))
                            else:
                                reader = cls._field_reader(field)
                                val = reader(p)
                                if field in PROFILE_FIELDS and not p_can_view_type_a:
                                    final.append("")   # 🔒 PII ของคนที่ยังไม่ยืนยันตัวตน — ไม่ dump ลงไฟล์
                                elif val is None or (isinstance(val, str) and not val.strip()):
                                    final.append("")
                                else:
                                    final.append(cls._translate_label(field, val))
                        ws_data.append(final)
                        for col_idx in range(1, len(fields) + 1):
                            cell = ws_data.cell(row=i, column=col_idx)
                            field = fields[col_idx - 1]
                            cell.border = THIN_BORDER
                            if field == "student_no":
                                cell.alignment = Alignment(horizontal="center", vertical="center")
                            elif field == "earned_hours":
                                cell.alignment = Alignment(horizontal="right", vertical="center")
                                if isinstance(cell.value, (int, float)):
                                    cell.number_format = "0.##"
                            elif field in WRAP_FIELDS:
                                cell.alignment = Alignment(vertical="top", wrap_text=True)
                            else:
                                cell.alignment = Alignment(vertical="center")
                            if field == "status":
                                # 🌟 แต้มสีสถานะเข้าร่วม (confirmed/attended/cancelled) ให้อ่านง่าย
                                status_color = PARTICIPANT_STATUS_COLORS.get(str(p["status"]))
                                if status_color:
                                    cell.font = Font(bold=True, color=status_color)
                            if i % 2 == 0:
                                cell.fill = ZEBRA_FILL
                    ws_data.freeze_panes = "A2"

                    # 🌟 AutoFilter (กรองหัวตาราง) — เฉพาะ header + แถวข้อมูล (ไม่รวมแถวรวม)
                    last_data_row = 1 + len(participants)
                    ws_data.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{last_data_row}"

                    # 🌟 แถวสรุปท้ายตาราง: รวมผู้เข้าร่วม
                    total_row = last_data_row + 1
                    merge_to = min(len(fields), 6)
                    ws_data.cell(row=total_row, column=1, value=f"รวมผู้เข้าร่วม: {len(participants)} คน")
                    if merge_to > 1:
                        ws_data.merge_cells(
                            start_row=total_row, start_column=1,
                            end_row=total_row, end_column=merge_to,
                        )
                    tc = ws_data.cell(row=total_row, column=1)
                    tc.font = Font(bold=True, color="0F172A")
                    tc.fill = TOTAL_FILL
                    tc.alignment = Alignment(horizontal="center", vertical="center")
                    ws_data.row_dimensions[total_row].height = 24
                    for col_idx in range(1, len(fields) + 1):
                        total_cell = ws_data.cell(row=total_row, column=col_idx)
                        total_cell.border = Border(
                            top=Side(style="medium", color="8B5CF6"),
                            left=Side(style="thin", color="E2E8F0"),
                            right=Side(style="thin", color="E2E8F0"),
                            bottom=Side(style="thin", color="E2E8F0"),
                        )
                        if col_idx > 1 and col_idx <= merge_to:
                            total_cell.fill = TOTAL_FILL

                    output = io.BytesIO()
                    wb.save(output)
                    output.seek(0)
                    # 🌟 ชื่อไฟล์ใช้ชื่อกิจกรรม (ไม่ใช่ activity_<id>_participants.xlsx) — router อ่านผ่าน attribute
                    output.filename = f"{cls._sanitize_filename(activity['title'])}_รายชื่อผู้เข้าร่วม.xlsx"

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
