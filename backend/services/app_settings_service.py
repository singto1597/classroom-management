"""ตั้งค่าของห้อง (`app_settings`) — รอบนี้มี quiet hours เป็นตัวแรก

═══════════════════════════════════════════════════════════════════════════════
🌙 quiet hours — ทำไมระดับห้อง ไม่ใช่ระดับคน
═══════════════════════════════════════════════════════════════════════════════
หนึ่งบัญชีอยู่ได้หลายห้อง และ "เวลางดรบกวน" ของนักเรียนคือเวลาของครอบครัว
ไม่ใช่ของห้องใดห้องหนึ่ง ⇒ ผู้ดูแลห้องเป็นคนกำหนด (มี `MANAGE_CLASSROOM_SETTINGS`)
และค่าที่ใช้ตัดสินใจตอนส่ง push คือ **ค่าของห้องที่แจ้งเตือนนั้นสังกัด**

═══════════════════════════════════════════════════════════════════════════════
⏰ กติกาการคิดเวลา (ล็อกด้วยเทสต์)
═══════════════════════════════════════════════════════════════════════════════
1. **ทุกอย่างคิดเป็น Asia/Bangkok** ไม่ใช้เวลาของเซิร์ฟเวอร์ (container เป็น UTC)
2. `start == end` = **ปิดฟีเจอร์** (ไม่ใช่ "เงียบ 24 ชั่วโมง" — เขียนให้ผิดง่ายมาก)
3. ข้ามเที่ยงคืนได้ (`22:00 → 07:00`): เงียบช่วง [22:00, 24:00) ∪ [00:00, 07:00)
4. `enabled = false` = ไม่เงียบเลย ไม่ว่า start/end เป็นอะไร
5. ค่าที่อ่านไม่ได้ (JSON เพี้ยน/รูปแบบเวลาไม่ถูก) ⇒ **ถือว่าไม่เงียบ**
   ปลอดภัยกว่าเลือกทางที่ทำให้แจ้งเตือนหายเงียบ ๆ ทั้งห้อง
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

import asyncpg

from core.exceptions import ValidationError

logger = logging.getLogger("API_APP_SETTINGS")

QUIET_HOURS_KEY = "quiet_hours"

BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")

_DEFAULT_QUIET_HOURS: dict[str, Any] = {
    "enabled": False,
    "start": "22:00",
    "end": "07:00",
}

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

SETTING_KEYS = (QUIET_HOURS_KEY,)


def _parse_hhmm(value: object) -> Optional[time]:
    if not isinstance(value, str):
        return None
    match = _HHMM_RE.match(value)
    if match is None:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def normalize_quiet_hours(value: object) -> dict[str, Any]:
    """แปลงค่า JSONB เป็นรูปแบบที่ใช้ตัดสินใจได้ — ค่าที่พังจะถูกกลบเป็น "ไม่เงียบ"

    คืน dict ที่มี `enabled`, `start`, `end` ครบเสมอ (ผู้เรียกไม่ต้องเช็ค key)
    """
    raw = value if isinstance(value, dict) else {}
    start = _parse_hhmm(raw.get("start"))
    end = _parse_hhmm(raw.get("end"))

    # เงื่อนไขปิด: ผู้ใช้ปิดเอง / เวลาอ่านไม่ได้ / start == end
    enabled = bool(raw.get("enabled")) and start is not None and end is not None and start != end

    return {
        "enabled": enabled,
        "start": raw.get("start") if start is not None else _DEFAULT_QUIET_HOURS["start"],
        "end": raw.get("end") if end is not None else _DEFAULT_QUIET_HOURS["end"],
    }


def is_quiet_at(quiet_hours: object, moment: datetime) -> bool:
    """`moment` อยู่ในช่วงเงียบหรือไม่ (ตีความ `moment` เป็นเวลาไทยเสมอ)"""
    config = normalize_quiet_hours(quiet_hours)
    if not config["enabled"]:
        return False

    start = _parse_hhmm(config["start"])
    end = _parse_hhmm(config["end"])
    if start is None or end is None:  # pragma: no cover — normalize กลบไปแล้ว
        return False

    local = moment.astimezone(BANGKOK).time()
    if start < end:
        return start <= local < end
    # ข้ามเที่ยงคืน: [start, 24:00) ∪ [00:00, end)
    return local >= start or local < end


def quiet_hours_end(quiet_hours: object, moment: datetime) -> Optional[datetime]:
    """ถ้าตอนนี้อยู่ในช่วงเงียบ คืน **เวลา UTC ที่คิวเปิด** ไม่งั้นคืน None

    ใช้โดย worker เพื่อเลื่อน `next_attempt_at` — ไม่ใช่การทิ้งแถว
    """
    if not is_quiet_at(quiet_hours, moment):
        return None

    config = normalize_quiet_hours(quiet_hours)
    end = _parse_hhmm(config["end"])
    if end is None:  # pragma: no cover
        return None

    local_now = moment.astimezone(BANGKOK)
    local_end = local_now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if local_end <= local_now:
        local_end += timedelta(days=1)
    return local_end.astimezone(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# อ่าน/เขียน
# ═════════════════════════════════════════════════════════════════════════════
def decode_setting(value: object) -> object:
    """ถอดค่า JSONB ที่ asyncpg คืนมา

    ⚠️ asyncpg **ไม่ได้ถอด JSONB ให้เอง** ถ้าไม่ได้ลง codec ตอน create_pool
    ⇒ ค่าที่หลุดไปถึงตรรกะจะเป็น `str` และ `isinstance(value, dict)` เป็น False
    เงียบ ๆ (เจอมาแล้วกับ quiet hours: ตั้งค่าไว้ถูก แต่ worker ไม่เคยเลื่อนส่งเลย)
    ⇒ ทุกจุดที่อ่าน app_settings ต้องผ่านฟังก์ชันนี้
    """
    if isinstance(value, str):
        import json

        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


async def get_setting(
    conn: asyncpg.Connection, *, room_id: int, key: str
) -> Optional[dict[str, Any]]:
    value = await conn.fetchval(
        "SELECT value FROM app_settings WHERE room_id = $1 AND key = $2",
        room_id,
        key,
    )
    if value is None:
        return None
    decoded = decode_setting(value)
    return dict(decoded) if isinstance(decoded, dict) else None


async def get_quiet_hours(
    conn: asyncpg.Connection, *, room_id: int
) -> dict[str, Any]:
    """ค่าที่ใช้ตัดสินใจจริง — ไม่มีแถว/อ่านไม่ได้ ⇒ ค่าเริ่มต้น (ไม่เงียบ)"""
    stored = await get_setting(conn, room_id=room_id, key=QUIET_HOURS_KEY)
    return normalize_quiet_hours(stored if stored is not None else _DEFAULT_QUIET_HOURS)


async def set_quiet_hours(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    enabled: bool,
    start: str,
    end: str,
    updated_by: Optional[int],
) -> dict[str, Any]:
    """บันทึกช่วงงดรบกวน — ตรวจรูปแบบ HH:MM ที่นี่ (ไม่ปล่อยให้ไปตายที่ DB)

    `start == end` **ไม่ใช่ error**: เป็นวิธีมาตรฐานที่ UI ใช้แทนสวิตช์ปิด
    ⇒ เก็บตามที่ส่งมา แต่ `normalize_quiet_hours` จะตีความเป็นปิด
    """
    if _parse_hhmm(start) is None:
        raise ValidationError("เวลาเริ่มต้องอยู่ในรูปแบบ HH:MM (00:00–23:59)")
    if _parse_hhmm(end) is None:
        raise ValidationError("เวลาสิ้นสุดต้องอยู่ในรูปแบบ HH:MM (00:00–23:59)")

    value = {"enabled": bool(enabled), "start": start, "end": end}
    import json

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (room_id, key, value, updated_by, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, NOW())
            ON CONFLICT (room_id, key)
            DO UPDATE SET value = EXCLUDED.value,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = NOW()
            """,
            room_id,
            QUIET_HOURS_KEY,
            json.dumps(value),
            updated_by,
        )
    return normalize_quiet_hours(value)
