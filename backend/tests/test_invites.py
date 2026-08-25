"""
Consent Model — คำเชิญเข้าร่วมห้อง (invites)

- แอดมินแอดชื่อที่ตรงกับบัญชีจริง → สร้างแถว pending (added_by=admin, identity_claimed=FALSE)
- เจ้าตัว login แล้วกดรับ (accept_invite) → active + identity_claimed=TRUE (PII ถึงเปิดให้ห้องดู)
- แอดมินอนุมัติแทนไม่ได้ (approve_join_request block ถ้า added_by IS NOT NULL)

ครอบคลุม service-level (RoomManagementService.list_my_invites / accept_invite)
+ HTTP-level (GET /api/classroom/invites, POST /api/classroom/invites/{id}/accept)
Pattern ตาม docs/rules/testing.md: async fixtures, deep-DB verify, mock ActionService กันแตะ Redis จริง
"""
import random
import string
import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from core.config import settings
from services.room_service import RoomManagementService

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, email=None, google_id=None, discord_id=None, first_name="Test", last_name="User", username=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, google_id, discord_id, first_name, last_name, username)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            email, google_id, discord_id, first_name, last_name, username,
        )


async def _insert_room(pool, owner_id: int, *, server_id=None, room_name="Test Room") -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id, server_id) VALUES ($1, $2, $3, $4) RETURNING id",
            room_name, code, owner_id, server_id,
        )
        # ผู้สร้างห้องเป็น admin + identity_claimed (เจ้าของยินยอมเอง)
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb, TRUE)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_invite(pool, room_id: int, user_id: int, student_no: int, added_by: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by)
            VALUES ($1, $2, $3, 'student', 'pending', FALSE, $4)
            RETURNING id
            """,
            room_id, user_id, student_no, added_by,
        )


def _make_web_headers(user_id: int) -> dict:
    from jose import jwt
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# === Service-level: list_my_invites ===


async def test_list_my_invites_returns_admin_added_pending(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    invitee = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="s@example.com")
    room_id = await _insert_room(db_pool, admin, room_name="M.4/1")
    await _insert_invite(db_pool, room_id, invitee, student_no=5, added_by=admin)

    invites = await RoomManagementService.list_my_invites(
        pool=db_pool, user_id=invitee, client_source="test", actor_identifier="test",
    )

    assert len(invites) == 1
    inv = invites[0]
    assert inv["invite_id"] is not None
    assert inv["student_no"] == 5
    assert inv["room_id"] == room_id
    assert inv["room_name"] == "M.4/1"
    assert inv["added_by_first"] == "Admin"
    assert inv["added_by_last"] == "Room"


async def test_list_my_invites_excludes_self_join_pending(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    joiner = await _insert_user(db_pool, first_name="Joiner", last_name="User")
    room_id = await _insert_room(db_pool, admin)
    # self-join pending (added_by NULL) — ไม่ใช่คำเชิญ ต้องไม่โผล่
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by) VALUES ($1, $2, $3, 'student', 'pending', FALSE, NULL)",
            room_id, joiner, 7,
        )

    invites = await RoomManagementService.list_my_invites(
        pool=db_pool, user_id=joiner, client_source="test", actor_identifier="test",
    )
    assert invites == []


async def test_list_my_invites_empty_for_others(db_pool):
    admin = await _insert_user(db_pool)
    a = await _insert_user(db_pool)
    b = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, admin)
    await _insert_invite(db_pool, room_id, a, student_no=1, added_by=admin)

    invites = await RoomManagementService.list_my_invites(
        pool=db_pool, user_id=b, client_source="test", actor_identifier="test",
    )
    assert invites == []


# === Service-level: accept_invite ===


async def test_accept_invite_flips_active_and_claimed(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    invitee = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="s@example.com")
    room_id = await _insert_room(db_pool, admin, server_id=random.randint(1_000_000, 9_999_999))
    invite_id = await _insert_invite(db_pool, room_id, invitee, student_no=5, added_by=admin)

    with patch("services.room_service.ActionService.notify_invite_accepted", new_callable=AsyncMock) as mock_notify:
        result = await RoomManagementService.accept_invite(
            pool=db_pool, invite_id=invite_id, user_id=invitee,
            client_source="test", actor_identifier="test",
        )
        mock_notify.assert_awaited_once()

    assert result["message"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, identity_claimed FROM students WHERE id = $1", invite_id)
        assert row["status"] == "active"
        assert row["identity_claimed"] is True


async def test_accept_invite_other_users_invite_forbidden(db_pool):
    admin = await _insert_user(db_pool)
    invitee = await _insert_user(db_pool, email="a@example.com")
    other = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, admin)
    invite_id = await _insert_invite(db_pool, room_id, invitee, student_no=1, added_by=admin)

    with patch("services.room_service.ActionService.notify_invite_accepted", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc:
            await RoomManagementService.accept_invite(
                pool=db_pool, invite_id=invite_id, user_id=other,
                client_source="test", actor_identifier="test",
            )
        assert exc.value.status_code == 403


async def test_accept_invite_twice_rejected(db_pool):
    admin = await _insert_user(db_pool)
    invitee = await _insert_user(db_pool, email="a@example.com")
    room_id = await _insert_room(db_pool, admin)
    invite_id = await _insert_invite(db_pool, room_id, invitee, student_no=1, added_by=admin)

    with patch("services.room_service.ActionService.notify_invite_accepted", new_callable=AsyncMock):
        await RoomManagementService.accept_invite(
            pool=db_pool, invite_id=invite_id, user_id=invitee,
            client_source="test", actor_identifier="test",
        )
        with pytest.raises(HTTPException) as exc:
            await RoomManagementService.accept_invite(
                pool=db_pool, invite_id=invite_id, user_id=invitee,
                client_source="test", actor_identifier="test",
            )
        assert exc.value.status_code == 400


async def test_accept_invite_non_invite_row_rejected(db_pool):
    admin = await _insert_user(db_pool)
    joiner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, admin)
    # self-join pending (added_by NULL) → ไม่ใช่คำเชิญ
    async with db_pool.acquire() as conn:
        sid = await conn.fetchval(
            "INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by) VALUES ($1, $2, $3, 'student', 'pending', FALSE, NULL) RETURNING id",
            room_id, joiner, 3,
        )

    with pytest.raises(HTTPException) as exc:
        await RoomManagementService.accept_invite(
            pool=db_pool, invite_id=sid, user_id=joiner,
            client_source="test", actor_identifier="test",
        )
    assert exc.value.status_code == 400


# === HTTP-level ===


async def test_get_invites_http_requires_auth(client):
    resp = client.get("/api/classroom/invites")
    assert resp.status_code == 401


async def test_accept_invite_http_requires_auth(client):
    resp = client.post("/api/classroom/invites/1/accept")
    assert resp.status_code == 401


async def test_get_invites_http_200_and_accept(client, db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    invitee = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee", email="s@example.com")
    room_id = await _insert_room(db_pool, admin, room_name="M.4/1")
    invite_id = await _insert_invite(db_pool, room_id, invitee, student_no=5, added_by=admin)

    headers = _make_web_headers(invitee)

    resp = client.get("/api/classroom/invites", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["room_name"] == "M.4/1"

    with patch("services.room_service.ActionService.notify_invite_accepted", new_callable=AsyncMock):
        resp2 = client.post(f"/api/classroom/invites/{invite_id}/accept", headers=headers)
    assert resp2.status_code == 200

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, identity_claimed FROM students WHERE id = $1", invite_id)
        assert row["status"] == "active"
        assert row["identity_claimed"] is True

    # รับซ้ำ → 400
    resp3 = client.post(f"/api/classroom/invites/{invite_id}/accept", headers=headers)
    assert resp3.status_code == 400
