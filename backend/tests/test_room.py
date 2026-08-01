import random
import string
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.exceptions import ForbiddenError
from models.room_schemas import RoomJoinRequest, RoomCreateRequest
from services.room_service import RoomManagementService

pytestmark = pytest.mark.asyncio


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


# === Section 5: Edge Cases & Boundary Tests ===


async def test_create_room_with_room_name_too_long_raises_validation():
    with pytest.raises(ValidationError):
        RoomCreateRequest(room_name="x" * 101)


async def test_create_room_with_empty_room_name_is_allowed(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Empty", last_name="Name")
    result = await RoomManagementService.create_room(
        pool=db_pool,
        room_name="",
        user_id=owner_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result["room_id"] is not None


async def test_join_room_unknown_code_returns_404(db_pool):
    user_id = await _insert_user(db_pool, first_name="No", last_name="Room")
    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.join_room(
            pool=db_pool,
            payload=RoomJoinRequest(
                room_code="XXXXXX",
                student_no=1,
                first_name="No",
                last_name="Room",
            ),
            user_id=user_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_join_room_student_no_zero_raises_validation():
    with pytest.raises(ValidationError):
        RoomJoinRequest(
            room_code="ABC123",
            student_no=0,
            first_name="Test",
            last_name="User",
        )


async def test_join_room_student_no_negative_raises_validation():
    with pytest.raises(ValidationError):
        RoomJoinRequest(
            room_code="ABC123",
            student_no=-1,
            first_name="Test",
            last_name="User",
        )


async def test_join_room_with_empty_names_creates_pending(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    student_id = await _insert_user(db_pool, first_name="", last_name="")
    result = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(
            room_code=room_code,
            student_no=10,
            first_name="",
            last_name="",
        ),
        user_id=student_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result["student_id"] is not None

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM students WHERE room_id = $1 AND student_no = 10 AND deleted_at IS NULL",
            room_id,
        )
        assert row is not None
        assert row["status"] == "pending"


async def test_join_room_existing_real_user_same_number_raises_400(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    existing_user = await _insert_user(db_pool, first_name="Real", last_name="Person")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, existing_user, 22, status="active", is_admin=False)

    new_user = await _insert_user(db_pool, first_name="Try", last_name="Join")

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.join_room(
            pool=db_pool,
            payload=RoomJoinRequest(
                room_code=room_code,
                student_no=22,
                first_name="Try",
                last_name="Join",
            ),
            user_id=new_user,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 400


async def test_join_room_ghost_name_mismatch_raises_400(db_pool):
    ghost_id = await _insert_user(
        db_pool,
        email=None,
        google_id=None,
        discord_id=None,
        first_name="Jane",
        last_name="Doe",
        username="ghost",
    )

    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)
        await _insert_student(db_pool, room_id, ghost_id, 5, status="pending")

    real_id = await _insert_user(
        db_pool,
        discord_id=111222777,
        first_name="Other",
        last_name="Person",
        username="real",
    )

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.join_room(
            pool=db_pool,
            payload=RoomJoinRequest(
                room_code=room_code,
                student_no=5,
                first_name="Other",
                last_name="Person",
            ),
            user_id=real_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 400


async def test_approve_join_request_with_no_pending_row_returns_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.approve_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=999,
            user_id=owner_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_reject_join_request_with_no_pending_row_returns_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.reject_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=998,
            user_id=owner_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_approve_join_request_with_normal_user_raises_forbidden(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    normal_id = await _insert_user(db_pool, first_name="Normal", last_name="Guy")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, normal_id, 2, status="active", is_admin=False)
        other_id = await _insert_user(db_pool, first_name="Other", last_name="Pending")
        await _insert_student(db_pool, room_id, other_id, 8, status="pending")

    with pytest.raises(ForbiddenError):
        await RoomManagementService.approve_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=8,
            user_id=normal_id,
            client_source="test",
            actor_identifier="test",
        )


async def test_reject_join_request_with_normal_user_raises_forbidden(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)

    normal_id = await _insert_user(db_pool, first_name="Normal", last_name="Guy")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, normal_id, 3, status="active", is_admin=False)
        other_id = await _insert_user(db_pool, first_name="Other", last_name="Pending")
        await _insert_student(db_pool, room_id, other_id, 9, status="pending")

    with pytest.raises(ForbiddenError):
        await RoomManagementService.reject_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=9,
            user_id=normal_id,
            client_source="test",
            actor_identifier="test",
        )


# === Section 6: State Violation & Privilege Escalation & Soft Delete Edge Cases ===


async def test_approve_after_reject_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="St", last_name="Privet")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 11, status="pending")

    await RoomManagementService.reject_join_request(
        pool=db_pool, room_id=room_id, student_no=11, user_id=owner_id,
        client_source="test", actor_identifier="test",
    )
    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.approve_join_request(
            pool=db_pool, room_id=room_id, student_no=11, user_id=owner_id,
            client_source="test", actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_reject_after_approve_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="Apr", last_name="Student")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 12, status="pending")

    await RoomManagementService.approve_join_request(
        pool=db_pool, room_id=room_id, student_no=12, user_id=owner_id,
        client_source="test", actor_identifier="test",
    )
    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.reject_join_request(
            pool=db_pool, room_id=room_id, student_no=12, user_id=owner_id,
            client_source="test", actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_approve_twice_second_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="Twice", last_name="Pending")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 13, status="pending")

    await RoomManagementService.approve_join_request(
        pool=db_pool, room_id=room_id, student_no=13, user_id=owner_id,
        client_source="test", actor_identifier="test",
    )
    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.approve_join_request(
            pool=db_pool, room_id=room_id, student_no=13, user_id=owner_id,
            client_source="test", actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_join_after_soft_delete_allows_rejoin(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Owner", last_name="One")
    room_id = await _insert_room(db_pool, owner_id)
    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    user_id = await _insert_user(db_pool, first_name="Soft", last_name="Delete")

    # First join creates a pending record
    result1 = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=20, first_name="Soft", last_name="Delete"),
        user_id=user_id,
        client_source="test",
        actor_identifier="test",
    )
    # Soft-delete the record manually
    async with db_pool.acquire() as conn:
        student_id = await conn.fetchval(
            "SELECT id FROM students WHERE room_id=$1 AND student_no=20 AND deleted_at IS NULL",
            room_id,
        )
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            student_id,
            _utcnow(),
        )

    # Second join with same user should succeed (no conflict with soft-deleted row)
    result2 = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=20, first_name="Soft", last_name="Delete"),
        user_id=user_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result2["student_id"] is not None

    async with db_pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id=$1 AND student_no=20 AND deleted_at IS NULL",
            room_id,
        )
        assert active_count == 1


async def test_join_same_student_no_when_previous_soft_deleted_allows_join(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    user_a = await _insert_user(db_pool, first_name="User", last_name="A")
    user_b = await _insert_user(db_pool, first_name="User", last_name="B")

    async with db_pool.acquire() as conn:
        student_a_id = await _insert_student(db_pool, room_id, user_a, 21, status="active")
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            student_a_id,
            _utcnow(),
        )

    result_b = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=21, first_name="User", last_name="B"),
        user_id=user_b,
        client_source="test",
        actor_identifier="test",
    )
    assert result_b["student_id"] is not None

    async with db_pool.acquire() as conn:
        non_deleted = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id=$1 AND student_no=21 AND deleted_at IS NULL",
            room_id,
        )
        assert non_deleted == 1


async def test_approve_after_soft_delete_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="SoftDel", last_name="Pending")
    async with db_pool.acquire() as conn:
        student_id = await _insert_student(db_pool, room_id, student_user_id, 14, status="pending")
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            student_id,
            _utcnow(),
        )

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.approve_join_request(
            pool=db_pool, room_id=room_id, student_no=14, user_id=owner_id,
            client_source="test", actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_reject_after_soft_delete_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="SoftDel", last_name="Reject")
    async with db_pool.acquire() as conn:
        student_id = await _insert_student(db_pool, room_id, student_user_id, 15, status="pending")
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            student_id,
            _utcnow(),
        )

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.reject_join_request(
            pool=db_pool, room_id=room_id, student_no=15, user_id=owner_id,
            client_source="test", actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_get_pending_requests_non_member_raises_forbidden(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    outsider_id = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await RoomManagementService.get_pending_requests(
            pool=db_pool,
            room_id=room_id,
            user_id=outsider_id,
            client_source="test",
            actor_identifier="test",
        )


async def test_get_pending_requests_regular_member_raises_forbidden(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    normal_id = await _insert_user(db_pool, first_name="Normal", last_name="Member")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, normal_id, 2, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await RoomManagementService.get_pending_requests(
            pool=db_pool,
            room_id=room_id,
            user_id=normal_id,
            client_source="test",
            actor_identifier="test",
        )


async def test_approve_request_from_other_room_raises_forbidden(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a)

    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b)

    pending_user = await _insert_user(db_pool, first_name="Pending", last_name="Guy")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_a, pending_user, 16, status="pending")

    outsider_b = await _insert_user(db_pool, first_name="Different", last_name="Room")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_b, outsider_b, 1, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await RoomManagementService.approve_join_request(
            pool=db_pool,
            room_id=room_a,
            student_no=16,
            user_id=outsider_b,
            client_source="test",
            actor_identifier="test",
        )


async def test_reject_request_from_other_room_raises_forbidden(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a)

    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b)

    pending_user = await _insert_user(db_pool, first_name="Pending", last_name="Guy2")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_a, pending_user, 17, status="pending")

    outsider_b = await _insert_user(db_pool, first_name="Different", last_name="Room2")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_b, outsider_b, 1, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await RoomManagementService.reject_join_request(
            pool=db_pool,
            room_id=room_a,
            student_no=17,
            user_id=outsider_b,
            client_source="test",
            actor_identifier="test",
        )


async def test_join_room_after_soft_deleted_ghost_claim_allows_reclaim(db_pool):
    ghost_id = await _insert_user(
        db_pool,
        email=None,
        google_id=None,
        discord_id=None,
        first_name="Ghost",
        last_name="Claim",
        username="ghostclaim",
    )
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)
        ghost_student_id = await _insert_student(db_pool, room_id, ghost_id, 18, status="pending")
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            ghost_student_id,
            _utcnow(),
        )

    real_id = await _insert_user(
        db_pool,
        discord_id=123456789,
        first_name="Ghost",
        last_name="Claim",
        username="realclaim",
    )

    result = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=18, first_name="Ghost", last_name="Claim"),
        user_id=real_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result["student_id"] is not None

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, status FROM students WHERE room_id=$1 AND student_no=18 AND deleted_at IS NULL",
            room_id,
        )
        assert row is not None
        assert row["user_id"] == real_id
        assert row["status"] == "pending"


# === Section 7: Additional Data Collision & Soft Delete / State Edge Cases ===


async def test_join_same_student_no_in_different_rooms_allowed(db_pool):
    owner1 = await _insert_user(db_pool, first_name="Owner", last_name="One")
    room1 = await _insert_room(db_pool, owner1, "Room One")
    owner2 = await _insert_user(db_pool, first_name="Owner", last_name="Two")
    room2 = await _insert_room(db_pool, owner2, "Room Two")

    async with db_pool.acquire() as conn:
        code1 = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room1)
        code2 = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room2)

    user = await _insert_user(db_pool, first_name="Multi", last_name="Room")

    res1 = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=code1, student_no=1, first_name="Multi", last_name="Room"),
        user_id=user,
        client_source="test",
        actor_identifier="test",
    )
    assert res1["student_id"] is not None

    res2 = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=code2, student_no=1, first_name="Multi", last_name="Room"),
        user_id=user,
        client_source="test",
        actor_identifier="test",
    )
    assert res2["student_id"] is not None

    async with db_pool.acquire() as conn:
        count1 = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id=$1 AND student_no=1 AND deleted_at IS NULL",
            room1,
        )
        count2 = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id=$1 AND student_no=1 AND deleted_at IS NULL",
            room2,
        )
        assert count1 == 1
        assert count2 == 1


async def test_ghost_claim_transfers_all_rooms(db_pool):
    ghost_id = await _insert_user(
        db_pool,
        email=None,
        google_id=None,
        discord_id=None,
        first_name="Niran",
        last_name="Pong",
        username="ghostniran",
        phone_number="0800000000",
        birthday="1999-12-31",
    )
    owner1 = await _insert_user(db_pool, first_name="Owner", last_name="A")
    room1 = await _insert_room(db_pool, owner1, "Room A")
    owner2 = await _insert_user(db_pool, first_name="Owner", last_name="B")
    room2 = await _insert_room(db_pool, owner2, "Room B")

    async with db_pool.acquire() as conn:
        code1 = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room1)
        code2 = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room2)
        await _insert_student(db_pool, room1, ghost_id, 1, status="pending")
        await _insert_student(db_pool, room2, ghost_id, 1, status="pending")

    real_id = await _insert_user(
        db_pool,
        discord_id=987654321,
        first_name="Niran",
        last_name="Pong",
        username="realniran",
    )

    await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=code1, student_no=1, first_name="Niran", last_name="Pong"),
        user_id=real_id,
        client_source="test",
        actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        ghost_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", ghost_id)
        assert ghost_count == 0

        for r_id in (room1, room2):
            row = await conn.fetchrow(
                "SELECT user_id, status FROM students WHERE room_id=$1 AND student_no=1 AND deleted_at IS NULL",
                r_id,
            )
            assert row is not None
            assert row["user_id"] == real_id
            assert row["status"] == "active"


async def test_approve_join_request_on_active_member_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="Active", last_name="Member")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 30, status="active", is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.approve_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=30,
            user_id=owner_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_reject_join_request_on_active_member_raises_404(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    student_user_id = await _insert_user(db_pool, first_name="Active", last_name="Reject")
    async with db_pool.acquire() as conn:
        await _insert_student(db_pool, room_id, student_user_id, 31, status="active", is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        await RoomManagementService.reject_join_request(
            pool=db_pool,
            room_id=room_id,
            student_no=31,
            user_id=owner_id,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404


async def test_get_pending_requests_excludes_soft_deleted(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    user1 = await _insert_user(db_pool, first_name="Pend", last_name="One")
    user2 = await _insert_user(db_pool, first_name="Pend", last_name="Two")

    async with db_pool.acquire() as conn:
        s1 = await _insert_student(db_pool, room_id, user1, 40, status="pending")
        await conn.execute(
            "UPDATE students SET deleted_at = $2 WHERE id = $1",
            s1,
            _utcnow(),
        )
        await _insert_student(db_pool, room_id, user2, 41, status="pending")

    rows = await RoomManagementService.get_pending_requests(
        pool=db_pool,
        room_id=room_id,
        user_id=owner_id,
        client_source="test",
        actor_identifier="test",
    )
    assert len(rows) == 1
    assert rows[0]["student_no"] == 41


async def test_join_after_reject_same_user_allowed(db_pool):
    owner_id = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner_id)
    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    user_id = await _insert_user(db_pool, first_name="Retry", last_name="Join")

    # First join creates pending, then admin rejects (hard delete)
    await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=50, first_name="Retry", last_name="Join"),
        user_id=user_id,
        client_source="test",
        actor_identifier="test",
    )
    await RoomManagementService.reject_join_request(
        pool=db_pool, room_id=room_id, student_no=50, user_id=owner_id,
        client_source="test", actor_identifier="test",
    )

    # After rejection the row is gone, so join again should succeed
    result = await RoomManagementService.join_room(
        pool=db_pool,
        payload=RoomJoinRequest(room_code=room_code, student_no=50, first_name="Retry", last_name="Join"),
        user_id=user_id,
        client_source="test",
        actor_identifier="test",
    )
    assert result["student_id"] is not None

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM students WHERE room_id=$1 AND student_no=50 AND deleted_at IS NULL",
            room_id,
        )
        assert count == 1
