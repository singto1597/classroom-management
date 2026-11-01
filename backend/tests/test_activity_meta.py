"""
หมวดกิจกรรม + วันปิดรับ + ลิงก์แชร์ (P4.3) — integration tests

ครอบคลุมตาม docs/rules/testing.md:
  - Real Postgres (test_db) + clean_database fixture → state isolation
  - Randomized room_code — ห้าม hardcode id
  - Deep DB verification: assert หลัง service call → query DB ตรง ๆ พิสูจน์ mutation
  - Mock ActionService (กันแตะ Redis)

สิ่งที่ต้องพิสูจน์ (DoD ของ P4):
  ✓ หมวดเป็นรายการปิด — ค่าที่ไม่รู้จัก = 400 ไม่ใช่บันทึกดิบ ๆ ลง DB
  ✓ วันปิดรับต้องไม่หลังวันจัดกิจกรรม และตรวจกับ "วันหลังแก้" ตอน PATCH
  ✓ null/"" ใน PATCH = ล้างค่า (ไม่ใช่ "ไม่ส่ง")
  ✓ ลิงก์แชร์: ออกซ้ำได้ลิงก์เดิม · rotate ทำให้ลิงก์เก่าตาย · เพิกถอนแล้ว 404
  ✓ หน้าสาธารณะ **ไม่มี PII** — เฉพาะตัวเลข/ข้อมูลงาน
  ✓ โทเคนไม่หลุดลง audit_logs
"""
import random
import string
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import ForbiddenError, ValidationError
from services.action_service import ActionService
from services.activity.share import SHARE_PATH_PREFIX
from services.activity_service import ActivityService

pytestmark = pytest.mark.asyncio

TODAY_ACTIVITY = date(2026, 12, 1)
DEADLINE = date(2026, 11, 20)


# === Fixtures & helpers (pattern เดียวกับ test_activity_capacity.py / qr_checkin) ===


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
    capacity=None,
    category=None,
    registration_deadline=None,
    participants=(),
) -> int:
    with patch.object(ActionService, "notify_new_activity", new_callable=AsyncMock):
        result = await ActivityService.create_activity(
            pool=pool,
            title=title,
            activity_date=activity_date,
            base_hours=6.0,
            status="upcoming",
            capacity=capacity,
            category=category,
            registration_deadline=registration_deadline,
            metadata={},
            participants=list(participants),
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
            "SELECT category, registration_deadline, share_token, deleted_at "
            "FROM activities WHERE id = $1",
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


async def test_create_with_category_and_deadline_persists(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(
        db_pool, room_id, owner, category="camp", registration_deadline=DEADLINE
    )

    row = await _db_meta(db_pool, activity_id)
    assert row["category"] == "camp"
    assert row["registration_deadline"] == DEADLINE

    detail = await _get(db_pool, room_id, owner, activity_id)
    assert detail["category"] == "camp"
    assert detail["category_label"] == "ค่าย"
    assert detail["registration_deadline"] == DEADLINE


async def test_create_without_category_is_null_and_label_is_null(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    row = await _db_meta(db_pool, activity_id)
    assert row["category"] is None
    assert row["registration_deadline"] is None

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


async def test_create_rejects_deadline_after_activity_date(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    with pytest.raises(ValidationError) as err:
        await _create(
            db_pool, room_id, owner,
            activity_date=date(2026, 12, 1),
            registration_deadline=date(2026, 12, 2),
        )

    assert "ต้องไม่หลังวันจัดกิจกรรม" in str(err.value)


async def test_create_allows_deadline_equal_to_activity_date(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(
        db_pool, room_id, owner,
        activity_date=date(2026, 12, 1),
        registration_deadline=date(2026, 12, 1),
    )

    assert (await _db_meta(db_pool, activity_id))["registration_deadline"] == date(2026, 12, 1)


async def test_update_sets_and_clears_category(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    await _patch(db_pool, room_id, owner, activity_id, category="competition")
    assert (await _db_meta(db_pool, activity_id))["category"] == "competition"

    # "" = ล้างหมวด (ผู้ใช้เลือก "ไม่ระบุ" ในดรอปดาวน์)
    await _patch(db_pool, room_id, owner, activity_id, category="")
    assert (await _db_meta(db_pool, activity_id))["category"] is None


async def test_update_clears_registration_deadline_with_null(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, registration_deadline=DEADLINE)

    await _patch(db_pool, room_id, owner, activity_id, registration_deadline=None)

    assert (await _db_meta(db_pool, activity_id))["registration_deadline"] is None


async def test_update_rejects_deadline_after_existing_activity_date(db_pool):
    """ย้ายวันปิดรับอย่างเดียว ห้ามให้เลยวันจัดที่มีอยู่แล้ว"""
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, activity_date=date(2026, 12, 1))

    with pytest.raises(ValidationError):
        await _patch(db_pool, room_id, owner, activity_id, registration_deadline=date(2026, 12, 5))


async def test_update_moving_both_dates_uses_new_activity_date(db_pool):
    """ย้ายวันจัด + วันปิดรับพร้อมกัน ต้องเทียบกันเอง ไม่ใช่กับวันเดิมใน DB"""
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(
        db_pool, room_id, owner,
        activity_date=date(2026, 12, 10),
        registration_deadline=date(2026, 12, 5),
    )

    await _patch(
        db_pool, room_id, owner, activity_id,
        activity_date=date(2026, 11, 20),
        registration_deadline=date(2026, 11, 15),
    )

    row = await _db_meta(db_pool, activity_id)
    assert row["registration_deadline"] == date(2026, 11, 15)


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
    assert rows[0]["has_share_link"] is False


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
# 🔗 ลิงก์แชร์ — ออก / หมุน / เพิกถอน
# ================================================================


async def _issue(pool, room_id, owner, activity_id, *, rotate=False):
    return await ActivityService.issue_share_link(
        pool=pool,
        activity_id=activity_id,
        user_id=owner,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        rotate=rotate,
    )


def _revoke(pool, room_id, owner, activity_id):
    return ActivityService.revoke_share_link(
        pool=pool,
        activity_id=activity_id,
        user_id=owner,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
    )


def _shared(pool, token):
    return ActivityService.get_shared_activity(pool=pool, token=token)


async def test_issue_share_link_returns_usable_token(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    result = await _issue(db_pool, room_id, owner, activity_id)

    assert result["activity_id"] == activity_id
    assert result["rotated"] is False
    assert len(result["share_token"]) >= 32
    assert result["path"] == SHARE_PATH_PREFIX + result["share_token"]
    assert (await _db_meta(db_pool, activity_id))["share_token"] == result["share_token"]

    detail = await _get(db_pool, room_id, owner, activity_id)
    assert detail["has_share_link"] is True


async def test_issue_share_link_is_idempotent(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    first = await _issue(db_pool, room_id, owner, activity_id)
    second = await _issue(db_pool, room_id, owner, activity_id)

    assert second["share_token"] == first["share_token"]
    assert second["rotated"] is False


async def test_rotate_invalidates_previous_token(db_pool):
    from core.exceptions import ActivityNotFoundError

    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    old = await _issue(db_pool, room_id, owner, activity_id)

    rotated = await _issue(db_pool, room_id, owner, activity_id, rotate=True)

    assert rotated["rotated"] is True
    assert rotated["share_token"] != old["share_token"]
    with pytest.raises(ActivityNotFoundError):
        await _shared(db_pool, old["share_token"])


async def test_revoke_kills_link(db_pool):
    from core.exceptions import ActivityNotFoundError

    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    link = await _issue(db_pool, room_id, owner, activity_id)

    result = await _revoke(db_pool, room_id, owner, activity_id)

    assert result["revoked"] is True
    assert (await _db_meta(db_pool, activity_id))["share_token"] is None
    with pytest.raises(ActivityNotFoundError):
        await _shared(db_pool, link["share_token"])


async def test_revoke_without_link_is_not_an_error(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)

    assert (await _revoke(db_pool, room_id, owner, activity_id))["revoked"] is False


async def test_issue_requires_manage_activities(db_pool):
    room_id, owner, students = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    _, student_user_id, _ = students[0]

    with pytest.raises(ForbiddenError):
        await ActivityService.issue_share_link(
            pool=db_pool,
            activity_id=activity_id,
            user_id=student_user_id,
            client_source="WEB_APP",
            actor_identifier="user_id:2",
            room_id=room_id,
        )


async def test_share_token_never_written_to_audit(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    link = await _issue(db_pool, room_id, owner, activity_id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT new_values::text AS nv, old_values::text AS ov FROM audit_logs "
            "WHERE entity_type = 'ACTIVITY' AND entity_id = $1 AND action = 'SHARE'",
            str(activity_id),
        )

    assert rows, "ต้องมีแถว audit ของการออกลิงก์"
    for row in rows:
        assert link["share_token"] not in (row["nv"] or "")
        assert link["share_token"] not in (row["ov"] or "")


# ================================================================
# 🌐 หน้าสาธารณะ — ข้อมูลงานเท่านั้น ไม่มี PII
# ================================================================


async def test_shared_view_returns_counts_without_pii(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 3, room_name="ม.5/1")
    activity_id = await _create(
        db_pool, room_id, owner,
        capacity=2,
        category="camp",
        participants=[{"student_no": 1}, {"student_no": 2}, {"student_no": 3}],
    )
    link = await _issue(db_pool, room_id, owner, activity_id)

    data = await _shared(db_pool, link["share_token"])

    assert data["activity_id"] == activity_id
    assert data["title"] == "ค่ายทดสอบหมวด"
    assert data["room_name"] == "ม.5/1"
    assert data["capacity"] == 2
    assert data["confirmed_count"] == 2
    assert data["waitlisted_count"] == 1
    assert data["seats_left"] == 0
    assert data["category"] == "camp"
    assert data["category_label"] == "ค่าย"
    assert data["status_label"] == "กำลังจะมา"

    # 🔒 ไม่มีกุญแจที่พาไปสู่ PII ได้เลย
    forbidden = {"participants", "student_no", "first_name", "last_name", "phone_number"}
    assert forbidden.isdisjoint(data.keys())


async def test_shared_view_unlimited_capacity_has_no_seats_left(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, participants=[{"student_no": 1}])
    link = await _issue(db_pool, room_id, owner, activity_id)

    data = await _shared(db_pool, link["share_token"])

    assert data["capacity"] is None
    assert data["seats_left"] is None


async def test_shared_view_unknown_token_raises(db_pool):
    from core.exceptions import ActivityNotFoundError

    with pytest.raises(ActivityNotFoundError):
        await _shared(db_pool, "not-a-real-token-at-all")


async def test_shared_view_of_soft_deleted_activity_is_gone(db_pool):
    from core.exceptions import ActivityNotFoundError

    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    link = await _issue(db_pool, room_id, owner, activity_id)

    await ActivityService.delete_activity(
        pool=db_pool,
        activity_id=activity_id,
        user_name="ผู้ดูแล",
        user_id=owner,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
    )

    with pytest.raises(ActivityNotFoundError):
        await _shared(db_pool, link["share_token"])


@pytest.mark.parametrize(
    "deadline, status, expected_open",
    [
        (date(2099, 1, 1), "upcoming", True),
        (None, "ongoing", True),
        (date(2000, 1, 1), "upcoming", False),   # เลยวันปิดรับมาแล้ว
        (date(2099, 1, 1), "completed", False),  # จบแล้ว = ปิดรับ แม้ยังไม่ถึง deadline
        (date(2099, 1, 1), "cancelled", False),
    ],
)
async def test_shared_view_registration_open_flags(db_pool, deadline, status, expected_open):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(
        db_pool, room_id, owner,
        activity_date=date(2099, 6, 1),
        registration_deadline=deadline,
    )
    await _patch(db_pool, room_id, owner, activity_id, status=status)
    link = await _issue(db_pool, room_id, owner, activity_id)

    data = await _shared(db_pool, link["share_token"])

    assert data["is_registration_open"] is expected_open


# ================================================================
# 🌐 HTTP — route จริง (รวม public route ที่ไม่มี auth)
# ================================================================


async def test_http_share_issue_and_public_view(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner, category="camp")

    issued = client.post(
        f"/api/classroom/{room_id}/activities/{activity_id}/share?target_type=room",
        json={"user_name": "ผู้ดูแล"},
        headers=_web_headers(owner),
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["share_token"]

    # 🔓 ไม่ส่ง header ใด ๆ — คือสิ่งที่ผู้ปกครองทำเมื่อเปิดลิงก์
    public = client.get(f"/api/shared/activity/{token}")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["title"] == "ค่ายทดสอบหมวด"
    assert body["category_label"] == "ค่าย"
    assert public.headers["cache-control"] == "no-store"

    unknown = client.get("/api/shared/activity/definitely-not-a-token")
    assert unknown.status_code == 404


async def test_http_revoke_then_public_view_404(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create(db_pool, room_id, owner)
    issued = client.post(
        f"/api/classroom/{room_id}/activities/{activity_id}/share?target_type=room",
        json={"user_name": "ผู้ดูแล"},
        headers=_web_headers(owner),
    )
    token = issued.json()["share_token"]

    revoked = client.request(
        "DELETE",
        f"/api/classroom/{room_id}/activities/{activity_id}/share?target_type=room",
        json={"user_name": "ผู้ดูแล"},
        headers=_web_headers(owner),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked"] is True

    assert client.get(f"/api/shared/activity/{token}").status_code == 404


async def test_http_create_with_deadline_after_activity_date_returns_400(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)

    resp = client.post(
        f"/api/classroom/{room_id}/activities?target_type=room",
        json={
            "title": "ผิดกติกา",
            "activity_date": "2026-12-01",
            "registration_deadline": "2026-12-09",
            "user_name": "ผู้ดูแล",
        },
        headers=_web_headers(owner),
    )

    assert resp.status_code == 400
    assert "ต้องไม่หลังวันจัดกิจกรรม" in resp.json()["detail"]


async def test_http_list_unknown_category_returns_400(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)

    resp = client.get(
        f"/api/classroom/{room_id}/activities?target_type=room&category=festival",
        headers=_web_headers(owner),
    )

    assert resp.status_code == 400
    assert "ไม่รู้จักหมวดกิจกรรม" in resp.json()["detail"]
