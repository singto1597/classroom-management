"""💓 สัญญาณชีพของโปรเซสที่แยก container (P6.3)

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมี
═══════════════════════════════════════════════════════════════════════════════
`/health` เดิมตอบแค่ "DB ต่อได้ไหม" ซึ่งเป็นเรื่องของ **backend** เท่านั้น
แต่ `push_worker` เป็น container แยก (`docker-compose.app.yml`) ที่อาจตายเพราะ
migration/ออกจากงานโดยที่ backend ยัง healthy ⇒ ตู้จดหมาย `push_outbox` จะโตขึ้น
เรื่อย ๆ โดยไม่มีใครส่ง และไม่มีอะไรบอกจนกว่าจะมีคนสังเกตว่าแจ้งเตือนไม่เด้ง

worker เขียน timestamp ลง Redis ทุกรอบ (รวมรอบที่ไม่มีงาน) ⇒ `/health` อ่านแล้ว
ตอบอายุของสัญญาณ ⇒ เห็นปัญหาได้จากคำสั่งเดียว โดยไม่ต้อง `docker service ps`

⚠️ **ห้ามทำให้ `/health` คืน 503 เพราะ heartbeat:** backend ยังให้บริการได้เต็มที่
แม้ worker ตาย (outbox แค่ค้าง) ⇒ ถ้าทำ 503, Swarm จะฆ่า backend ที่ดีทิ้งเป็นวงจร
ระหว่างที่ worker มีปัญหา ⇒ รายงานเป็นข้อมูลประกอบ แต่ตัดสิน restart จาก DB เท่านั้น
"""

from __future__ import annotations

import time
from typing import Optional

# 🔑 ชื่อ key ใน Redis — worker เขียน, API อ่าน (ทั้งคู่อยู่ container คนละตัว)
PUSH_WORKER_HEARTBEAT_KEY = "push_worker:last_beat"

# TTL = "ถ้า worker หยุดหายไปนานกว่านี้ให้ key หมดอายุเอง" (10 นาที)
# ⇒ /health ได้ `null` (= ไม่รู้) แทนตัวเลขที่ค้างจากวันก่อนแล้วหลอกว่า worker ยังอยู่
PUSH_WORKER_HEARTBEAT_TTL_SECONDS = 600


async def record_heartbeat(redis, *, key: str = PUSH_WORKER_HEARTBEAT_KEY, now: Optional[float] = None) -> None:
    """เขียนเวลาปัจจุบัน (epoch วินาที) — เรียกทุกรอบของ worker"""
    if redis is None:
        return
    timestamp = int(now if now is not None else time.time())
    await redis.set(key, str(timestamp), ex=PUSH_WORKER_HEARTBEAT_TTL_SECONDS)


async def read_heartbeat_age(redis, *, key: str = PUSH_WORKER_HEARTBEAT_KEY, now: Optional[float] = None) -> Optional[int]:
    """อายุของสัญญาณ (วินาที) หรือ `None` ถ้าไม่เคยมี/อ่านไม่ออก

    ค่าติดลบ (นาฬิกาของ worker เร็วกว่า API) ถูกปัดเป็น 0 — ตัวเลขติดลบทำให้
    คนอ่าน log เข้าใจผิดว่า "มีแค่ -3 วินาที" ซึ่งไม่มีความหมาย
    """
    if redis is None:
        return None
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        beat = int(raw)
    except (TypeError, ValueError):
        return None
    age = int((now if now is not None else time.time()) - beat)
    return max(0, age)
