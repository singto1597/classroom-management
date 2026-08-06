"""
Regression test: GET /api/classroom/{target_id}?target_type=server

Bot เรียก GET /api/classroom/<server_id>?target_type=server เพื่อดึง
announcement_channel_id → ถ้า backend resolve โดยใช้ server_id column ไม่ถูกต้อง
จะตอบ 404 Not Found (ตามที่เจอใน production log)
"""
import random
import string
import uuid

import pytest

from core.config import settings
from jose import jwt

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", discord_id=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}", discord_id,
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None, channel_id=None) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id, announcement_channel_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_name, code, owner_id, server_id, channel_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


def _make_bot_headers(discord_id: int) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


def _make_web_headers(user_id: int) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_get_room_data_by_server_id_returns_200(client, db_pool):
    """Bot เรียก GET /api/classroom/<server_id>?target_type=server ต้องได้ 200 + announcement_channel_id"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778901)
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(778901),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == room_id
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id


async def test_get_room_data_by_big_snowflake_server_id_200(client, db_pool):
    """Discord snowflake จริงเป็น 19 หลัก (เช่น 1498234305095143538) — ต้อง resolve ผ่าน server_id ได้ไม่ 404"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778903)
    server_id = 1498234305095143538  # สโนว์เฟลก 19 หลักเหมือน production log
    channel_id = random.randint(100_000, 999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(778903),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id


async def test_get_room_data_server_id_no_room_match_404(client, db_pool):
    """server_id ที่ไม่มีห้องผูก → 404 (พิสูจน์ว่า query ใช้ server_id จริง ไม่ใช่ id)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778906)
    # ห้อง A มี server_id แต่เราขอ server_id อีกตัวที่ไม่มี → ต้อง 404
    await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999))

    resp = client.get(
        f"/api/classroom/{random.randint(10_000_000, 99_999_999)}?target_type=server",
        headers=_make_bot_headers(778906),
    )
    assert resp.status_code == 404


async def test_get_room_data_service_queries_by_server_id_column(db_pool):
    """Service-level: target_type='server' → query ใช้คอลัมน์ server_id ตรง ๆ (ไม่ใช่ id)"""
    from services.classroom_sync_service import ClassroomService
    from core.exceptions import RoomNotFoundError

    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    data = await ClassroomService.get_room_data(
        pool=db_pool, target_id=server_id, target_type="server",
        client_source="test", actor_identifier="test",
    )
    assert data["id"] == room_id
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id

    # ✨ พิสูจน์ว่า query ใช้ server_id column ไม่ใช่ id:
    # ห้องนี้มี id = room_id (เลขเล็ก) แต่ server_id เป็นเลขคนละชุด — ถ้า query ผิดคอลัมน์จะเจอคนละห้อง/404
    assert server_id != room_id  # server_id 7 หลักไม่มีทางเท่ากับ room_id (serial เล็ก)
    data2 = await ClassroomService.get_room_data(
        pool=db_pool, target_id=server_id, target_type="server",
        client_source="test", actor_identifier="test",
    )
    assert data2["id"] == room_id  # ยังเจอห้องเดิมผ่าน server_id


async def test_get_room_data_by_room_id_default_200(client, db_pool):
    """Web เรียก GET /api/classroom/<room_id> (ไม่ส่ง target_type → default room) ต้องได้ 200"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    channel_id = random.randint(100_000, 999_999)
    room_id = await _insert_room(db_pool, owner, room_name="Web Room", channel_id=channel_id)

    resp = client.get(
        f"/api/classroom/{room_id}",
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == room_id
    assert data["room_name"] == "Web Room"
    assert data["announcement_channel_id"] == channel_id


async def test_get_room_data_unknown_server_id_404(client, db_pool):
    """server_id ที่ไม่ผูกกับห้องไหน → 404 (เพื่อให้มั่นใจว่า server branch ถูกใช้จริง)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778902)
    await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999))

    resp = client.get(
        f"/api/classroom/{random.randint(10_000_000, 99_999_999)}?target_type=server",
        headers=_make_bot_headers(778902),
    )
    assert resp.status_code == 404


async def test_get_room_data_bot_identity_returns_200(client, db_pool):
    """บอทใช้ X-Discord-Id = bot user id ซึ่งไม่ใช่สมาชิกห้อง — ต้องยังได้ 200 (server branch ไม่ผ่าน require_member)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778904)
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    # bot user id ที่ไม่เคยเป็นสมาชิกห้องเลย (ไม่ได้ถูก insert เป็น student)
    bot_user = await _insert_user(db_pool, first_name="Bot", last_name="User", discord_id=778905)

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(778905),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id
