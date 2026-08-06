import io
import json
import random
import string
import uuid

import openpyxl
import pytest

from core.exceptions import (
    ForbiddenError,
    RoomNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from services.student_service import StudentService

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
    username=None,
    phone_number=None,
    phone_number_parent=None,
    line_id=None,
    blood_group=None,
) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (
                email, google_id, discord_id, first_name, last_name, username,
                phone_number, phone_number_parent, line_id, blood_group
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            email,
            google_id,
            discord_id,
            first_name,
            last_name,
            username,
            phone_number,
            phone_number_parent,
            line_id,
            blood_group,
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


def _parse_permissions(raw) -> list:
    """asyncpg คืน JSONB เป็น str หรือ list ได้ตามเวอร์ชัน → normalize ไว้เทียบ"""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return []


async def _insert_student(
    pool,
    room_id: int,
    user_id: int,
    student_no: int,
    *,
    status="active",
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


# === Section 1: Happy Paths (CREATE/READ) ===


async def test_add_student_creates_user_and_student(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=10, first_name="Somchai", last_name="Jaidee",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        student = await conn.fetchrow(
            """SELECT s.*, u.first_name, u.last_name
               FROM students s JOIN users u ON s.user_id = u.id
               WHERE s.room_id = $1 AND s.student_no = 10 AND s.deleted_at IS NULL""",
            room_id,
        )
        assert student is not None
        assert student["first_name"] == "Somchai"
        assert student["last_name"] == "Jaidee"
        assert student["status"] == "active"


async def test_add_student_reuses_existing_user_for_same_name(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    existing = await _insert_user(db_pool, first_name="Reuse", last_name="Name")
    await _insert_student(db_pool, room_id, existing, 1)

    await StudentService.add_student(
        pool=db_pool, student_no=2, first_name="Reuse", last_name="Name",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL",
            "Reuse", "Name",
        )
        assert count == 1
        new_student = await conn.fetchrow(
            "SELECT user_id FROM students WHERE room_id = $1 AND student_no = 2 AND deleted_at IS NULL",
            room_id,
        )
        assert new_student["user_id"] == existing


async def test_bulk_add_students_creates_all(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    students = [
        {"student_no": 1, "first_name": "A", "last_name": "One"},
        {"student_no": 2, "first_name": "B", "last_name": "Two"},
        {"student_no": 3, "first_name": "C", "last_name": "Three"},
    ]

    await StudentService.bulk_add_students(
        pool=db_pool, students=students, user_name="Owner",
        client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT student_no FROM students WHERE room_id = $1 AND deleted_at IS NULL ORDER BY student_no",
            room_id,
        )
        # เลขที่ 0 คือ owner ที่สร้างห้อง, แล้วตามด้วย 1,2,3
        assert [r["student_no"] for r in rows] == [0, 1, 2, 3]


async def test_bulk_add_students_skips_existing_student_no(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="A", last_name="One",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    students = [
        {"student_no": 1, "first_name": "A", "last_name": "One"},  # ซ้ำ → ข้าม
        {"student_no": 2, "first_name": "B", "last_name": "Two"},
    ]
    await StudentService.bulk_add_students(
        pool=db_pool, students=students, user_name="Owner",
        client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT student_no FROM students WHERE room_id = $1 AND deleted_at IS NULL ORDER BY student_no",
            room_id,
        )
        # เลขที่ 0 คือ owner, ไม่มีเลขที่ 1 ซ้ำ
        assert [r["student_no"] for r in rows] == [0, 1, 2]


async def test_get_student_by_user_id_returns_profile(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Viewer", last_name="Me")
    await _insert_student(db_pool, room_id, member, 5)

    data = await StudentService.get_student_by_user_id(
        pool=db_pool, user_id=member, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    assert data["student_no"] == 5
    assert data["first_name"] == "Viewer"
    assert data["permissions"] == []
    assert data["data_completion"]["percentage"] == 0


async def test_get_all_students_returns_summaries(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Listed", last_name="Student")
    await _insert_student(db_pool, room_id, member, 5)

    rows = await StudentService.get_all_students(
        pool=db_pool, user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    student_nos = [r["student_no"] for r in rows]
    assert student_nos == [0, 5]
    assert rows[1]["first_name"] == "Listed"
    assert rows[1]["status"] == "active"
    assert "data_completion" in rows[1]


async def test_get_student_profile_self_view_no_masking(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Self", last_name="View")
    await _insert_student(db_pool, room_id, member, 3)

    data = await StudentService.get_student_profile(
        pool=db_pool, student_no=3, requester_user_id=member,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    assert data["student_no"] == 3
    assert data["first_name"] == "Self"


async def test_get_user_rooms_lists_rooms(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    rows = await StudentService.get_user_rooms(
        pool=db_pool, user_id=owner, client_source="test", actor_identifier="test",
    )

    assert len(rows) == 1
    assert rows[0]["room_id"] == room_id
    assert rows[0]["is_admin"] is True
    assert rows[0]["permissions"] == ["all"]


async def test_search_students_by_name(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee")
    await _insert_student(db_pool, room_id, member, 5)

    results = await StudentService.search_students(
        pool=db_pool, query="somchai", client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert len(results) == 1
    assert results[0]["student_no"] == 5


async def test_search_students_by_student_no(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Number", last_name="Search")
    await _insert_student(db_pool, room_id, member, 7)

    results = await StudentService.search_students(
        pool=db_pool, query="7", client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert len(results) == 1
    assert results[0]["student_no"] == 7


async def test_export_students_excel_returns_valid_xlsx(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Excel", last_name="Export")
    await _insert_student(db_pool, room_id, member, 2)

    excel_file = await StudentService.export_students_excel(
        pool=db_pool, fields=["student_no", "first_name", "last_name"], user_name="Owner",
        user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
    )

    assert isinstance(excel_file, io.BytesIO)
    wb = openpyxl.load_workbook(excel_file)
    ws = wb["Students_List"]
    rows = list(ws.values)
    assert rows[0] == ("student_no", "first_name", "last_name")
    assert len(rows) >= 2  # header + ข้อมูล


async def test_export_students_excel_member_without_export_perm_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="NoExport", last_name="Perm")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.export_students_excel(
            pool=db_pool, fields=["student_no"], user_name="NoExport", user_id=member,
            client_source="test", actor_identifier="test", room_id=room_id,
        )


# === Section 2: Updates & Mutations ===


async def test_update_student_updates_user_global_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Old", last_name="Name")
    await _insert_student(db_pool, room_id, member, 4)

    await StudentService.update_student(
        pool=db_pool, student_no=4,
        update_data={"first_name": "New", "last_name": "Name", "nickname": "NewNick"},
        updater_user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT first_name, last_name, nickname FROM users WHERE id = $1", member)
        assert row["first_name"] == "New"
        assert row["last_name"] == "Name"
        assert row["nickname"] == "NewNick"


async def test_update_student_updates_student_local_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Local", last_name="Field")
    await _insert_student(db_pool, room_id, member, 6)

    await StudentService.update_student(
        pool=db_pool, student_no=6,
        update_data={"class_role": "treasurer", "cleaning_duty": "วันจันทร์"},
        updater_user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT class_role, cleaning_duty FROM students WHERE room_id = $1 AND student_no = 6", room_id)
        assert row["class_role"] == "treasurer"
        assert row["cleaning_duty"] == "วันจันทร์"


async def test_update_student_changes_student_no(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Move", last_name="Number")
    await _insert_student(db_pool, room_id, member, 4)

    await StudentService.update_student(
        pool=db_pool, student_no=4,
        update_data={"new_student_no": 14},
        updater_user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        old_exists = await conn.fetchval("SELECT 1 FROM students WHERE room_id = $1 AND student_no = 4 AND deleted_at IS NULL", room_id)
        new_exists = await conn.fetchval("SELECT 1 FROM students WHERE room_id = $1 AND student_no = 14 AND deleted_at IS NULL", room_id)
        assert old_exists is None
        assert new_exists is not None


async def test_update_student_admin_can_update_permissions(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Perm", last_name="Test")
    await _insert_student(db_pool, room_id, member, 8)

    await StudentService.update_student(
        pool=db_pool, student_no=8,
        update_data={"permissions": ["MANAGE_STUDENTS", "EXPORT_STUDENTS"], "is_admin": True},
        updater_user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin, permissions FROM students WHERE room_id = $1 AND student_no = 8", room_id)
        assert row["is_admin"] is True
        assert sorted(_parse_permissions(row["permissions"])) == ["EXPORT_STUDENTS", "MANAGE_STUDENTS"]


async def test_update_student_member_with_manage_can_edit_other_but_not_escalate(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    manager = await _insert_user(db_pool, first_name="Manager", last_name="Guy")
    await _insert_student(db_pool, room_id, manager, 1, is_admin=False, permissions='["MANAGE_STUDENTS"]')

    target = await _insert_user(db_pool, first_name="Target", last_name="Student")
    await _insert_student(db_pool, room_id, target, 2)

    await StudentService.update_student(
        pool=db_pool, student_no=2,
        update_data={"class_role": "vice_academic", "is_admin": True},
        updater_user_id=manager, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT class_role, is_admin FROM students WHERE room_id = $1 AND student_no = 2", room_id,
        )
        assert row["class_role"] == "vice_academic"  # มี MANAGE_STUDENTS → แก้ role ได้
        assert row["is_admin"] is False  # ไม่ใช่ god → ตั้ง admin ไม่ได้


async def test_update_student_self_edit_allowed(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="SelfEdit", last_name="Allowed")
    await _insert_student(db_pool, room_id, member, 9)

    await StudentService.update_student(
        pool=db_pool, student_no=9,
        update_data={"nickname": "SelfNick"},
        updater_user_id=member, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT nickname FROM users WHERE id = $1", member)
        assert row["nickname"] == "SelfNick"


async def test_update_status_changes_status(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Status", last_name="Change")
    await _insert_student(db_pool, room_id, member, 11)

    await StudentService.update_status(
        pool=db_pool, student_no=11, status="inactive", user_name="Owner",
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 11", room_id)
        assert row["status"] == "inactive"


# === Section 3: Deletions (Soft & Hard) ===


async def test_delete_student_soft_deletes(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Soft", last_name="Delete")
    await _insert_student(db_pool, room_id, member, 12)

    await StudentService.delete_student(
        pool=db_pool, student_no=12, user_name="Owner", user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM students WHERE room_id = $1 AND student_no = 12", room_id)
        assert row["deleted_at"] is not None


async def test_delete_student_permanent_removes_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Hard", last_name="Delete")
    await _insert_student(db_pool, room_id, member, 13)

    await StudentService.delete_student_permanent(
        pool=db_pool, student_no=13, user_name="Owner", user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1 AND student_no = 13", room_id)
        assert count == 0


async def test_delete_student_permanent_blocked_when_payment_exists(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Paid", last_name="Student")
    student_id = await _insert_student(db_pool, room_id, member, 14)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'เงินห้อง', 100)",
            room_id,
        )
        account_id = await conn.fetchval("SELECT id FROM finance_accounts WHERE room_id = $1 LIMIT 1", room_id)
        await conn.execute(
            """INSERT INTO fee_collections (room_id, title, amount, due_date)
               VALUES ($1, 'ค่าเทอม', 500, '2026-12-31')""",
            room_id,
        )
        collection_id = await conn.fetchval("SELECT id FROM fee_collections WHERE room_id = $1 LIMIT 1", room_id)
        await conn.execute(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount, paid_to_account_id)
               VALUES ($1, $2, 'paid', 500, $3)""",
            collection_id, student_id, account_id,
        )

    with pytest.raises(ValidationError):
        await StudentService.delete_student_permanent(
            pool=db_pool, student_no=14, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    # ยังต้องไม่ถูกลบ
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1 AND student_no = 14", room_id)
        assert count == 1


# === Section 4: Edge Cases & Validation ===


async def test_add_student_duplicate_student_no_raises_valueerror(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="First", last_name="Person",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    with pytest.raises(ValueError):
        await StudentService.add_student(
            pool=db_pool, student_no=1, first_name="Second", last_name="Person",
            user_name="Owner", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=owner,
        )


async def test_add_student_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.add_student(
            pool=db_pool, student_no=10, first_name="No", last_name="Perm",
            user_name="Plain", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=member,
        )


async def test_add_student_unknown_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(RoomNotFoundError):
        await StudentService.add_student(
            pool=db_pool, student_no=1, first_name="Ghost", last_name="Room",
            user_name="Owner", client_source="test", actor_identifier="test",
            room_id=999999, actor_user_id=owner,
        )


async def test_bulk_add_students_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.bulk_add_students(
            pool=db_pool,
            students=[{"student_no": 10, "first_name": "No", "last_name": "Perm"}],
            user_name="Plain", client_source="test", actor_identifier="test",
            room_id=room_id, actor_user_id=member,
        )


async def test_update_student_member_editing_other_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    target = await _insert_user(db_pool, first_name="Other", last_name="Target")
    await _insert_student(db_pool, room_id, target, 6)

    with pytest.raises(ForbiddenError):
        await StudentService.update_student(
            pool=db_pool, student_no=6,
            update_data={"nickname": "Hacked"},
            updater_user_id=member, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_update_student_non_admin_cannot_escalate_is_admin(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Escalate", last_name="Attempt")
    await _insert_student(db_pool, room_id, member, 15)

    # สมาชิกธรรมดาแก้ตัวเอง พยายามตั้ง is_admin → ต้องถูกตัดสิทธิ์เงียบๆ
    await StudentService.update_student(
        pool=db_pool, student_no=15,
        update_data={"is_admin": True},
        updater_user_id=member, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM students WHERE room_id = $1 AND student_no = 15", room_id)
        assert row["is_admin"] is False


async def test_update_student_nonexistent_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(StudentNotFoundError):
        await StudentService.update_student(
            pool=db_pool, student_no=999,
            update_data={"nickname": "Ghost"},
            updater_user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_get_all_students_non_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await StudentService.get_all_students(
            pool=db_pool, user_id=outsider, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_get_student_profile_masks_private_fields_for_member(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    target = await _insert_user(
        db_pool, first_name="Private", last_name="Student",
        phone_number="0811111111",
    )
    await _insert_student(db_pool, room_id, target, 5)

    # สมาชิกธรรมดาดูโปรไฟล์เพื่อนร่วมห้อง → ข้อมูลส่วนตัวถูกปิด
    member = await _insert_user(db_pool, first_name="Curious", last_name="Member")
    await _insert_student(db_pool, room_id, member, 6)

    data = await StudentService.get_student_profile(
        pool=db_pool, student_no=5, requester_user_id=member,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    assert data["student_no"] == 5
    assert data["first_name"] == "Private"
    assert data["phone_number"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["phone_number_parent"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["address_province"] == "🔒 ไม่มีสิทธิ์เข้าถึง"


async def test_get_student_by_user_id_not_found_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    ghost = await _insert_user(db_pool, first_name="Ghost", last_name="User")

    with pytest.raises(StudentNotFoundError):
        await StudentService.get_student_by_user_id(
            pool=db_pool, user_id=ghost, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_sync_discord_account_links_user(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Sync", last_name="Discord")
    await _insert_student(db_pool, room_id, member, 5)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    await StudentService.sync_discord_account(
        pool=db_pool, room_code=room_code, student_no=5,
        discord_id=123456789, discord_username="sync_discord",
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT discord_id, discord_username FROM users WHERE id = $1", member)
        assert row["discord_id"] == 123456789
        assert row["discord_username"] == "sync_discord"


async def test_sync_discord_account_duplicate_id_raises_validation(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # user1 ผูก discord_id ไว้แล้ว
    user1 = await _insert_user(db_pool, first_name="Has", last_name="Discord", discord_id=555666777)
    await _insert_student(db_pool, room_id, user1, 1)

    # user2 ยังไม่มี discord_id แต่โดนพยายามผูก ID ซ้ำ
    user2 = await _insert_user(db_pool, first_name="No", last_name="Discord")
    await _insert_student(db_pool, room_id, user2, 2)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    with pytest.raises(ValidationError):
        await StudentService.sync_discord_account(
            pool=db_pool, room_code=room_code, student_no=2,
            discord_id=555666777, discord_username="dup",
            client_source="test", actor_identifier="test",
        )


async def test_sync_discord_account_unknown_room_raises_roomnotfound(db_pool):
    with pytest.raises(RoomNotFoundError):
        await StudentService.sync_discord_account(
            pool=db_pool, room_code="ZZZZZZ", student_no=1,
            discord_id=123456, discord_username="ghost",
            client_source="test", actor_identifier="test",
        )


async def test_delete_student_permanent_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.delete_student_permanent(
            pool=db_pool, student_no=5, user_name="Plain", user_id=member,
            client_source="test", actor_identifier="test", room_id=room_id,
        )


# === Section 5: RBAC Hardening — update_status (เดิมไม่มี require_permission) ===


async def test_update_status_non_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = await _insert_user(db_pool, first_name="Target", last_name="Status")
    await _insert_student(db_pool, room_id, target, 5)

    # คนนอกห้อง (ไม่มี student row ในห้องนี้) → ต้องโดน ForbiddenError
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    with pytest.raises(ForbiddenError):
        await StudentService.update_status(
            pool=db_pool, student_no=5, status="inactive", user_name="Outsider",
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=outsider,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["status"] == "active"


async def test_update_status_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 1)

    target = await _insert_user(db_pool, first_name="Other", last_name="Student")
    await _insert_student(db_pool, room_id, target, 5)

    # สมาชิกธรรมดา (ไม่ใช่ admin) → ต้องโดน ForbiddenError
    with pytest.raises(ForbiddenError):
        await StudentService.update_status(
            pool=db_pool, student_no=5, status="inactive", user_name="Plain",
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=member,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["status"] == "active"


async def test_update_status_admin_cannot_deactivate_owner_or_admin(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # admin คนที่สอง (เลข 1)
    admin2 = await _insert_user(db_pool, first_name="Co", last_name="Admin")
    await _insert_student(db_pool, room_id, admin2, 1, is_admin=True)

    # owner (เลข 0) พยายามปลด admin2 → ต้องโดนป้องกัน
    with pytest.raises(ForbiddenError):
        await StudentService.update_status(
            pool=db_pool, student_no=1, status="inactive", user_name="Owner",
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=owner,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 1", room_id)
        assert row["status"] == "active"


async def test_update_status_cannot_deactivate_self(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(ForbiddenError):
        await StudentService.update_status(
            pool=db_pool, student_no=0, status="inactive", user_name="Owner",
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=owner,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 0", room_id)
        assert row["status"] == "active"


async def test_update_status_admin_can_deactivate_regular_member(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Regular", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    await StudentService.update_status(
        pool=db_pool, student_no=5, status="inactive", user_name="Owner",
        client_source="test", actor_identifier="test", room_id=room_id,
        user_id=owner,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["status"] == "inactive"


async def test_update_status_manager_with_manage_perm_can_deactivate_regular(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    manager = await _insert_user(db_pool, first_name="Manager", last_name="Guy")
    await _insert_student(db_pool, room_id, manager, 1, is_admin=False, permissions='["MANAGE_STUDENTS"]')

    target = await _insert_user(db_pool, first_name="Regular", last_name="Member")
    await _insert_student(db_pool, room_id, target, 5)

    await StudentService.update_status(
        pool=db_pool, student_no=5, status="inactive", user_name="Manager",
        client_source="test", actor_identifier="test", room_id=room_id,
        user_id=manager,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["status"] == "inactive"


async def test_update_status_manager_with_manage_perm_cannot_deactivate_admin(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    manager = await _insert_user(db_pool, first_name="Manager", last_name="Guy")
    await _insert_student(db_pool, room_id, manager, 1, is_admin=False, permissions='["MANAGE_STUDENTS"]')

    admin2 = await _insert_user(db_pool, first_name="Co", last_name="Admin")
    await _insert_student(db_pool, room_id, admin2, 2, is_admin=True)

    with pytest.raises(ForbiddenError):
        await StudentService.update_status(
            pool=db_pool, student_no=2, status="inactive", user_name="Manager",
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=manager,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM students WHERE room_id = $1 AND student_no = 2", room_id)
        assert row["status"] == "active"


# === Section 6: RBAC Hardening — delete_student / delete_student_permanent ===


async def test_delete_student_cannot_delete_self(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # owner พยายามลบตัวเอง (เลข 0) → ต้องโดนป้องกัน
    with pytest.raises(ForbiddenError):
        await StudentService.delete_student(
            pool=db_pool, student_no=0, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM students WHERE room_id = $1 AND student_no = 0", room_id)
        assert row["deleted_at"] is None


async def test_delete_student_admin_cannot_delete_another_admin(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    admin2 = await _insert_user(db_pool, first_name="Co", last_name="Admin")
    await _insert_student(db_pool, room_id, admin2, 1, is_admin=True)

    with pytest.raises(ForbiddenError):
        await StudentService.delete_student(
            pool=db_pool, student_no=1, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM students WHERE room_id = $1 AND student_no = 1", room_id)
        assert row["deleted_at"] is None


async def test_delete_student_permanent_cannot_delete_self(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(ForbiddenError):
        await StudentService.delete_student_permanent(
            pool=db_pool, student_no=0, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1 AND student_no = 0", room_id)
        assert count == 1


async def test_delete_student_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 1)

    target = await _insert_user(db_pool, first_name="Other", last_name="Student")
    await _insert_student(db_pool, room_id, target, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.delete_student(
            pool=db_pool, student_no=5, user_name="Plain", user_id=member,
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM students WHERE room_id = $1 AND student_no = 5", room_id)
        assert row["deleted_at"] is None


# === Section 7: Boundary — delete / update / status on nonexistent ===


async def test_delete_student_nonexistent_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(StudentNotFoundError):
        await StudentService.delete_student(
            pool=db_pool, student_no=999, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )


async def test_delete_student_permanent_nonexistent_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(StudentNotFoundError):
        await StudentService.delete_student_permanent(
            pool=db_pool, student_no=999, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )


async def test_delete_student_permanent_double_delete_second_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Double", last_name="Delete")
    await _insert_student(db_pool, room_id, member, 6)

    await StudentService.delete_student_permanent(
        pool=db_pool, student_no=6, user_name="Owner", user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    # ครั้งที่ 2 → ต้องโดน StudentNotFoundError (ไม่ใช่ "สำเร็จ" ซ้ำ)
    with pytest.raises(StudentNotFoundError):
        await StudentService.delete_student_permanent(
            pool=db_pool, student_no=6, user_name="Owner", user_id=owner,
            client_source="test", actor_identifier="test", room_id=room_id,
        )


async def test_update_status_nonexistent_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(StudentNotFoundError):
        await StudentService.update_status(
            pool=db_pool, student_no=999, status="inactive", user_name="Owner",
            client_source="test", actor_identifier="test", room_id=room_id,
        )


async def test_search_students_unknown_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(RoomNotFoundError):
        await StudentService.search_students(
            pool=db_pool, query="nobody", client_source="test", actor_identifier="test",
            room_id=999999, user_id=owner,
        )


async def test_sync_discord_account_unknown_student_raises_studentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    with pytest.raises(StudentNotFoundError):
        await StudentService.sync_discord_account(
            pool=db_pool, room_code=room_code, student_no=999,
            discord_id=999999, discord_username="ghost",
            client_source="test", actor_identifier="test",
        )


async def test_sync_discord_account_actor_mismatch_raises_forbidden(db_pool):
    """
    🛡️ IDOR guard: ผู้ยิง (actor_user_id) ไม่ใช่เจ้าของ student ที่ระบุ room_code+student_no
    → ต้องโดน ForbiddenError ห้ามผูก Discord ID ทับบัญชีเพื่อน
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    victim = await _insert_user(db_pool, first_name="Victim", last_name="User")
    await _insert_student(db_pool, room_id, victim, 3)
    attacker = await _insert_user(db_pool, first_name="Attacker", last_name="User")

    async with db_pool.acquire() as conn:
        room_code = await conn.fetchval("SELECT room_code FROM rooms WHERE id = $1", room_id)

    with pytest.raises(ForbiddenError):
        await StudentService.sync_discord_account(
            pool=db_pool, room_code=room_code, student_no=3,
            discord_id=999888777, discord_username="attacker",
            client_source="test", actor_identifier="test",
            actor_user_id=attacker,
        )
    # Deep verify: discord_id ของเหยื่อต้องไม่โดนแก้
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT discord_id FROM users WHERE id = $1", victim)
        assert row["discord_id"] is None


# === Section 8: Ghost / soft-delete interplay ===


async def test_add_student_after_soft_delete_reuses_same_user(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # เพิ่ม → soft-delete → เพิ่มชื่อเดิมอีกครั้ง
    await StudentService.add_student(
        pool=db_pool, student_no=10, first_name="ReAdd", last_name="Same",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )
    await StudentService.delete_student(
        pool=db_pool, student_no=10, user_name="Owner", user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    await StudentService.add_student(
        pool=db_pool, student_no=11, first_name="ReAdd", last_name="Same",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        # ต้อง reuse user เดิม ไม่สร้าง ghost ซ้ำ
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE first_name = $1 AND last_name = $2 AND deleted_at IS NULL",
            "ReAdd", "Same",
        )
        assert count == 1
        student = await conn.fetchrow(
            "SELECT user_id FROM students WHERE room_id = $1 AND student_no = 11 AND deleted_at IS NULL",
            room_id,
        )
        assert student["user_id"] == (await conn.fetchval(
            "SELECT user_id FROM students WHERE room_id = $1 AND student_no = 10", room_id,
        ))


async def test_get_all_students_excludes_soft_deleted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Alive", last_name="Student")
    await _insert_student(db_pool, room_id, member, 5)

    ghost = await _insert_user(db_pool, first_name="Gone", last_name="Student")
    ghost_student_id = await _insert_student(db_pool, room_id, ghost, 6)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE students SET deleted_at = NOW() WHERE id = $1", ghost_student_id)

    rows = await StudentService.get_all_students(
        pool=db_pool, user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    student_nos = [r["student_no"] for r in rows]
    assert 6 not in student_nos


async def test_search_students_excludes_pending(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    pending_user = await _insert_user(db_pool, first_name="Pending", last_name="Guy")
    await _insert_student(db_pool, room_id, pending_user, 5, status="pending")

    results = await StudentService.search_students(
        pool=db_pool, query="Pending", client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    # search ควรกรองเฉพาะ active เท่านั้น (pending ไม่ควรโผล่)
    assert all(r["status"] == "active" for r in results)


async def test_search_students_non_member_should_be_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Search", last_name="Me")
    await _insert_student(db_pool, room_id, member, 5)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await StudentService.search_students(
            pool=db_pool, query="Search", client_source="test", actor_identifier="test",
            room_id=room_id, user_id=outsider,
        )


async def test_get_student_profile_cannot_read_other_room(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a)
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b)

    target = await _insert_user(db_pool, first_name="Target", last_name="RoomA")
    await _insert_student(db_pool, room_a, target, 5)

    with pytest.raises(ForbiddenError):
        await StudentService.get_student_profile(
            pool=db_pool, student_no=5, requester_user_id=owner_b,
            client_source="test", actor_identifier="test", room_id=room_a,
        )


async def test_get_student_profile_masks_extra_private_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    target = await _insert_user(
        db_pool, first_name="Rich", last_name="Profile",
        email="rich@example.com", phone_number_parent="021234567",
        line_id="rich.line", blood_group="O",
    )
    await _insert_student(db_pool, room_id, target, 5)

    member = await _insert_user(db_pool, first_name="Curious", last_name="Member")
    await _insert_student(db_pool, room_id, member, 6)

    data = await StudentService.get_student_profile(
        pool=db_pool, student_no=5, requester_user_id=member,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    assert data["phone_number_parent"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["line_id"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["blood_group"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["email"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["address_province"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["first_name"] == "Rich"  # ชื่อยังต้องเห็น


async def test_get_student_profile_admin_sees_unmasked_private_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    target = await _insert_user(
        db_pool, first_name="Visible", last_name="ToAdmin",
        phone_number="0899999999", line_id="admin.view", blood_group="A",
    )
    await _insert_student(db_pool, room_id, target, 5)

    data = await StudentService.get_student_profile(
        pool=db_pool, student_no=5, requester_user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    assert data["phone_number"] == "0899999999"  # admin เห็นข้อมูลจริง ไม่ถูก mask
    assert data["line_id"] == "admin.view"
    assert data["blood_group"] == "A"


async def test_search_students_excludes_soft_deleted_user(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    ghost = await _insert_user(db_pool, first_name="SoftDeleted", last_name="User")
    ghost_student_id = await _insert_student(db_pool, room_id, ghost, 5)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE students SET deleted_at = NOW() WHERE id = $1", ghost_student_id)
        await conn.execute("UPDATE users SET deleted_at = NOW() WHERE id = $1", ghost)

    results = await StudentService.search_students(
        pool=db_pool, query="SoftDeleted", client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    # สมาชิกที่ user ถูกลบ soft แล้ว → ต้องไม่โผล่ในการค้นหา (u.deleted_at IS NULL)
    assert len(results) == 0


# === Section 9: Multi-room / same user ===


async def test_get_student_by_user_id_returns_matching_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room1 = await _insert_room(db_pool, owner, "Room One")
    room2 = await _insert_room(db_pool, owner, "Room Two")

    member = await _insert_user(db_pool, first_name="Multi", last_name="Room")
    await _insert_student(db_pool, room1, member, 1, is_admin=False)
    await _insert_student(db_pool, room2, member, 7, is_admin=False)

    # ถามห้อง 2 → ต้องได้เลข 7 (ไม่ใช่แถวแรกที่เจอ)
    data = await StudentService.get_student_by_user_id(
        pool=db_pool, user_id=member, client_source="test", actor_identifier="test",
        room_id=room2,
    )
    assert data["student_no"] == 7
    assert data["room_id"] == room2


async def test_get_user_rooms_excludes_deleted_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room1 = await _insert_room(db_pool, owner, "Keep Room")
    room2 = await _insert_room(db_pool, owner, "Drop Room")

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET deleted_at = NOW() WHERE id = $1", room2)

    rows = await StudentService.get_user_rooms(
        pool=db_pool, user_id=owner, client_source="test", actor_identifier="test",
    )
    room_ids = [r["room_id"] for r in rows]
    assert room1 in room_ids
    assert room2 not in room_ids


# === Section 10: Idempotency / concurrency ===


async def test_add_student_duplicate_student_no_after_soft_delete_allowed(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # เพิ่มเลข 10 → soft delete
    await StudentService.add_student(
        pool=db_pool, student_no=10, first_name="Old", last_name="Guy",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )
    await StudentService.delete_student(
        pool=db_pool, student_no=10, user_name="Owner", user_id=owner,
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    # เอาเลข 10 มาใช้ใหม่กับคนใหม่ → ต้องสำเร็จ (partial index ไม่ชน soft-deleted)
    await StudentService.add_student(
        pool=db_pool, student_no=10, first_name="New", last_name="Guy",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT first_name FROM users u JOIN students s ON s.user_id = u.id WHERE s.room_id = $1 AND s.student_no = 10 AND s.deleted_at IS NULL",
            room_id,
        )
        assert row["first_name"] == "New"


async def test_update_student_new_student_no_conflict_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member1 = await _insert_user(db_pool, first_name="Occupied", last_name="One")
    await _insert_student(db_pool, room_id, member1, 5)
    member2 = await _insert_user(db_pool, first_name="Mover", last_name="Two")
    await _insert_student(db_pool, room_id, member2, 6)

    with pytest.raises(ValidationError):
        await StudentService.update_student(
            pool=db_pool, student_no=6,
            update_data={"new_student_no": 5},
            updater_user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_add_student_permissions_string_database(db_pool):
    """permissions เก็บเป็น JSONB → ต้อง parse เป็น list ได้เสมอ (กัน regression asyncpg str/list)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Perm", last_name="Store")
    await _insert_student(db_pool, room_id, member, 5, permissions='["MANAGE_STUDENTS"]')

    data = await StudentService.get_student_by_user_id(
        pool=db_pool, user_id=member, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert data["permissions"] == ["MANAGE_STUDENTS"]
