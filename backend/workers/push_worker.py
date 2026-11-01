"""worker ส่ง Web Push — ลูปเดียวต่อ container, claim ด้วย `FOR UPDATE SKIP LOCKED`

═══════════════════════════════════════════════════════════════════════════════
🔁 ลำดับของแต่ละรอบ
═══════════════════════════════════════════════════════════════════════════════
1. **claim** แถวที่ถึงเวลา (`processing_at` = "ฉันกำลังทำอยู่") — ยังไม่นับ attempts
2. ตัดสินก่อนส่ง:
   - subscription ถูกลบไปแล้ว ⇒ `stale` (ไม่เสีย attempts)
   - อยู่ใน quiet hours และไม่ใช่ `urgent` ⇒ เลื่อน `next_attempt_at` ไปเวลาเปิดคิว
   - **ไม่ใช่การทิ้งแถว** และไม่เสีย attempts เช่นกัน (ไม่งั้นแจ้งเตือนตอนกลางคืน
     จะถูกทิ้งหลังลองครบ 5 ครั้งโดยไม่มีใครส่งเลย)
3. ส่งจริง ⇒ attempts + 1 แล้วบันทึกผล (`sent`/`retry`/`gone`/`dropped`)
4. ถ้าถือ claim ค้างเกิน `STALE_PROCESSING_MINUTES` (worker ตายกลางทาง)
   รอบถัดไปหยิบกลับมาทำใหม่ได้

═══════════════════════════════════════════════════════════════════════════════
🧪 ทำไม `drain_once()` รับ `sender` และ `now`
═══════════════════════════════════════════════════════════════════════════════
เทสต์ต้องพิสูจน์ "จัดประเภทถูก" และ "quiet hours เลื่อนจริง" โดยไม่ยิงเน็ต
และไม่ต้องรอเวลา ⇒ ทั้งคู่เป็นพารามิเตอร์ ไม่ใช่อ่านจาก global
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import redis.asyncio as aioredis

from core.config import settings
from core.heartbeat import record_heartbeat
from services import app_settings_service, push_service

logger = logging.getLogger("API_WORKER_PUSH")

# ต่อรอบหยิบกี่แถว — เล็กพอให้แจ้งเตือนใหม่ไม่ต้องรอคิวเก่าทั้งก้อน
BATCH_SIZE = 20

# รอบที่ไม่มีงาน ⇒ พักนานเท่านี้ (ไม่ spin)
IDLE_SLEEP_SECONDS = 5

# งบเวลาต่อรอบ: ถ้ามีงานค้างเยอะ ให้ drain ต่อจนเกลี้ยงแต่ไม่เกินนี้
DRAIN_BUDGET_SECONDS = 45

# claim ที่ค้างนานเกินไป = worker ตายกลางทาง ⇒ ให้ตัวอื่นหยิบได้
STALE_PROCESSING_MINUTES = 5


async def _claim(
    pool: asyncpg.Pool, *, now: datetime, limit: int = BATCH_SIZE
) -> list[dict[str, Any]]:
    """จองแถวที่ถึงเวลา — คืนแถวพร้อมข้อมูลที่ต้องใช้ส่ง (notification + device)"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetch(
                """
                WITH claimed AS (
                    SELECT o.id
                    FROM push_outbox o
                    WHERE o.status IN ('pending', 'retry')
                      AND o.next_attempt_at <= $1
                      AND (
                            o.processing_at IS NULL
                            OR o.processing_at < NOW() - make_interval(mins => $3)
                          )
                    ORDER BY o.next_attempt_at
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE push_outbox o
                SET processing_at = NOW()
                FROM claimed c
                WHERE o.id = c.id
                RETURNING o.id, o.attempts
                """,
                now,
                limit,
                STALE_PROCESSING_MINUTES,
            )
            ids = [row["id"] for row in claimed]
            if not ids:
                return []

            rows = await conn.fetch(
                """
                SELECT o.id AS outbox_id,
                       o.attempts,
                       n.id, n.room_id, n.user_id, n.group_type, n.type, n.priority,
                       n.title, n.body, n.url, n.created_at,
                       s.id AS subscription_id, s.endpoint, s.p256dh, s.auth,
                       s.deleted_at AS subscription_deleted_at
                FROM push_outbox o
                JOIN notifications n ON n.id = o.notification_id
                JOIN push_subscriptions s ON s.id = o.subscription_id
                WHERE o.id = ANY($1::bigint[])
                """,
                ids,
            )

            room_ids = sorted({row["room_id"] for row in rows})
            quiet_rows = await conn.fetch(
                "SELECT room_id, value FROM app_settings WHERE key = $1 AND room_id = ANY($2::int[])",
                app_settings_service.QUIET_HOURS_KEY,
                room_ids,
            )
    quiet_by_room = {
        row["room_id"]: app_settings_service.decode_setting(row["value"]) for row in quiet_rows
    }

    return [
        {**dict(row), "quiet_hours": quiet_by_room.get(row["room_id"])}
        for row in rows
    ]


async def _release(conn: asyncpg.Connection, outbox_id: int, **fields: Any) -> None:
    """อัปเดตผลของแถวหนึ่ง — ใช้ชื่อคอลัมน์จากพารามิเตอร์เจาะจง (ไม่รับ dict ดิบ)"""
    sets: list[str] = ["processing_at = NULL"]
    params: list[Any] = []

    mapping = {
        "status": "status",
        "next_attempt_at": "next_attempt_at",
        "last_error": "last_error",
    }
    for key, column in mapping.items():
        if key in fields:
            params.append(fields[key])
            sets.append(f"{column} = ${len(params)}")
    if fields.get("bump_attempts"):
        sets.append("attempts = attempts + 1")
    if fields.get("sent"):
        sets.append("sent_at = NOW()")
    if fields.get("clear_error"):
        sets.append("last_error = NULL")

    params.append(outbox_id)
    await conn.execute(
        f"UPDATE push_outbox SET {', '.join(sets)} WHERE id = ${len(params)}",
        *params,
    )


async def drain_once(
    pool: asyncpg.Pool,
    *,
    sender: Optional[push_service.Sender] = None,
    now: Optional[datetime] = None,
    limit: int = BATCH_SIZE,
) -> dict[str, int]:
    """ทำงานหนึ่งรอบ คืนสถิติแยกตามผลลัพธ์ — `0` ทุกช่องคือคำตอบที่ assert ได้"""
    stats = {"claimed": 0, "sent": 0, "retry": 0, "gone": 0, "dropped": 0, "deferred": 0, "stale": 0}
    moment = now or datetime.now(timezone.utc)

    rows = await _claim(pool, now=moment, limit=limit)
    stats["claimed"] = len(rows)
    if not rows:
        return stats

    async with pool.acquire() as conn:
        async with conn.transaction():
            for row in rows:
                outbox_id = row["outbox_id"]

                # อุปกรณ์ถูกลบ/เลิกสมัครไปแล้วหลังเข้าคิว
                if row["subscription_deleted_at"] is not None:
                    await _release(conn, outbox_id, status="stale")
                    stats["stale"] += 1
                    continue

                # quiet hours — urgent ทะลุได้เสมอ
                if row["priority"] != "urgent":
                    resume_at = app_settings_service.quiet_hours_end(row["quiet_hours"], moment)
                    if resume_at is not None:
                        await _release(conn, outbox_id, next_attempt_at=resume_at)
                        stats["deferred"] += 1
                        continue

                result, error = push_service.deliver(
                    subscription_id=row["subscription_id"],
                    endpoint=row["endpoint"],
                    p256dh=row["p256dh"],
                    auth=row["auth"],
                    payload=push_service.build_payload(row),
                    sender=sender,
                )

                attempts = int(row["attempts"]) + 1

                if result == "sent":
                    await _release(conn, outbox_id, status="sent", sent=True, bump_attempts=True, clear_error=True)
                    stats["sent"] += 1
                elif result == "gone":
                    await _release(conn, outbox_id, status="stale", bump_attempts=True, last_error=error)
                    await push_service.drop_device(conn, row["subscription_id"])
                    stats["gone"] += 1
                elif result == "dropped" or attempts >= push_service.MAX_ATTEMPTS:
                    # ลองครบเพดานแล้วยังไม่ผ่าน ⇒ ทิ้งพร้อมเก็บ error ไว้ตรวจ
                    await _release(conn, outbox_id, status="dropped", bump_attempts=True, last_error=error)
                    stats["dropped"] += 1
                else:
                    await _release(
                        conn,
                        outbox_id,
                        status="retry",
                        bump_attempts=True,
                        last_error=error,
                        next_attempt_at=push_service.next_attempt_at(attempts, moment),
                    )
                    stats["retry"] += 1

    return stats


async def run_forever(pool: asyncpg.Pool, redis=None) -> None:  # pragma: no cover — ลูปไม่รู้จบ
    """ลูปของ container — หยุดได้ด้วย SIGTERM ตามปกติของ Swarm (grace period 10 วิ)

    💓 [P6.3] เขียน `push_worker:last_beat` ลง Redis ทุกรอบ (**รวมรอบที่ไม่มีงาน**)
    เพื่อให้ `/health` บอกได้ว่า worker ยังมีชีวิต — ถ้าไม่มี heartbeat, worker ที่ตาย
    จะเงียบสนิทและคนเห็นแค่ "แจ้งเตือนไม่เด้ง" โดยไม่รู้ว่าอะไรพัง
    """
    if not push_service.push_enabled():
        logger.warning(
            "⚠️ ไม่ได้ตั้ง VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY — worker จะหลับ "
            "(pushes จะสะสมใน outbox ไม่ถูกส่ง)"
        )

    heartbeat_warned = False
    while True:
        # heartbeat ก่อนทำงานเสมอ — รอบที่ไม่มีงานก็ต้องบอกว่ายังอยู่
        if redis is not None:
            try:
                await record_heartbeat(redis)
            except Exception:
                if not heartbeat_warned:
                    heartbeat_warned = True
                    logger.warning("เขียน heartbeat ลง Redis ไม่ได้ (จะลองรอบถัดไป)", exc_info=True)

        started = time.monotonic()
        totals = {"sent": 0, "retry": 0, "gone": 0, "dropped": 0, "deferred": 0, "stale": 0}
        processed_any = False

        while time.monotonic() - started < DRAIN_BUDGET_SECONDS:
            if not push_service.push_enabled():
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                break
            stats = await drain_once(pool)
            if stats["claimed"] == 0:
                break
            processed_any = True
            for key in totals:
                totals[key] += stats[key]

        if processed_any:
            logger.info("📮 push รอบนี้: %s", totals)

        if not processed_any:
            await asyncio.sleep(IDLE_SLEEP_SECONDS)


def _generate_keys() -> None:  # pragma: no cover — คำสั่งช่วยติดตั้ง
    """พิมพ์คู่คีย์ VAPID แบบ **บรรทัดเดียว** เพื่อวางใน `.env` ได้ตรง ๆ

    ⚠️ ห้ามพิมพ์เป็น PEM: `.env` และ `docker stack deploy` ถือ multiline ได้ไม่ดี
    และถ้า copy พลาดบรรทัดเดียวคีย์จะเสียเงียบ ๆ ⇒ ใช้ base64url ของ DER
    (`Vapid.from_string` อ่านได้) และ public key เป็น uncompressed point
    ซึ่งเป็นรูปแบบที่เบราว์เซอร์ต้องการ (`applicationServerKey`)
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()

    private_der = vapid.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private_b64 = base64.urlsafe_b64encode(private_der).rstrip(b"=").decode()
    public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode()

    print("VAPID_PRIVATE_KEY=" + private_b64)
    print("VAPID_PUBLIC_KEY=" + public_b64)


async def _main() -> None:  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)
    # 💓 heartbeat ใช้ Redis ตัวเดียวกับ backend · timeout สั้น + ไม่ทำให้ worker ตายถ้า Redis ล่ม
    redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await run_forever(pool, redis)
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="worker ส่ง Web Push ของระบบห้องเรียน")
    parser.add_argument("--generate-keys", action="store_true", help="พิมพ์คู่คีย์ VAPID แล้วออก")
    args = parser.parse_args()
    if args.generate_keys:
        _generate_keys()
    else:
        asyncio.run(_main())
