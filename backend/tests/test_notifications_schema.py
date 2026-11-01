"""
สคีมาแพลตฟอร์มแจ้งเตือน (migration 0002) — ล็อกพฤติกรรมที่ "พังแล้วเงียบ"

ครอบคลุม:
  1. ตารางทั้ง 6 ตัวถูกสร้างจริงจาก `apply_migrations` (ไม่ใช่แค่ `init_db`)
  2. migration เป็น idempotent — รันซ้ำแล้วไม่ล้ม ไม่สร้างตารางซ้ำ
  3. trigger `AFTER INSERT ON notifications` ยิง `pg_notify` จริง (SSE พึ่งตัวนี้)
  4. **ประตูตอนเข้าคิว**: push_outbox เกิดเฉพาะเมื่อ "มีทางสำเร็จ"
     - มีอุปกรณ์ active + ไม่ได้ปิด push  → เข้าคิว
     - ปิด push ของกลุ่มนั้น            → **ไม่** เข้าคิว
     - อุปกรณ์ถูกลบ (soft delete)       → **ไม่** เข้าคิว
     - ประกาศ (announcement) ปิดไม่ได้  → เข้าคิวแม้มี preference push=false
  5. constraint: กลุ่มที่ไม่รู้จัก / สถานะ outbox มั่ว / priority มั่ว ถูกปฏิเสธที่ DB

⚠️ ทำไมต้องเช็คข้อ 4 ที่ระดับ DB: กฎนี้อยู่ใน trigger ซึ่งเป็น SQL ล้วน —
   ถ้ามีคนไปแก้เงื่อนไขใน trigger ภายหลัง เทสต์ชุดนี้คือที่ที่จะพังก่อน production
"""
import asyncio
import json
import random
import string
import uuid

import pytest

from core.migrations.runner import apply_migrations

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────────────────
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


async def _insert_subscription(pool, user_id: int, *, deleted: bool = False) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, deleted_at)
            VALUES ($1, $2, 'p256dh', 'auth', CASE WHEN $3 THEN NOW() ELSE NULL END)
            RETURNING id
            """,
            user_id,
            f"https://push.example/{uuid.uuid4().hex}",
            deleted,
        )


async def _insert_notification(pool, room_id: int, user_id: int, **overrides):
    values = {
        "group_type": "task",
        "type": "task_assigned",
        "priority": "normal",
        "title": "มีงานใหม่",
        "body": "การบ้านหน้า 45",
    }
    values.update(overrides)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notifications
                (room_id, user_id, group_type, type, priority, title, body)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            room_id,
            user_id,
            values["group_type"],
            values["type"],
            values["priority"],
            values["title"],
            values["body"],
        )


async def _outbox_count(pool, user_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM push_outbox o
            JOIN notifications n ON n.id = o.notification_id
            WHERE n.user_id = $1
            """,
            user_id,
        )


# ── 1. ตารางครบ ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "table",
    [
        "notifications",
        "push_subscriptions",
        "push_outbox",
        "notification_preferences",
        "app_settings",
        "announcements",
    ],
)
async def test_all_notification_tables_exist(db_pool, table):
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
    assert exists is not None, f"ตาราง {table} ไม่ถูกสร้างโดย migration 0002"


# ── 2. idempotent ───────────────────────────────────────────────────────────
async def test_migrations_are_idempotent(db_pool):
    """รันซ้ำต้องไม่ execute อะไรเลย (ทุกไฟล์ถูกบันทึกใน schema_migrations แล้ว)"""
    applied_again = await apply_migrations(db_pool)
    assert applied_again == 0

    async with db_pool.acquire() as conn:
        versions = [r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")]
    assert "0002_notifications" in versions


# ── 3. pg_notify ────────────────────────────────────────────────────────────
async def test_trigger_notifies_with_pointer_only(db_pool):
    """SSE พึ่ง pg_notify — payload ต้องมีแค่ตัวชี้ ไม่มีเนื้อหาข้อความ"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)

    event = asyncio.Event()
    received: list[dict] = []

    listen_conn = await db_pool.acquire()
    try:
        def _on_notify(_conn, _pid, _channel, payload):
            received.append(json.loads(payload))
            event.set()

        await listen_conn.add_listener("classroom_notify", _on_notify)
        await _insert_notification(db_pool, room_id, recipient, title="ความลับ")
        await asyncio.wait_for(event.wait(), timeout=5)
    finally:
        await listen_conn.remove_listener("classroom_notify", _on_notify)
        await db_pool.release(listen_conn)

    assert len(received) == 1
    assert received[0]["user_id"] == recipient
    assert received[0]["room_id"] == room_id
    assert set(received[0]) == {"user_id", "room_id", "id"}, "payload ต้องมีแค่ตัวชี้"
    assert "ความลับ" not in json.dumps(received[0], ensure_ascii=False)


# ── 4. ประตูตอนเข้าคิว ──────────────────────────────────────────────────────
async def test_outbox_enqueued_when_device_exists_and_push_on(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    sub_id = await _insert_subscription(db_pool, recipient)

    await _insert_notification(db_pool, room_id, recipient)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT subscription_id, status, attempts FROM push_outbox WHERE notification_id = "
            "(SELECT id FROM notifications WHERE user_id = $1)",
            recipient,
        )
    assert len(rows) == 1
    assert rows[0]["subscription_id"] == sub_id
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempts"] == 0


async def test_outbox_skipped_when_push_disabled_for_group(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_subscription(db_pool, recipient)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_preferences (user_id, group_type, inapp, push)
            VALUES ($1, 'task', TRUE, FALSE)
            """,
            recipient,
        )

    await _insert_notification(db_pool, room_id, recipient, group_type="task")
    assert await _outbox_count(db_pool, recipient) == 0

    # กลุ่มอื่นที่ไม่ได้ปิด ยังเข้าคิวปกติ ⇒ สวิตช์ต้องแยกตามกลุ่ม ไม่ใช่เหมาโหล
    await _insert_notification(db_pool, room_id, recipient, group_type="finance", type="finance_receipt")
    assert await _outbox_count(db_pool, recipient) == 1


async def test_outbox_skipped_when_subscription_soft_deleted(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_subscription(db_pool, recipient, deleted=True)

    await _insert_notification(db_pool, room_id, recipient)
    assert await _outbox_count(db_pool, recipient) == 0


async def test_announcement_cannot_be_muted(db_pool):
    """ประกาศปิดไม่ได้ — preference push=false ต้องไม่มีผลกับกลุ่ม announcement"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_subscription(db_pool, recipient)

    async with db_pool.acquire() as conn:
        # CHECK ของ notification_preferences ไม่อนุญาต group = announcement
        # ⇒ จำลอง "ผู้ใช้ที่ปิดทุกกลุ่มที่ปิดได้" แล้วประกาศต้องยังเข้าคิว
        await conn.executemany(
            "INSERT INTO notification_preferences (user_id, group_type, inapp, push) VALUES ($1, $2, TRUE, FALSE)",
            [(recipient, g) for g in ("task", "finance", "activity", "member")],
        )

    await _insert_notification(
        db_pool, room_id, recipient, group_type="announcement", type="announcement_new"
    )
    assert await _outbox_count(db_pool, recipient) == 1


# ── 5. constraint ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "overrides",
    [
        {"group_type": "unknown"},
        {"priority": "critical"},
    ],
)
async def test_invalid_values_rejected(db_pool, overrides):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)

    with pytest.raises(Exception) as excinfo:
        await _insert_notification(db_pool, room_id, recipient, **overrides)
    assert "CheckViolation" in type(excinfo.value).__name__


async def test_outbox_status_rejects_unknown_value(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    sub_id = await _insert_subscription(db_pool, recipient)
    await _insert_notification(db_pool, room_id, recipient)
    notification_id = await db_pool.fetchval(
        "SELECT id FROM notifications WHERE user_id = $1", recipient
    )

    async with db_pool.acquire() as conn:
        with pytest.raises(Exception) as excinfo:
            await conn.execute(
                "INSERT INTO push_outbox (notification_id, subscription_id, status) VALUES ($1, $2, 'queued')",
                notification_id,
                sub_id,
            )
    assert "CheckViolation" in type(excinfo.value).__name__
