"""
Integration tests for:
1. rooms.birthday_channel_id / rooms.minor_notify_channel_id columns + set_channel(channel_type=...)
2. GET /api/classroom/birthdays/today — หาคนที่วันเกิดวันนี้ (system RPC สำหรับบอท)
3. ActionService low-priority events → channel="minor" (ส่งไปห้องแจ้งเตือนงานเล็กๆน้อยๆ)

ครอบคลุม:
- set_channel รองรับ channel_type 3 แบบ (announcement/birthday/minor) → เขียนคอลัมน์ถูกตัว
- channel_type ไม่ถูกต้อง → ValueError (400)
- get_room_data คืนคอลัมน์ใหม่ทั้ง 2
- get_birthday_celebrants: ตรงวันเกิด → ถูกต้อง, ต่างวัน → ไม่คืน, ห้องไม่มีช่อง → ไม่คืน
- birthdays/today ผ่าน X-API-Key (system RPC) ได้ ไม่ต้องเป็น member
- low-priority notify_* → publish channel="minor"; งานใหม่/โน้ต/ประกาศ/เก็บเงิน → channel="announcement"
"""
import random
import string
import uuid
from datetime import date
from unittest.mock import patch, AsyncMock

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


# === Helpers ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", discord_id=None, birthday=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id, birthday)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}", discord_id, birthday,
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None, channel_id=None,
                       birthday_channel_id=None, minor_channel_id=None) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id, announcement_channel_id,
                               birthday_channel_id, minor_notify_channel_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            room_name, code, owner_id, server_id, channel_id, birthday_channel_id, minor_channel_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, status="active") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status)
            VALUES ($1, $2, $3, 'student', $4)
            RETURNING id
            """,
            room_id, user_id, student_no, status,
        )


def _bot_headers(discord_id: int = 999999999) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


# === Section 1: set_channel(channel_type=...) ===


async def test_set_channel_birthday_type_writes_birthday_column(db_pool):
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    birthday_channel = random.randint(100_000, 999_999)
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=birthday_channel, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test", channel_type="birthday",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id, birthday_channel_id, minor_notify_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["birthday_channel_id"] == birthday_channel
        assert row["announcement_channel_id"] is None
        assert row["minor_notify_channel_id"] is None


async def test_set_channel_minor_type_writes_minor_column(db_pool):
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    minor_channel = random.randint(100_000, 999_999)
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=minor_channel, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test", channel_type="minor",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT minor_notify_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["minor_notify_channel_id"] == minor_channel


async def test_set_channel_invalid_type_raises_value_error(db_pool):
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(ValueError):
        await ClassroomService.set_channel(
            pool=db_pool, channel_id=123, user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test", channel_type="garbage",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id, birthday_channel_id, minor_notify_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] is None
        assert row["birthday_channel_id"] is None
        assert row["minor_notify_channel_id"] is None


async def test_set_channel_default_type_still_announcement(client, db_pool):
    """channel_type ไม่ส่ง (bot เดิม) → ยังเขียน announcement_channel_id เหมือนเดิม"""
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    channel_id = random.randint(100_000, 999_999)
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=channel_id, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] == channel_id


# === Section 2: get_room_data returns new columns ===


async def test_get_room_data_returns_new_channel_columns(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    main_channel = random.randint(100_000, 999_999)
    bday_channel = random.randint(100_000, 999_999)
    minor_channel = random.randint(100_000, 999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id, channel_id=main_channel,
                                 birthday_channel_id=bday_channel, minor_channel_id=minor_channel)

    resp = client.get(f"/api/classroom/{server_id}?target_type=server", headers=_bot_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == room_id
    assert data["birthday_channel_id"] == bday_channel
    assert data["minor_notify_channel_id"] == minor_channel
    assert data["announcement_channel_id"] == main_channel


# === Section 3: get_birthday_celebrants ===


async def test_birthday_celebrants_match_today(db_pool):
    from services.classroom_sync_service import ClassroomService
    from services.classroom_sync_service import THAI_TZ
    from datetime import datetime

    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id, channel_id=random.randint(100_000, 999_999))

    # ผู้ใช้คนหนึ่งเกิดวันนี้ (ปีใดก็ได้ — ระบบเทียบเดือน/วัน)
    today = datetime.now(THAI_TZ).date()
    birthday_user = await _insert_user(db_pool, first_name="สิงโต", last_name="ใจดี", birthday=today)
    await _insert_student(db_pool, room_id, birthday_user, 1)

    rooms = await ClassroomService.get_birthday_celebrants(
        pool=db_pool, target_date=today,
        client_source="test", actor_identifier="test",
    )
    assert len(rooms) == 1
    assert rooms[0]["server_id"] == server_id
    names = [c["first_name"] for c in rooms[0]["celebrants"]]
    assert "สิงโต" in names


async def test_birthday_celebrants_wrong_day_excluded(db_pool):
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999),
                                 channel_id=random.randint(100_000, 999_999))

    birthday_user = await _insert_user(db_pool, first_name="คนอื่น", last_name="ไม่ตรง", birthday=date(2008, 1, 1))
    await _insert_student(db_pool, room_id, birthday_user, 2)

    today = date(2026, 8, 7)  # วันนี้ของระบบ (เห็นที่ 1 ม.ค. ไม่ตรง)
    rooms = await ClassroomService.get_birthday_celebrants(
        pool=db_pool, target_date=today,
        client_source="test", actor_identifier="test",
    )
    assert rooms == []


async def test_birthday_celebrants_room_without_channel_excluded(db_pool):
    """ห้องที่ยังไม่ตั้งช่องไหน (announcement/birthday/minor เป็น NULL) → ไม่คืน"""
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999))  # ไม่มี channel

    birthday_user = await _insert_user(db_pool, first_name="สิงโต", last_name="ใจดี", birthday=date(2008, 8, 7))
    await _insert_student(db_pool, room_id, birthday_user, 1)

    rooms = await ClassroomService.get_birthday_celebrants(
        pool=db_pool, target_date=date(2026, 8, 7),
        client_source="test", actor_identifier="test",
    )
    assert rooms == []


async def test_birthday_celebrants_pending_student_excluded(db_pool):
    """สมาชิกที่ยัง pending → ไม่ถูกนับเป็นคนเกิดวันนี้"""
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999),
                                 channel_id=random.randint(100_000, 999_999))

    birthday_user = await _insert_user(db_pool, first_name="รออนุมัติ", last_name="ยังไม่เข้า", birthday=date(2008, 8, 7))
    await _insert_student(db_pool, room_id, birthday_user, 1, status="pending")

    rooms = await ClassroomService.get_birthday_celebrants(
        pool=db_pool, target_date=date(2026, 8, 7),
        client_source="test", actor_identifier="test",
    )
    assert rooms == []


async def test_birthday_endpoint_requires_api_key(client, db_pool):
    """GET /birthdays/today ไม่มี X-API-Key → 401"""
    resp = client.get("/api/classroom/birthdays/today", params={"target_date": "2026-08-07"})
    assert resp.status_code == 401


async def test_birthday_endpoint_bot_path(client, db_pool):
    """บอทเรียก GET /birthdays/today ด้วย X-API-Key → 200 + คนที่เกิดวันนี้"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id,
                                 birthday_channel_id=random.randint(100_000, 999_999),
                                 channel_id=random.randint(100_000, 999_999))

    birthday_user = await _insert_user(db_pool, first_name="สิงโต", last_name="ใจดี", birthday=date(2008, 8, 7))
    await _insert_student(db_pool, room_id, birthday_user, 1)

    resp = client.get("/api/classroom/birthdays/today", params={"target_date": "2026-08-07"}, headers=_bot_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["server_id"] == server_id
    assert data[0]["birthday_channel_id"] is not None
    assert "สิงโต" in [c["first_name"] for c in data[0]["celebrants"]]


async def test_birthday_leap_year_matches_feb_29(db_pool):
    """คนเกิด 29 ก.พ. → ตรงกับวันที่ 29 ก.พ. (ปีใดก็ได้)"""
    from services.classroom_sync_service import ClassroomService
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999),
                                 channel_id=random.randint(100_000, 999_999))

    leap_user = await _insert_user(db_pool, first_name="ลีป", last_name="เดย์", birthday=date(2008, 2, 29))
    await _insert_student(db_pool, room_id, leap_user, 1)

    # 2028 เป็นปีอธิกสุรทิน → 29 ก.พ. มีจริง
    rooms = await ClassroomService.get_birthday_celebrants(
        pool=db_pool, target_date=date(2028, 2, 29),
        client_source="test", actor_identifier="test",
    )
    assert len(rooms) == 1
    assert rooms[0]["celebrants"][0]["first_name"] == "ลีป"


# === Section 4: ActionService low-priority → minor channel ===


async def test_low_priority_events_publish_to_minor_channel(db_pool):
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_task_done(server_id, "งาน", "นร.")
        await ActionService.notify_new_finance(server_id, "income", 500.0, "รายได้", "เหรัญญิก")
        await ActionService.notify_payment_confirmed(server_id, "สิงโต", "ค่าเทอม", 1000.0, "เหรัญญิก")
        await ActionService.notify_new_student(server_id, 5, "สมชาย", "ใจดี", "ครู")

    channels = [call.kwargs.get("channel") for call in mock_pub.await_args_list]
    assert all(c == "minor" for c in channels)


async def test_important_events_publish_to_announcement_channel(db_pool):
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_new_task(server_id, "งาน", "ละเอียด", "2026-08-10", "ครู")
        await ActionService.notify_new_note(server_id, "2026-08-10", "หัวข้อ", "ครู")
        await ActionService.notify_custom_message(server_id, "หัว", "ข้อความ", "ครู")
        await ActionService.notify_new_collection(server_id, "ค่าเทอม", 1000.0, "2026-08-10", "เหรัญญิก")

    channels = [call.kwargs.get("channel") for call in mock_pub.await_args_list]
    assert all(c == "announcement" for c in channels)


async def test_publish_payload_includes_channel_field(client, db_pool):
    """_publish จริงใส่ channel ลง payload (ผ่าน patch aioredis กัน Redis จริง)"""
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch("services.action_service.aioredis.from_url") as mock_redis:
        mock_pubsub = AsyncMock()
        mock_redis.return_value.publish = mock_pubsub
        mock_redis.return_value.aclose = AsyncMock()

        await ActionService.notify_task_done(server_id, "งาน", "นร.")

    args, kwargs = mock_pubsub.call_args
    import json as _json
    # publish(channel_name, json_string) → JSON อยู่ตำแหน่ง args[1]
    payload = _json.loads(args[1])
    assert payload["event"] == "TASK_DONE"
    assert payload["channel"] == "minor"
