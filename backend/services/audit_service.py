"""อ่านบันทึกกิจกรรมของห้อง (`audit_logs`) — หน้าดูของผู้บริหารห้อง (P6.2)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมไม่ใช้ endpoint เดิม `GET /{target_id}/logs`
═══════════════════════════════════════════════════════════════════════════════
ตัวเดิม (`ClassroomService.get_audit_logs`) คืน 20 แถวล่าสุด ไม่มีตัวกรอง ไม่มีการ
เลื่อนหน้า และให้สิทธิ์แค่ "เป็นสมาชิกห้อง" — ใช้ตรวจย้อนไม่ได้จริง (ตาราง audit
มีเป็นแสนแถว) ตัวนี้แทนที่ด้วย:

· สิทธิ์ `VIEW_AUDIT_LOGS` (ไม่ใช่แค่สมาชิก — บันทึกนี้มี IP/User-Agent/ข้อมูลเก่า)
· ตัวกรอง service/action/status/ช่วงวันที่/คำค้น
· **keyset pagination บน `(created_at, id)`**

═══════════════════════════════════════════════════════════════════════════════
🔑 ทำไม keyset ไม่ใช่ OFFSET
═══════════════════════════════════════════════════════════════════════════════
`audit_logs` เดินโตตลอดเวลา ⇒ `OFFSET 40` ที่หน้าถัดไป **ไม่ใช่แถวเดิม** (มีแถวใหม่
แทรกหัวตารางระหว่างที่ผู้ใช้กำลังอ่าน) ทำให้เห็นรายการซ้ำหรือข้ามไปเลย. keyset
เทียบ `(created_at, id) < แถวสุดท้ายที่เห็น` จึงไม่สนว่ามีแถวใหม่แทรกแค่ไหน

⚠️ ต้องประกาศสองคีย์ ไม่ใช่ `created_at` เดียว: หลายแถวเขียนในไมโครวินาทีเดียวกัน
ได้ (`CURRENT_TIMESTAMP` = เวลาที่เริ่ม transaction) ⇒ `created_at` อย่างเดียวจะตัด
แถวที่ชนกันทิ้งเป็นช่วง ๆ. `id` (UUID) เป็นตัวตัดสินลำดับสุดท้ายที่นิ่งแล้ว

index ที่รองรับคือ `idx_audit_logs_room_created (room_id, created_at DESC, id DESC)`
จาก migration `0009` — ถ้าไม่มี ตัวกรองของห้องจะกลายเป็น seq scan ทั้งตารางทุกหน้า

═══════════════════════════════════════════════════════════════════════════════
📝 เขียน audit ของ "การดู" แค่หน้าแรก
═══════════════════════════════════════════════════════════════════════════════
endpoint เดิมเขียนแถว `VIEW` **ทุกครั้งที่เรียก** ⇒ เมื่อมีหน้าดูแบบเลื่อนหน้า
การเลื่อนผ่าน 50 หน้า = เขียน 50 แถวเข้าไปในตารางที่กำลังอ่านอยู่ (ทั้งกินที่และ
ทำให้ผู้ใช้เห็นแถวของตัวเองท่วมรายการที่อยากดู) ที่นี่จึงเขียนแถว `VIEW` **เฉพาะ
เมื่อ `cursor` ว่าง** = หนึ่งครั้งต่อการเปิดหน้า/เริ่มกรองใหม่ ซึ่งเพียงพอสำหรับสืบเหตุ
ว่า "ใครเข้ามาดูบันทึกนี้ เมื่อไร" โดยไม่ปนเปื้อนตัวเอง

⚠️ บันทึกแถว `VIEW` นี้ **หลัง** อ่านข้อมูลแล้ว และ **ไม่** อยู่ในรายการที่เพิ่งอ่าน
⇒ ไม่ทำให้ cursor เพี้ยน

═══════════════════════════════════════════════════════════════════════════════
🕵️ ข้อมูลส่วนตัว
═══════════════════════════════════════════════════════════════════════════════
`old_values`/`new_values` คืนครบตามที่เก็บ (ปัญหา PII ค้างจาก audit 2026-09-23 —
`purge_audit_pii` ยังไม่อนุมัติ) สิทธิ์ `VIEW_AUDIT_LOGS` จึงถูกให้เฉพาะผู้บริหารห้อง
ไม่ใช่สมาชิกทั่วไป
"""
from __future__ import annotations

import base64
import binascii
import logging
import time
from datetime import date, datetime
from typing import Optional
from uuid import UUID

import asyncpg

from core.exceptions import ValidationError
from core.logger import AuditLogger
from core.rbac import require_permission

audit_logger = AuditLogger(service_name="AUDIT")

VIEW_PERMISSION = "VIEW_AUDIT_LOGS"

DEFAULT_LIMIT = 30
MAX_LIMIT = 100

# ขอบเขตการค้นหา: คอลัมน์ที่ผู้ใช้พิมพ์จับได้ (ไม่ค้นใน old/new_values —
# JSON ขนาดใหญ่ค้นช้าและสร้าง false positive เยอะ)
_SEARCH_SQL = """(
    a.actor_identifier ILIKE $7 ESCAPE '\\'
    OR a.endpoint_or_command ILIKE $7 ESCAPE '\\'
    OR a.entity_id ILIKE $7 ESCAPE '\\'
    OR a.error_detail ILIKE $7 ESCAPE '\\'
)"""


def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """ถอด cursor — ค่าที่พิมพ์มือ/ตัดขาดต้องได้ 400 ไม่ใช่ 500"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        ts_part, id_part = raw.split("|", 1)
        return datetime.fromisoformat(ts_part), UUID(id_part)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError("cursor ไม่ถูกต้อง — ให้ใช้ค่าที่ API ส่งกลับมาเท่านั้น") from exc


def _escape_like(value: str) -> str:
    """ILIKE ใช้ `%`/`_` เป็นไวลด์การ์ด — ผู้ใช้พิมพ์ `%` ต้องค้นหา `%` จริง ๆ"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_logs(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    client_source: str,
    actor_identifier: str,
    service_name: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = DEFAULT_LIMIT,
    cursor: Optional[str] = None,
) -> dict:
    """คืน `{items, next_cursor, has_more}` ของบันทึกกิจกรรมในห้องเดียว"""
    start_time = time.time()
    safe_limit = min(max(int(limit), 1), MAX_LIMIT)

    cursor_ts: Optional[datetime] = None
    cursor_id: Optional[UUID] = None
    if cursor:
        cursor_ts, cursor_id = _decode_cursor(cursor)

    search_pattern = f"%{_escape_like(search.strip())}%" if search and search.strip() else None

    async with pool.acquire() as conn:
        await require_permission(conn, room_id, user_id, VIEW_PERMISSION)

        # ⚠️ asyncpg ต้องรู้ชนิดของ $n แม้ค่าจะเป็น None ⇒ ใส่ cast ทุกพารามิเตอร์
        #    (`($1::text IS NULL OR ...)` = "ถ้าไม่ได้กรอง ก็ให้ผ่านทั้งหมด")
        rows = await conn.fetch(
            f"""
            SELECT
                a.id, a.trace_id, a.user_id, a.actor_identifier,
                NULLIF(TRIM(CONCAT_WS(' ', u.prefix, u.first_name, u.last_name)), '') AS actor_name,
                a.client_source, a.service_name, a.action,
                a.entity_type, a.entity_id, a.status, a.error_detail,
                a.old_values, a.new_values, a.endpoint_or_command,
                a.ip_address, a.user_agent, a.execution_time_ms, a.created_at
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.room_id = $1
              AND ($2::text IS NULL OR a.service_name = $2)
              AND ($3::text IS NULL OR a.action = $3)
              AND ($4::text IS NULL OR a.status = $4)
              -- ช่วงวันที่เป็น "วันตามเวลาไทย" ⇒ เทียบกับ midnight Bangkok
              -- ไม่ใช่ UTC (ถ้าใช้ UTC แถว 00:00–07:00 ไทยจะตกไปวันก่อนหน้า)
              AND ($5::date IS NULL
                   OR a.created_at >= ($5::date::timestamp AT TIME ZONE 'Asia/Bangkok'))
              AND ($6::date IS NULL
                   OR a.created_at < (($6::date + 1)::timestamp AT TIME ZONE 'Asia/Bangkok'))
              AND ($7::text IS NULL OR {_SEARCH_SQL})
              AND ($8::timestamptz IS NULL
                   OR (a.created_at, a.id) < ($8::timestamptz, $9::uuid))
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT $10
            """,
            room_id, service_name, action, status, date_from, date_to,
            search_pattern, cursor_ts, cursor_id, safe_limit + 1,
        )

        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]
        next_cursor = (
            _encode_cursor(page[-1]["created_at"], page[-1]["id"]) if has_more and page else None
        )

        # 📝 ดูรายละเอียด "ทำไมเขียนแค่หน้าแรก" ที่หัวไฟล์
        if cursor is None:
            exec_time = int((time.time() - start_time) * 1000)
            await audit_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=room_id,
                entity_type="AUDIT_LOG", endpoint_or_command="list_audit_logs",
                execution_time_ms=exec_time,
            )

        return {
            "items": [dict(r) for r in page],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }


async def get_options(
    pool: asyncpg.Pool, *, room_id: int, user_id: int
) -> dict:
    """ค่าที่มีจริงในบันทึกของห้องนี้ — เติม dropdown โดยไม่ต้องเดาจากโค้ด

    ⚠️ จำกัดที่ 90 วันล่าสุด: ถ้าไม่จำกัด ตารางที่โตเป็นแสนแถวจะต้อง DISTINCT
    ทั้งตารางทุกครั้งที่เปิดหน้า ⇒ ช้ากว่าการดูข้อมูลที่ต้องการเสียอีก
    (ตัวกรองวันที่ของผู้ใช้ยังเลือกช่วงไหนก็ได้ — อันนี้จำกัดแค่รายการตัวเลือก)
    """
    async with pool.acquire() as conn:
        await require_permission(conn, room_id, user_id, VIEW_PERMISSION)

        service_names = await conn.fetch(
            """
            SELECT DISTINCT service_name FROM audit_logs
            WHERE room_id = $1 AND created_at >= NOW() - INTERVAL '90 days'
            ORDER BY service_name
            """,
            room_id,
        )
        actions = await conn.fetch(
            """
            SELECT DISTINCT action FROM audit_logs
            WHERE room_id = $1 AND created_at >= NOW() - INTERVAL '90 days'
            ORDER BY action
            """,
            room_id,
        )
        statuses = await conn.fetch(
            """
            SELECT DISTINCT status FROM audit_logs
            WHERE room_id = $1 AND status IS NOT NULL
              AND created_at >= NOW() - INTERVAL '90 days'
            ORDER BY status
            """,
            room_id,
        )

    return {
        "service_names": [r["service_name"] for r in service_names],
        "actions": [r["action"] for r in actions],
        "statuses": [r["status"] for r in statuses],
    }
