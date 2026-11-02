"""
หมวดกิจกรรม — integration tests

ครอบคลุมตาม docs/rules/testing.md:
  - Real Postgres (test_db) + clean_database fixture → state isolation
  - Randomized room_code — ห้าม hardcode id
  - Deep DB verification: assert หลัง service call → query DB ตรง ๆ พิสูจน์ mutation
  - Mock ActionService (กันแตะ Redis)

สิ่งที่ต้องพิสูจน์:
  ✓ หมวดเป็นรายการปิด — ค่าที่ไม่รู้จัก = 400 ไม่ใช่บันทึกดิบ ๆ ลง DB
  ✓ null/"" ใน PATCH = ล้างค่า (ไม่ใช่ "ไม่ส่ง")
  ✓ กรองรายการตามหมวดได้ และหมวดที่ไม่รู้จัก = 400 ไม่ใช่ลิสต์ว่าง
"""
import random
import string
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import ValidationError
from services.action_service import ActionService
from services.activity_service import ActivityService

pytestmark = pytest.mark.asyncio

TODAY_ACTIVITY = date(2026, 12, 1)


# === Fixtures & helpers ===


async def _insert_user(pool, *, first_name="Test", last_name="User", email=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}",
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room") -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            room_name, code, owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb, TRUE)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _make_room(pool, student_count: int, room_name="Test Room"):
    """ห้อง + เจ้าของ (admin) + นักเรียน n คน → (room_id, owner_id, [(student_id, user_id, student_no)])"""
    owner = await _insert_user(pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(pool, owner, room_name)
    students = []
    for no in range(1, student_count + 1):
        uid = await _insert_user(pool, first_name=f"นักเรียน{no}", last_name="ทดสอบ")
        async with pool.acquire() as conn:
            sid = await conn.fetchval(
                """
                INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
                VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb, TRUE)
                RETURNING id
                """,
                room_id, uid, no,
            )
        students.append((sid, uid, no))
    return room_id, owner, students


async def _create(
    pool,
    room_id,
    owner,
    *,
    title="ค่ายทดสอบหมวด",
    activity_date=TODAY_ACTIVITY,
    category=None,
) -> int:
    with patch.object(ActionService, "notify_new_activity", new_callable=AsyncMock):
        result = await ActivityService.create_activity(
            pool=pool,
            title=title,
            activity_date=activity_date,
            base_hours=6.0,
            status="upcoming",
            category=category,
            metadata={},
            participants=[],
            user_name="ผู้ดูแล",
            client_source="WEB_APP",
            actor_identifier="user_id:1",
            room_id=room_id,
            actor_user_id=owner,
        )
    return result["activity_id"]


def _patch(pool, room_id, owner, activity_id, **fields):
    return ActivityService.update_activity(
        pool=pool,
        activity_id=activity_id,
        update_data=fields,
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
    )


def _get(pool, room_id, owner, activity_id):
    return ActivityService.get_activity(
        pool=pool,
        activity_id=activity_id,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        user_id=owner,
    )


async def _db_meta(pool, activity_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT category, deleted_at FROM activities WHERE id = $1",
            activity_id,
        )
    return dict(row)


def _web_headers(user_id: int) -> dict:
    from jose import jwt

    from core.config import settings

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# ================================================================
# 🏷️ หมวดกิจกรรม
# ================================================================


async def test_create_with_category_persists(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, category="camp")

    row = await _db_meta(db_pool, activity_id)
    assert row["category"] == "camp"

    detail = await _get(db_pool, room_id, owner, activity_id)
    assert detail["category"] == "camp"
    assert detail["category_label"] == "ค่าย"


async def test_create_without_category_is_null_and_label_is_null(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    row = await _db_meta(db_pool, activity_id)
    assert row["category"] is None

    detail = await _get(db_pool, room_id, owner, activity_id)
    assert detail["category"] is None
    assert detail["category_label"] is None


async def test_create_normalizes_category_case_and_spaces(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, category="  Volunteer ")

    assert (await _db_meta(db_pool, activity_id))["category"] == "volunteer"


async def test_create_rejects_unknown_category(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    with pytest.raises(ValidationError) as err:
        await _create(db_pool, room_id, owner, category="festival")

    assert "ไม่รู้จักหมวดกิจกรรม" in str(err.value)


async def test_update_sets_and_clears_category(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    await _patch(db_pool, room_id, owner, activity_id, category="competition")
    assert (await _db_meta(db_pool, activity_id))["category"] == "competition"

    # "" = ล้างหมวด (ผู้ใช้เลือก "ไม่ระบุ" ในดรอปดาวน์)
    await _patch(db_pool, room_id, owner, activity_id, category="")
    assert (await _db_meta(db_pool, activity_id))["category"] is None


async def test_update_rejects_unknown_category(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    with pytest.raises(ValidationError):
        await _patch(db_pool, room_id, owner, activity_id, category="festival")


async def test_list_filters_by_category(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    camp_id = await _create(db_pool, room_id, owner, title="ค่าย", category="camp")
    await _create(db_pool, room_id, owner, title="ประกวด", category="competition")

    rows = await ActivityService.list_activities(
        pool=db_pool,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        user_id=owner,
        category="camp",
    )

    assert [r["id"] for r in rows] == [camp_id]
    assert rows[0]["category_label"] == "ค่าย"


async def test_list_rejects_unknown_category_filter(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    with pytest.raises(ValidationError):
        await ActivityService.list_activities(
            pool=db_pool,
            client_source="WEB_APP",
            actor_identifier="user_id:1",
            room_id=room_id,
            user_id=owner,
            category="festival",
        )


# ================================================================
# 🌐 HTTP — route จริง
# ================================================================


async def test_http_list_unknown_category_returns_400(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)

    resp = client.get(
        f"/api/classroom/{room_id}/activities?target_type=room&category=festival",
        headers=_web_headers(owner),
    )

    assert resp.status_code == 400
    assert "ไม่รู้จักหมวดกิจกรรม" in resp.json()["detail"]
