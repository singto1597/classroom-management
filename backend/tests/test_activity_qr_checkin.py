"""
เช็คอินด้วย QR (P4.2) — integration tests

ครอบคลุมตาม docs/rules/testing.md:
  - Real Postgres (test_db) + clean_database fixture → state isolation
  - Randomized server_id / room_code — ห้าม hardcode id
  - Deep DB verification: assert หลัง service call → query DB ตรง ๆ พิสูจน์ mutation
  - Mock ActionService (กันแตะ Redis)

สิ่งที่ต้องพิสูจน์ (DoD ของ P4):
  ✓ บัตรผูกกับกิจกรรม — token ของกิจกรรมอื่น/ที่ถูกแก้ = ปฏิเสธ
  ✓ สแกนซ้ำ **ไม่สร้างแถวซ้ำ** และไม่ทับเวลาเช็คอินครั้งแรก
  ✓ คนในคิวสำรองสแกนได้เฉพาะเมื่อมีที่นั่งว่างจริง (ไม่งั้น 400 พร้อมบอกที่ต้องทำ)
  ✓ PATCH/batch ที่ตั้ง `attended` = เช็คอินด้วยมือ → เวลาถูกประทับ; ออกจาก attended = ล้าง
"""
import json
import random
import string
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import ValidationError
from services.action_service import ActionService
from services.activity.qr import build_qr_token, parse_qr_token
from services.activity_service import ActivityService

pytestmark = pytest.mark.asyncio

STAFF = "ทีมงานหน้างาน"


# === Fixtures & helpers (pattern เดียวกับ test_activity_capacity.py) ===


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
            """
            INSERT INTO rooms (room_name, room_code, owner_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
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


async def _make_room(pool, student_count: int):
    """สร้างห้อง + เจ้าของ (admin) + นักเรียน n คน → (room_id, owner_id, [(student_id, user_id, student_no)])"""
    owner = await _insert_user(pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(pool, owner)
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


async def _create_activity(pool, room_id, owner, *, capacity=None, participants=()):
    with patch.object(ActionService, "notify_new_activity", new_callable=AsyncMock):
        result = await ActivityService.create_activity(
            pool=pool,
            title="ค่ายทดสอบ QR",
            activity_date=date(2026, 12, 1),
            base_hours=6.0,
            status="upcoming",
            capacity=capacity,
            metadata={},
            participants=list(participants),
            user_name="ผู้ดูแล",
            client_source="WEB_APP",
            actor_identifier="user_id:1",
            room_id=room_id,
            actor_user_id=owner,
        )
    return result["activity_id"]


async def _participant_ids(pool, activity_id: int):
    """{student_no: participant_id} ของแถวที่ยังไม่ถูกลบ"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.student_no, ap.id
            FROM activity_participants ap
            JOIN students s ON s.id = ap.student_id
            WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL
            """,
            activity_id,
        )
    return {r["student_no"]: r["id"] for r in rows}


async def _db_row(pool, participant_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, queue_position, checked_in_at, checked_in_by "
            "FROM activity_participants WHERE id = $1",
            participant_id,
        )
    return dict(row)


def _scan(pool, room_id, owner, activity_id, *, token=None, participant_id=None):
    return ActivityService.checkin_by_qr(
        pool=pool,
        activity_id=activity_id,
        token=token,
        participant_id=participant_id,
        user_name=STAFF,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
    )


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
# 🎟️ บัตร — HMAC ผูกกับกิจกรรม, แก้ไม่ได้
# ================================================================


async def test_token_roundtrip_returns_participant_id():
    token = build_qr_token(12, 345)
    assert token.startswith("CLS-EVT1:12:345:")
    assert parse_qr_token(token, 12) == 345


async def test_token_of_another_activity_is_rejected():
    """บัตรที่ออกให้กิจกรรม 12 ใช้กับกิจกรรม 13 ไม่ได้ แม้จะแก้ตัวเลขใน token"""
    token = build_qr_token(12, 345)
    with pytest.raises(ValidationError):
        parse_qr_token(token, 13)


async def test_tampered_signature_is_rejected():
    token = build_qr_token(12, 345)
    head, sig = token.rsplit(":", 1)
    bad = f"{head}:{'0' * len(sig)}"
    with pytest.raises(ValidationError):
        parse_qr_token(bad, 12)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "hello",
        "CLS-EVT1:12:345",           # ขาดลายเซ็น
        "CLS-EVT2:12:345:abcd",      # คนละรุ่นบัตร
        "CLS-EVT1:x:345:abcd",       # id ไม่ใช่ตัวเลข
        "CLS-EVT1:12:345:abcd:extra",  # ชิ้นเกิน
    ],
)
async def test_malformed_token_is_rejected(bad):
    with pytest.raises(ValidationError):
        parse_qr_token(bad, 12)


# ================================================================
# 📋 ออกบัตรรายกิจกรรม
# ================================================================


async def test_list_codes_skips_cancelled_and_starts_un_checked_in(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(
        db_pool, room_id, owner,
        participants=[
            {"student_no": 1},
            {"student_no": 2},
            {"student_no": 3, "status": "cancelled"},
        ],
    )

    result = await ActivityService.list_checkin_qr_tokens(
        pool=db_pool, activity_id=activity_id,
        client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )

    assert result["activity_id"] == activity_id
    assert result["title"] == "ค่ายทดสอบ QR"
    assert [c["student_no"] for c in result["codes"]] == [1, 2]
    assert all(c["checked_in_at"] is None for c in result["codes"])
    # บัตรที่ออกต้องใช้สแกนได้จริง (ผูกกับ participant_id ที่คืนมา)
    first = result["codes"][0]
    assert parse_qr_token(first["token"], activity_id) == first["participant_id"]


# ================================================================
# ✅ สแกนครั้งแรก / ซ้ำ
# ================================================================


async def test_scan_marks_attended_stamps_time_and_staff(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    pid = (await _participant_ids(db_pool, activity_id))[1]

    result = await _scan(db_pool, room_id, owner, activity_id, token=build_qr_token(activity_id, pid))

    assert result["participant_id"] == pid
    assert result["status"] == "attended"
    assert result["already_checked_in"] is False
    assert result["checked_in_by"] == STAFF
    assert result["checked_in_at"] is not None

    row = await _db_row(db_pool, pid)
    assert row["status"] == "attended"
    assert row["checked_in_at"] is not None
    assert row["checked_in_by"] == STAFF

    async with db_pool.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT new_values FROM audit_logs "
            "WHERE endpoint_or_command = 'checkin_qr' AND entity_id = $1",
            str(pid),
        )
    assert audit is not None
    new_values = audit["new_values"]
    data = json.loads(new_values) if isinstance(new_values, str) else new_values
    assert data["via"] == "qr"


async def test_scan_twice_is_idempotent_and_keeps_first_timestamp(db_pool):
    """DoD: สแกนซ้ำไม่สร้างแถวซ้ำ — 200/สำเร็จทั้งสองครั้ง และเวลาเดิมไม่ถูกทับ"""
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    pid = (await _participant_ids(db_pool, activity_id))[1]
    token = build_qr_token(activity_id, pid)

    first = await _scan(db_pool, room_id, owner, activity_id, token=token)
    second = await _scan(db_pool, room_id, owner, activity_id, token=token)

    assert first["already_checked_in"] is False
    assert second["already_checked_in"] is True
    assert second["checked_in_at"] == first["checked_in_at"]

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM activity_participants WHERE activity_id = $1", activity_id
        )
    assert count == 1, "สแกนซ้ำต้องไม่สร้างแถวใหม่"


async def test_scan_via_participant_id_works_without_token(db_pool):
    """โหมดกรอกรหัส/กดชื่อ (กล้องถูกปฏิเสธ) — ไม่ต้องมี token"""
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    pid = (await _participant_ids(db_pool, activity_id))[1]

    result = await _scan(db_pool, room_id, owner, activity_id, participant_id=pid)

    assert result["status"] == "attended"
    async with db_pool.acquire() as conn:
        via = await conn.fetchval(
            "SELECT new_values->>'via' FROM audit_logs "
            "WHERE endpoint_or_command = 'checkin_qr' AND entity_id = $1",
            str(pid),
        )
    assert via == "participant_id"


async def test_scan_cancelled_participant_is_rejected(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(
        db_pool, room_id, owner, participants=[{"student_no": 1, "status": "cancelled"}]
    )
    pid = (await _participant_ids(db_pool, activity_id))[1]

    with pytest.raises(ValidationError, match="ถูกยกเลิกการเข้าร่วม"):
        await _scan(db_pool, room_id, owner, activity_id, participant_id=pid)

    assert (await _db_row(db_pool, pid))["status"] == "cancelled"


async def test_scan_token_of_other_activity_is_rejected(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 2)
    a1 = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    a2 = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 2}])
    pid1 = (await _participant_ids(db_pool, a1))[1]

    with pytest.raises(ValidationError, match="บัตร QR ไม่ถูกต้อง"):
        await _scan(db_pool, room_id, owner, a2, token=build_qr_token(a1, pid1))

    assert (await _db_row(db_pool, pid1))["status"] == "confirmed"


# ================================================================
# 🪑 คิวสำรอง vs การสแกน
# ================================================================


async def test_waitlisted_can_check_in_when_there_is_a_free_seat(db_pool):
    """ไม่จำกัดความจุ → คนที่ถูกตั้งเป็นคิวสำรองด้วยมือสแกนได้ และหลุดจากคิว"""
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(
        db_pool, room_id, owner,
        participants=[{"student_no": 1}, {"student_no": 2, "status": "waitlisted"}],
    )
    pid = (await _participant_ids(db_pool, activity_id))[2]

    result = await _scan(db_pool, room_id, owner, activity_id, participant_id=pid)

    assert result["was_waitlisted"] is True
    row = await _db_row(db_pool, pid)
    assert row["status"] == "attended"
    assert row["queue_position"] is None


async def test_waitlisted_check_in_rejected_when_activity_is_full(db_pool):
    """คิวสำรองห้ามแอบเกินเพดาน — 400 พร้อมบอกว่าต้องยกเลิกหรือเพิ่มความจุ"""
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(
        db_pool, room_id, owner, capacity=1,
        participants=[{"student_no": 1}, {"student_no": 2}],
    )
    pid = (await _participant_ids(db_pool, activity_id))[2]

    with pytest.raises(ValidationError, match="กิจกรรมเต็มแล้ว"):
        await _scan(db_pool, room_id, owner, activity_id, participant_id=pid)

    assert (await _db_row(db_pool, pid))["status"] == "waitlisted"


# ================================================================
# 🖐️ เช็คอินด้วยมือ (PATCH participant) — เวลาเดินคู่กับสถานะ
# ================================================================


async def test_patch_to_attended_stamps_checkin_and_back_clears_it(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    pid = (await _participant_ids(db_pool, activity_id))[1]

    await ActivityService.update_participant(
        pool=db_pool, activity_id=activity_id, participant_id=pid,
        update_data={"status": "attended"}, user_name=STAFF,
        client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )
    row = await _db_row(db_pool, pid)
    assert row["status"] == "attended"
    assert row["checked_in_at"] is not None
    assert row["checked_in_by"] == STAFF

    # ย้อนกลับเป็นยืนยันแล้ว ⇒ ไม่ได้ "มาแล้ว" อีก ⇒ ต้องไม่มีเวลาเช็คอินค้าง
    await ActivityService.update_participant(
        pool=db_pool, activity_id=activity_id, participant_id=pid,
        update_data={"status": "confirmed"}, user_name=STAFF,
        client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )
    row = await _db_row(db_pool, pid)
    assert row["status"] == "confirmed"
    assert row["checked_in_at"] is None
    assert row["checked_in_by"] is None


async def test_batch_update_to_attended_stamps_checkin(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(
        db_pool, room_id, owner, participants=[{"student_no": 1}, {"student_no": 2}]
    )
    ids = await _participant_ids(db_pool, activity_id)

    await ActivityService.batch_update_participants(
        pool=db_pool, activity_id=activity_id,
        items=[
            {"participant_id": ids[1], "status": "attended"},
            {"participant_id": ids[2], "status": "attended"},
        ],
        user_name=STAFF, client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )

    for no in (1, 2):
        row = await _db_row(db_pool, ids[no])
        assert row["status"] == "attended"
        assert row["checked_in_at"] is not None
        assert row["checked_in_by"] == STAFF


# ================================================================
# 🌐 HTTP — 200 ทั้งครั้งแรก/ซ้ำ · 400 บัตรผิด · 404 คนไม่มีจริง
# ================================================================


async def test_http_scan_first_and_repeat_both_200(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])
    pid = (await _participant_ids(db_pool, activity_id))[1]
    token = build_qr_token(activity_id, pid)
    url = f"/api/classroom/{room_id}/activities/{activity_id}/checkin/qr?target_type=room"
    headers = _web_headers(owner)

    first = client.post(url, json={"token": token, "user_name": STAFF}, headers=headers)
    second = client.post(url, json={"token": token, "user_name": STAFF}, headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["already_checked_in"] is False
    assert second.status_code == 200, second.text
    assert second.json()["already_checked_in"] is True


async def test_http_scan_with_invalid_token_returns_400(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])

    resp = client.post(
        f"/api/classroom/{room_id}/activities/{activity_id}/checkin/qr?target_type=room",
        json={"token": "CLS-EVT1:1:1:deadbeef", "user_name": STAFF},
        headers=_web_headers(owner),
    )

    assert resp.status_code == 400
    assert "บัตร QR ไม่ถูกต้อง" in resp.json()["detail"]


async def test_http_scan_unknown_participant_returns_404(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])

    resp = client.post(
        f"/api/classroom/{room_id}/activities/{activity_id}/checkin/qr?target_type=room",
        json={"participant_id": 987654321, "user_name": STAFF},
        headers=_web_headers(owner),
    )

    assert resp.status_code == 404


async def test_http_list_codes_returns_tokens(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(
        db_pool, room_id, owner, participants=[{"student_no": 1}, {"student_no": 2}]
    )

    resp = client.get(
        f"/api/classroom/{room_id}/activities/{activity_id}/checkin/qr?target_type=room",
        headers=_web_headers(owner),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [c["student_no"] for c in body["codes"]] == [1, 2]
    assert all(c["token"].startswith("CLS-EVT1:") for c in body["codes"])


async def test_http_scan_without_proof_returns_422(client, db_pool):
    """body ที่ไม่มีทั้ง token และ participant_id ต้องถูกปฏิเสธที่ schema (422)"""
    room_id, owner, _ = await _make_room(db_pool, 1)
    activity_id = await _create_activity(db_pool, room_id, owner, participants=[{"student_no": 1}])

    resp = client.post(
        f"/api/classroom/{room_id}/activities/{activity_id}/checkin/qr?target_type=room",
        json={"user_name": STAFF},
        headers=_web_headers(owner),
    )

    assert resp.status_code == 422
