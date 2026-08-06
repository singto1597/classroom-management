"""
Integration tests for ClassroomService (services/classroom_sync_service.py)
ครอบคลุม: Room settings, Schedule, Tasks, Daily Notes, Summary

Note: service-level tests — เรียก service โดยตรง (ไม่ผ่าน HTTP)
- require_permission เป็น RBAC จริง (owner = is_admin ผ่านฉลุย)
- add_task / mark_task_done ติดต่อ Redis → ต้อง mock ActionService
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from core.exceptions import ForbiddenError, TaskNotFoundError
from services.classroom_sync_service import ClassroomService, THAI_TZ

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
            room_name,
            code,
            owner_id,
            server_id,
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


async def _insert_task(
    pool, room_id: int, task_name="การบ้านคณิต", due_date=None, status="pending", deleted=False
) -> int:
    if due_date is None:
        due_date = date(2026, 12, 31)
    async with pool.acquire() as conn:
        task_id = await conn.fetchval(
            """
            INSERT INTO tasks (room_id, task_name, task_detail, due_date, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_id,
            task_name,
            "รายละเอียดงาน",
            due_date,
            status,
        )
        if deleted:
            await conn.execute("UPDATE tasks SET deleted_at = NOW() WHERE id = $1", task_id)
        return task_id


# === Section 1: Happy Paths (CREATE/READ) ===


async def test_get_room_data_returns_room_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้อง 1/1")

    data = await ClassroomService.get_room_data(
        pool=db_pool, target_id=room_id, target_type="room",
        client_source="test", actor_identifier="test",
    )

    assert data["id"] == room_id
    assert data["room_name"] == "ห้อง 1/1"
    assert data["notify_time"] == "19:00"
    assert "server_id" in data
    assert "announcement_channel_id" in data


async def test_setup_room_links_web_room_to_server(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="Web Room")

    server_id = random.randint(1_000_000, 9_999_999)
    await ClassroomService.setup_room(
        pool=db_pool, room_name="Web Room", user_name="Owner",
        client_source="test", actor_identifier="test",
        server_id=server_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT server_id FROM rooms WHERE id = $1", room_id)
        assert row["server_id"] == server_id


async def test_set_channel_sets_announcement_channel(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    channel_id = random.randint(100_000, 999_999)
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=channel_id, user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] == channel_id


async def test_set_notify_time_sets_time(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_notify_time(
        pool=db_pool, notify_time="08:30", user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT notify_time FROM rooms WHERE id = $1", room_id)
        assert row["notify_time"] == "08:30"


async def test_get_rooms_to_notify_returns_matching_rooms(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_a = random.randint(1_000_000, 9_999_999)
    server_b = random.randint(1_000_000, 9_999_999)
    room1 = await _insert_room(db_pool, owner, "Room A", server_id=server_a)
    room2 = await _insert_room(db_pool, owner, "Room B", server_id=server_b)

    channel_id = random.randint(100_000, 999_999)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET notify_time = '07:00', announcement_channel_id = $2 WHERE id = $1", room1, channel_id)

    rows = await ClassroomService.get_rooms_to_notify(
        pool=db_pool, current_time="07:00",
        client_source="test", actor_identifier="test",
    )

    server_ids = [r["server_id"] for r in rows]
    assert server_a in server_ids
    assert server_b not in server_ids  # notify_time ยังเป็น default 19:00


async def test_set_default_schedule_creates_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดนักเรียน", subjects="คณิต, ไทย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM default_schedules WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )
        assert row is not None
        assert row["attire"] == "ชุดนักเรียน"
        assert row["subjects"] == "คณิต, ไทย"


async def test_set_override_creates_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_override(
        pool=db_pool, target_date=date(2026, 8, 10), new_attire="ชุดกีฬา", note="กิจกรรมเข้าค่าย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM schedule_overrides WHERE room_id = $1 AND target_date = $2",
            room_id, date(2026, 8, 10),
        )
        assert row is not None
        assert row["new_attire"] == "ชุดกีฬา"
        assert row["note"] == "กิจกรรมเข้าค่าย"


async def test_add_task_creates_task_and_notifies(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        await ClassroomService.add_task(
            pool=db_pool, task_name="การบ้านคณิต", task_detail="แบบฝึกหัดหน้า 5", due_date=date(2026, 8, 15),
            user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )

        mock_notify.assert_called_once_with(server_id, "การบ้านคณิต", "แบบฝึกหัดหน้า 5", date(2026, 8, 15), "Owner")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE room_id = $1 AND task_name = $2", room_id, "การบ้านคณิต")
        assert row is not None
        assert row["status"] == "pending"
        assert row["deleted_at"] is None


async def test_add_task_without_server_id_skips_notify(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)  # ไม่มี server_id

    with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
        await ClassroomService.add_task(
            pool=db_pool, task_name="งานไม่ผูก Discord", task_detail=None, due_date=date(2026, 8, 15),
            user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )

        mock_notify.assert_not_called()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE room_id = $1 AND task_name = $2", room_id, "งานไม่ผูก Discord")
        assert row is not None


async def test_get_tasks_returns_pending_tasks_ordered(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    later = await _insert_task(db_pool, room_id, task_name="งานช้า", due_date=date(2026, 12, 31))
    sooner = await _insert_task(db_pool, room_id, task_name="งานเร็ว", due_date=date(2026, 8, 1))

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="pending", room_id=room_id,
    )

    assert [r["id"] for r in rows] == [sooner, later]  # ORDER BY due_date ASC
    assert rows[0]["task_name"] == "งานเร็ว"
    assert rows[0]["status"] == "pending"


async def test_get_tasks_returns_done_tasks_by_status(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await _insert_task(db_pool, room_id, task_name="ยังไม่ส่ง", status="pending")
    done_id = await _insert_task(db_pool, room_id, task_name="ส่งแล้ว", status="done")

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="done", room_id=room_id,
    )

    assert [r["id"] for r in rows] == [done_id]


async def test_get_tasks_status_all_returns_both_statuses(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    pending_id = await _insert_task(db_pool, room_id, task_name="ยังไม่ส่ง", status="pending")
    done_id = await _insert_task(db_pool, room_id, task_name="ส่งแล้ว", status="done")

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="all", room_id=room_id,
    )

    assert {r["id"] for r in rows} == {pending_id, done_id}
    assert {r["status"] for r in rows} == {"pending", "done"}


async def test_get_tasks_status_all_orders_by_due_date_and_excludes_deleted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    later = await _insert_task(db_pool, room_id, task_name="งานช้า", due_date=date(2026, 12, 31), status="pending")
    sooner_done = await _insert_task(db_pool, room_id, task_name="ส่งเร็ว", due_date=date(2026, 8, 1), status="done")
    await _insert_task(db_pool, room_id, task_name="ถูกลบ", due_date=date(2026, 9, 1), status="pending", deleted=True)

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="all", room_id=room_id,
    )

    assert [r["id"] for r in rows] == [sooner_done, later]  # ORDER BY due_date ASC
    assert "ถูกลบ" not in [r["task_name"] for r in rows]  # deleted_at IS NULL


async def test_get_task_by_id_returns_task(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานเดียว")

    data = await ClassroomService.get_task_by_id(
        pool=db_pool, task_id=task_id, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert data["id"] == task_id
    assert data["task_name"] == "งานเดียว"
    assert data["task_detail"] == "รายละเอียดงาน"
    assert data["status"] == "pending"


async def test_add_daily_note_creates_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=date(2026, 8, 10), bring_items="ชุดว่ายน้ำ", announcement="พรุ่งนี้สอบ",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, date(2026, 8, 10),
        )
        assert row is not None
        assert row["bring_items"] == "ชุดว่ายน้ำ"
        assert row["announcement"] == "พรุ่งนี้สอบ"


async def test_get_daily_summary_combines_schedule_and_tasks(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # เลือกวันจันทร์ถัดจากวันนี้เสมอ → วันไทยตรงกับ enum โดยไม่ hardcode date
    # ใช้ THAI_TZ (เหมือน service) — ไม่ใช่ UTC ไม่งั้น flaky ระหว่าง 00:00-06:59 UTC+7 (วันยังไม่เปลี่ยน)
    today = datetime.now(THAI_TZ).date()
    days_until_monday = (0 - today.weekday()) % 7
    monday = today + timedelta(days=days_until_monday)

    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดนักเรียน", subjects="คณิต, ไทย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.set_override(
        pool=db_pool, target_date=monday, new_attire="ชุดกีฬา", note="กิจกรรมเข้าค่าย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=monday, bring_items="ขวดน้ำ", announcement="ไปเร็ว",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await _insert_task(db_pool, room_id, task_name="งานส่งวันนี้", due_date=today)

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=monday, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert data["day"] == "จันทร์"
    assert data["attire"] == "🚨 ชุดกีฬา (กรณีพิเศษ)"  # override ชนะ default
    assert data["subjects"] == "คณิต, ไทย"
    assert data["bring"] == "ขวดน้ำ"
    assert data["note"] == "⚠️ กิจกรรมเข้าค่าย | 📢 ไปเร็ว"
    assert len(data["tasks_due"]) == 1
    assert data["tasks_due"][0]["task_name"] == "งานส่งวันนี้"
    assert data["tasks_due"][0]["days_left"] == 0


async def test_get_daily_summary_returns_dashes_when_empty(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=date(2026, 8, 10), room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert data["attire"] == "-"
    assert data["subjects"] == "-"
    assert data["bring"] == "-"
    assert data["note"] == "-"
    assert data["tasks_due"] == []


async def test_get_audit_logs_returns_recent_logs(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # สร้าง log สัก 2-3 รายการ
    await ClassroomService.set_channel(
        pool=db_pool, channel_id=123456, user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.set_notify_time(
        pool=db_pool, notify_time="09:00", user_name="Owner",
        user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    logs = await ClassroomService.get_audit_logs(
        pool=db_pool, room_id=room_id,
        client_source="test", actor_identifier="test", limit=20,
    )

    assert len(logs) >= 2
    assert all(l["user_name"] == "test" for l in logs)  # actor_identifier alias
    assert all(l["action"] in ("UPDATE", "VIEW") for l in logs)
    assert all(l["detail"] in ("set_channel", "set_notify_time", "get_audit_logs") for l in logs)
    assert all("created_at" in l for l in logs)
    # ORDER BY created_at DESC → ตัวล่าสุดต้องมาก่อน
    created = [l["created_at"] for l in logs]
    assert created == sorted(created, reverse=True)


# === Section 2: Updates & Mutations ===


async def test_setup_room_renames_existing_bound_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, room_name="ชื่อเดิม", server_id=server_id)

    # ผูกแล้ว → อัปเดตแค่ชื่อห้อง ต้องไม่สร้างห้องใหม่
    await ClassroomService.setup_room(
        pool=db_pool, room_name="ชื่อใหม่", user_name="Owner",
        client_source="test", actor_identifier="test",
        server_id=server_id,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT room_name, server_id FROM rooms WHERE id = $1", room_id)
        assert row["room_name"] == "ชื่อใหม่"
        assert row["server_id"] == server_id  # server_id ยังเป็นตัวเดิม
        count = await conn.fetchval("SELECT COUNT(*) FROM rooms WHERE server_id = $1", server_id)
        assert count == 1


async def test_set_default_schedule_updates_existing_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดแรก", subjects="ไทย",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.set_default_schedule(
        pool=db_pool, day_of_week="จันทร์", attire="ชุดใหม่", subjects="คณิต",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM default_schedules WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )
        assert count == 1  # UPSERT — ไม่มีแถวซ้ำ
        row = await conn.fetchrow(
            "SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = $2",
            room_id, "จันทร์",
        )
        assert row["attire"] == "ชุดใหม่"
        assert row["subjects"] == "คณิต"


async def test_set_override_updates_existing_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 1)

    await ClassroomService.set_override(
        pool=db_pool, target_date=target, new_attire="ชุดแรก", note="note1",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.set_override(
        pool=db_pool, target_date=target, new_attire="ชุดใหม่", note="note2",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM schedule_overrides WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert count == 1
        row = await conn.fetchrow(
            "SELECT new_attire, note FROM schedule_overrides WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert row["new_attire"] == "ชุดใหม่"
        assert row["note"] == "note2"


async def test_add_daily_note_updates_existing_row(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 2)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ขวดแรก", announcement="ann1",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ขวดใหม่", announcement="ann2",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL",
            room_id, target,
        )
        assert count == 1
        row = await conn.fetchrow(
            "SELECT bring_items, announcement FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert row["bring_items"] == "ขวดใหม่"
        assert row["announcement"] == "ann2"


async def test_edit_task_updates_fields(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานเดิม", due_date=date(2026, 9, 1))

    await ClassroomService.edit_task(
        pool=db_pool, task_id=task_id, task_name="งานใหม่", task_detail="รายละเอียดใหม่", due_date=date(2026, 9, 15),
        user_name="Owner", room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        assert row["task_name"] == "งานใหม่"
        assert row["task_detail"] == "รายละเอียดใหม่"
        assert row["due_date"] == date(2026, 9, 15)
        assert row["status"] == "pending"  # status ไม่เปลี่ยน


async def test_mark_task_done_sets_status_and_notifies(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    task_id = await _insert_task(db_pool, room_id, task_name="งานส่ง", due_date=date(2026, 9, 1))

    with patch("services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock) as mock_notify:
        task_name = await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )

        assert task_name == "งานส่ง"
        mock_notify.assert_called_once_with(server_id, "งานส่ง", "Owner")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "done"


async def test_mark_task_done_without_server_id_skips_notify(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานไม่มี server")

    with patch("services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock) as mock_notify:
        await ClassroomService.mark_task_done(
            pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )

        mock_notify.assert_not_called()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task_id)
        assert row["status"] == "done"


async def test_restore_task_brings_back_deleted_task(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานกู้คืน", deleted=True)

    task_name = await ClassroomService.restore_task(
        pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert task_name == "งานกู้คืน"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is None


# === Section 3: Deletions (Soft & Hard) ===


async def test_delete_task_soft_deletes_and_returns_name(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="งานจะลบ")

    task_name = await ClassroomService.delete_task(
        pool=db_pool, task_id=task_id, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert task_name == "งานจะลบ"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at, task_name FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is not None  # soft delete
        assert row["task_name"] == "งานจะลบ"


async def test_get_deleted_tasks_returns_only_soft_deleted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    alive_id = await _insert_task(db_pool, room_id, task_name="ยังอยู่")
    deleted_id = await _insert_task(db_pool, room_id, task_name="โดนลบ", deleted=True)

    rows = await ClassroomService.get_deleted_tasks(
        pool=db_pool, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    ids = [r["id"] for r in rows]
    assert deleted_id in ids
    assert alive_id not in ids
    assert all(r["deleted_at"] is not None for r in rows)


async def test_delete_daily_note_soft_deletes_and_returns_content(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 3)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="หนังสือ", announcement="สอบปลายภาค",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    data = await ClassroomService.delete_daily_note(
        pool=db_pool, target_date=target, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert data["bring_items"] == "หนังสือ"
    assert data["announcement"] == "สอบปลายภาค"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deleted_at FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert row["deleted_at"] is not None


# === Section 4: Edge Cases & Validation ===


async def test_setup_room_requires_server_id(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(ValueError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="Bot Room", user_name="Owner",
            client_source="test", actor_identifier="test",
            server_id=None,
        )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM rooms WHERE room_name = $1", "Bot Room")
        assert count == 0


async def test_setup_room_rejects_missing_web_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(ValueError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="No Such Room", user_name="Owner",
            client_source="test", actor_identifier="test",
            server_id=random.randint(1_000_000, 9_999_999),
        )


async def test_setup_room_rejects_unbound_name_that_belongs_to_other_server(db_pool):
    """ห้องที่มีชื่อนี้แต่ผูก server อื่นแล้ว → ต้องไม่หลุดเข้าไปผิดห้อง"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_a = random.randint(1_000_000, 9_999_999)
    await _insert_room(db_pool, owner, room_name="ห้อง ม.6/2", server_id=server_a)

    with pytest.raises(ValueError):
        await ClassroomService.setup_room(
            pool=db_pool, room_name="ห้อง ม.6/2", user_name="Owner",
            client_source="test", actor_identifier="test",
            server_id=random.randint(1_000_000, 9_999_999),
        )


async def test_set_channel_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await ClassroomService.set_channel(
            pool=db_pool, channel_id=123456789, user_name="Plain",
            user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT announcement_channel_id FROM rooms WHERE id = $1", room_id)
        assert row["announcement_channel_id"] is None


async def test_set_notify_time_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await ClassroomService.set_notify_time(
            pool=db_pool, notify_time="08:00", user_name="Plain",
            user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT notify_time FROM rooms WHERE id = $1", room_id)
        assert row["notify_time"] == "19:00"  # ไม่ถูกแก้


async def test_set_default_schedule_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await ClassroomService.set_default_schedule(
            pool=db_pool, day_of_week="จันทร์", attire="ชุด", subjects="ไทย",
            user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_set_override_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await ClassroomService.set_override(
            pool=db_pool, target_date=date(2026, 9, 5), new_attire="ชุด", note="note",
            user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_add_daily_note_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    with pytest.raises(ForbiddenError):
        await ClassroomService.add_daily_note(
            pool=db_pool, target_date=date(2026, 9, 5), bring_items="ของ", announcement="ประกาศ",
            user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_delete_daily_note_plain_member_forbidden(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)
    target = date(2026, 9, 5)

    # เตรียม note ไว้ก่อน แล้วให้ member พยายามลบ
    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ของ", announcement="ประกาศ",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    with pytest.raises(ForbiddenError):
        await ClassroomService.delete_daily_note(
            pool=db_pool, target_date=target, user_name="Plain", user_id=member, room_id=room_id,
            client_source="test", actor_identifier="test",
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deleted_at FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
        assert row["deleted_at"] is None


async def test_delete_task_plain_member_forbidden(db_pool):
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


async def test_get_task_by_id_wrong_room_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, "Room A")
    room_b = await _insert_room(db_pool, owner, "Room B")
    task_id = await _insert_task(db_pool, room_a)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.get_task_by_id(
            pool=db_pool, task_id=task_id, room_id=room_b,
            client_source="test", actor_identifier="test",
        )


async def test_get_task_by_id_nonexistent_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.get_task_by_id(
            pool=db_pool, task_id=999999, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_edit_task_nonexistent_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.edit_task(
            pool=db_pool, task_id=999999, task_name="X", task_detail="Y", due_date=date(2026, 9, 1),
            user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_edit_task_wrong_room_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, "Room A")
    room_b = await _insert_room(db_pool, owner, "Room B")
    task_id = await _insert_task(db_pool, room_a)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.edit_task(
            pool=db_pool, task_id=task_id, task_name="X", task_detail="Y", due_date=date(2026, 9, 1),
            user_name="Owner", room_id=room_b,
            client_source="test", actor_identifier="test",
        )


async def test_mark_task_done_nonexistent_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.mark_task_done(
            pool=db_pool, task_id=999999, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_delete_task_nonexistent_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.delete_task(
            pool=db_pool, task_id=999999, user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_delete_task_already_deleted_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="ลบไปแล้ว", deleted=True)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.delete_task(
            pool=db_pool, task_id=task_id, user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_restore_task_not_deleted_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    task_id = await _insert_task(db_pool, room_id, task_name="ยังไม่ถูกลบ")

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.restore_task(
            pool=db_pool, task_id=task_id, user_name="Owner", room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_delete_daily_note_nonexistent_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.delete_daily_note(
            pool=db_pool, target_date=date(2026, 9, 5), user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_delete_daily_note_already_deleted_raises_tasknotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 6)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ของ", announcement="ประกาศ",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.delete_daily_note(
        pool=db_pool, target_date=target, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    with pytest.raises(TaskNotFoundError):
        await ClassroomService.delete_daily_note(
            pool=db_pool, target_date=target, user_name="Owner", user_id=owner, room_id=room_id,
            client_source="test", actor_identifier="test",
        )


async def test_get_tasks_after_soft_delete_excludes_deleted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    alive = await _insert_task(db_pool, room_id, task_name="อยู่")
    deleted = await _insert_task(db_pool, room_id, task_name="โดนลบ", deleted=True)

    rows = await ClassroomService.get_tasks(
        pool=db_pool, client_source="test", actor_identifier="test",
        status="pending", room_id=room_id,
    )

    ids = [r["id"] for r in rows]
    assert alive in ids
    assert deleted not in ids


async def test_get_rooms_to_notify_excludes_rooms_without_channel(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_a = random.randint(1_000_000, 9_999_999)
    room1 = await _insert_room(db_pool, owner, "Room A", server_id=server_a)

    # notify_time ตรง แต่ไม่มี announcement_channel_id → ต้องไม่โผล่
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET notify_time = '06:30' WHERE id = $1", room1)

    rows = await ClassroomService.get_rooms_to_notify(
        pool=db_pool, current_time="06:30",
        client_source="test", actor_identifier="test",
    )

    assert rows == []


async def test_get_daily_summary_excludes_deleted_daily_note(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    target = date(2026, 9, 7)

    await ClassroomService.add_daily_note(
        pool=db_pool, target_date=target, bring_items="ของเก่า", announcement="ann",
        user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )
    await ClassroomService.delete_daily_note(
        pool=db_pool, target_date=target, user_name="Owner", user_id=owner, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    data = await ClassroomService.get_daily_summary(
        pool=db_pool, target_date=target, room_id=room_id,
        client_source="test", actor_identifier="test",
    )

    assert data["bring"] == "-"  # note ที่ soft-delete แล้วต้องไม่แสดง
