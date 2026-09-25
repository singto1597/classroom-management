"""
🧪 เทสต์ของ `redis_listener` — **ทุกครั้งที่ต่อใหม่ ต้องปิดของเก่าก่อน** (M11)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```

## บั๊กที่เทสต์ชุดนี้ล็อกไว้ (พบจากการตรวจระบบ 2026-09-23)

`RedisListener.listen_to_redis` เป็น `while True:` ที่สร้าง
`redis_client = aioredis.from_url(...)` **ใหม่ทุกรอบ** แต่เดิม **ไม่มี `finally`**
ที่ปิดตัวเก่า ⇒ ทุกครั้งที่เชื่อมต่อหลุด จะทิ้ง connection pool + pubsub ค้างไว้ทั้งชุด

🔴 **เกิดตอนบูตด้วย ไม่ใช่แค่ตอนเน็ตกระตุก** — ถ้าตู้ Redis ยังไม่ตื่น `ping()` จะล้ม
   แล้ววนซ้ำทุก 5 วินาที ⇒ ตอน deploy (ที่ Redis กับบอทสตาร์ทพร้อมกัน) คือเคสที่เกิดชัวร์
   อาการที่ผู้ใช้เห็นคือ "บอทเงียบ" แล้ว Redis ปฏิเสธการเชื่อมต่อใหม่ — ซึ่งอ่านจาก
   log ของบอทไม่ออกเลยว่าต้นเหตุคือ connection ของตัวเอง

⚠️ เทสต์นี้ **ไม่แตะ Discord และไม่แตะ Redis จริง** — `listen_to_redis` ใช้แค่
   `aioredis` + `logger` + `asyncio.sleep` ⇒ สแตกทั้งก้อนแทนได้ด้วย stub
   และ **ไม่เรียก `__init__`** (ซึ่งจะ `bot.loop.create_task` ทำให้ต้องมีบอทจริง)
"""
import asyncio
import unittest
from unittest import mock

from cogs import redis_listener


class _StubPubSub:
    def __init__(self):
        self.subscribed: list[str] = []
        self.closed = False
        self.aclose_raises: BaseException | None = None

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def get_message(self, **kwargs):
        raise ConnectionError("redis หลุดกลางทาง")

    async def aclose(self) -> None:
        self.closed = True
        if self.aclose_raises is not None:
            raise self.aclose_raises


class _StubRedis:
    """client ปลอมที่บันทึกว่าถูกปิดหรือยัง

    `ping_raises` ใช้จำลอง "ตู้ Redis ยังไม่ตื่นตอนบูต" ซึ่งเป็นเคสที่ทำให้วนซ้ำ
    `message_raises` ใช้จำลอง "หลุดกลางทางหลัง subscribe สำเร็จ"
    """

    def __init__(self, *, ping_raises: BaseException | None = None):
        self.ping_raises = ping_raises
        self.closed = False
        self.aclose_raises: BaseException | None = None
        self.pubsub_obj: _StubPubSub | None = None
        self.pinged = False

    async def ping(self) -> None:
        self.pinged = True
        if self.ping_raises is not None:
            raise self.ping_raises

    def pubsub(self, **kwargs) -> _StubPubSub:
        self.pubsub_obj = _StubPubSub()
        return self.pubsub_obj

    async def aclose(self) -> None:
        self.closed = True
        if self.aclose_raises is not None:
            raise self.aclose_raises


class _Harness:
    """สร้าง stub แบบมีสถานะ + รัน `listen_to_redis` จนครบ `rounds` รอบ แล้วออก

    🔑 ใช้ `CancelledError` จาก `from_url` เพื่อ **ออกจาก `while True` อย่างตั้งใจ**
       (`except Exception` ไม่ดัก `BaseException`) ⇒ `finally` ยังทำงานครบ
       ถ้าใช้ `task.cancel()` แทน จะไม่รู้แน่ว่ารันไปกี่รอบแล้ว
    """

    def __init__(self, *, rounds: int, ping_raises=None, on_client=None):
        self.rounds = rounds
        self.clients: list[_StubRedis] = []
        self._ping_raises = ping_raises
        # `on_client(index, client)` — ให้เทสต์ปรับ stub ก่อนโค้ดจริงได้ใช้
        self._on_client = on_client

    def from_url(self, url, **kwargs):
        if len(self.clients) >= self.rounds:
            raise asyncio.CancelledError
        client = _StubRedis(ping_raises=self._ping_raises)
        self.clients.append(client)
        if self._on_client is not None:
            self._on_client(len(self.clients), client)
        return client

    async def run(self, cog) -> None:
        # ⚠️ patch `asyncio.sleep` ให้เป็น no-op — ไม่มีอะไรในโค้ดที่ทดสอบต้องรอจริง
        #    (`sleep(3)` ตอนบูต + `sleep(5)` ตอน reconnect + `sleep(0.1)` ในลูป)
        with mock.patch.object(redis_listener.asyncio, "sleep", new=mock.AsyncMock()):
            with mock.patch.object(
                redis_listener.aioredis, "from_url", side_effect=self.from_url
            ):
                try:
                    await cog.listen_to_redis()
                except asyncio.CancelledError:
                    pass  # ทางออกที่ตั้งใจ (ดู docstring ของ _Harness)
                else:
                    raise AssertionError("listen_to_redis ต้องออกด้วย CancelledError")


class ReconnectClosesResourcesTest(unittest.IsolatedAsyncioTestCase):
    def _cog(self):
        # ไม่เรียก __init__ — มันสร้าง BotActionService(bot) และ create_task
        return redis_listener.RedisListener.__new__(redis_listener.RedisListener)

    async def test_every_reconnect_closes_the_previous_client(self):
        """🔴 หัวใจของ M11 — ต่อ 3 รอบ ต้องปิดครบทั้ง 3 ตัว ไม่ใช่ปิดแค่ตัวสุดท้าย"""
        harness = _Harness(rounds=3, ping_raises=ConnectionError("redis ยังไม่ตื่น"))
        await harness.run(self._cog())

        self.assertEqual(len(harness.clients), 3, "ต้องลองต่อใหม่ 3 รอบ")
        for index, client in enumerate(harness.clients):
            self.assertTrue(client.closed, f"client รอบที่ {index + 1} ไม่ถูกปิด ⇒ รั่ว")

    async def test_pubsub_is_closed_when_the_message_loop_dies(self):
        """หลุด **หลัง** subscribe สำเร็จ — เคสนี้เดิมทิ้ง pubsub ค้างด้วย"""
        harness = _Harness(rounds=1)
        await harness.run(self._cog())

        client = harness.clients[0]
        self.assertTrue(client.pinged, "ต้อง ping สำเร็จก่อน")
        self.assertIsNotNone(client.pubsub_obj, "ต้องสร้าง pubsub")
        self.assertEqual(client.pubsub_obj.subscribed, ["classroom_events"])
        self.assertTrue(client.pubsub_obj.closed, "pubsub ต้องถูกปิด")
        self.assertTrue(client.closed, "client ต้องถูกปิด")

    async def test_a_failing_close_does_not_kill_the_loop(self):
        """🔑 ปิดแบบ best-effort — ถ้าการปิดล้มเหลวทำให้ loop ตาย บอทจะไม่ได้ reconnect เลย
        ซึ่งแย่กว่าการรั่ว ⇒ ต้องลองรอบถัดไปให้ได้
        """

        def break_the_first_close(index, client):
            if index == 1:
                client.aclose_raises = RuntimeError("ปิดไม่สำเร็จ")

        harness = _Harness(
            rounds=2, ping_raises=ConnectionError("boom"), on_client=break_the_first_close
        )
        await harness.run(self._cog())

        self.assertEqual(len(harness.clients), 2, "ต้องลองต่อรอบที่ 2 แม้ปิดรอบแรกไม่สำเร็จ")
        self.assertTrue(harness.clients[0].closed)
        self.assertTrue(harness.clients[1].closed)


if __name__ == "__main__":
    unittest.main()
