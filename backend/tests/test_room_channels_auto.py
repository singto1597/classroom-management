"""เทสต์ช่อง Discord ที่บอทสร้างเอง + mute รายช่อง (P7)

สิ่งที่ล็อกไว้:
1. `POST /{server_id}/channels/auto` (system RPC ของบอท) บันทึกช่องที่ยัง **ว่างเท่านั้น**
   ⇒ เชิญบอทกลับเข้าเซิร์ฟเวอร์ต้องไม่ทับช่องที่แอดมินเลือกไว้
2. `PUT /{target_id}/channel/mute` ต้องมี `MANAGE_CLASSROOM_SETTINGS` · รับเฉพาะช่องที่
   ตั้งเป็นช่องแจ้งเตือนของห้องแล้ว · เรียกซ้ำได้ (idempotent)
3. ช่องที่ถูก mute ต้องหลุดจาก `get_rooms_to_notify` (ลูปสรุปรายวันของบอท)
   — ถ้าไม่หลุด "mute" จะเป็นแค่ตัวเลขใน DB ที่ไม่มีใครอ่าน
"""
import random
import string
import uuid

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


# === Helpers ===


async def _insert_user(pool, *, first_name="Test", last_name="User", discord_id=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            f"u{uuid.uuid4().hex[:12]}@test.local", first_name, last_name,
            f"user_{uuid.uuid4().hex[:8]}", discord_id,
        )


async def _insert_room(
    pool,
    owner_id: int,
    *,
    server_id=None,
    announcement_channel_id=None,
    birthday_channel_id=None,
    minor_channel_id=None,
    info_channel_id=None,
    notify_time="19:00",
) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id, announcement_channel_id,
                               birthday_channel_id, minor_notify_channel_id, info_channel_id, notify_time)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            "Test Room", code, owner_id, server_id, announcement_channel_id,
            birthday_channel_id, minor_channel_id, info_channel_id, notify_time,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '["all"]'::jsonb)
            """,
            room_id, owner_id,
        )
        return room_id


async def _add_member(pool, room_id: int, discord_id: int, *, permissions="[]") -> int:
    user_id = await _insert_user(pool, discord_id=discord_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 1, 'student', 'active', FALSE, $3::jsonb)
            """,
            room_id, user_id, permissions,
        )
    return user_id


def _bot_headers() -> dict:
    """system RPC ของบอท — API key เท่านั้น ไม่มีผู้ใช้"""
    return {"X-API-Key": settings.API_KEY}


def _user_headers(discord_id: int) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


# === 1. POST /{server_id}/channels/auto ===


async def test_auto_channels_fills_empty_columns(db_pool, client):
    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    channels = {
        "announcement": random.randint(100_000, 999_999),
        "birthday": random.randint(100_000, 999_999),
        "info": random.randint(100_000, 999_999),
    }

    resp = client.post(
        f"/api/classroom/{server_id}/channels/auto",
        params={"target_type": "server"},
        json={"channels": channels},
        headers=_bot_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == channels
    assert resp.json()["kept"] == {}

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT announcement_channel_id, birthday_channel_id, info_channel_id FROM rooms WHERE id = $1",
            room_id,
        )
    assert row["announcement_channel_id"] == channels["announcement"]
    assert row["birthday_channel_id"] == channels["birthday"]
    assert row["info_channel_id"] == channels["info"]


async def test_auto_channels_never_overwrites_admin_choice(db_pool, client):
    """🔒 เชิญบอทกลับเข้าเซิร์ฟเวอร์ = ต้องไม่เปลี่ยนช่องที่แอดมินเลือกไว้"""
    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    admin_channel = random.randint(100_000, 999_999)
    room_id = await _insert_room(
        db_pool, owner, server_id=server_id, announcement_channel_id=admin_channel,
    )
    new_channel = admin_channel + 1

    resp = client.post(
        f"/api/classroom/{server_id}/channels/auto",
        params={"target_type": "server"},
        json={"channels": {"announcement": new_channel, "info": new_channel + 2}},
        headers=_bot_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "updated": {"info": new_channel + 2},
        "kept": {"announcement": admin_channel},
    }

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT announcement_channel_id, info_channel_id FROM rooms WHERE id = $1", room_id
        )
    assert row["announcement_channel_id"] == admin_channel
    assert row["info_channel_id"] == new_channel + 2


async def test_auto_channels_requires_api_key(db_pool, client):
    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    await _insert_room(db_pool, owner, server_id=server_id)

    resp = client.post(
        f"/api/classroom/{server_id}/channels/auto",
        params={"target_type": "server"},
        json={"channels": {"announcement": 111}},
    )
    assert resp.status_code == 401


async def test_auto_channels_unknown_server_is_404(db_pool, client):
    resp = client.post(
        "/api/classroom/9876543/channels/auto",
        params={"target_type": "server"},
        json={"channels": {"announcement": 111}},
        headers=_bot_headers(),
    )
    assert resp.status_code == 404


# === 2. set_channel(channel_type="info") ===


async def test_set_channel_info_type_writes_info_column(db_pool):
    from services.classroom_sync_service import ClassroomService

    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    info_channel = random.randint(100_000, 999_999)

    await ClassroomService.set_channel(
        pool=db_pool, channel_id=info_channel, user_name="Owner", user_id=owner,
        room_id=room_id, client_source="test", actor_identifier="test", channel_type="info",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT announcement_channel_id, info_channel_id FROM rooms WHERE id = $1", room_id
        )
    assert row["info_channel_id"] == info_channel
    assert row["announcement_channel_id"] is None


# === 3. PUT /{room_id}/channel/mute ===


async def test_mute_and_unmute_toggle_the_same_channel(db_pool, client):
    owner_discord = random.randint(1_000_000, 9_999_999)
    owner = await _insert_user(db_pool, discord_id=owner_discord)
    announcement = random.randint(100_000, 999_999)
    room_id = await _insert_room(
        db_pool, owner, announcement_channel_id=announcement,
        birthday_channel_id=announcement + 1,
    )

    resp = client.put(
        f"/api/classroom/{room_id}/channel/mute",
        json={"channel_id": announcement, "muted": True, "user_name": "Owner"},
        headers=_user_headers(owner_discord),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "channel_id": announcement,
        "muted": True,
        "muted_channel_ids": [announcement],
    }

    # เรียกซ้ำด้วยค่าเดิม = ไม่เกิดแถวซ้ำในอาร์เรย์
    again = client.put(
        f"/api/classroom/{room_id}/channel/mute",
        json={"channel_id": announcement, "muted": True, "user_name": "Owner"},
        headers=_user_headers(owner_discord),
    )
    assert again.json()["muted_channel_ids"] == [announcement]

    async with db_pool.acquire() as conn:
        stored = await conn.fetchval("SELECT muted_channel_ids FROM rooms WHERE id = $1", room_id)
    assert list(stored) == [announcement]

    resp = client.put(
        f"/api/classroom/{room_id}/channel/mute",
        json={"channel_id": announcement, "muted": False, "user_name": "Owner"},
        headers=_user_headers(owner_discord),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["muted_channel_ids"] == []

    async with db_pool.acquire() as conn:
        stored = await conn.fetchval("SELECT muted_channel_ids FROM rooms WHERE id = $1", room_id)
    assert list(stored) == []


async def test_mute_rejects_channel_not_configured_for_room(db_pool, client):
    owner_discord = random.randint(1_000_000, 9_999_999)
    owner = await _insert_user(db_pool, discord_id=owner_discord)
    room_id = await _insert_room(db_pool, owner, announcement_channel_id=111)

    resp = client.put(
        f"/api/classroom/{room_id}/channel/mute",
        json={"channel_id": 999999, "muted": True, "user_name": "Owner"},
        headers=_user_headers(owner_discord),
    )
    assert resp.status_code == 400


async def test_mute_requires_manage_settings_permission(db_pool, client):
    owner = await _insert_user(db_pool)
    announcement = random.randint(100_000, 999_999)
    room_id = await _insert_room(db_pool, owner, announcement_channel_id=announcement)

    member_discord = random.randint(1_000_000, 9_999_999)
    await _add_member(db_pool, room_id, member_discord)

    resp = client.put(
        f"/api/classroom/{room_id}/channel/mute",
        json={"channel_id": announcement, "muted": True, "user_name": "Member"},
        headers=_user_headers(member_discord),
    )
    assert resp.status_code == 403

    async with db_pool.acquire() as conn:
        stored = await conn.fetchval("SELECT muted_channel_ids FROM rooms WHERE id = $1", room_id)
    assert list(stored) == []


# === 4. ผลของ mute ต่อลูป/ข้อมูลที่บอทอ่าน ===


async def test_get_rooms_to_notify_excludes_muted_announcement(db_pool):
    from services.classroom_sync_service import ClassroomService

    owner = await _insert_user(db_pool)
    live = await _insert_room(
        db_pool, owner, server_id=random.randint(1_000_000, 9_999_999),
        announcement_channel_id=111, notify_time="07:00",
    )
    muted = await _insert_room(
        db_pool, owner, server_id=random.randint(1_000_000, 9_999_999),
        announcement_channel_id=222, notify_time="07:00",
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE rooms SET muted_channel_ids = $1::bigint[] WHERE id = $2", [222], muted
        )

    rows = await ClassroomService.get_rooms_to_notify(
        pool=db_pool, current_time="07:00",
        client_source="test", actor_identifier="test",
    )
    channel_ids = {row["announcement_channel_id"] for row in rows}
    assert 111 in channel_ids
    assert 222 not in channel_ids
    # 🔎 ยังต้องเห็นแถวของห้องที่ live อยู่ (กัน WHERE ที่กรองแรงเกินจนคืน 0)
    assert any(row["announcement_channel_id"] == 111 for row in rows)


async def test_get_room_data_returns_mute_state(db_pool):
    from services.classroom_sync_service import ClassroomService

    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(
        db_pool, owner, server_id=server_id,
        announcement_channel_id=111, info_channel_id=333,
    )
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET muted_channel_ids = $1::bigint[] WHERE id = $2", [111], room_id)

    room = await ClassroomService.get_room_data(
        pool=db_pool, target_id=server_id, target_type="server",
        client_source="test", actor_identifier="test", user_id=None,
    )
    assert room["info_channel_id"] == 333
    assert room["muted_channel_ids"] == [111]
