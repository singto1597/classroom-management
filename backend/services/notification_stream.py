"""fan-out แจ้งเตือนสด (SSE) — LISTEN `classroom_notify` แล้วกระจายให้ connection ที่เปิดอยู่

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมไม่ใช้ Redis pub/sub (ทั้งที่ stack มี Redis อยู่แล้ว)
═══════════════════════════════════════════════════════════════════════════════
แจ้งเตือนถูกสร้างใน **transaction เดียวกับงานจริง** ⇒ ถ้าประกาศสดผ่าน Redis
มันจะถูกส่งก่อน/หลัง commit ไม่แน่นอน (ส่งก่อน commit = ผู้ใช้เห็นแจ้งเตือนของงาน
ที่ rollback ไปแล้ว) PostgreSQL ปล่อย NOTIFY **ตอน commit เท่านั้น** ซึ่งตรงกับ
ความหมายที่ต้องการพอดี และ `LISTEN` เป็นคำสั่งที่ Postgres จัดการให้ทุก replica
อยู่แล้วโดยไม่ต้องมีตัวกลางเพิ่ม

═══════════════════════════════════════════════════════════════════════════════
🔒 กฎที่ล็อกไว้ด้วยเทสต์
═══════════════════════════════════════════════════════════════════════════════
1. **routes ตาม `user_id` เท่านั้น** — payload จาก DB ไม่มีทางบอกผู้รับผิดคน
   ได้ เพราะ trigger เขียน `NEW.user_id` และเราใช้ค่านั้นเป็นกุญแจ (ไม่เชื่อ room)
2. **`Queue(maxsize=1)`** — ผู้ใช้ที่เปิด 3 แท็บในเครื่องเดียวไม่ทำให้แรมโต
   และ slow consumer ไม่ทำให้ fan-out ค้าง: คิวเต็ม ⇒ ทิ้ง event ใหม่
   (client จะดึงรายการจริงจาก API อยู่แล้ว ⇒ สูญเสียแค่ "สัญญาณ" ไม่ใช่ข้อมูล)
3. **connection เดียวต่อโปรเซส อยู่นอก pool** — ถ้ายืมจาก pool 10 ตัวจะเหลือ 9
   ตลอดอายุโปรเซส และติดค้างถ้า pool หมดตอนบูต
4. **supervisor ต้องต่อกลับเอง** — Postgres restart / network blip ต้องไม่ทำให้
   SSE ตายเงียบ ๆ (ผู้ใช้จะหยุดได้แจ้งเตือนโดยไม่มีใครรู้)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import asyncpg

logger = logging.getLogger("API_NOTIFICATION_STREAM")

# ชื่อ channel ต้องตรงกับที่ trigger ใน migration 0002 ยิง
CHANNEL = "classroom_notify"

# ตรวจว่าค้าง/ขาดทุกกี่วินาที
_HEALTHCHECK_SECONDS = 5.0
# ถ้าต่อไม่ติด ให้รอเท่านี้ก่อนลองใหม่ (ไม่ให้ log ท่วมตอน DB ล่ม)
_RECONNECT_SECONDS = 2.0


class NotificationStream:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[dict]]] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._conn: Optional[asyncpg.Connection] = None
        self._dsn: Optional[str] = None
        self._stopping = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self, dsn: str) -> None:
        """เริ่ม supervisor (idempotent — เรียกซ้ำระหว่าง lifespan ไม่สร้างซ้ำ)"""
        if self._task is not None and not self._task.done():
            return
        self._dsn = dsn
        self._stopping = False
        self._task = asyncio.create_task(self._supervise(), name="notification-stream")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        conn, self._conn = self._conn, None
        if conn is not None and not conn.is_closed():
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                logger.debug("ปิด connection ของ stream ไม่สำเร็จ", exc_info=True)
        self._subscribers.clear()

    async def _supervise(self) -> None:
        while not self._stopping:
            try:
                conn = await asyncpg.connect(self._dsn)
                self._conn = conn
                await conn.add_listener(CHANNEL, self._on_notify)
                logger.info("✅ Notification stream LISTEN %s แล้ว", CHANNEL)

                # รอจน connection ขาด — asyncpg ไม่มี callback "closed" ที่ใช้ได้ตรง ๆ
                while not self._stopping and not conn.is_closed():
                    await asyncio.sleep(_HEALTHCHECK_SECONDS)
                if not conn.is_closed():
                    await conn.close()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — supervisor ต้องไม่ตาย
                logger.warning("Notification stream หลุด — กำลังต่อใหม่", exc_info=True)
                await asyncio.sleep(_RECONNECT_SECONDS)
            finally:
                self._conn = None

    # ── fan-out ──────────────────────────────────────────────────────────────
    def _on_notify(
        self, _conn: asyncpg.Connection, _pid: int, _channel: str, payload: str
    ) -> None:
        """asyncpg เรียกแบบ sync ในลูปของ connection — ต้องไม่บล็อก"""
        try:
            event = json.loads(payload)
            user_id = int(event["user_id"])
        except (ValueError, KeyError, TypeError):
            logger.warning("payload ของ %s อ่านไม่ได้: %r", CHANNEL, payload)
            return

        for queue in self._subscribers.get(user_id, set()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # ทิ้งสัญญาณ — client จะได้ตัวเลขล่าสุดตอนดึงรายการครั้งถัดไป
                logger.debug("คิวของผู้ใช้ %s เต็ม — ทิ้งสัญญาณหนึ่งครั้ง", user_id)

    # ── subscription ────────────────────────────────────────────────────────
    def subscribe(self, user_id: int) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
        self._subscribers.setdefault(user_id, set()).add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict]) -> None:
        queues = self._subscribers.get(user_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(user_id, None)

    @property
    def subscriber_count(self) -> int:
        return sum(len(queues) for queues in self._subscribers.values())

    @property
    def connected(self) -> bool:
        return self._conn is not None and not self._conn.is_closed()


# singleton ของโปรเซส — main.py เริ่ม/หยุดตาม lifespan
notification_stream = NotificationStream()
