"""
Deep-dive: ทำไม GET /api/classroom/<server_id>?target_type=server ถึง 404

สมมติฐาน: 404 ไม่ได้มาจาก resolve server_id แต่มาจาก get_current_user
ที่ต้องหา users.discord_id = X-Discord-Id (bot user id) — ถ้าไม่มีแถว → 404
ก่อนที่ router จะ resolve target ด้วยซ้ำ
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


async def test_bot_unregistered_identity_200(client, db_pool):
    """
    บอทใช้ self.bot.user.id (bot user id ที่ไม่ใช่สมาชิก/ไม่ถูก insert ใน users)
    → ตอนนี้ผ่านเป็น system bot (get_current_user_or_bot) → resolve server_id → 200
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778911)
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    # bot user id ที่ไม่เคยอยู่ใน users table เลย (จำลอง bot application)
    bot_user_id = random.randint(10_000_000_000, 99_999_999_999)  # เลขใหญ่ ๆ ต่างจาก user จริง

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(bot_user_id),
    )
    # ← บอทผ่านเป็น system bot → 200 (ไม่ 404 เหมือนเดิม)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id


async def test_bot_unregistered_identity_room_200(client, db_pool):
    """บอท system เรียก target_type=room ก็ได้ (resolve ผ่าน id)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778917)
    room_id = await _insert_room(db_pool, owner, room_name="Bot Room")
    bot_user_id = random.randint(10_000_000_000, 99_999_999_999)

    resp = client.get(
        f"/api/classroom/{room_id}?target_type=room",
        headers=_make_bot_headers(bot_user_id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == room_id


async def test_bot_registered_identity_200(client, db_pool):
    """
    ถ้าบอท identity ถูก insert ใน users (มี discord_id) → ผ่าน auth → resolve server_id → 200
    (is_bot_system=False แต่ user_id มี → require_member ทำงาน — บอทที่ลงทะเบียนเป็น user)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778912)
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    # บอท identity ถูก insert เป็น users แล้ว (มี discord_id) แต่ไม่ใช่สมาชิกห้อง
    bot_user_id = 778913
    await _insert_user(db_pool, first_name="Bot", last_name="App", discord_id=bot_user_id)

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(bot_user_id),
    )
    # บอทเป็น user แต่ไม่ใช่สมาชิก → require_member → 403 (ไม่ 404 เหมือนเก่า)
    assert resp.status_code == 403, resp.text
    assert "ไม่ได้เป็นสมาชิก" in resp.json().get("detail", "") or "ไม่พบข้อมูลของคุณ" in resp.json().get("detail", "")
