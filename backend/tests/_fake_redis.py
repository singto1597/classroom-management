"""Redis ปลอมสำหรับเทสต์ (ไม่ใช่ไฟล์เทสต์ — ชื่อขึ้นต้น `_` จึงไม่ถูก pytest เก็บ)

เทสต์ทุกตัวในชุดนี้ **ห้ามต่อ Redis จริง**: `docker-compose.test.yml` ชี้
`REDIS_URL=redis://127.0.0.1:6379/15` (ไม่มีอะไรฟังอยู่) ⇒ ถ้าโค้ดพึ่ง Redis จริง
ผลจะขึ้นกับว่าเครื่องที่รันบังเอิญมี Redis หรือไม่ ซึ่งแยกไม่ออกระหว่าง
"โค้ดถูก" กับ "สภาพแวดล้อมต่างกัน"

รองรับเฉพาะคำสั่งที่ `core/rate_limit.py` กับ `core/heartbeat.py` ใช้จริง
(`set`/`incr`/`ttl`/`expire`/`get`/`ping`) — ถ้าโค้ดจะใช้คำสั่งใหม่ ให้เพิ่มที่นี่
แล้วเทสต์จะเตือนเอง (`AttributeError`) แทนการแอบต่อ Redis จริง
"""

from __future__ import annotations

import time
from typing import Optional


class FakeRedis:
    """หน่วยความจำในโปรเซส — TTL คำนวณจาก `time.monotonic()`"""

    def __init__(self) -> None:
        # key -> (ค่า, เวลาหมดอายุแบบ monotonic หรือ None = ไม่มี TTL)
        self.store: dict[str, tuple[str, Optional[float]]] = {}
        self.commands: list[str] = []

    def _live(self, key: str) -> Optional[tuple[str, Optional[float]]]:
        item = self.store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and time.monotonic() >= expires_at:
            del self.store[key]
            return None
        return item

    async def set(self, key: str, value, ex: Optional[int] = None, nx: bool = False):
        self.commands.append("set")
        if nx and self._live(key) is not None:
            return None
        expires_at = time.monotonic() + ex if ex else None
        self.store[key] = (str(value), expires_at)
        return True

    async def incr(self, key: str) -> int:
        self.commands.append("incr")
        item = self._live(key)
        current = int(item[0]) if item else 0
        expires_at = item[1] if item else None
        self.store[key] = (str(current + 1), expires_at)
        return current + 1

    async def ttl(self, key: str) -> int:
        self.commands.append("ttl")
        item = self._live(key)
        if item is None:
            return -2
        expires_at = item[1]
        if expires_at is None:
            return -1
        return max(0, int(expires_at - time.monotonic()))

    async def expire(self, key: str, seconds: int) -> bool:
        self.commands.append("expire")
        item = self._live(key)
        if item is None:
            return False
        self.store[key] = (item[0], time.monotonic() + seconds)
        return True

    async def get(self, key: str) -> Optional[str]:
        self.commands.append("get")
        item = self._live(key)
        return item[0] if item else None

    async def ping(self) -> bool:
        self.commands.append("ping")
        return True


class BrokenRedis:
    """ต่อไม่ได้ — ใช้พิสูจน์ว่า rate limit **fail-open** (ปล่อยผ่าน) ไม่ใช่ล็อกทั้งระบบ"""

    async def set(self, *_args, **_kwargs):
        raise ConnectionError("จำลอง: ต่อ Redis ไม่ได้")

    async def ping(self):
        raise ConnectionError("จำลอง: ต่อ Redis ไม่ได้")

    async def get(self, *_args, **_kwargs):
        raise ConnectionError("จำลอง: ต่อ Redis ไม่ได้")
