"""📊 สถิติการส่ง push ของห้อง (P6.5) — สำหรับการ์ดในหน้าตั้งค่าแจ้งเตือน

═══════════════════════════════════════════════════════════════════════════════
สองแหล่งข้อมูล สองความหมาย — ห้ามใช้แทนกัน
═══════════════════════════════════════════════════════════════════════════════
| ที่มา | ตอบคำถาม | ขอบเขต |
|---|---|---|
| `push_outbox` (DB) | "ตอนนี้คิวเป็นอย่างไร" | **เฉพาะห้องนี้** |
| `worker_stats` (Redis) | "รอบล่าสุดเกิดอะไรขึ้น" | **ทั้งระบบ** (worker 1 ตัวส่งทุกห้อง) |

- `deferred` (เลื่อนเพราะช่วงงดรบกวน) มีได้จาก Redis เท่านั้น — ใน DB แถวยังเป็น
  `pending`/`retry` แค่ `next_attempt_at` ถูกเลื่อน ⇒ ดูจาก DB แยกไม่ออก
- `last_round` เป็น `null` ได้ (worker ยังไม่เคยรัน/key หมดอายุ) ⇒ UI ต้องแสดง
  "ไม่รู้" ไม่ใช่ "0" — สองอย่างนี้ต่างกัน (กฎเหล็กข้อ 5)

🔒 สิทธิ์: `MANAGE_CLASSROOM_SETTINGS` — สถิติการส่งเป็นข้อมูลปฏิบัติงานของผู้ดูแล
ไม่ใช่ของสมาชิกทั่วไป (สมาชิกเห็นแค่ quiet hours ซึ่งอธิบาย "ทำไมเงียบ")

📉 `sent_24h` จำกัดช่วง 24 ชม. โดยเจตนา: `sent` สะสมตลอดชีพจะโตตลอดกาล
และค่าน้อยๆ ที่ไม่ขยับไม่บอกอะไร ⇒ ตัวเลขที่ควรเห็นคือ "เมื่อวานนี้ส่งได้กี่ครั้ง"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg

from core import worker_stats
from core.heartbeat import read_heartbeat_age
from core.rbac import require_permission

logger = logging.getLogger("API_PUSH_STATS")

# หน้าต่างของ "ส่งสำเร็จ" — กว้างพอให้เห็นกิจกรรมปกติของห้อง
SENT_WINDOW_HOURS = 24

# 🔑 `FILTER` ของ Postgres ทำให้ได้ทุกตัวนับจาก query เดียว (ไม่ยิง 7 รอบ)
#
# `due_now` นับเฉพาะที่ถึงกำหนดแล้ว — แถว `pending` ที่ตั้งเวลาไว้ในอนาคต
# (เช่นเพิ่งถูกเลื่อนออกจาก quiet hours) ไม่ใช่ "ของค้าง" และไม่ควรทำให้
# ผู้ดูแลตกใจว่าคิวติด
#
# `oldest_due_seconds` ใช้ `created_at` ของ outbox (ไม่ใช่ next_attempt_at):
# คำถามคือ "ของชิ้นนี้รอมากี่โมงแล้ว" ไม่ใช่ "เลยกำหนดมากี่วินาที"
_QUEUE_SQL = """
SELECT
    COUNT(*) FILTER (WHERE o.status = 'pending')                     AS pending,
    COUNT(*) FILTER (WHERE o.status = 'retry')                       AS retry,
    COUNT(*) FILTER (WHERE o.status = 'dropped')                     AS dropped,
    COUNT(*) FILTER (WHERE o.status = 'stale')                       AS stale,
    COUNT(*) FILTER (
        WHERE o.status = 'sent'
          AND o.sent_at >= NOW() - make_interval(hours => $2)
    )                                                                AS sent_24h,
    COUNT(*) FILTER (
        WHERE o.status IN ('pending', 'retry')
          AND o.next_attempt_at <= NOW()
    )                                                                AS due_now,
    COALESCE(
        EXTRACT(EPOCH FROM (
            NOW() - MIN(o.created_at) FILTER (
                WHERE o.status IN ('pending', 'retry')
                  AND o.next_attempt_at <= NOW()
            )
        ))::bigint,
        0
    )                                                                AS oldest_due_seconds
FROM push_outbox o
JOIN notifications n ON n.id = o.notification_id
WHERE n.room_id = $1
"""


async def get_delivery_stats(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    redis=None,
) -> dict:
    """คืนสถิติพร้อมใช้กับ `PushDeliveryStatsResponse`

    Redis เป็น **ข้อมูลประกอบ**: ต่อไม่ได้ก็ยังคืนสถานะคิวจาก DB ได้
    (fail-open — สถิติไม่ใช่ด่านความปลอดภัย ไม่มีเหตุให้ล้มทั้งหน้า)
    """
    async with pool.acquire() as conn:
        await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
        row = await conn.fetchrow(_QUEUE_SQL, room_id, SENT_WINDOW_HOURS)

    queue = {
        "pending": int(row["pending"]),
        "retry": int(row["retry"]),
        "dropped": int(row["dropped"]),
        "stale": int(row["stale"]),
        "sent_24h": int(row["sent_24h"]),
        "due_now": int(row["due_now"]),
        "oldest_due_seconds": int(row["oldest_due_seconds"]),
    }

    last_round = None
    heartbeat_age = None
    if redis is not None:
        # แยก try ของสองค่า: อ่านตัวหนึ่งพังไม่ควรทำให้อีกตัวหายไปด้วย
        try:
            raw = await worker_stats.read_last_round(redis)
        except Exception:
            logger.warning("อ่านสถิติรอบล่าสุดของ worker ไม่ได้ (แสดงเป็น 'ไม่รู้')", exc_info=True)
            raw = None
        if raw is not None:
            last_round = {
                "at": datetime.fromtimestamp(raw["at"], tz=timezone.utc),
                "claimed": raw["claimed"],
                "sent": raw["sent"],
                "retry": raw["retry"],
                "gone": raw["gone"],
                "dropped": raw["dropped"],
                "deferred": raw["deferred"],
                "stale": raw["stale"],
                "enabled": raw["enabled"],
            }
        try:
            heartbeat_age = await read_heartbeat_age(redis)
        except Exception:
            logger.warning("อ่าน heartbeat ของ worker ไม่ได้", exc_info=True)

    return {
        "room_id": room_id,
        "queue": queue,
        "last_round": last_round,
        "worker_heartbeat_age_seconds": heartbeat_age,
        "generated_at": datetime.now(timezone.utc),
    }
