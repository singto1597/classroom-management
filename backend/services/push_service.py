"""Web Push — ทะเบียนอุปกรณ์ + การส่งจริงผ่าน VAPID

═══════════════════════════════════════════════════════════════════════════════
📦 สิ่งที่ส่งได้และไม่ได้
═══════════════════════════════════════════════════════════════════════════════
ได้: หัวข้อ/เนื้อหาย่อ/url/tag — payload ถูกเข้ารหัสต่ออุปกรณ์ (http-ece) อยู่แล้ว
ไม่ได้: ข้อมูลที่ไม่อยากให้ใครถือเครื่องอ่าน — **ห้ามใส่ข้อมูลการเงินละเอียด**
         ให้ส่งแค่ "มีใบเสร็จใหม่" แล้วให้ผู้ใช้เปิดแอป ซึ่งมีการตรวจสิทธิ์

═══════════════════════════════════════════════════════════════════════════════
🏷️ การจัดประเภทผลการส่ง (ตัวนับต้องแยกให้ออก)
═══════════════════════════════════════════════════════════════════════════════
    sent    ส่งสำเร็จ
    gone    อุปกรณ์หายแล้ว (404/410) ⇒ **soft-delete subscription ทันที**
    dropped ทิ้งถาวร (413 payload ใหญ่ / 4xx ที่ไม่ใช่ 429 / ครบจำนวนครั้ง)
    retry   ลองใหม่ได้ (5xx / 429 / network / payload เข้ารหัสพัง)
            ⚠️ `binascii.Error` มาจากคีย์อุปกรณ์ที่เพี้ยน — ถ้าปล่อยให้ retry
               ไม่มีที่สิ้นสุด แถวจะค้างในคิวตลอดกาล ⇒ มีเพดาน attempts
"""

from __future__ import annotations

import binascii
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import asyncpg

from core.config import settings

logger = logging.getLogger("API_PUSH")

# เพดานการลอง — เกินกว่านี้ = dropped (ไม่ปล่อยให้แถวค้างตลอดกาล)
MAX_ATTEMPTS = 5

# backoff: 30 วิ, 1 นาที, 2 นาที, 4 นาที (เพดาน 30 นาที)
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 1800


def push_enabled() -> bool:
    """push พร้อมใช้เฉพาะเมื่อตั้งคีย์ VAPID ครบ — ไม่ครบ = ปิดทั้งระบบอย่างสุภาพ"""
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def backoff_delay(attempts: int) -> timedelta:
    seconds = min(BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_MAX_SECONDS)
    return timedelta(seconds=seconds)


def build_payload(notification: asyncpg.Record) -> dict[str, Any]:
    """payload ที่ service worker จะเอาไปแสดง — เก็บให้เล็ก (เบราว์เซอร์จำกัด ~4KB)"""
    return {
        "id": notification["id"],
        "title": notification["title"],
        "body": notification["body"] or "",
        "url": notification["url"] or "/",
        # tag เดียวกัน ⇒ เบราว์เซอร์แทนที่ของเดิม ไม่ทับซ้อนกัน 5 อันในถาดแจ้งเตือน
        "tag": f"cls-{notification['group_type']}-{notification['id']}",
        "group": notification["group_type"],
        "priority": notification["priority"],
        "created_at": notification["created_at"].isoformat(),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ทะเบียนอุปกรณ์
# ═════════════════════════════════════════════════════════════════════════════
async def save_subscription(
    pool: asyncpg.Pool,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str],
) -> int:
    """ลงทะเบียน/อัปเดตอุปกรณ์ — endpoint เป็นกุญแจธรรมชาติ

    เครื่องที่เคยสมัครด้วยบัญชีอื่น (เช่น logout แล้ว login บัญชีใหม่ในเบราว์เซอร์เดิม)
    ต้อง **ย้ายเจ้าของ** ไม่ใช่สร้างแถวที่สอง ⇒ otherwise ผู้ใช้คนก่อน
    จะได้รับ push ของคนใหม่ (ข้อมูลรั่วข้ามบัญชีบนเครื่องใช้ร่วม)
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (endpoint) DO UPDATE
            SET user_id = EXCLUDED.user_id,
                p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth,
                user_agent = EXCLUDED.user_agent,
                failure_count = 0,
                deleted_at = NULL
            RETURNING id
            """,
            user_id,
            endpoint,
            p256dh,
            auth,
            user_agent,
        )


async def delete_subscription(pool: asyncpg.Pool, *, user_id: int, endpoint: str) -> bool:
    """เลิกสมัคร (soft delete) — เฉพาะอุปกรณ์ของตัวเอง คืน False ถ้าไม่ใช่ของเรา"""
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            """
            UPDATE push_subscriptions
            SET deleted_at = NOW()
            WHERE endpoint = $1 AND user_id = $2 AND deleted_at IS NULL
            RETURNING id
            """,
            endpoint,
            user_id,
        )
    return row is not None


async def count_active_subscriptions(pool: asyncpg.Pool, *, user_id: int) -> int:
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = $1 AND deleted_at IS NULL",
            user_id,
        )
    return int(value or 0)


async def drop_device(conn: asyncpg.Connection, subscription_id: int) -> None:
    """อุปกรณ์ตอบ 404/410 ⇒ ลบถาวรจากทะเบียน (ส่งต่ออีกก็มีแต่เสียเวลา)"""
    await conn.execute(
        "UPDATE push_subscriptions SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL",
        subscription_id,
    )


# ═════════════════════════════════════════════════════════════════════════════
# ส่งจริง
# ═════════════════════════════════════════════════════════════════════════════
Sender = Callable[[dict[str, Any], dict[str, Any]], None]


def _default_sender(subscription_info: dict[str, Any], payload: dict[str, Any]) -> None:
    """เรียก pywebpush — แยกเป็นฟังก์ชันเดียวเพื่อให้เทสต์แทนที่ได้โดยไม่ส่งออกเน็ต"""
    from pywebpush import webpush

    webpush(
        subscription_info=subscription_info,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=settings.VAPID_PRIVATE_KEY,
        vapid_claims={"sub": settings.VAPID_SUBJECT},
        timeout=10,
    )


def classify_error(error: Exception) -> str:
    """แปลงข้อยกเว้นเป็น sent/gone/dropped/retry (ชื่อค่าต้องตรงกับ CHECK ของ push_outbox)"""
    from pywebpush import WebPushException

    if isinstance(error, WebPushException):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if status in (404, 410):
            return "gone"
        if status == 429 or (status is not None and 500 <= status < 600):
            return "retry"
        if status is not None and 400 <= status < 500:
            # 400/401/403 = คีย์ VAPID หรือ subscription เพี้ยน — ลองซ้ำไม่มีทางผ่าน
            return "dropped"
        return "retry"

    if isinstance(error, binascii.Error):
        # คีย์อุปกรณ์เสียรูป — ลองซ้ำได้เผื่อ subscription ถูกอัปเดตใหม่
        return "retry"

    # network/timeout ฯลฯ
    return "retry"


def deliver(
    *,
    subscription_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, Any],
    sender: Optional[Sender] = None,
) -> tuple[str, Optional[str]]:
    """ส่ง push หนึ่งครั้ง คืน (ผลลัพธ์, ข้อความ error) — ไม่ raise ออกมา"""
    send = sender or _default_sender
    try:
        send(
            {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            payload,
        )
        return "sent", None
    except Exception as error:  # noqa: BLE001 — ทุกข้อยกเว้นต้องถูกจัดประเภท
        result = classify_error(error)
        logger.info(
            "push #%s → %s (%s)", subscription_id, result, type(error).__name__
        )
        return result, f"{type(error).__name__}: {error}"[:500]


def next_attempt_at(attempts: int, now: Optional[datetime] = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + backoff_delay(attempts)
