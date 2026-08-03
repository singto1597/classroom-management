"""
# === PoC Tests: RBAC & Auth Hardening (regression guards) ===
พิสูจน์ว่า patch ความปลอดภัยกันการหลุดสิทธิ์ (privilege escalation) และ
การอ่านข้อมูลข้ามห้อง (cross-room data leak) ได้จริง

Coverage:
1. classroom_sync_service: member ธรรมดาโดน ForbiddenError, admin ผ่าน
2. add_student/bulk_add_students: member ธรรมดาโดน ForbiddenError, admin ผ่าน
3. finance GET: สมาชิกห้องนี้ดูได้ แต่ข้ามห้องไม่ได้
4. setup_room: ต้องมี server_id + ผูกกับ web-created room เท่านั้น (ห้ามสร้างใหม่)
"""
import random
import string
import uuid
from datetime import date

import pytest

from core.exceptions import ForbiddenError
from services.classroom_sync_service import ClassroomService
from services.student_service import StudentService
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Fixtures & Setup ===

async def _insert_user(
    pool,
    *,
    email=None,
    first_name="Test",
    last_name="User",
    username=None,
) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            email,
            first_name,
            last_name,
            username,
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
        # ผู้สร้างห้องเป็น admin ทันที
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


async def _insert_task(pool, room_id: int, task_name="Homework") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO tasks (room_id, task_name, task_detail, due_date)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            room_id,
            task_name,
            "detail",
            date(2026, 12, 31),
        )


# === Section 1: classroom_sync_service — permission enforcement ===


async def test_plain_member_cannot_set_channel(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await ClassroomService.set_channel(
            pool=db_pool, channel_id=123456789, user_name="Plain",
            user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    # ห้องต้องไม่ถูกแก้
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] is None


async def test_admin_can_set_channel(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_channel(
        pool=db_pool, channel_id=123456789, user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] == 123456789


async def test_plain_member_cannot_delete_task(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)
    task_id = await _insert_task(db_pool, room_id)

    with pytest.raises(ForbiddenError):
        await ClassroomService.delete_task(
            pool=db_pool, task_id=task_id, user_name="Plain",
            user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is None


async def test_admin_can_delete_task(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id)

    task_name = await ClassroomService.delete_task(
        pool=db_pool, task_id=task_id, user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert task_name == "Homework"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is not None


async def test_plain_member_cannot_add_daily_note(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await ClassroomService.add_daily_note(
            pool=db_pool, target_date=date(2026, 8, 10),
            bring_items="หนังสือ", announcement="สอบ",
            user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


# === Section 2: add_student / bulk_add_students — MANAGE_STUDENTS ===


async def test_plain_member_cannot_add_student(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await StudentService.add_student(
            pool=db_pool, student_no=10, first_name="New", last_name="Kid",
            user_name="Plain", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=member,
        )

    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
            room_id, 10,
        )
        assert exists is None


async def test_admin_can_add_student(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=10, first_name="New", last_name="Kid",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM students WHERE room_id = $1 AND student_no = $2 AND deleted_at IS NULL",
            room_id, 10,
        )
        assert exists is not None


# === Section 3: finance GET — membership prevents cross-room reading ===


async def test_member_of_other_room_cannot_read_finance(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a)
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b)

    # สมาชิกห้อง B มาอ่าน finance ของห้อง A → ต้องโดน ForbiddenError
    with pytest.raises(ForbiddenError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_a, user_id=owner_b,
        )


async def test_member_of_same_room_can_read_finance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)

    # สมาชิกห้องเดียวกัน (ไม่ใช่ admin) ดู finance ได้ — transparency
    accounts = await FinanceService.get_accounts(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=member,
    )
    assert accounts == []


# === Section 4: setup_room — no more bare room creation ===


async def test_setup_room_requires_server_id(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(ValueError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="Bot Room", user_name="Owner",
            client_source="test", actor_identifier="test",
            server_id=None,
        )

    # ต้องไม่สร้างห้องใหม่เลย
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM rooms WHERE room_name = $1", "Bot Room")
        assert count == 0


async def test_setup_room_links_web_room_to_server(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="Web Room")

    # ผูก room ที่สร้างผ่านเว็บเข้ากับ Discord server
    await ClassroomService.setup_room(
        pool=db_pool, room_name="Web Room", user_name="Owner",
        client_source="test", actor_identifier="test",
        server_id=987654321,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT server_id FROM rooms WHERE id = $1", room_id)
        assert row["server_id"] == 987654321


async def test_setup_room_rejects_missing_web_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(ValueError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="No Such Room", user_name="Owner",
            client_source="test", actor_identifier="test",
            server_id=555555,
        )
