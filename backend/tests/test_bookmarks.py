"""
Integration tests — บุ๊กมาร์ก "บันทึกไว้" (`routers/bookmark_router.py` · P3.4)

สิ่งที่ล็อกไว้:
  1. กดบันทึกแล้วรายการโผล่พร้อมชื่อ/ลิงก์ที่ hydrate จากตารางต้นทาง
  2. กดซ้ำ = ไม่สร้างแถวใหม่ (200 + created=false) และ audit ไม่โกหก
  3. ลบ = soft delete (แถวยังอยู่) แล้วกดใหม่ได้แถวเดิม (ไม่สะสมขยะ)
  4. ลบของคนอื่น = 404 ไม่ใช่ 204 และไม่แตะแถวของเจ้าของ
  5. เป้าหมายที่ไม่มีจริง/อยู่คนละห้อง = 404 (บุ๊กมาร์กไม่ใช่ประตูหลังข้ามห้อง)
  6. pagination เดินครบทุกแถวครั้งเดียว · cursor ผิดรูป = 400
  7. คนนอกห้อง = 403

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
ไม่ hardcode id และสุ่มรหัสห้องทุกครั้ง
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _insert_user(pool, first_name: str = "Test") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, 'User', $3)
            RETURNING id
            """,
            f"{uuid.uuid4().hex[:12]}@example.com",
            first_name,
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


async def _insert_announcement(
    pool, room_id: int, title: str, body: str = "เนื้อหา", archived: bool = False
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO announcements (room_id, title, body, archived_at)
            VALUES ($1, $2, $3, CASE WHEN $4 THEN NOW() ELSE NULL END)
            RETURNING id
            """,
            room_id,
            title,
            body,
            archived,
        )


async def _insert_activity(pool, room_id: int, title: str, activity_date: date | None = None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO activities (room_id, title, description, activity_date, created_by)
            VALUES ($1, $2, 'รายละเอียดกิจกรรม', $3, 'tester')
            RETURNING id
            """,
            room_id,
            title,
            activity_date or date.today(),
        )


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int, path: str, query: str = "") -> str:
    base = f"/api/classroom/{room_id}{path}?target_type=room"
    return f"{base}&{query}" if query else base


async def _add(client, room_id: int, user_id: int, entity_type: str, entity_id: int):
    return client.post(
        _api(room_id, "/bookmarks"),
        json={"entity_type": entity_type, "entity_id": entity_id},
        headers=_headers(user_id),
    )


# ── 1. เพิ่ม + hydrate ──────────────────────────────────────────────────────
async def test_add_bookmark_returns_hydrated_item(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    announcement_id = await _insert_announcement(db_pool, room_id, "นัดประชุมผู้ปกครอง")

    resp = await _add(client, room_id, owner, "announcement", announcement_id)
    assert resp.status_code == 201
    assert resp.json()["created"] is True

    body = client.get(_api(room_id, "/bookmarks"), headers=_headers(owner)).json()
    assert body["has_more"] is False
    item = body["items"][0]
    assert item["entity_type"] == "announcement"
    assert item["entity_id"] == announcement_id
    assert item["title"] == "นัดประชุมผู้ปกครอง"
    assert item["url"] == f"/announcements/{announcement_id}"
    assert item["available"] is True
    bangkok_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Bangkok")).date()
    assert item["occurred_on"] == bangkok_today.isoformat()


async def test_bookmark_activity_uses_activity_date(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    event_day = date.today() - timedelta(days=3)
    activity_id = await _insert_activity(db_pool, room_id, "ค่ายลูกเสือ", event_day)

    await _add(client, room_id, owner, "activity", activity_id)
    body = client.get(
        _api(room_id, "/bookmarks", "entity_type=activity"), headers=_headers(owner)
    ).json()

    item = body["items"][0]
    assert item["title"] == "ค่ายลูกเสือ"
    assert item["occurred_on"] == event_day.isoformat()
    assert item["url"] == f"/activities/{activity_id}"


# ── 2. กดซ้ำ ────────────────────────────────────────────────────────────────
async def test_add_twice_is_idempotent(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    announcement_id = await _insert_announcement(db_pool, room_id, "ประกาศซ้ำ")

    first = await _add(client, room_id, owner, "announcement", announcement_id)
    second = await _add(client, room_id, owner, "announcement", announcement_id)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]

    async with db_pool.acquire() as conn:
        live = await conn.fetchval(
            "SELECT COUNT(*) FROM bookmarks WHERE user_id = $1 AND deleted_at IS NULL",
            owner,
        )
    assert live == 1


# ── 3. ลบ + คืนชีพ ─────────────────────────────────────────────────────────
async def test_delete_is_soft_and_readd_reuses_row(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    announcement_id = await _insert_announcement(db_pool, room_id, "ประกาศชั่วคราว")

    bookmark_id = (await _add(client, room_id, owner, "announcement", announcement_id)).json()["id"]

    delete = client.delete(_api(room_id, f"/bookmarks/{bookmark_id}"), headers=_headers(owner))
    assert delete.status_code == 204

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deleted_at FROM bookmarks WHERE id = $1", bookmark_id
        )
    assert row["deleted_at"] is not None  # soft delete จริง ไม่ได้ลบแถว

    empty = client.get(_api(room_id, "/bookmarks"), headers=_headers(owner)).json()
    assert empty["items"] == []

    again = await _add(client, room_id, owner, "announcement", announcement_id)
    assert again.status_code == 201
    assert again.json()["id"] == bookmark_id  # คืนชีพแถวเดิม ไม่สะสมแถวขยะ
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM bookmarks WHERE user_id = $1", owner)
    assert total == 1


async def test_cannot_delete_someone_elses_bookmark(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    friend = await _insert_user(db_pool, "เพื่อน")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 1, 'student', 'active', FALSE, '[]'::jsonb)
            """,
            room_id,
            friend,
        )
    announcement_id = await _insert_announcement(db_pool, room_id, "ประกาศ")
    bookmark_id = (await _add(client, room_id, friend, "announcement", announcement_id)).json()["id"]

    resp = client.delete(_api(room_id, f"/bookmarks/{bookmark_id}"), headers=_headers(owner))
    assert resp.status_code == 404

    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval(
            "SELECT deleted_at FROM bookmarks WHERE id = $1", bookmark_id
        )
    assert deleted_at is None  # ของเพื่อนยังอยู่ครบ


# ── 4. เป้าหมายไม่ถูกต้อง ──────────────────────────────────────────────────
async def test_missing_or_cross_room_target_is_404(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    other_owner = await _insert_user(db_pool, "เจ้าของอีกห้อง")
    other_room = await _insert_room(db_pool, other_owner)
    foreign_announcement = await _insert_announcement(db_pool, other_room, "ของห้องอื่น")

    missing = await _add(client, room_id, owner, "announcement", 99_999_999)
    assert missing.status_code == 404

    cross_room = await _add(client, room_id, owner, "announcement", foreign_announcement)
    assert cross_room.status_code == 404  # รู้ว่ามีอยู่แต่ไม่ใช่ของห้องนี้ — ปฏิเสธเหมือนไม่มี

    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM bookmarks WHERE user_id = $1", owner)
    assert total == 0


async def test_invalid_entity_type_is_422_or_400(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = await _add(client, room_id, owner, "task", 1)
    assert resp.status_code == 422  # Literal ใน Pydantic ตัดก่อนถึง service

    listed = client.get(_api(room_id, "/bookmarks", "entity_type=task"), headers=_headers(owner))
    assert listed.status_code == 400


# ── 5. แบ่งหน้า ─────────────────────────────────────────────────────────────
async def test_pagination_returns_every_row_exactly_once(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    ids = []
    for index in range(5):
        announcement_id = await _insert_announcement(db_pool, room_id, f"ประกาศ {index}")
        ids.append(announcement_id)
        await _add(client, room_id, owner, "announcement", announcement_id)

    seen: list[int] = []
    cursor = None
    for _ in range(10):  # เพดานกันลูปไม่จบ
        query = f"limit=2&cursor={cursor}" if cursor else "limit=2"
        body = client.get(_api(room_id, "/bookmarks", query), headers=_headers(owner)).json()
        seen.extend(item["bookmark_id"] for item in body["items"])
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
    else:  # pragma: no cover
        pytest.fail("has_more ไม่เคยเป็น False — pagination ไม่จบ")

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_invalid_cursor_returns_400(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    resp = client.get(_api(room_id, "/bookmarks", "cursor=not-a-cursor"), headers=_headers(owner))
    assert resp.status_code == 400


# ── 6. สิทธิ์ + สถานะ ──────────────────────────────────────────────────────
async def test_non_member_gets_403(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    announcement_id = await _insert_announcement(db_pool, room_id, "ประกาศ")
    outsider = await _insert_user(db_pool, "คนนอก")

    assert client.get(_api(room_id, "/bookmarks"), headers=_headers(outsider)).status_code == 403
    resp = await _add(client, room_id, outsider, "announcement", announcement_id)
    assert resp.status_code == 403


async def test_state_reflects_bookmark_lifecycle(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    announcement_id = await _insert_announcement(db_pool, room_id, "ประกาศ")

    path = "/bookmarks/state"
    query = f"entity_type=announcement&entity_id={announcement_id}"

    before = client.get(_api(room_id, path, query), headers=_headers(owner)).json()
    assert before == {"bookmarked": False, "bookmark_id": None}

    bookmark_id = (await _add(client, room_id, owner, "announcement", announcement_id)).json()["id"]
    during = client.get(_api(room_id, path, query), headers=_headers(owner)).json()
    assert during == {"bookmarked": True, "bookmark_id": bookmark_id}

    client.delete(_api(room_id, f"/bookmarks/{bookmark_id}"), headers=_headers(owner))
    after = client.get(_api(room_id, path, query), headers=_headers(owner)).json()
    assert after == {"bookmarked": False, "bookmark_id": None}


async def test_archived_announcement_stays_available(client, db_pool):
    """เก็บถาวร = ซ่อนจากลิสต์ แต่หน้ารายละเอียดยังเปิดได้ ⇒ บุ๊กมาร์กต้องไม่กลายเป็นลิงก์ตาย"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    archived_id = await _insert_announcement(db_pool, room_id, "ประกาศเก่า", archived=True)

    await _add(client, room_id, owner, "announcement", archived_id)
    body = client.get(_api(room_id, "/bookmarks"), headers=_headers(owner)).json()
    assert body["items"][0]["available"] is True
