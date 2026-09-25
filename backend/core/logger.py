import json
import re
import time
import uuid
import asyncpg
from typing import Optional, Dict, Any

# === การปกปิดข้อมูลส่วนบุคคลก่อนลง audit_logs ===
# **ที่มา:** การตรวจระบบเมื่อ 2026-09-23 พบว่า `auth_service.py` ใช้ `SELECT *`
# แล้วส่งทั้งแถวเข้า `old_values` ⇒ ข้อมูลสุขภาพ/เบอร์โทร/ที่อยู่ของนักเรียน
# ถูกคัดลอกลง audit_logs หลายร้อยแถว (ตารางที่คนอ่านได้กว้างกว่าตาราง users มาก)
#
# แก้ที่ "ขอบเขตการเขียน log" ไม่ใช่แก้ที่ผู้เรียกทีละคน เพราะผู้เรียกมี 31 จุด
# และจะเพิ่มอีกในอนาคต — ด่านเดียวที่ทุกคนต้องผ่านคือที่นี่
#
# ใช้ "[REDACTED]" แทนการลบคีย์ทิ้ง เพราะ audit ยังต้องตอบได้ว่า
# "มีคนแก้ฟิลด์นี้" ซึ่งเป็นสาระของ audit — แค่ไม่ต้องรู้ค่า
REDACTED = "[REDACTED]"

# คีย์ที่ห้ามลง audit_logs เด็ดขาด — ตรงกับคอลัมน์ในตาราง users
_SENSITIVE_KEYS = frozenset({
    # สุขภาพ
    "congenital_disease", "food_allergy", "blood_group", "shirt_size",
    # ติดต่อ
    "phone_number", "phone_number_parent", "phone_number_parent_relation",
    "line_id", "ig_username",
    # ที่อยู่
    "address_house_no", "address_road", "address_sub_district",
    "address_district", "address_province", "address_post_code",
    # ส่วนตัว
    "birthday",
})

# รูปแบบชื่อคีย์ที่ถือว่าเป็นความลับ — กันคีย์ใหม่ที่ยังไม่เกิดวันนี้
# (เช่นถ้าอนาคตมี `refresh_token` หรือ `student_password` ก็ถูกปกปิดอัตโนมัติ)
_SENSITIVE_PATTERNS = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api_?key", re.IGNORECASE),
    re.compile(r"_hash$", re.IGNORECASE),
)


def _is_sensitive_key(key: Any) -> bool:
    name = str(key)
    if name in _SENSITIVE_KEYS:
        return True
    return any(p.search(name) for p in _SENSITIVE_PATTERNS)


def redact_sensitive(value: Any) -> Any:
    """คืนสำเนาของ `value` ที่แทนค่าความลับด้วย ``[REDACTED]``

    ไล่ลงไปทั้ง dict/list ที่ซ้อนกัน เพราะ payload ของ audit มีได้ทั้ง
    ``{"user": {...}}`` และ ``{"items": [{...}, {...}]}``
    """
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive_key(k) else redact_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(v) for v in value]
    return value


class AuditLogger:
    def __init__(self, service_name: str):
        self.service_name = service_name

    async def log(
        self,
        conn: asyncpg.Connection,
        action: str,
        actor_identifier: str,
        client_source: str,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        status: str = 'success',
        error_detail: Optional[str] = None,
        old_values: Optional[Dict] = None,
        new_values: Optional[Dict] = None,
        endpoint_or_command: Optional[str] = None,
        ip_address: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
        trace_id: Optional[str] = None
    ):
        # ถ้าไม่มี Trace ID ให้สร้างใหม่
        current_trace_id = trace_id or str(uuid.uuid4())

        # 🔒 ปกปิดข้อมูลส่วนบุคคลก่อนเขียน — ดูคำอธิบายที่ _SENSITIVE_KEYS ด้านบน
        # ทำที่ชั้นนี้ชั้นเดียว จึงคุมได้ทุกผู้เรียกโดยไม่ต้องพึ่งวินัยของแต่ละ service
        old_values = redact_sensitive(old_values)
        new_values = redact_sensitive(new_values)

        await conn.execute("""
            INSERT INTO audit_logs (
                trace_id, room_id, user_id, actor_identifier, client_source, 
                service_name, action, entity_type, entity_id, status, 
                error_detail, old_values, new_values, endpoint_or_command, 
                ip_address, execution_time_ms
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14, $15, $16)
        """, 
            current_trace_id, room_id, user_id, actor_identifier, client_source,
            self.service_name, action, entity_type, str(entity_id) if entity_id else None,
            status, error_detail, 
            json.dumps(old_values, default=str) if old_values else None,
            json.dumps(new_values, default=str) if new_values else None,
            endpoint_or_command, ip_address, execution_time_ms
        )