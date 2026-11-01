"""📊 P6.5 — สถิติการส่ง push (`GET .../notifications/push/stats`)

═══════════════════════════════════════════════════════════════════════════════
สิ่งที่เทสต์ชุดนี้ล็อกไว้ (อ่านก่อนแก้)
═══════════════════════════════════════════════════════════════════════════════
1. **"จะลองใหม่" กับ "ยอมแพ้" ถูกนับแยก** — `retry` ≠ `dropped`/`stale`
   (กฎเหล็กข้อ 5: ตัวนับรวมกลุ่มจะซ่อนว่าอุปกรณ์จำนวนหนึ่งตายไปแล้ว)
2. **ศูนย์คือข้อมูลจริง** — ห้องที่ไม่มีแถว outbox ได้ 0 ทุกช่อง **แต่ยังได้
   `last_round`** (worker มีชีวิตอยู่ คิวว่าง) ⇒ ไม่ใช่ null
3. **"ไม่รู้" ≠ ศูนย์** — Redis ต่อไม่ได้/ไม่มี key ⇒ `last_round` เป็น `null`
   แต่ endpoint ยังตอบ 200 (สถิติไม่ใช่ด่านความปลอดภัย ⇒ fail-open)
4. **`due_now` ไม่รวมของที่ตั้งเวลาไว้ในอนาคต** — แถวที่เพิ่งถูกเลื่อนออกจาก
   quiet hours ยัง `pending` แต่ไม่ใช่ของค้าง
5. **ข้ามห้องไม่ได้** — สถิติผูกกับ `notifications.room_id`
6. **ต้องมี `MANAGE_CLASSROOM_SETTINGS`** — สมาชิกทั่วไปได้ 403

Pattern ตาม docs/rules/testing.md: seed ด้วย SQL ตรง ๆ, ตรวจค่าจริงจาก response,
และใช้ `_fake_redis` เท่านั้น (ห้ามต่อ Redis จริง)
"""

import random
import string
import uuid
from datetime import datetime, timezone

import pytest

from _fake_redis import BrokenRedis, FakeRedis
from core.config import settings
from core.worker_stats import LAST_ROUND_KEY, record_last_round
from main import app as real_app

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
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('Test Room', $1, $2) RETURNING id",
            code,
            owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)
            """,
            room_id,
            owner_id,
        )
        return room_id


async def _insert_member(pool, room_id: int, user_id: int, student_no: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)
            """,
            room_id,
            user_id,
            student_no,
        )


async def _add_subscription(pool, user_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
            VALUES ($1, $2, 'p256dh', 'auth')
            RETURNING id
            """,
            user_id,
            f"https://push.example/{uuid.uuid4().hex}",
        )


async def _add_outbox(
    pool,
    *,
    room_id: int,
    user_id: int,
    status: str,
    waited_seconds: int = 0,
    next_in_seconds: int = -60,
    sent_ago_seconds: int | None = None,
) -> int:
    """สร้าง notification (trigger สร้าง outbox ให้) แล้วปรับสถานะ/เวลาให้ตรงกรณีทดสอบ"""
    async with pool.acquire() as conn:
        notification_id = await conn.fetchval(
            """
            INSERT INTO notifications (room_id, user_id, group_type, type, priority, title, body)
            VALUES ($1, $2, 'task', 'task_assigned', 'normal', 'มีงานใหม่', 'การบ้านหน้า 45')
            RETURNING id
            """,
            room_id,
            user_id,
        )
        row = await conn.fetchrow(
            """
            UPDATE push_outbox
               SET status = $2,
                   attempts = CASE WHEN $2 = 'pending' THEN 0 ELSE 1 END,
                   created_at = NOW() - make_interval(secs => $3),
                   next_attempt_at = NOW() + make_interval(secs => $4),
                   sent_at = CASE
                               WHEN $5::int IS NULL THEN NULL
                               ELSE NOW() - make_interval(secs => $5::int)
                             END
             WHERE notification_id = $1
            RETURNING id
            """,
            notification_id,
            status,
            waited_seconds,
            next_in_seconds,
            sent_ago_seconds,
        )
        assert row is not None, "trigger ต้องสร้างแถว outbox ให้ subscription ที่ active"
        return int(row["id"])


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int) -> str:
    return f"/api/classroom/{room_id}/notifications/push/stats?target_type=room"


def _with_redis(fake, fn):
    original = real_app.state.redis
    real_app.state.redis = fake
    try:
        return fn()
    finally:
        real_app.state.redis = original


# ── 1. สิทธิ์ ────────────────────────────────────────────────────────────────
async def test_member_without_permission_gets_403(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    await _insert_member(db_pool, room_id, member, 1)

    resp = client.get(_api(room_id), headers=_headers(member))
    assert resp.status_code == 403


async def test_admin_gets_200(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    assert resp.status_code == 200


# ── 2. ตัวนับแยกกลุ่ม ───────────────────────────────────────────────────────
async def test_queue_counts_split_retry_from_dropped(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_member(db_pool, room_id, recipient, 1)
    await _add_subscription(db_pool, recipient)

    # ถึงกำหนดแล้ว (รอมา 10 นาที) — ต้องอยู่ใน due_now
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="pending", waited_seconds=600)
    # ตั้งเวลาไว้ในอนาคต (เพิ่งเลื่อนออกจาก quiet hours) — ยังไม่ถึงกำหนด
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="pending", next_in_seconds=1800)
    # จะลองใหม่ — ยังไม่ยอมแพ้
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="retry", waited_seconds=120)
    # ยอมแพ้สองแบบ — ต้องอยู่คนละช่อง
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="dropped", waited_seconds=900)
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="stale", waited_seconds=900)

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    assert resp.status_code == 200
    queue = resp.json()["queue"]

    assert queue["pending"] == 2
    assert queue["retry"] == 1
    assert queue["dropped"] == 1
    assert queue["stale"] == 1
    assert queue["due_now"] == 2, "pending อนาคตต้องไม่ถูกนับเป็นของค้าง"


async def test_oldest_due_seconds_measures_waiting_not_lateness(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_member(db_pool, room_id, recipient, 1)
    await _add_subscription(db_pool, recipient)

    # รอมา 15 นาที แต่เลยกำหนดเพียง 1 นาที ⇒ คำตอบต้องเป็น ~900 ไม่ใช่ ~60
    await _add_outbox(
        db_pool,
        room_id=room_id,
        user_id=recipient,
        status="pending",
        waited_seconds=900,
        next_in_seconds=-60,
    )

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    oldest = resp.json()["queue"]["oldest_due_seconds"]
    assert 880 <= oldest <= 940, f"ควรวัดเวลารอ ไม่ใช่เวลาที่เลยกำหนด (ได้ {oldest})"


async def test_sent_24h_ignores_older_sends(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_member(db_pool, room_id, recipient, 1)
    await _add_subscription(db_pool, recipient)

    await _add_outbox(
        db_pool, room_id=room_id, user_id=recipient, status="sent", sent_ago_seconds=3600
    )
    await _add_outbox(
        db_pool, room_id=room_id, user_id=recipient, status="sent", sent_ago_seconds=48 * 3600
    )

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    assert resp.json()["queue"]["sent_24h"] == 1


async def test_counts_do_not_leak_across_rooms(client, db_pool):
    owner_a = await _insert_user(db_pool)
    room_a = await _insert_room(db_pool, owner_a)
    recipient_a = await _insert_user(db_pool)
    await _insert_member(db_pool, room_a, recipient_a, 1)
    await _add_subscription(db_pool, recipient_a)

    owner_b = await _insert_user(db_pool)
    room_b = await _insert_room(db_pool, owner_b)
    recipient_b = await _insert_user(db_pool)
    await _insert_member(db_pool, room_b, recipient_b, 1)
    await _add_subscription(db_pool, recipient_b)

    await _add_outbox(db_pool, room_id=room_a, user_id=recipient_a, status="retry")
    await _add_outbox(db_pool, room_id=room_b, user_id=recipient_b, status="retry")
    await _add_outbox(db_pool, room_id=room_b, user_id=recipient_b, status="retry")

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_a), headers=_headers(owner_a)))
    assert resp.json()["queue"]["retry"] == 1, "ต้องเห็นเฉพาะคิวของห้องตัวเอง"


# ── 3. รอบล่าสุด (Redis) ────────────────────────────────────────────────────
async def test_last_round_is_reported_with_deferred_and_enabled(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    fake = FakeRedis()
    await record_last_round(
        fake,
        claimed=5,
        sent=2,
        retry=1,
        gone=0,
        dropped=1,
        deferred=3,
        stale=0,
        enabled=True,
        now=1_800_000_000,
    )

    resp = _with_redis(fake, lambda: client.get(_api(room_id), headers=_headers(owner)))
    last = resp.json()["last_round"]

    assert last is not None
    assert last["claimed"] == 5
    assert last["sent"] == 2
    assert last["deferred"] == 3, "quiet/deferred ต้องมาจากรอบของ worker เท่านั้น"
    assert last["enabled"] is True
    assert datetime.fromisoformat(last["at"]).timestamp() == 1_800_000_000


async def test_no_round_recorded_means_unknown_not_zero(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = _with_redis(FakeRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    body = resp.json()

    assert body["queue"] == {
        "pending": 0,
        "retry": 0,
        "dropped": 0,
        "stale": 0,
        "sent_24h": 0,
        "due_now": 0,
        "oldest_due_seconds": 0,
    }
    assert body["last_round"] is None, "ไม่เคยรัน ≠ รันแล้วแต่ไม่มีงาน"
    assert body["worker_heartbeat_age_seconds"] is None


async def test_zero_round_is_reported_as_zero_not_unknown(client, db_pool):
    """รอบที่ไม่มีงาน = ข้อมูลจริง (worker มีชีวิต คิวว่าง) — UI ต้องแยกออกจาก null"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    fake = FakeRedis()
    await record_last_round(
        fake, claimed=0, sent=0, retry=0, gone=0, dropped=0, deferred=0, stale=0
    )

    resp = _with_redis(fake, lambda: client.get(_api(room_id), headers=_headers(owner)))
    last = resp.json()["last_round"]
    assert last is not None
    assert last["claimed"] == 0 and last["sent"] == 0


async def test_broken_redis_still_returns_queue(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    recipient = await _insert_user(db_pool)
    await _insert_member(db_pool, room_id, recipient, 1)
    await _add_subscription(db_pool, recipient)
    await _add_outbox(db_pool, room_id=room_id, user_id=recipient, status="retry")

    resp = _with_redis(BrokenRedis(), lambda: client.get(_api(room_id), headers=_headers(owner)))
    body = resp.json()

    assert resp.status_code == 200, "Redis ล่มต้องไม่ทำให้หน้าสถิติล้ม"
    assert body["queue"]["retry"] == 1
    assert body["last_round"] is None
    assert body["worker_heartbeat_age_seconds"] is None


async def test_last_round_key_is_stored_with_ttl(client, db_pool):
    """กันลืม TTL: ถ้า worker ตาย ค่าค้างจะหลอกว่า 'เพิ่งส่งสำเร็จ' ตลอดไป"""
    fake = FakeRedis()
    await record_last_round(
        fake, claimed=1, sent=1, retry=0, gone=0, dropped=0, deferred=0, stale=0
    )

    assert LAST_ROUND_KEY in fake.store
    expires_at = fake.store[LAST_ROUND_KEY][1]
    assert expires_at is not None
    assert 0 < await fake.ttl(LAST_ROUND_KEY) <= 3600


async def test_corrupt_payload_is_unknown_not_partial(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    fake = FakeRedis()
    await fake.set(LAST_ROUND_KEY, '{"at": 1, "claimed": 3}')  # ขาด key ที่เหลือ

    resp = _with_redis(fake, lambda: client.get(_api(room_id), headers=_headers(owner)))
    assert resp.json()["last_round"] is None, "payload ไม่ครบ = ไม่รู้ ดีกว่าเดาเป็นศูนย์"


@pytest.mark.parametrize("bad", ["not-json", "[]", "null"])
async def test_malformed_payload_never_raises(client, db_pool, bad):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    fake = FakeRedis()
    await fake.set(LAST_ROUND_KEY, bad)

    resp = _with_redis(fake, lambda: client.get(_api(room_id), headers=_headers(owner)))
    assert resp.status_code == 200
    assert resp.json()["last_round"] is None
