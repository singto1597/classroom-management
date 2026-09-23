"""
Integration tests — auth ของ GET /api/classroom/{target_id}/summary

**ที่มา:** การตรวจระบบเมื่อ 2026-09-23 พบว่า endpoint นี้เป็น route เดียวจาก 106 ตัว
ที่ไม่มี auth dependency ใด ๆ เลย — ยืนยันด้วยการยิงจริงแล้วว่าได้ข้อมูลจริงของโรงเรียน
ตอบ 200 ทั้งบน production และ staging โดยไม่ต้องส่ง credential แม้แต่ตัวเดียว
และเพราะ `target_id` ไล่เพิ่มทีละหนึ่งได้ จึง enumerate ข้อมูลทั้งโรงเรียนได้

**ทำไมเทสต์ชุดเดิมจับไม่ได้:** เทสต์ของ `get_daily_summary` ทั้ง 6 ตัวใน
`test_classroom_sync.py` / `test_classroom_sync_extended.py` เรียก
`ClassroomService.get_daily_summary()` ตรง ๆ ไม่ผ่าน HTTP layer
จึงไม่มีตัวใดตรวจ dependency ของ route เลย ไฟล์นี้จึงยิงผ่าน `client` จริง

**สัญญาที่ไฟล์นี้ล็อกไว้:**
1. ไม่มี credential → 401 (ทุกกรณี)
2. API key ผิด → 401
3. target_id ที่ไม่มีอยู่จริง → 401 ไม่ใช่ 404 (ห้ามมี enumeration oracle)
4. บอท (X-API-Key) → 200 ใช้ได้ตามปกติ
5. JWT อย่างเดียวไม่พอ — endpoint นี้ไม่ใช่ของเว็บ (เว็บเรียก /finance/summary ซึ่งคนละตัว)
"""
import random
import string
import uuid
from datetime import date

import pytest
from jose import jwt

from core.config import settings

pytestmark = pytest.mark.asyncio


# === Helpers ===


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


def _bot_headers(discord_id: int = 999999999) -> dict:
    """เหมือน `api_client` ฝั่งบอทเป๊ะ — session ตั้ง X-API-Key ไว้ทุกคำขอ"""
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


def _jwt_headers(user_id: int) -> dict:
    """JWT ของเว็บ — มี token แต่ไม่มี X-API-Key"""
    token = jwt.encode({"user_id": user_id}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


# === Section 1: ปฏิเสธเมื่อไม่มี credential ===


async def test_summary_without_credentials_returns_401(client, db_pool):
    """หัวใจของข้อ C1 — ห้องมีอยู่จริง แต่ไม่ส่ง credential → ต้อง 401 (เดิมตอบ 200)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=random.randint(1_000_000, 9_999_999))

    resp = client.get(
        f"/api/classroom/{room_id}/summary",
        params={"target_date": str(date(2026, 9, 23)), "target_type": "room"},
    )
    assert resp.status_code == 401, f"ข้อมูลโรงเรียนรั่ว! ได้ {resp.status_code}: {resp.text}"


async def test_summary_bot_target_type_also_protected(client, db_pool):
    """เส้นทาง target_type=server (ที่บอทใช้) ก็ต้องถูกป้องกันเหมือนกัน"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    await _insert_room(db_pool, owner, server_id=server_id)

    resp = client.get(
        f"/api/classroom/{server_id}/summary",
        params={"target_date": str(date(2026, 9, 23)), "target_type": "server"},
    )
    assert resp.status_code == 401, resp.text


async def test_summary_wrong_api_key_returns_401(client, db_pool):
    """API key ผิด → 401 (ไม่ใช่ 200)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        f"/api/classroom/{room_id}/summary",
        params={"target_date": str(date(2026, 9, 23))},
        headers={"X-API-Key": "not-the-key", "X-Discord-Id": "123"},
    )
    assert resp.status_code == 401, resp.text


async def test_summary_jwt_alone_does_not_grant_access(client, db_pool):
    """JWT อย่างเดียวไม่พอ — endpoint นี้เป็น system RPC ของบอท ไม่ใช่ของเว็บ.

    เว็บเรียก `GET /{target_id}/finance/summary` ซึ่งเป็นคนละ route
    (`routers/finance/reporting.py`) และมี auth ของตัวเอง
    เทสต์นี้กันคนที่เผลอมาเติม `get_current_user` ทีหลังโดยคิดว่า "ต้องให้เว็บเข้าได้ด้วย"
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        f"/api/classroom/{room_id}/summary",
        params={"target_date": str(date(2026, 9, 23))},
        headers=_jwt_headers(owner),
    )
    assert resp.status_code == 401, resp.text


# === Section 2: ห้ามมี enumeration oracle ===


async def test_summary_nonexistent_target_returns_401_not_404(client, db_pool):
    """target_id ที่ไม่มีอยู่จริง → 401 ไม่ใช่ 404

    ถ้า auth ถูกวาง "หลัง" resolve_target_to_room_id จะได้ 404 แทน
    ทำให้แยกออกได้ว่าห้องไหนมีจริงโดยไม่ต้องมี credential — เป็น oracle ให้ enumerate
    เทสต์นี้จึงบังคับลำดับ dependency ไว้ด้วย (ดูคอมเมนต์ใน router)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # ยืนยันก่อนว่าห้องนี้มีจริง — ไม่งั้นเทสต์จะเขียวเพราะเหตุผลผิด
    assert client.get(
        f"/api/classroom/{room_id}/summary",
        params={"target_date": str(date(2026, 9, 23))},
        headers=_bot_headers(),
    ).status_code == 200

    resp = client.get(
        f"/api/classroom/{room_id + 999_999}/summary",
        params={"target_date": str(date(2026, 9, 23))},
    )
    assert resp.status_code == 401, (
        f"ได้ {resp.status_code} — ถ้าเป็น 404 แปลว่า auth ถูกวางหลัง resolve_target_to_room_id "
        f"และมี enumeration oracle"
    )


async def test_summary_enumeration_sweep_all_401(client, db_pool):
    """ไล่ target_id หลายค่าพร้อมกันโดยไม่ส่ง credential → ต้อง 401 ทุกตัว

    จำลองการโจมตีจริง: ก่อนแก้ วิธีนี้ทำให้ดึงข้อมูลทั้งโรงเรียนได้
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    real_rooms = [
        await _insert_room(db_pool, owner, room_name=f"Room {i}", server_id=random.randint(1_000_000, 9_999_999))
        for i in range(3)
    ]

    targets = [*real_rooms, *[random.randint(1_000_000, 9_999_999) for _ in range(3)]]
    statuses = {
        t: client.get(
            f"/api/classroom/{t}/summary",
            params={"target_date": str(date(2026, 9, 23))},
        ).status_code
        for t in targets
    }

    leaked = {t: s for t, s in statuses.items() if s != 401}
    assert not leaked, f"มี target ที่ไม่ได้ 401: {leaked}"


# === Section 3: บอทยังทำงานได้ตามปกติ ===


async def test_summary_bot_path_returns_data(client, db_pool):
    """บอทเรียกด้วย X-API-Key → 200 + ฟิลด์ครบตาม DailySummaryResponse"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    await _insert_room(db_pool, owner, server_id=server_id, channel_id=random.randint(100_000, 999_999))

    target_date = date(2026, 9, 23)
    resp = client.get(
        f"/api/classroom/{server_id}/summary",
        params={"target_date": str(target_date), "target_type": "server"},
        headers=_bot_headers(),
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()
    for field in ("date", "day", "attire", "subjects", "bring", "note", "tasks_due"):
        assert field in data, f"ขาดฟิลด์ {field} — response_model เพี้ยน"
    assert data["date"] == str(target_date)
    assert isinstance(data["tasks_due"], list)


async def test_summary_room_target_type_bot_ok(client, db_pool):
    """บอทเรียกด้วย target_type=room ก็ยังได้ 200 (resolve ผ่าน id)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        f"/api/classroom/{room_id}/summary",
        params={"target_date": str(date(2026, 9, 23)), "target_type": "room"},
        headers=_bot_headers(),
    )
    assert resp.status_code == 200, resp.text
