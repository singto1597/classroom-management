"""
Integration tests — Deep edge-case coverage for ClassroomService.

โฟกัส 4 ด้านที่เทสเดิม (`test_classroom_sync.py`) ยังไม่ครอบคลุม:
  A. Soft-delete guards ใน mutation queries  — งาน/note ที่ถูกลบไปแล้วต้องแตะไม่ได้
  B. RBAC `require_member`                  — คนนอกห้อง (non-member) ต้องโดน ForbiddenError
     (สมาชิก active ยัง add / mark งานได้ — UX ของบอทไม่พัง)
  C. Summary / get_rooms_to_notify semantics
  D. Edge & validation

Note: service-level — เรียก service ตรงๆ ไม่ผ่าน HTTP
- ส่ง `user_id=...` เสมอเมื่อต้องการให้ enforce RBAC (web path)
- `add_task` / `mark_task_done` ติดต่อ Redis → ต้อง mock ActionService
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from core.exceptions import ForbiddenError, RoomNotFoundError, TaskNotFoundError
from services.classroom_sync_service import ClassroomService, THAI_TZ

pytestmark = pytest.mark.asyncio


# === Fixtures & Setup ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", username=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            email, first_name, last_name, username,
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            room_name, code, owner_id, server_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(
    pool, room_id: int, user_id: int, student_no: int,
    *, status="active", is_admin=False, permissions="[]",
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
            room_id, user_id, student_no, final_status, is_admin, permissions,
        )


async def _insert_task(
    pool, room_id: int, task_name="การบ้านคณิต", due_date=None, status="pending", deleted=False
) -> int:
    if due_date is None:
        due_date = date(2099, 12, 31)
    async with pool.acquire() as conn:
        task_id = await conn.fetchval(
            """
            INSERT INTO tasks (room_id, task_name, task_detail, due_date, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_id, task_name, "รายละเอียดงาน", due_date, status,
        )
        if deleted:
            await conn.execute("UPDATE tasks SET deleted_at = NOW() WHERE id = $1", task_id)
        return task_id


async def _soft_delete_room(pool, room_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET deleted_at = NOW() WHERE id = $1", room_id)


def _monday_from(today: date) -> date:
    """วันจันทร์ถัดไปจาก today (ไม่ hardcode date)"""
    return today + timedelta(days=(0 - today.weekday()) % 7)


# === Section A: Soft-delete guards ใน mutation queries ===


async def test_mark_task_done_on_deleted_task_raises_and_no_notify(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="โดนลบไปแล้ว", deleted=True)

    with patch("services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock) as mock_notify:
        with pytest.raises(TaskNotFoundError):
            await ClassroomService.mark_task_done(
                pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
                client_source="test", actor_identifier="test", user_id=owner,
            )
        mock_notify.assert_not_called()

    # งาน soft-delete แล้ว ต้องไม่มีถูก set เป็น done
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "pending"
        assert row["deleted_at"] is not None


async def test_edit_task_on_deleted_task_raises_and_does_not_change(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="เดิม", due_date=date(2026, 9, 1), deleted=True)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.edit_task(
            pool=db_pool, task_id=task_id, task_name="แก้แล้ว", task_detail="x", due_date=date(2026, 9, 2),
            user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=owner,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT task_name, due_date FROM tasks WHERE id = $1", task_id)
        assert row["task_name"] == "เดิม"
        assert row["due_date"] == date(2026, 9, 1)


async def test_mark_task_done_twice_is_idempotent(db_pool):
    """mark done กับงาน pending → done แล้ว mark อีกครั้ง → ไม่ error (second UPDATE 0 แต่ task_name ยังคืน)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานช้ำ")

    with patch("services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock) as mock_notify:
        name1 = await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=owner,
        )
        # ครั้งที่สอง: UPDATE 0 → task_name เป็น None → TaskNotFoundError? จริงๆ ไม่ควรทำซ้ำ แต่ guard ไว้
        name2 = await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=owner,
        )

    assert name1 == "งานช้ำ"
    assert name2 == "งานช้ำ"  # ถ้า fail แปลว่า mark ซ้ำพัง → เป็น behavior เดิม (document ไว้)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "done"


async def test_add_daily_note_after_soft_delete_does_not_accumulate_rows(db_pool):
    """add → delete (soft) → add ซ้ำ → ต้องเหลือ active row เดียว ไม่สะสม"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 8)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ชุดแรก", announcement="ann1",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.delete_daily_note(
        pool=db_pool, target_date=target, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ชุดใหม่", announcement="ann2",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert total == 1  # row เก่าที่ soft-delete ถูก DELETE ทิ้งก่อน INSERT ใหม่
        active = await conn.fetchval(
            "SELECT COUNT(*) FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL",
            room_id, target,
        )
        assert active == 1


async def test_set_default_schedule_after_soft_delete_no_accumulation(db_pool):
    """set → soft-delete ตรงๆ → set ซ้ำ → ไม่สะสม + action log ถูกต้อง"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดแรก", subjects="ไทย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    # soft-delete ด้วยมือ (สถานะที่เกิดได้จริง)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE default_schedules SET deleted_at = NOW() WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )
    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดใหม่", subjects="คณิต",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM default_schedules WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )
        assert total == 1
        row = await conn.fetchrow(
            "SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = $2 AND deleted_at IS NULL",
            room_id, "จันทร์",
        )
        assert row["attire"] == "ชุดใหม่"


async def test_get_room_data_nonexistent_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(RoomNotFoundError):
        await ClassroomService.get_room_data(
            pool=db_pool, room_id=999999,
            client_source="test", actor_identifier="test", user_id=owner,
        )


async def test_get_room_data_soft_deleted_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _soft_delete_room(db_pool, room_id)

    with pytest.raises(RoomNotFoundError):
        await ClassroomService.get_room_data(
            pool=db_pool, room_id=room_id,
            client_source="test", actor_identifier="test", user_id=owner,
        )


async def test_set_channel_on_deleted_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _soft_delete_room(db_pool, room_id)

    with pytest.raises(RoomNotFoundError):
        await ClassroomService.set_channel(
            pool=db_pool, channel_id=123, user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_set_notify_time_on_deleted_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _soft_delete_room(db_pool, room_id)

    with pytest.raises(RoomNotFoundError):
        await ClassroomService.set_notify_time(
            pool=db_pool, notify_time="08:00", user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_add_task_on_deleted_room_raises_and_no_notify(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    await _soft_delete_room(db_pool, room_id)

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        with pytest.raises(RoomNotFoundError):
            await ClassroomService.add_task(
                pool=db_pool, task_name="งานห้องตาย", task_detail=None, due_date=date(2026, 9, 1),
                user_name="Owner", room_id=room_id,
                client_source="test", actor_identifier="test", user_id=owner,
            )
        mock_notify.assert_not_called()

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE room_id = $1", room_id)
        assert count == 0


# === Section B: RBAC — require_member กันคนนอกห้อง ===


async def test_add_task_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        with pytest.raises(ForbiddenError):
            await ClassroomService.add_task(
                pool=db_pool, task_name="ขโมยแทรก", task_detail=None, due_date=date(2026, 9, 1),
                user_name="Outsider", room_id=room_id,
                client_source="test", actor_identifier="test", user_id=outsider,
            )
        mock_notify.assert_not_called()

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE room_id = $1", room_id)
        assert count == 0


async def test_edit_task_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    task_id = await _insert_task(db_pool, room_id, task_name="ของแท้")

    with pytest.raises(ForbiddenError):
        await ClassroomService.edit_task(
            pool=db_pool, task_id=task_id, task_name="โดนแฮก", task_detail="x", due_date=date(2026, 9, 1),
            user_name="Outsider", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT task_name FROM tasks WHERE id = $1", task_id)
        assert row["task_name"] == "ของแท้"


async def test_mark_task_done_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    task_id = await _insert_task(db_pool, room_id, task_name="งานยังไม่ส่ง")

    with pytest.raises(ForbiddenError):
        await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Outsider", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "pending"


async def test_restore_task_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    task_id = await _insert_task(db_pool, room_id, task_name="โดนลบ", deleted=True)

    with pytest.raises(ForbiddenError):
        await ClassroomService.restore_task(
            pool=db_pool, task_id=task_id, user_name="Outsider", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is not None


async def test_get_tasks_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    await _insert_task(db_pool, room_id, task_name="ความลับ")

    with pytest.raises(ForbiddenError):
        await ClassroomService.get_tasks(
            pool=db_pool, client_source="test", actor_identifier="test",
            status="pending", room_id=room_id, user_id=outsider,
        )


async def test_get_task_by_id_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    task_id = await _insert_task(db_pool, room_id)

    with pytest.raises(ForbiddenError):
        await ClassroomService.get_task_by_id(
            pool=db_pool, task_id=task_id, room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )


async def test_get_deleted_tasks_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")
    await _insert_task(db_pool, room_id, task_name="ขยะ", deleted=True)

    with pytest.raises(ForbiddenError):
        await ClassroomService.get_deleted_tasks(
            pool=db_pool, room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )


async def test_get_room_data_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await ClassroomService.get_room_data(
            pool=db_pool, room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )


async def test_get_audit_logs_outside_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await ClassroomService.get_audit_logs(
            pool=db_pool, room_id=room_id,
            client_source="test", actor_identifier="test", user_id=outsider,
        )


async def test_setup_room_cannot_rename_other_server_room(db_pool):
    """คนนอก (ไม่เป็นสมาชิก) เปลี่ยนชื่อห้องที่ผูก server อยู่ → ต้องโดน ForbiddenError"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, room_name="ของคนอื่น", server_id=server_id)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="NoRoom")

    with pytest.raises(ForbiddenError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="เปลี่ยนชื่อ", user_name="Outsider",
            client_source="test", actor_identifier="test",
            server_id=server_id, user_id=outsider,
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        assert row["room_name"] == "ของคนอื่น"


# === Section B2: Regression — สมาชิก active ยังใช้ได้ (UX บอทไม่พัง) ===


async def test_active_member_can_add_task(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        await ClassroomService.add_task(
            pool=db_pool, task_name="สมาชิกเพิ่มเอง", task_detail=None, due_date=date(2026, 9, 1),
            user_name="Plain", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=member,
        )
        mock_notify.assert_called_once()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT task_name FROM tasks WHERE room_id = $1 AND task_name = $2", room_id, "สมาชิกเพิ่มเอง")
        assert row is not None


async def test_active_member_can_mark_task_done(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)
    task_id = await _insert_task(db_pool, room_id, task_name="งานส่งโดยสมาชิก")

    with patch("services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock) as mock_notify:
        await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Plain", room_id=room_id,
            client_source="test", actor_identifier="test", user_id=member,
        )
        mock_notify.assert_called_once()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "done"


async def test_active_member_can_read_tasks(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)
    await _insert_task(db_pool, room_id, task_name="งานที่สมาชิกเห็นได้")

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="pending", room_id=room_id, user_id=member,
    )
    assert len(rows) == 1


async def test_delete_task_still_requires_manage_permission_for_member(db_pool):
    """Regression: delete_task ยังต้อง MANAGE_CLASSROOM_TASKS — สมาชิกธรรมดาไม่ได้"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)
    task_id = await _insert_task(db_pool, room_id, task_name="ห้ามลบ")

    with pytest.raises(ForbiddenError):
        await ClassroomService.delete_task(
            pool=db_pool, task_id=task_id, user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is None


async def test_outsider_with_member_perm_cannot_act_on_other_room(db_pool):
    """คนที่เป็น member ของห้อง B เอา permission มาทำในห้อง A ไม่ได้"""
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a)
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b)
    # member ของ B (มีสิทธิ์) มาลอง add งานใน A
    intruder = await _insert_user(db_pool, first_name="Intruder", last_name="B")
    await _insert_student(db_pool, room_b, intruder, 1, is_admin=True)

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        with pytest.raises(ForbiddenError):
            await ClassroomService.add_task(
                pool=db_pool, task_name="ข้ามห้อง", task_detail=None, due_date=date(2026, 9, 1),
                user_name="Intruder", room_id=room_a,
                client_source="test", actor_identifier="test", user_id=intruder,
            )
        mock_notify.assert_not_called()

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE room_id = $1", room_a)
        assert count == 0


# === Section C: Summary / get_rooms_to_notify semantics ===


async def test_summary_overdue_task_shows_negative_days(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = _monday_from(date(2026, 1, 1))  # ใช้วันที่แน่นอนอดีต กัน flaky กับ "now"
    overdue = target - timedelta(days=5)
    await _insert_task(db_pool, room_id, task_name="งานเลยกำหนด", due_date=overdue)

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=target, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert len(data["tasks_due"]) == 1
    t = data["tasks_due"][0]
    assert t["task_name"] == "งานเลยกำหนด"
    assert t["days_left"] < 0  # ติดลบ = เลยกำหนด
    assert "เลยกำหนด" in t["display_text"]


async def test_summary_due_today_and_due_tomorrow_text(db_pool):
    """days_left 0 → 'ส่งวันนี้'; 1 → 'ส่งพรุ่งนี้' (เทียบกับ 'วันนี้' จริง เพราะ summary ใช้ real today)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    today = datetime.now(THAI_TZ).date()
    await _insert_task(db_pool, room_id, task_name="ส่งวันนี้", due_date=today)
    await _insert_task(db_pool, room_id, task_name="ส่งพรุ่งนี้", due_date=today + timedelta(days=1))
    await _insert_task(db_pool, room_id, task_name="ส่งปีหน้า", due_date=today + timedelta(days=365))

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=today, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    by_name = {t["task_name"]: t for t in data["tasks_due"]}
    assert by_name["ส่งวันนี้"]["days_left"] == 0
    assert "ส่งวันนี้" in by_name["ส่งวันนี้"]["display_text"]
    assert by_name["ส่งพรุ่งนี้"]["days_left"] == 1
    assert "ส่งพรุ่งนี้" in by_name["ส่งพรุ่งนี้"]["display_text"]
    assert by_name["ส่งปีหน้า"]["days_left"] == 365
    assert "🟢" in by_name["ส่งปีหน้า"]["display_text"]


async def test_summary_excludes_done_and_deleted_tasks(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 1, 5)
    await _insert_task(db_pool, room_id, task_name="ยังค้าง", due_date=date(2099, 12, 31))
    await _insert_task(db_pool, room_id, task_name="ส่งแล้ว", due_date=date(2099, 12, 31), status="done")
    await _insert_task(db_pool, room_id, task_name="โดนลบ", due_date=date(2099, 12, 31), deleted=True)

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=target, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    names = [t["task_name"] for t in data["tasks_due"]]
    assert names == ["ยังค้าง"]


async def test_summary_does_not_include_soft_deleted_default_schedule(db_pool):
    """Regression ของ fix เดิม: default schedule ที่ soft-delete แล้วไม่โผล่ใน summary"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    monday = _monday_from(date(2026, 1, 1))

    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดเดิม", subjects="ไทย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE default_schedules SET deleted_at = NOW() WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=monday, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    assert data["attire"] == "-"
    assert data["subjects"] == "-"


async def test_get_rooms_to_notify_excludes_deleted_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_a = random.randint(1_000_000, 9_999_999)
    server_b = random.randint(1_000_000, 9_999_999)
    room_live = await _insert_room(db_pool, owner, "Live", server_id=server_a)
    room_dead = await _insert_room(db_pool, owner, "Dead", server_id=server_b)

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET notify_time = '07:00', announcement_channel_id = 111 WHERE id = $1", room_live)
        await conn.execute("UPDATE rooms SET notify_time = '07:00', announcement_channel_id = 222 WHERE id = $1", room_dead)
    await _soft_delete_room(db_pool, room_dead)

    rows = await ClassroomService.get_rooms_to_notify(
        pool=db_pool, current_time="07:00",
        client_source="test", actor_identifier="test",
    )
    server_ids = [r["server_id"] for r in rows]
    assert server_a in server_ids
    assert server_b not in server_ids  # ห้องที่ถูกลบแล้วต้องไม่ถูกแจ้ง


# === Section D: Edge & validation ===


async def test_get_audit_logs_negative_limit_does_not_error(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=111, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    rows = await ClassroomService.get_audit_logs(
        pool=db_pool, room_id=room_id, limit=-1,
        client_source="test", actor_identifier="test", user_id=owner,
    )
    assert rows == []


async def test_get_audit_logs_zero_limit_returns_empty(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await ClassroomService.set_notify_time(
        pool=db_pool, notify_time="08:00", user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    rows = await ClassroomService.get_audit_logs(
        pool=db_pool, room_id=room_id, limit=0,
        client_source="test", actor_identifier="test", user_id=owner,
    )
    assert rows == []


async def test_get_tasks_empty_room_returns_empty(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="pending", room_id=room_id, user_id=owner,
    )
    assert rows == []


async def test_get_tasks_invalid_status_returns_empty(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _insert_task(db_pool, room_id, task_name="งานจริง", status="pending")

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="bogus", room_id=room_id, user_id=owner,
    )
    assert rows == []  # ไม่ error — คืนว่าง


async def test_summary_past_date_returns_override(db_pool):
    """override บนวันในอดีตยังโผล่ใน summary (ใช้สำหรับดูย้อนหลัง)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    past = date(2026, 1, 2)  # ศุกร์

    await ClassroomService.set_override(
        pool=db_pool, target_date=past, new_attire="ชุดพละ", note="วันกีฬา",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=past, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    assert data["attire"] == "🚨 ชุดพละ (กรณีพิเศษ)"
    assert data["day"] == "ศุกร์"


async def test_add_daily_note_logs_create_then_update(db_pool):
    """audit action: add ครั้งแรก → CREATE, add ซ้ำ (มี active row) → UPDATE"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 10)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ของ1", announcement="a1",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ของ2", announcement="a2",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        actions = await conn.fetch(
            "SELECT action FROM audit_logs WHERE room_id = $1 AND entity_type = 'DAILY_NOTE' ORDER BY created_at ASC",
            room_id,
        )
        assert [r["action"] for r in actions] == ["CREATE", "UPDATE"]
