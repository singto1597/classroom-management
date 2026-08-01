import random
import string
import uuid
from datetime import datetime

import asyncpg
import pytest
from fastapi import HTTPException

from core.exceptions import ForbiddenError
from models.room_schemas import RoomJoinRequest
from services.room_service import RoomManagementService

pytestmark = pytest.mark.asyncio


async def _insert_user(
    pool,
    *,
    email=None,
    google_id=None,
    discord_id=None,
    first_name="Test",
    last_name="User",
    username=None,
    phone_number=None,
    birthday=None,
) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    if birthday is not None and isinstance(birthday, str):
        birthday = datetime.strptime(birthday, "%Y-%m-%d").date()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users
                (email, google_id, discord_id, first_name, last_name, username, phone_number, birthday)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            email,
            google_id,
            discord_id,
            first_name,
            last_name,
            username,
            phone_number,
            birthday,
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
            room_name,
            code,
            owner_id,
        )
        # รองรับผู้สร้างห้องให้เป็น Admin ในตาราง students ทันที
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id,
            owner_id,
            '["all"]',
        )
        return room_id


async def _insert_student(
    pool,
    room_id: int,
    user_id: int,
    student_no: int,
    *,
    status="pending",
    is_admin=False,
    permissions="[]",
) -> int:
    async with pool.acquire() as conn:
        final_status = "active" if is_admin else status
        return await conn.fetchval(
            """
            INSERT INTO students
                (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', $4, $5, $6::jsonb)
            RETURNING id
            """,
            room_id,
            user_id,
            student_no,
            final_status,
            is_admin,
            permissions,
        )


# === Section 1: create_room ===


async def test_create_room_creates_room_and_president_student(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Creator", last_name="Teacher")

    result = await RoomManagementService.create_room(
        pool=db_pool,
        room_name="New Room",
        user_id=owner_id,
        client_source="test",
        actor_identifier="test",
    )

    assert result["room_id"] is not None
    assert result["room_code"]

    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", result["room_id"])
        assert room is not None
        assert room["room_code"] == result["room_code"]
        assert room["owner_id"] == owner_id

        student = await conn.fetchrow(
            """
            SELECT * FROM students
            WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL
            """,
            result["room_id"],
            owner_id,
        )
        assert student is not None
        assert student["student_no"] == 0
        assert student["class_role"] == "president"
        assert student["is_admin"] is True
        assert student["status"] == "active"


# === Section 2: join_room (normal flow) ===


async def test_join_room_creates_pending_student(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    student_user_id = await _insert_user(db_pool, first_name="Join", last_name="User")

    payload = RoomJoinRequest(
        room_code=room_code,
        student_no=5,
        first_name="Join",
        last_name="User",
    )

    result = await RoomManagementService.join_room(
        pool=db_pool,
        payload=payload,
        user_id=student_user_id,
        client_source="test",
        actor_identifier="test",
    )

    assert result["room_id"] == room_id

    async with db_pool.acquire() as conn:
        student = await conn.fetchrow(
            """
            SELECT * FROM students
            WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL
            """,
            room_id,
            student_user_id,
        )
        assert student is not None
        assert student["student_no"] == 5
        assert student["status"] == "pending"


async def test_join_room_duplicate_raises_400(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    student_user_id = await _insert_user(db_pool, first_name="Again", last_name="User")

    payload_1 = RoomJoinRequest(
        room_code=room_code,
        student_no=6,
        first_name="Again",
        last_name="User",
    )
    await RoomManagementService.join_room(
        pool=db_pool,
        payload=payload_1,
        user_id=student_user_id,
        client_source="test",
        actor_identifier="test",
    )

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.join_room(
            pool=db_pool,
            payload=payload_1,
            user_id=student_user_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 400


# === Section 3: join_room (Ghost Account Claiming) ===


async def test_join_room_ghost_account_claim(db_pool):
    # Create a "ghost" user with no email / google / discord identifiers
    ghost_id = await _insert_user(
        db_pool,
        email=None,
        google_id=None,
        discord_id=None,
        first_name="Somchai",
        last_name="Jaidee",
        username="ghost",
        phone_number="0811111111",
        birthday="2000-01-01",
    )

    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)
        await _insert_student(db_pool, room_id, ghost_id, 9, status="pending")

    # Real user with same name but has Discord ID (authenticated)
    real_id = await _insert_user(
        db_pool,
        discord_id=111222333,
        first_name="Somchai",
        last_name="Jaidee",
        username="real",
    )

    payload = RoomJoinRequest(
        room_code=room_code,
        student_no=9,
        first_name="Somchai",
        last_name="Jaidee",
    )

    result = await RoomManagementService.join_room(
        pool=db_pool,
        payload=payload,
        user_id=real_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result["room_id"] == room_id
    assert result["student_id"] is not None

    async with db_pool.acquire() as conn:
        ghost_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", ghost_id)
        assert ghost_count == 0

        student = await conn.fetchrow(
            """
            SELECT * FROM students
            WHERE room_id = $1 AND student_no = 9 AND deleted_at IS NULL
            """,
            room_id,
        )
        assert student is not None
        assert student["user_id"] == real_id
        assert student["status"] == "active"

        real_user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", real_id)
        assert real_user["phone_number"] == "0811111111"
        assert real_user["birthday"] is not None


# === Section 4: approve_join_request & reject_join_request ===


async def test_approve_join_request_updates_status(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    student_user_id = await _insert_user(db_pool, first_name="Pending", last_name="Student")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 3, status="pending")

    await RoomManagementService.approve_join_request(
        pool=db_pool,
        room_id=room_id,
        student_no=3,
        user_id=owner_id,
        client_source="test",
        actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM students
            WHERE room_id = $1 AND student_no = 3 AND deleted_at IS NULL
            """,
            room_id,
        )
        assert row is not None
        assert row["status"] == "active"


async def test_reject_join_request_deletes_row(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    student_user_id = await _insert_user(db_pool, first_name="Cancel", last_name="Student")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 4, status="pending")

    await RoomManagementService.reject_join_request(
        pool=db_pool,
        room_id=room_id,
        student_no=4,
        user_id=owner_id,
        client_source="test",
        actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id = $1 AND student_no = 4",
            room_id,
        )
        assert count == 0


async def test_approve_join_request_rejects_non_admin(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    normal_user_id = await _insert_user(db_pool, first_name="Normal", last_name="User")

    async with db_pool.acquire() as conn:
        # Normal user is already an active (non-admin) member
        await _insert_student(
            db_pool,
            room_id,
            normal_user_id,
            1,
            status="active",
            permissions="[]",
        )

        pending_user_id = await _insert_user(db_pool, first_name="New", last_name="Request")
        await _insert_student(db_pool, room_id, pending_user_id, 7, status="pending")

    with pytest.raises(ForbiddenError):
        await RoomManagementService.approve_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=7,
            user_id=normal_user_id,
            client_source="test",
            actor_identifier="test",
        )
