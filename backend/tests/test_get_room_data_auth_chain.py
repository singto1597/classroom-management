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


async def test_bot_unregistered_identity_404(client, db_pool):
    """
    บอทใช้ self.bot.user.id (bot user id ที่ไม่ใช่สมาชิก/ไม่ถูก insert ใน users)
    → get_current_user 404 ก่อน resolve target → endpoint ตอบ 404 ทั้งที่ server_id ถูกต้อง
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
    # ← ถึง server_id ถูกต้องก็ยัง 404 เพราะ auth มาก่อน
    assert resp.status_code == 404, resp.text
    assert "ไม่พบบัญชีผู้ใช้" in resp.json().get("detail", "")


async def test_bot_registered_identity_200(client, db_pool):
    """
    ถ้าบอท identity ถูก insert ใน users (มี discord_id) → ผ่าน auth → resolve server_id → 200
    พิสูจน์ว่าปัญหาคือ auth ไม่ใช่ server_id query
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778912)
    server_id = random.randint(1_000_000, 9_999_999)
    channel_id = random.randint(100_000, 999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=channel_id)

    # บอท identity ถูก insert เป็น users แล้ว (มี discord_id)
    bot_user_id = 778913
    await _insert_user(db_pool, first_name="Bot", last_name="App", discord_id=bot_user_id)

    resp = client.get(
        f"/api/classroom/{server_id}?target_type=server",
        headers=_make_bot_headers(bot_user_id),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["announcement_channel_id"] == channel_id
