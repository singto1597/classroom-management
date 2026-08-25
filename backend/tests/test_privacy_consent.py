"""
Consent Model — PII gate ฝั่งอ่าน (profile / search / export) + ฝั่งเขียน (add / join / approve)

ช่องโหว่ที่ปิด: แอดมินสร้างห้องแล้วแอดชื่อคนอื่น (ที่ตรงกับบัญชีจริง) → เห็น PII เต็ม
กฎ: can_view_pii = super_admin OR ดูตัวเอง OR (identity_claimed AND VIEW_ALL_STUDENTS)

Pattern ตาม docs/rules/testing.md: async fixtures, deep-DB verify, mock ActionService กันแตะ Redis
"""
import io
import json
import random
import string
import uuid

import openpyxl
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from core.config import settings
from core.privacy import SENTINEL
from models.room_schemas import RoomJoinRequest
from services.room_service import RoomManagementService
from services.student_service import StudentService

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, email=None, google_id=None, discord_id=None, phone_number=None,
                       first_name="Test", last_name="User", username=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, google_id, discord_id, phone_number, first_name, last_name, username,
                               blood_group, phone_number_parent)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            email, google_id, discord_id, phone_number, first_name, last_name, username,
            "B", "081-234-5678",
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room"):
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
        return room_id, code


def _parse_claim_meta(raw) -> dict:
    """asyncpg คืน JSONB เป็น str/dict ตามเวอร์ชัน → normalize (ตาม lesson skills.md)"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, status="active",
                          identity_claimed=False, added_by=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by)
            VALUES ($1, $2, $3, 'student', $4, $5, $6)
            RETURNING id
            """,
            room_id, user_id, student_no, status, identity_claimed, added_by,
        )


# === profile: can_view_pii ===


async def test_admin_cannot_read_pii_of_unclaimed_member(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    victim = await _insert_user(db_pool, first_name="Victim", last_name="One", email="v1@example.com")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, victim, student_no=5, status="active", identity_claimed=False)

    profile = await StudentService.get_student_profile(
        pool=db_pool, student_no=5, requester_user_id=admin,
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert profile["phone_number"] == SENTINEL
    assert profile["blood_group"] == SENTINEL
    assert profile["email"] == SENTINEL


async def test_admin_can_read_pii_of_claimed_member(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    victim = await _insert_user(db_pool, first_name="Victim", last_name="Two", email="v2@example.com", phone_number="089-999-9999")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, victim, student_no=6, status="active", identity_claimed=True)

    profile = await StudentService.get_student_profile(
        pool=db_pool, student_no=6, requester_user_id=admin,
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert profile["phone_number"] is not None
    assert profile["email"] == "v2@example.com"
    assert profile["blood_group"] == "B"


async def test_self_sees_own_pii_even_unclaimed(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    victim = await _insert_user(db_pool, first_name="Victim", last_name="Three", email="v3@example.com", phone_number="089-999-9999")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, victim, student_no=7, status="active", identity_claimed=False)

    profile = await StudentService.get_student_profile(
        pool=db_pool, student_no=7, requester_user_id=victim,
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert profile["phone_number"] is not None
    assert profile["email"] == "v3@example.com"


async def test_super_admin_sees_unclaimed_pii(db_pool, monkeypatch):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    victim = await _insert_user(db_pool, first_name="Victim", last_name="Four", email="v4@example.com")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, victim, student_no=8, status="active", identity_claimed=False)
    monkeypatch.setattr(settings, "SUPER_ADMIN_ID", admin)

    profile = await StudentService.get_student_profile(
        pool=db_pool, student_no=8, requester_user_id=admin,
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert profile["email"] == "v4@example.com"


# === search: mask per row ===


async def test_search_masks_unclaimed_but_shows_claimed(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    unclaimed = await _insert_user(db_pool, first_name="Somchai", last_name="Unclaimed", email="u@example.com")
    claimed = await _insert_user(db_pool, first_name="Somchai", last_name="Claimed", email="c@example.com")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, unclaimed, student_no=1, identity_claimed=False)
    await _insert_student(db_pool, room_id, claimed, student_no=2, identity_claimed=True)

    results = await StudentService.search_students(
        pool=db_pool, query="Somchai", client_source="test", actor_identifier="test",
        room_id=room_id, user_id=admin,
    )
    by_name = {r["last_name"]: r for r in results}
    assert by_name["Unclaimed"]["email"] == SENTINEL
    assert by_name["Claimed"]["email"] == "c@example.com"


# === export: blank PII of unclaimed ===


async def test_export_blanks_unclaimed_pii(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    unclaimed = await _insert_user(db_pool, first_name="Somchai", last_name="Unclaimed", email="u@example.com")
    claimed = await _insert_user(db_pool, first_name="Somchai", last_name="Claimed", email="c@example.com")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, unclaimed, student_no=1, identity_claimed=False)
    await _insert_student(db_pool, room_id, claimed, student_no=2, identity_claimed=True)

    output = await StudentService.export_students_excel(
        pool=db_pool, fields=["student_no", "first_name", "last_name", "email", "blood_group"],
        user_name="Admin", user_id=admin, client_source="test", actor_identifier="test", room_id=room_id,
    )
    wb = openpyxl.load_workbook(io.BytesIO(output.read()))
    ws = wb["รายชื่อ"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    email_idx = header.index("อีเมล")
    blood_idx = header.index("กรุ๊ปเลือด")
    data = {r[2]: r for r in rows[1:]}  # key by last_name
    # unclaimed → blank
    assert data["Unclaimed"][email_idx] in ("", None)
    assert data["Unclaimed"][blood_idx] in ("", None)
    # claimed → มีค่า
    assert data["Claimed"][email_idx] == "c@example.com"


# === add_student: real account → invite, ghost → active ===


async def test_add_student_real_account_creates_pending_invite(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    existing = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="s@example.com")
    room_id, _ = await _insert_room(db_pool, admin)

    with patch("services.student_service.ActionService.notify_student_invite", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=10, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=admin,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, status, identity_claimed, added_by FROM students WHERE room_id = $1 AND student_no = 10",
            room_id,
        )
        assert row["user_id"] == existing
        assert row["status"] == "pending"
        assert row["identity_claimed"] is False
        assert row["added_by"] == admin


async def test_add_student_ghost_creates_active(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    room_id, _ = await _insert_room(db_pool, admin)

    with patch("services.student_service.ActionService.notify_new_student", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=11, first_name="Somchai", last_name="Newbie",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=admin,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, identity_claimed, added_by FROM students WHERE room_id = $1 AND student_no = 11",
            room_id,
        )
        assert row["status"] == "active"
        assert row["identity_claimed"] is False


# === approve: admin cannot approve a pending invite ===


async def test_approve_join_request_blocks_admin_added_invite(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    invitee = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="s@example.com")
    room_id, _ = await _insert_room(db_pool, admin)
    await _insert_student(db_pool, room_id, invitee, student_no=5, status="pending", added_by=admin)

    with pytest.raises(HTTPException) as exc:
        await RoomManagementService.approve_join_request(
            pool=db_pool, room_id=room_id, student_no=5, user_id=admin,
            client_source="test", actor_identifier="test",
        )
    assert exc.value.status_code == 400

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["status"] == "pending"  # ไม่โดนอนุมัติ


# === join_room: ghost claim ต้องผ่าน admin approval (ไม่สวมรอยทันที) ===


async def test_join_room_ghost_claim_becomes_pending_then_approved(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    room_id, code = await _insert_room(db_pool, admin)
    # แอดมินแอด ghost (ไม่มีบัญชี) ชื่อ "Somchai Jaidee" → active
    with patch("services.student_service.ActionService.notify_new_student", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=3, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=admin,
        )
    # บัญชีจริงที่ชื่อเดียวกัน ขอเข้าห้อง → ต้องกลายเป็น pending claim (ไม่ active ทันที)
    real = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="real@example.com")

    payload = RoomJoinRequest(room_code=code, student_no=3, first_name="Somchai", last_name="Jaidee")
    result = await RoomManagementService.join_room(
        pool=db_pool, payload=payload, user_id=real, client_source="test", actor_identifier="test",
    )
    assert "รอการอนุมัติ" in result["message"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, status, identity_claimed, claim_meta FROM students WHERE room_id = $1 AND student_no = 3",
            room_id,
        )
        assert row["user_id"] == real
        assert row["status"] == "pending"
        assert row["identity_claimed"] is False
        assert _parse_claim_meta(row["claim_meta"])["name_match"] is True

    # แอดมินอนุมัติ → active + claimed
    await RoomManagementService.approve_join_request(
        pool=db_pool, room_id=room_id, student_no=3, user_id=admin,
        client_source="test", actor_identifier="test",
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, identity_claimed FROM students WHERE room_id = $1 AND student_no = 3", room_id)
        assert row["status"] == "active"
        assert row["identity_claimed"] is True


async def test_join_room_ghost_claim_name_mismatch_goes_to_admin(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    room_id, code = await _insert_room(db_pool, admin)
    with patch("services.student_service.ActionService.notify_new_student", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=4, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=admin,
        )
    real = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="real@example.com")

    # ชื่อเพี้ยนเล็กน้อย (นามสกุลต่าง) — ไม่ error 400 แบบเดิม แต่ไปเป็นคำขอให้แอดมินตัดสิน
    payload = RoomJoinRequest(room_code=code, student_no=4, first_name="Somchai", last_name="Jai-Dee")
    result = await RoomManagementService.join_room(
        pool=db_pool, payload=payload, user_id=real, client_source="test", actor_identifier="test",
    )
    assert "รอการอนุมัติ" in result["message"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT claim_meta, status FROM students WHERE room_id = $1 AND student_no = 4", room_id)
        assert row["status"] == "pending"
        assert _parse_claim_meta(row["claim_meta"])["name_match"] is False
        assert _parse_claim_meta(row["claim_meta"])["ghost_last_name"] == "Jaidee"  # ชื่อเดิมที่แอดมินแอดไว้


async def test_join_room_ghost_claim_does_not_link_cross_room(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    room_a, _ = await _insert_room(db_pool, admin, room_name="Room A")
    room_b, code_b = await _insert_room(db_pool, admin, room_name="Room B")
    # ghost เดียวกันถูกแอดในสองห้อง
    with patch("services.student_service.ActionService.notify_new_student", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=1, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_a, actor_user_id=admin,
        )
        await StudentService.add_student(
            pool=db_pool, student_no=1, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_b, actor_user_id=admin,
        )

    async with db_pool.acquire() as conn:
        ghost_id = await conn.fetchval(
            "SELECT s.user_id FROM students s WHERE s.room_id = $1 AND s.student_no = 1", room_a,
        )

    real = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="real@example.com")
    payload = RoomJoinRequest(room_code=code_b, student_no=1, first_name="Somchai", last_name="Jaidee")
    await RoomManagementService.join_room(
        pool=db_pool, payload=payload, user_id=real, client_source="test", actor_identifier="test",
    )
    await RoomManagementService.approve_join_request(
        pool=db_pool, room_id=room_b, student_no=1, user_id=admin,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row_b = await conn.fetchrow("SELECT user_id, status FROM students WHERE room_id = $1 AND student_no = 1", room_b)
        row_a = await conn.fetchrow("SELECT user_id, status FROM students WHERE room_id = $1 AND student_no = 1", room_a)
        assert row_b["user_id"] == real       # ห้องที่ขอ ถูก link ไปบัญชีจริง
        assert row_b["status"] == "active"
        assert row_a["user_id"] == ghost_id   # ห้องอื่นยังเป็น ghost → PII ยังถูกปิด
        assert row_a["status"] == "active"


async def test_reject_claim_restores_ghost(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    room_id, code = await _insert_room(db_pool, admin)
    with patch("services.student_service.ActionService.notify_new_student", new_callable=AsyncMock):
        await StudentService.add_student(
            pool=db_pool, student_no=9, first_name="Somchai", last_name="Jaidee",
            user_name="Admin", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=admin,
        )
    async with db_pool.acquire() as conn:
        ghost_id = await conn.fetchval("SELECT s.user_id FROM students s WHERE s.room_id = $1 AND s.student_no = 9", room_id)

    real = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="real@example.com")
    payload = RoomJoinRequest(room_code=code, student_no=9, first_name="Somchai", last_name="Jaidee")
    await RoomManagementService.join_room(
        pool=db_pool, payload=payload, user_id=real, client_source="test", actor_identifier="test",
    )
    await RoomManagementService.reject_join_request(
        pool=db_pool, room_id=room_id, student_no=9, user_id=admin,
        client_source="test", actor_identifier="test",
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, status, identity_claimed FROM students WHERE room_id = $1 AND student_no = 9", room_id,
        )
        assert row["user_id"] == ghost_id   # กู้คืน ghost
        assert row["status"] == "active"
        assert row["identity_claimed"] is False
