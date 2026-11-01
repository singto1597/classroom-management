"""
Integration tests — แจ้งเตือนในแอป (`routers/notification_router.py`)

สิ่งที่ล็อกไว้ (เพราะพังแล้ว "ไม่มีใครรู้" ไม่ใช่พังดัง ๆ):
  1. **ไม่เห็นของคนอื่น**: รายการ/ตัวเลข/ทำเครื่องหมายอ่าน แยกตามผู้ใช้จริง ๆ
     และการยิง mark-read ใส่ไอดีของคนอื่นต้องตอบ `marked=False` โดยไม่แตะแถว
  2. **กระดิ่ง = รายการ**: `unread_count` จาก endpoint ต้องเท่ากับจำนวนที่ไม่ถูกอ่าน
     ในลิสต์เดียวกัน **หลังกรอง preference** (บั๊ก "34 กดแล้วเจอ 5" เวอร์ชันแจ้งเตือน)
  3. **preference inapp=false** ซ่อนจากทั้งรายการและตัวเลข — สองที่ต้องขยับพร้อมกัน
  4. **ไม่ใช่สมาชิก ⇒ 403** แม้จะถือ JWT ที่ถูกต้อง
  5. **fan-out ของ stream** ส่งถึงเฉพาะผู้ใช้เจ้าของ และคิวเต็มแล้วทิ้งสัญญาณ
     ไม่ทำให้ fan-out ค้าง (ทดสอบที่ระดับ service เพราะ endpoint เป็น SSE ไม่รู้จบ)

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
และไม่แตะ Redis/Discord (เส้นทางนี้ไม่ได้เรียก ActionService เลย)
"""
import asyncio
import random
import string
import uuid

import pytest

from core.config import settings
from services import notification_service
from services.notification_stream import NotificationStream

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


async def _insert_student(pool, room_id: int, user_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)
            RETURNING id
            """,
            room_id,
            user_id,
            student_no,
        )


async def _seed_notification(pool, room_id: int, user_id: int, **overrides) -> int:
    values = {
        "group_type": "task",
        "type": "task_assigned",
        "title": "มีงานใหม่",
        "body": "การบ้านหน้า 45",
    }
    values.update(overrides)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO notifications (room_id, user_id, group_type, type, priority, title, body)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            room_id,
            user_id,
            values["group_type"],
            values["type"],
            values.get("priority", "normal"),
            values["title"],
            values["body"],
        )


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int, path: str) -> str:
    return f"/api/classroom/{room_id}{path}?target_type=room"


# ── 1. รายการแยกตามผู้ใช้ ───────────────────────────────────────────────────
async def test_list_returns_only_own_notifications(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    alice = await _insert_user(db_pool)
    bob = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, alice, 1)
    await _insert_student(db_pool, room_id, bob, 2)

    await _seed_notification(db_pool, room_id, alice, title="ของอลิส")
    await _seed_notification(db_pool, room_id, bob, title="ของบ๊อบ")

    resp = client.get(_api(room_id, "/notifications"), headers=_headers(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert [item["title"] for item in body["items"]] == ["ของอลิส"]
    assert body["unread_count"] == 1
    assert body["has_more"] is False


async def test_non_member_is_forbidden(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool)

    resp = client.get(_api(room_id, "/notifications"), headers=_headers(outsider))
    assert resp.status_code == 403


# ── 2–3. กระดิ่ง = รายการ (หลังกรอง preference) ──────────────────────────────
async def test_unread_count_matches_list_after_preference_filter(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    user = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, user, 1)

    await _seed_notification(db_pool, room_id, user, group_type="task")
    await _seed_notification(db_pool, room_id, user, group_type="finance", type="finance_receipt")
    await _seed_notification(db_pool, room_id, user, group_type="activity", type="activity_open")

    # ปิดการเงินในแอป
    put = client.put(
        _api(room_id, "/notifications/preferences"),
        json={"group_type": "finance", "inapp": False, "push": True},
        headers=_headers(user),
    )
    assert put.status_code == 200

    listed = client.get(_api(room_id, "/notifications"), headers=_headers(user)).json()
    count = client.get(_api(room_id, "/notifications/unread-count"), headers=_headers(user)).json()

    assert len(listed["items"]) == 2
    assert "finance" not in [item["group_type"] for item in listed["items"]]
    assert listed["unread_count"] == count["unread_count"] == 2


async def test_pagination_has_more_and_cursor(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    for _ in range(5):
        await _seed_notification(db_pool, room_id, owner)

    first = client.get(
        f"/api/classroom/{room_id}/notifications?target_type=room&limit=2",
        headers=_headers(owner),
    )
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["items"]) == 2
    assert page1["has_more"] is True

    before_id = page1["items"][-1]["id"]
    second = client.get(
        f"/api/classroom/{room_id}/notifications?target_type=room&limit=2&before_id={before_id}",
        headers=_headers(owner),
    ).json()
    assert len(second["items"]) == 2
    assert all(item["id"] < before_id for item in second["items"])
    # ไม่มี id ซ้ำข้ามหน้า
    assert not ({i["id"] for i in page1["items"]} & {i["id"] for i in second["items"]})


# ── 4. mark read ────────────────────────────────────────────────────────────
async def test_mark_read_does_not_touch_other_users_row(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    alice = await _insert_user(db_pool)
    bob = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, alice, 1)
    await _insert_student(db_pool, room_id, bob, 2)

    bobs = await _seed_notification(db_pool, room_id, bob)

    resp = client.post(_api(room_id, f"/notifications/{bobs}/read"), headers=_headers(alice))
    assert resp.status_code == 200
    assert resp.json() == {"notification_id": bobs, "marked": False}

    async with db_pool.acquire() as conn:
        read_at = await conn.fetchval("SELECT read_at FROM notifications WHERE id = $1", bobs)
    assert read_at is None, "แถวของคนอื่นต้องไม่ถูกแตะ"


async def test_mark_read_is_idempotent_and_keeps_first_timestamp(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    nid = await _seed_notification(db_pool, room_id, owner)

    first = client.post(_api(room_id, f"/notifications/{nid}/read"), headers=_headers(owner)).json()
    async with db_pool.acquire() as conn:
        first_read_at = await conn.fetchval("SELECT read_at FROM notifications WHERE id = $1", nid)
    await asyncio.sleep(0.05)
    second = client.post(_api(room_id, f"/notifications/{nid}/read"), headers=_headers(owner)).json()
    async with db_pool.acquire() as conn:
        second_read_at = await conn.fetchval("SELECT read_at FROM notifications WHERE id = $1", nid)

    assert first == second == {"notification_id": nid, "marked": True}
    assert first_read_at == second_read_at, "เวลาอ่านครั้งแรกต้องไม่ถูกทับ"


async def test_mark_all_read_only_affects_current_room(client, db_pool):
    owner = await _insert_user(db_pool)
    room_a = await _insert_room(db_pool, owner)
    room_b = await _insert_room(db_pool, owner)  # owner เป็น admin ทั้งสองห้อง

    await _seed_notification(db_pool, room_a, owner)
    await _seed_notification(db_pool, room_a, owner)
    other_room = await _seed_notification(db_pool, room_b, owner)

    resp = client.post(_api(room_a, "/notifications/read-all"), headers=_headers(owner))
    assert resp.status_code == 200
    assert resp.json()["marked_count"] == 2

    async with db_pool.acquire() as conn:
        still_unread = await conn.fetchval(
            "SELECT read_at FROM notifications WHERE id = $1", other_room
        )
    assert still_unread is None


# ── 5. preference ───────────────────────────────────────────────────────────
async def test_preferences_return_all_groups_with_defaults(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    body = client.get(_api(room_id, "/notifications/preferences"), headers=_headers(owner)).json()
    assert [item["group_type"] for item in body["items"]] == ["task", "finance", "activity", "member"]
    assert all(item["inapp"] and item["push"] for item in body["items"])


async def test_announcement_preference_rejected(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = client.put(
        _api(room_id, "/notifications/preferences"),
        json={"group_type": "announcement", "inapp": False, "push": False},
        headers=_headers(owner),
    )
    assert resp.status_code == 422, "ประกาศต้องปิดไม่ได้ (Literal ไม่รับ announcement)"


# ── 6. fan-out ของ stream ───────────────────────────────────────────────────
async def test_stream_fans_out_only_to_owner_and_drops_when_full():
    stream = NotificationStream()
    alice_q = stream.subscribe(1)
    bob_q = stream.subscribe(2)

    stream._on_notify(None, 0, "classroom_notify", '{"user_id": 1, "room_id": 9, "id": 7}')

    assert alice_q.qsize() == 1
    assert bob_q.qsize() == 0
    assert alice_q.get_nowait()["id"] == 7

    # คิวเต็ม (maxsize=1) ⇒ สัญญาณที่สองถูกทิ้ง ไม่ใช่บล็อก fan-out
    stream._on_notify(None, 0, "classroom_notify", '{"user_id": 1, "room_id": 9, "id": 8}')
    stream._on_notify(None, 0, "classroom_notify", '{"user_id": 1, "room_id": 9, "id": 9}')
    assert alice_q.qsize() == 1

    stream.unsubscribe(1, alice_q)
    assert stream.subscriber_count == 1


async def test_stream_endpoint_rejects_non_member(client, db_pool):
    """ปลายทาง SSE ใช้ dependency ชุดเดียวกับ endpoint อื่น — คนนอกต้องไม่ได้สตรีม

    ⚠️ **ไม่ทดสอบการอ่านสตรีมที่นี่**: `TestClient` ต้องอ่านจนจบ response ถึงจะคืน
    แต่สตรีมจะไม่จบเอง (ตั้งใจ) ⇒ เทสต์จะค้างจน CI timeout
    ส่วน fan-out ถูกทดสอบที่ระดับ service (`test_stream_fans_out_only_to_owner_...`)
    และการต่อจริงควรตรวจใน e2e/staging
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool)

    resp = client.get(_api(room_id, "/notifications/stream"), headers=_headers(outsider))
    assert resp.status_code == 403


async def test_stream_ignores_malformed_payload():
    stream = NotificationStream()
    queue = stream.subscribe(1)
    stream._on_notify(None, 0, "classroom_notify", "not-json")
    stream._on_notify(None, 0, "classroom_notify", '{"room_id": 1}')
    assert queue.qsize() == 0


# ── 7. service: fan-out ต่อห้อง ─────────────────────────────────────────────
async def test_notify_room_targets_active_members_with_accounts(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    with_account = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, with_account, 1)

    # สมาชิกที่ไม่มีบัญชี (ยังไม่ผูก user) — ต้องไม่ถูกสร้างแถวให้
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, NULL, 3, 'student', 'active', FALSE, '[]'::jsonb)
            """,
            room_id,
        )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            created = await notification_service.notify_room(
                conn,
                room_id=room_id,
                group_type="task",
                type="task_new",
                title="งานใหม่ทั้งห้อง",
                exclude_user_ids=[owner],
            )

    assert created == 1
    async with db_pool.acquire() as conn:
        recipients = await conn.fetch(
            "SELECT user_id FROM notifications WHERE room_id = $1", room_id
        )
    assert [r["user_id"] for r in recipients] == [with_account]
