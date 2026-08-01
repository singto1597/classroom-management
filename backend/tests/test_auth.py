import random
import string
import uuid

import asyncpg
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.exceptions import ForbiddenError
from models.auth_schemas import OAuthProfilePayload, UserProfileUpdate
from services.auth_service import (
    link_oauth_account,
    process_user_login,
    update_user_profile,
)

pytestmark = pytest.mark.asyncio

# === Fixtures & Setup ===


async def _insert_user(
    pool,
    *,
    email=None,
    google_id=None,
    discord_id=None,
    first_name="Test",
    last_name="User",
    username="tester",
) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (email, google_id, discord_id, first_name, last_name, username)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            email,
            google_id,
            discord_id,
            first_name,
            last_name,
            username,
        )
    return user_id


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id)
            VALUES ('Test Room', $1, $2)
            RETURNING id
            """,
            code,
            owner_id,
        )
    return room_id


async def _insert_student(
    pool,
    room_id: int,
    user_id: int,
    student_no: int,
    *,
    status="active",
    is_admin=False,
):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students
                (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', $4, $5, '[]'::jsonb)
            """,
            room_id,
            user_id,
            student_no,
            status,
            is_admin,
        )


async def _fetch_user(pool, user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


# === Section 1: process_user_login ===


async def test_process_user_login_creates_new_user(db_pool):
    email = f"new_{uuid.uuid4().hex}@example.com"
    discord_id = 1_111_222_333

    payload = OAuthProfilePayload(
        email=email,
        google_id=None,
        discord_id=discord_id,
        first_name="Korn",
        last_name="Test",
        username="korn",
    )

    result = await process_user_login(
        pool=db_pool,
        payload=payload,
        client_source="test",
        actor_identifier="test",
    )

    assert result.user_id is not None

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", result.user_id)
        assert row is not None
        assert row["email"] == email
        assert row["discord_id"] == discord_id
        assert row["google_id"] is None


async def test_process_user_login_updates_existing_email_with_new_provider(db_pool):
    email = f"existing_{uuid.uuid4().hex}@example.com"
    old_user_id = await _insert_user(
        db_pool,
        email=email,
        first_name="Old",
        last_name="User",
        username="olduser",
    )

    discord_id = 2_222_333_444
    payload = OAuthProfilePayload(
        email=email,
        google_id=None,
        discord_id=discord_id,
        first_name="New",
        last_name="Name",
        username="newname",
    )

    result = await process_user_login(
        pool=db_pool,
        payload=payload,
        client_source="test",
        actor_identifier="test",
    )

    assert result.user_id == old_user_id

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE email = $1", email)
        assert count == 1

        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", old_user_id)
        assert row["discord_id"] == discord_id
        # first_name is NOT updated in process_user_login
        assert row["first_name"] == "Old"


async def test_process_user_login_merges_duplicate_accounts_and_moves_students(db_pool):
    email = f"merge_{uuid.uuid4().hex}@example.com"
    discord_id = 3_333_444_555

    # Accounts: one matches only discord_id, the other matches only email
    user_a_id = await _insert_user(
        db_pool,
        email=None,
        discord_id=discord_id,
        first_name="Alpha",
        last_name="A",
        username="alpha",
    )
    user_b_id = await _insert_user(
        db_pool,
        email=email,
        discord_id=None,
        first_name="Beta",
        last_name="B",
        username="beta",
    )

    room_for_b = await _insert_room(db_pool, owner_id=user_a_id)
    await _insert_student(db_pool, room_for_b, user_b_id, 7)

    payload = OAuthProfilePayload(
        email=email,
        google_id=None,
        discord_id=discord_id,
        first_name="Alpha",
        last_name="A",
        username="alpha",
    )

    result = await process_user_login(
        pool=db_pool,
        payload=payload,
        client_source="test",
        actor_identifier="test",
    )

    # Merge should keep the account that already had the Discord ID
    assert result.user_id == user_a_id

    async with db_pool.acquire() as conn:
        # old email-only account is gone
        old_user_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", user_b_id)
        assert old_user_count == 0

        # the student row that belonged to the deleted account now belongs to user_a
        student = await conn.fetchrow(
            "SELECT * FROM students WHERE room_id = $1 AND student_no = 7 AND deleted_at IS NULL",
            room_for_b,
        )
        assert student is not None
        assert student["user_id"] == user_a_id


# === Section 2: link_oauth_account (Identity Engine) ===


async def test_link_oauth_account_success_updates_provider_id(db_pool):
    user_id = await _insert_user(
        db_pool,
        email="current@example.com",
        discord_id=9_999_999_999,
        google_id=None,
        first_name="Curr",
        last_name="User",
        username="current",
    )

    result = await link_oauth_account(
        pool=db_pool,
        current_user_id=user_id,
        provider="google",
        profile={"sub": "google-new-id", "email": "current@example.com"},
        client_source="test",
        actor_identifier="test",
    )

    assert result["status"] == "success"

    row = await _fetch_user(db_pool, user_id)
    assert row["google_id"] == "google-new-id"


async def test_link_oauth_account_merges_old_account_and_moves_students(db_pool):
    # Old account that already has the Google ID
    old_user_id = await _insert_user(
        db_pool,
        email="old@example.com",
        google_id="google-merge-id",
        discord_id=None,
        first_name="Old",
        last_name="Ghost",
        username="oldghost",
    )

    # Current user that does not have a Google ID yet
    current_user_id = await _insert_user(
        db_pool,
        email="current@example.com",
        google_id=None,
        discord_id=8_888_777_666,
        first_name="Curr",
        last_name="Active",
        username="current",
    )

    room_for_old = await _insert_room(db_pool, owner_id=current_user_id)
    await _insert_student(db_pool, room_for_old, old_user_id, 42)

    result = await link_oauth_account(
        pool=db_pool,
        current_user_id=current_user_id,
        provider="google",
        profile={"sub": "google-merge-id", "email": "current@example.com"},
        client_source="test",
        actor_identifier="test",
    )

    assert result["status"] == "success"

    async with db_pool.acquire() as conn:
        # old account is fully deleted
        old_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", old_user_id)
        assert old_count == 0

        # provider id moved to current user
        curr = await conn.fetchrow("SELECT * FROM users WHERE id = $1", current_user_id)
        assert curr["google_id"] == "google-merge-id"

        # student row transferred to current user
        student = await conn.fetchrow(
            "SELECT * FROM students WHERE room_id = $1 AND student_no = 42 AND deleted_at IS NULL",
            room_for_old,
        )
        assert student is not None
        assert student["user_id"] == current_user_id


# === Section 3: update_user_profile ===


async def test_update_user_profile_updates_fields_in_db(db_pool):
    user_id = await _insert_user(
        db_pool,
        email=f"profile_{uuid.uuid4().hex}@example.com",
        first_name="OldFirst",
        last_name="OldLast",
        username="profileuser",
    )

    profile_update = UserProfileUpdate(
        prefix="Mr.",
        first_name="John",
        last_name="Doe",
    )

    result = await update_user_profile(
        pool=db_pool,
        user_id=user_id,
        profile_data=profile_update,
        client_source="test",
        actor_identifier="test",
    )

    assert result["status"] == "success"

    row = await _fetch_user(db_pool, user_id)
    assert row["prefix"] == "Mr."
    assert row["first_name"] == "John"
    assert row["last_name"] == "Doe"


# === Section 4: Edge Cases & Validation ===


@pytest.mark.parametrize(
    "provider, existing_value, new_value, expected",
    [
        # ✅ ผูกซ้ำด้วย Provider เดิมและ ID เดิม → ควรยอมรับ (Idempotent)
        ("google", "google-id-one", "google-id-one", "success"),
        ("discord", 123456789, 123456789, "success"),
        # ❌ ผูกซ้ำด้วย Provider เดิมแต่ ID ต่างกัน → ควรปฏิเสธ (ForbiddenError)
        ("google", "google-id-one", "google-id-two", "forbidden"),
        ("discord", 123456789, 987654321, "forbidden"),
        # ✅ ยังไม่มี Provider มาก่อน → ผูก ID ใหม่ได้เสมอ
        ("google", None, "google-new-id", "success"),
        ("discord", None, 555666777, "success"),
        # ❌ ใช้ Provider ที่ไม่รู้จัก → ควรมี ValidationError
        ("unknown", None, "anything", "validation_error"),
    ],
)
async def test_link_oauth_account_duplicate_provider_cases(
    db_pool,
    provider,
    existing_value,
    new_value,
    expected,
):
    user_id = await _insert_user(
        db_pool,
        email=f"dup_{uuid.uuid4().hex}@example.com",
        google_id=existing_value if provider == "google" else None,
        discord_id=existing_value if provider == "discord" else None,
        first_name="Dup",
        last_name="User",
        username="dupuser",
    )
    if provider == "discord":
        profile = {"id": new_value, "email": "dup@example.com"}
    else:
        profile = {"sub": new_value, "email": "dup@example.com"}

    if expected == "success":
        result = await link_oauth_account(
            pool=db_pool,
            current_user_id=user_id,
            provider=provider,
            profile=profile,
            client_source="test",
            actor_identifier="test",
        )
        assert result["status"] == "success"
    elif expected == "forbidden":
        with pytest.raises(ForbiddenError):
            await link_oauth_account(
                pool=db_pool,
                current_user_id=user_id,
                provider=provider,
                profile=profile,
                client_source="test",
                actor_identifier="test",
            )
    else:  # validation_error
        with pytest.raises(ValidationError):
            await link_oauth_account(
                pool=db_pool,
                current_user_id=user_id,
                provider=provider,
                profile=profile,
                client_source="test",
                actor_identifier="test",
            )


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("first_name", "x" * 101),
        ("last_name", "y" * 101),
        ("prefix", "z" * 11),
    ],
)
async def test_update_user_profile_rejects_too_long_fields(field_name, invalid_value):
    data = {
        "prefix": "Mr.",
        "first_name": "John",
        "last_name": "Doe",
    }
    data[field_name] = invalid_value
    with pytest.raises(ValidationError):
        UserProfileUpdate(**data)


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("prefix", None),
        ("first_name", None),
        ("last_name", None),
    ],
)
async def test_update_user_profile_rejects_null_fields(field_name, invalid_value):
    data = {
        "prefix": "Mr.",
        "first_name": "John",
        "last_name": "Doe",
    }
    data[field_name] = invalid_value
    with pytest.raises(ValidationError):
        UserProfileUpdate(**data)


@pytest.mark.parametrize(
    "payload_kwargs",
    [
        {"email": None, "google_id": None, "discord_id": None},
        {"email": "", "google_id": None, "discord_id": None},
        {"email": None, "google_id": "", "discord_id": None},
        {"email": None, "google_id": None, "discord_id": None},
    ],
)
async def test_process_user_login_payload_requires_identifier(payload_kwargs):
    base = {
        "first_name": "Ident",
        "last_name": "Test",
        "username": "identtest",
    }
    with pytest.raises(ValidationError):
        OAuthProfilePayload(**base, **payload_kwargs)


# === Section 5: More Auth Edge Cases ===


async def test_process_user_login_invalid_email_raises_validation():
    with pytest.raises(ValidationError):
        OAuthProfilePayload(
            email="invalid-email",
            google_id=None,
            discord_id=None,
            first_name="Test",
            last_name="User",
            username="invalid",
        )


async def test_process_user_login_with_both_provider_ids(db_pool):
    email = f"both_{uuid.uuid4().hex}@example.com"
    payload = OAuthProfilePayload(
        email=email,
        google_id="google-both-123",
        discord_id=555666777,
        first_name="Dual",
        last_name="Identity",
        username="dual",
    )
    result = await process_user_login(
        pool=db_pool,
        payload=payload,
        client_source="test",
        actor_identifier="test",
    )
    assert result.user_id is not None

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", result.user_id)
        assert row["google_id"] == "google-both-123"
        assert row["discord_id"] == 555666777


async def test_update_user_profile_nonexistent_user_raises_404(db_pool):
    profile_update = UserProfileUpdate(prefix="Mr.", first_name="Ghost", last_name="No")
    with pytest.raises(HTTPException) as exc_info:
        await update_user_profile(
            pool=db_pool,
            user_id=999_999,
            profile_data=profile_update,
            client_source="test",
            actor_identifier="test",
        )
    assert exc_info.value.status_code == 404
