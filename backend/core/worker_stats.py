"""📊 สถิติรอบล่าสุดของ worker (P6.5) — ตัวนับที่แยก "จะลองใหม่" กับ "ทิ้งแล้ว"

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมี ทั้งที่ `push_outbox` มีสถานะอยู่แล้ว
═══════════════════════════════════════════════════════════════════════════════
สถานะใน DB บอก **แถวแต่ละแถวเป็นอะไร** แต่บอกไม่ได้ว่า **รอบล่าสุดเกิดอะไรขึ้น**:
- `deferred` (เลื่อนเพราะช่วงงดรบกวน) **ไม่ใช่สถานะ** — แถวยังเป็น `pending`/`retry`
  แค่ `next_attempt_at` ถูกเลื่อนไป ⇒ ถ้าดูแต่ DB จะแยก "เงียบเพราะตั้งใจ" ออกจาก
  "รอส่งปกติ" ไม่ออก
- `gone` (อุปกรณ์ถูกลบ) กลายเป็นสถานะ `stale` รวมกับกรณีอื่น ⇒ แยกได้ยาก
- ค่า `0` ในรอบที่ไม่มีงาน เป็นข้อมูลจริง (worker ยังมีชีวิตและคิวว่าง) ไม่ใช่ "ไม่เคยรัน"

⇒ worker เขียนผลของรอบล่าสุดลง Redis (ค่าเดียว เขียนทับทุกรอบ) แล้ว API อ่านไปแสดงคู่กับ
สถานะคิวจริงใน DB — **DB = สถานะปัจจุบัน · Redis = สิ่งที่เพิ่งเกิดขึ้น**

⚠️ ต้องมี TTL: ถ้า worker ตาย การเห็นตัวเลขค้างจากชั่วโมงก่อนจะหลอกว่า "รอบล่าสุด
เพิ่งส่งสำเร็จ 20 ครั้ง" ⇒ หมดอายุแล้วอ่านได้ `null` (= ไม่รู้) ซึ่งซื่อสัตย์กว่า
"""

from __future__ import annotations

import json
import time
from typing import Optional

# 🔑 worker เขียน, API อ่าน (container คนละตัว)
LAST_ROUND_KEY = "push_worker:stats:last_round"

# TTL = "ถ้า worker หยุดหายไปนานกว่านี้ ให้ถือว่า 'รอบล่าสุด' ไม่มีความหมายแล้ว"
LAST_ROUND_TTL_SECONDS = 3600

# keys ที่ต้องมีครบทุกตัวใน payload — ชื่อเดียวกับ `stats` ของ `drain_once()`
_COUNT_KEYS = ("claimed", "sent", "retry", "gone", "dropped", "deferred", "stale")


async def record_last_round(
    redis,
    *,
    claimed: int,
    sent: int,
    retry: int,
    gone: int,
    dropped: int,
    deferred: int,
    stale: int,
    enabled: bool = True,
    now: Optional[float] = None,
) -> None:
    """เขียนผลรอบล่าสุด (ทับของเดิม) — เรียกทุกรอบ **รวมรอบที่ไม่มีงาน**

    `enabled=False` คือกรณีที่ยังไม่ได้ตั้ง VAPID — worker ยังวนอยู่แต่ไม่ส่งอะไร
    ⇒ หน้าเว็บต้องแยก "คิวว่าง" กับ "ส่งไม่ได้เลย" ออกจากกันได้
    """
    if redis is None:
        return
    payload = {
        "at": int(now if now is not None else time.time()),
        "enabled": bool(enabled),
        "claimed": int(claimed),
        "sent": int(sent),
        "retry": int(retry),
        "gone": int(gone),
        "dropped": int(dropped),
        "deferred": int(deferred),
        "stale": int(stale),
    }
    await redis.set(LAST_ROUND_KEY, json.dumps(payload), ex=LAST_ROUND_TTL_SECONDS)


async def read_last_round(redis) -> Optional[dict]:
    """คืน `{"at": epoch, "claimed": …, …}` หรือ `None` ถ้าไม่มี/อ่านไม่ออก

    ค่าเสีย (JSON พัง/คีย์หาย) ถือเป็น `None` ทั้งก้อน — ไม่เดาเป็นศูนย์
    เพราะ "ศูนย์" มีความหมายว่า "รอบล่าสุดไม่มีงาน" ซึ่งต่างจาก "อ่านไม่ได้"
    """
    if redis is None:
        return None
    raw = await redis.get(LAST_ROUND_KEY)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        at = int(data["at"])
        counts = {key: int(data[key]) for key in _COUNT_KEYS}
        # ค่าเก่าที่ไม่มี `enabled` (ช่วง rolling deploy) ถือว่าเปิดอยู่ — สถานะ
        # เริ่มต้นของ worker คือ "พยายามส่ง" ไม่ใช่ "ปิด"
        enabled = bool(data.get("enabled", True))
    except (ValueError, KeyError, TypeError):
        return None
    return {"at": at, "enabled": enabled, **counts}
