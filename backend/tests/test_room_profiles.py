"""
Hybrid profile — override ต่อห้อง (`student_room_profiles`) + view `v_student_profiles`

กฎที่ล็อกไว้:
1. ผู้จัดการแก้ให้นักเรียนในห้อง → เขียน override ของห้องนั้น **ไม่แตะ `users`** ⇒ ห้องอื่นไม่กระทบ
2. นักเรียนแก้โปรไฟล์ตัวเอง → เขียน `users` + ล้าง override ของฟิลด์นั้นในห้อง
3. ยืนยันตัวตน → merge: บัญชีชนะช่องที่มีค่า, ช่องที่บัญชีว่างเก็บค่าของห้อง
4. อ่านทุกจุดผ่าน view (COALESCE) ⇒ `BASE_STUDENT_SELECT` คืนค่าที่ resolve แล้ว
5. `init_db` รันซ้ำต้องไม่ flip `identity_claimed` (บทเรียน: ห้ามมี backfill ใน init_db)

Pattern ตาม docs/rules/testing.md: async fixtures, deep-DB verify, mock ActionService
"""
import json
import random
import string
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from core.init_db import init_db
from services.student.profiles import merge_room_overrides_on_claim
from services.student_service import StudentService

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, first_name="Test", last_name="User", nickname=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (first_name, last_name, nickname, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            first_name, last_name, nickname, f"u{uuid.uuid4().hex[:12]}",
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
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '["all"]'::jsonb, TRUE)
            """,
            room_id, owner_id,
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *,
                          status="active", identity_claimed=False, added_by=None,
                          permissions=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by, permissions)
            VALUES ($1, $2, $3, 'student', $4, $5, $6, $7::jsonb)
            RETURNING id
            """,
            room_id, user_id, student_no, status, identity_claimed, added_by,
            json.dumps(permissions or []),
        )


# === 1) manager แก้ → override, users ไม่เปลี่ยน, ห้องอื่นไม่กระทบ ===


async def test_manager_edit_creates_override_and_leaves_account_untouched(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    student_user = await _insert_user(db_pool, first_name="Account", last_name="Name")
    room_a = await _insert_room(db_pool, admin, room_name="Room A")
    room_b = await _insert_room(db_pool, admin, room_name="Room B")
    student_a_id = await _insert_student(db_pool, room_a, student_user, student_no=5, identity_claimed=False)
    await _insert_student(db_pool, room_b, student_user, student_no=1, identity_claimed=True)

    await StudentService.update_student(
        pool=db_pool, student_no=5, update_data={"first_name": "RoomTyped"},
        updater_user_id=admin, client_source="test", actor_identifier="test", room_id=room_a,
    )

    async with db_pool.acquire() as conn:
        # บัญชีกลางไม่ถูกแตะ
        assert await conn.fetchval("SELECT first_name FROM users WHERE id = $1", student_user) == "Account"
        # override ถูกสร้าง
        assert await conn.fetchval(
            "SELECT first_name FROM student_room_profiles WHERE student_id = $1", student_a_id
        ) == "RoomTyped"
        # view resolve ตามห้อง
        assert await conn.fetchval(
            "SELECT first_name FROM v_student_profiles WHERE student_id = $1", student_a_id
        ) == "RoomTyped"
        room_b_row = await conn.fetchrow(
            "SELECT s.id, u.first_name FROM students s JOIN v_student_profiles u ON u.student_id = s.id "
            "WHERE s.room_id = $1 AND s.user_id = $2",
            room_b, student_user,
        )
        assert room_b_row["first_name"] == "Account"   # ห้องอื่นยังเห็นชื่อบัญชีเดิม


# === 2) self แก้ → users เปลี่ยน + override ของฟิลด์นั้นถูกล้าง ===


async def test_self_edit_updates_account_and_clears_override(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    student_user = await _insert_user(db_pool, first_name="Account", last_name="Name")
    room_id = await _insert_room(db_pool, admin)
    student_id = await _insert_student(db_pool, room_id, student_user, student_no=5, identity_claimed=False)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO student_room_profiles (student_id, first_name, nickname) VALUES ($1, 'RoomTyped', 'RoomNick')",
            student_id,
        )

    await StudentService.update_student(
        pool=db_pool, student_no=5, update_data={"first_name": "SelfTyped"},
        updater_user_id=student_user, client_source="test", actor_identifier="test", room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT first_name FROM users WHERE id = $1", student_user) == "SelfTyped"
        override = await conn.fetchrow(
            "SELECT first_name, nickname FROM student_room_profiles WHERE student_id = $1", student_id
        )
        assert override["first_name"] is None       # ล้างเฉพาะฟิลด์ที่แก้
        assert override["nickname"] == "RoomNick"   # ฟิลด์อื่นยังอยู่
        assert await conn.fetchval(
            "SELECT first_name FROM v_student_profiles WHERE student_id = $1", student_id
        ) == "SelfTyped"


# === 3) merge on claim ===


async def test_merge_on_claim_keeps_room_values_where_account_is_empty(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    student_user = await _insert_user(db_pool, first_name="Account", last_name="Name", nickname=None)
    room_id = await _insert_room(db_pool, admin)
    student_id = await _insert_student(db_pool, room_id, student_user, student_no=5)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO student_room_profiles (student_id, first_name, nickname) VALUES ($1, 'RoomTyped', 'RoomNick')",
            student_id,
        )
        await merge_room_overrides_on_claim(conn, student_id, student_user)

        override = await conn.fetchrow(
            "SELECT first_name, nickname FROM student_room_profiles WHERE student_id = $1", student_id
        )
        assert override["first_name"] is None      # บัญชีมีค่า → บัญชีชนะ
        assert override["nickname"] == "RoomNick"  # บัญชีว่าง → เก็บของห้อง

        resolved = await conn.fetchrow(
            "SELECT first_name, nickname FROM v_student_profiles WHERE student_id = $1", student_id
        )
        assert resolved["first_name"] == "Account"
        assert resolved["nickname"] == "RoomNick"


# === 4) อ่านรายชื่อใช้ค่าที่ resolve แล้ว ===


async def test_roster_reads_use_resolved_override(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    student_user = await _insert_user(db_pool, first_name="Account", last_name="Name")
    room_id = await _insert_room(db_pool, admin)
    student_id = await _insert_student(db_pool, room_id, student_user, student_no=5, identity_claimed=False)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO student_room_profiles (student_id, last_name) VALUES ($1, 'RoomLast')",
            student_id,
        )

    rows = await StudentService.get_all_students(
        pool=db_pool, user_id=admin, client_source="test", actor_identifier="test", room_id=room_id,
    )
    row = next(r for r in rows if r["student_no"] == 5)
    assert row["first_name"] == "Account"
    assert row["last_name"] == "RoomLast"


# === 5) init_db รันซ้ำต้องไม่ flip identity_claimed (กัน backfill หลุดกลับมา) ===


async def test_repeated_init_db_keeps_active_unclaimed_rows_unclaimed(db_pool):
    admin = await _insert_user(db_pool, first_name="Admin", last_name="Room")
    student_user = await _insert_user(db_pool, first_name="Account", last_name="Name")
    room_id = await _insert_room(db_pool, admin)
    await _insert_student(
        db_pool, room_id, student_user, student_no=5,
        status="active", identity_claimed=False, added_by=admin,
    )

    with patch("services.action_service.ActionService._publish", new_callable=AsyncMock):
        await init_db(db_pool)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, identity_claimed FROM students WHERE room_id = $1 AND student_no = 5", room_id
        )
    assert row["status"] == "active"
    assert row["identity_claimed"] is False
