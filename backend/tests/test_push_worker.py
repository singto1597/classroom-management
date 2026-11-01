"""
Web Push — quiet hours + คิวส่ง (`workers/push_worker.py`)

สิ่งที่ล็อกไว้:
  1. quiet hours: `start == end` = ปิด, ข้ามเที่ยงคืนได้, ใช้เวลา Asia/Bangkok,
     ค่าที่อ่านไม่ได้ ⇒ ไม่เงียบ (ปลอดภัยกว่าแจ้งเตือนหายทั้งห้อง)
  2. worker: sent / retry (มี backoff) / gone (ลบอุปกรณ์) / dropped (ครบเพดาน)
  3. **quiet hours ไม่กิน attempts และไม่ทิ้งแถว** — แค่เลื่อน `next_attempt_at`
     ไปถึงเวลาเปิดคิว
  4. `urgent` ทะลุ quiet hours ได้
  5. อุปกรณ์ที่ถูกลบหลังเข้าคิว ⇒ `stale` โดยไม่ยิงเน็ตเลย

ทุกเทสต์ใช้ `sender` ปลอม ⇒ ไม่มีการยิงออกเน็ตจริง และไม่ต้องมีคีย์ VAPID
"""

from datetime import datetime, timedelta, timezone
import random
import string
import uuid

import pytest
from pywebpush import WebPushException

from services import app_settings_service, push_service
from workers import push_worker

pytestmark = pytest.mark.asyncio

BANGKOK = app_settings_service.BANGKOK


# ── Helpers ─────────────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _raise(status: int):
    raise WebPushException(f"boom {status}", response=_FakeResponse(status))


async def _insert_user(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, 'Test', 'User', $2)
            RETURNING id
            """,
            f"{uuid.uuid4().hex[:12]}@example.com",
            f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('Test Room', $1, $2) RETURNING id",
            code,
            owner_id,
        )


async def _seed(pool, *, priority: str = "normal") -> tuple[int, int, int]:
    """สร้าง (notification_id, subscription) พร้อมแถว outbox ที่ trigger สร้างให้"""
    owner = await _insert_user(pool)
    room_id = await _insert_room(pool, owner)
    recipient = await _insert_user(pool)
    async with pool.acquire() as conn:
        sub_id = await conn.fetchval(
            """
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
            VALUES ($1, $2, 'p256dh', 'auth')
            RETURNING id
            """,
            recipient,
            f"https://push.example/{uuid.uuid4().hex}",
        )
        notification_id = await conn.fetchval(
            """
            INSERT INTO notifications (room_id, user_id, group_type, type, priority, title, body)
            VALUES ($1, $2, 'task', 'task_assigned', $3, 'มีงานใหม่', 'การบ้านหน้า 45')
            RETURNING id
            """,
            room_id,
            recipient,
            priority,
        )
        outbox_id = await conn.fetchval(
            "SELECT id FROM push_outbox WHERE notification_id = $1", notification_id
        )
    return notification_id, sub_id, outbox_id


async def _outbox(pool, outbox_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM push_outbox WHERE id = $1", outbox_id)


# ── 1. quiet hours ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "config, moment, expected",
    [
        # ปิดทั้งฟีเจอร์
        ({"enabled": False, "start": "22:00", "end": "07:00"}, "2026-11-01T23:00:00+07:00", False),
        # ช่วงปกติ (ไม่ข้ามเที่ยงคืน) 13:00–15:00
        ({"enabled": True, "start": "13:00", "end": "15:00"}, "2026-11-01T14:00:00+07:00", True),
        ({"enabled": True, "start": "13:00", "end": "15:00"}, "2026-11-01T15:00:00+07:00", False),
        ({"enabled": True, "start": "13:00", "end": "15:00"}, "2026-11-01T15:01:00+07:00", False),
        # ข้ามเที่ยงคืน 22:00–07:00
        ({"enabled": True, "start": "22:00", "end": "07:00"}, "2026-11-01T23:30:00+07:00", True),
        ({"enabled": True, "start": "22:00", "end": "07:00"}, "2026-11-02T02:00:00+07:00", True),
        ({"enabled": True, "start": "22:00", "end": "07:00"}, "2026-11-02T07:00:00+07:00", False),
        ({"enabled": True, "start": "22:00", "end": "07:00"}, "2026-11-02T12:00:00+07:00", False),
        # start == end = ปิด (ไม่ใช่เงียบ 24 ชม.)
        ({"enabled": True, "start": "09:00", "end": "09:00"}, "2026-11-01T09:00:00+07:00", False),
        # ค่าพัง ⇒ ไม่เงียบ
        ({"enabled": True, "start": "99:99", "end": "07:00"}, "2026-11-01T23:00:00+07:00", False),
        ({"enabled": True}, "2026-11-01T23:00:00+07:00", False),
        (None, "2026-11-01T23:00:00+07:00", False),
    ],
)
async def test_quiet_hours_boundaries(config, moment, expected):
    moment_dt = datetime.fromisoformat(moment)
    assert app_settings_service.is_quiet_at(config, moment_dt) is expected


async def test_quiet_hours_end_returns_next_opening_in_utc():
    config = {"enabled": True, "start": "22:00", "end": "07:00"}
    moment = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)  # = 03:00 น. วันที่ 2 (ไทย)
    resume = app_settings_service.quiet_hours_end(config, moment)
    assert resume == datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # 07:00 ไทย


async def test_quiet_hours_roundtrip_through_db(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    async with db_pool.acquire() as conn:
        default = await app_settings_service.get_quiet_hours(conn, room_id=room_id)
    assert default["enabled"] is False

    saved = await app_settings_service.set_quiet_hours(
        db_pool, room_id=room_id, enabled=True, start="22:00", end="07:00", updated_by=owner
    )
    assert saved == {"enabled": True, "start": "22:00", "end": "07:00"}

    async with db_pool.acquire() as conn:
        reread = await app_settings_service.get_quiet_hours(conn, room_id=room_id)
    assert reread == saved


async def test_quiet_hours_rejects_bad_format(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(Exception) as excinfo:
        await app_settings_service.set_quiet_hours(
            db_pool, room_id=room_id, enabled=True, start="25:00", end="07:00", updated_by=owner
        )
    assert type(excinfo.value).__name__ == "ValidationError"


# ── 2–4. worker ─────────────────────────────────────────────────────────────
async def test_drain_marks_sent(db_pool):
    _, _, outbox_id = await _seed(db_pool)
    sent: list[dict] = []

    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: sent.append(payload))

    assert stats["sent"] == 1 and stats["claimed"] == 1
    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "sent"
    assert row["sent_at"] is not None
    assert row["processing_at"] is None
    assert row["attempts"] == 1
    # payload ต้องพอกดเปิดแอปได้ แต่ไม่ใหญ่เกิน
    assert len(sent) == 1
    assert sent[0]["title"] == "มีงานใหม่"
    assert sent[0]["url"] == "/"
    assert sent[0]["tag"].startswith("cls-task-")


async def test_drain_gone_soft_deletes_device(db_pool):
    _, sub_id, outbox_id = await _seed(db_pool)

    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: _raise(410))

    assert stats["gone"] == 1
    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "stale"
    assert row["last_error"] is not None

    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval(
            "SELECT deleted_at FROM push_subscriptions WHERE id = $1", sub_id
        )
    assert deleted_at is not None, "อุปกรณ์ที่ตอบ 410 ต้องถูกถอดออกจากทะเบียน"


async def test_drain_retries_with_backoff_then_drops_at_ceiling(db_pool):
    _, _, outbox_id = await _seed(db_pool)
    now = datetime.now(timezone.utc)

    stats = await push_worker.drain_once(
        db_pool, sender=lambda sub, payload: _raise(503), now=now
    )
    assert stats["retry"] == 1
    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "retry"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] > now  # เลื่อนออกไปจริง ไม่ใช่ NOW()

    # ดันไปจนครบเพดาน — ต้องถูกทิ้ง ไม่ใช่ค้างในคิวตลอดกาล
    for attempt in range(2, push_service.MAX_ATTEMPTS + 1):
        later = now + timedelta(hours=1) * attempt
        await push_worker.drain_once(db_pool, sender=lambda sub, payload: _raise(503), now=later)

    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "dropped"
    assert row["attempts"] == push_service.MAX_ATTEMPTS


async def test_drain_marks_stale_when_device_removed_after_enqueue(db_pool):
    _, sub_id, outbox_id = await _seed(db_pool)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE push_subscriptions SET deleted_at = NOW() WHERE id = $1", sub_id)

    called = []
    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: called.append(1))

    assert stats["stale"] == 1
    assert called == [], "อุปกรณ์ที่ถูกลบแล้วต้องไม่ถูกยิง push"
    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "stale"
    assert row["attempts"] == 0, "การตัดสินว่า stale ไม่ใช่ความล้มเหลวของการส่ง"


async def test_quiet_hours_defers_without_consuming_attempts(db_pool):
    notification_id, _, outbox_id = await _seed(db_pool)
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    # สร้าง quiet hours ที่ "ครอบเวลาปัจจุบัน" เสมอ (ไม่ผูกกับเวลาเครื่อง)
    now = datetime.now(timezone.utc)
    local = now.astimezone(BANGKOK)
    start = (local - timedelta(hours=1)).strftime("%H:%M")
    end = (local + timedelta(hours=1)).strftime("%H:%M")
    async with db_pool.acquire() as conn:
        room_of_notification = await conn.fetchval(
            "SELECT room_id FROM notifications WHERE id = $1", notification_id
        )
    await app_settings_service.set_quiet_hours(
        db_pool, room_id=room_of_notification, enabled=True, start=start, end=end, updated_by=owner
    )

    called = []
    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: called.append(1), now=now)

    assert stats["deferred"] == 1
    assert called == []
    row = await _outbox(db_pool, outbox_id)
    assert row["status"] == "pending", "การเลื่อนส่งต้องไม่เปลี่ยนสถานะเป็น retry"
    assert row["attempts"] == 0, "การเลื่อนส่งต้องไม่กิน attempts"
    assert row["processing_at"] is None
    assert row["next_attempt_at"] > now


async def test_urgent_bypasses_quiet_hours(db_pool):
    _, _, outbox_id = await _seed(db_pool, priority="urgent")
    now = datetime.now(timezone.utc)
    local = now.astimezone(BANGKOK)
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    async with db_pool.acquire() as conn:
        target_room = await conn.fetchval(
            "SELECT n.room_id FROM notifications n JOIN push_outbox o ON o.notification_id = n.id WHERE o.id = $1",
            outbox_id,
        )
    await app_settings_service.set_quiet_hours(
        db_pool,
        room_id=target_room,
        enabled=True,
        start=(local - timedelta(hours=1)).strftime("%H:%M"),
        end=(local + timedelta(hours=1)).strftime("%H:%M"),
        updated_by=owner,
    )

    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: None, now=now)

    assert stats["sent"] == 1
    assert stats["deferred"] == 0


async def test_drain_reclaims_stale_processing_claim(db_pool):
    """worker ตายกลางทาง ⇒ แถวต้องกลับมาถูกหยิบได้ภายในไม่กี่นาที ไม่ค้างตลอดกาล"""
    _, _, outbox_id = await _seed(db_pool)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE push_outbox SET processing_at = NOW() - INTERVAL '30 minutes' WHERE id = $1",
            outbox_id,
        )

    stats = await push_worker.drain_once(db_pool, sender=lambda sub, payload: None)
    assert stats["sent"] == 1


# ── 5. การจัดประเภทข้อยกเว้น ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "status, expected",
    [
        (410, "gone"),
        (404, "gone"),
        (429, "retry"),
        (500, "retry"),
        (503, "retry"),
        (400, "dropped"),
        (401, "dropped"),
        (403, "dropped"),
        (413, "dropped"),
    ],
)
async def test_classify_webpush_status(status, expected):
    class _Resp:
        status_code = status

    assert push_service.classify_error(WebPushException("x", response=_Resp())) == expected


async def test_classify_network_error_is_retry():
    assert push_service.classify_error(ConnectionError("network down")) == "retry"
