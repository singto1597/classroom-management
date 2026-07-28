"""
tests/test_classroom.py

Comprehensive integration test suite for ClassroomSync API.

Design decisions:
  - `server_id` fixture generates a random int per test → full room isolation
  - `uid` fixture generates a short hex string → unique task/note names, no cross-test collision
  - `setup_room` depends on the per-test `server_id`, so every test starts with a fresh room
  - ActionService side-effects are patched at the service layer, not at redis, for precision
  - Every mutation test verifies the DB directly via pool.acquire()
  - Regression section documents known bugs in the service layer with failing-if-fixed markers
"""

import pytest
import pytest_asyncio
import uuid
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock

from core.config import settings

# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def mock_redis():
    """Prevent any real Redis connection attempts during tests."""
    with patch("services.action_service.aioredis.from_url") as mock_redis_url:
        mock_redis_client = AsyncMock()
        mock_redis_url.return_value = mock_redis_client
        yield mock_redis_client


@pytest.fixture(autouse=True)
def mock_rbac():
    """
    Fake RBAC:  discord_id == 999  →  admin (all permissions granted)
                anything else       →  ForbiddenError
    """
    async def _fake(conn, room_id, discord_id, perm):
        if discord_id != 999:
            from core.exceptions import ForbiddenError
            raise ForbiddenError("Access Denied: คุณไม่มีสิทธิ์จัดการข้อมูลห้องเรียนนี้")

    with patch("services.classroom_sync_service.require_permission", new=_fake):
        yield


@pytest.fixture
def admin_headers():
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": "999"}


@pytest.fixture
def user_headers():
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": "111"}


@pytest.fixture
def uid():
    """Short unique string — append to names to prevent cross-test collisions."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def server_id():
    """Unique Discord server ID per test — guarantees full room isolation."""
    return int(uuid.uuid4().int % (10 ** 15)) + 100_000_000


@pytest.fixture
def setup_room(client, server_id, admin_headers):
    """Creates a fresh room for the test and returns its server_id."""
    res = client.post(
        "/api/classroom/setup",
        json={"server_id": server_id, "room_name": "Test Room", "user_name": "AdminSetup"},
        headers=admin_headers,
    )
    assert res.status_code == 200, f"setup_room fixture failed: {res.text}"
    return server_id


# ===========================================================================
# Section 1 – Room Setup
# ===========================================================================

@pytest.mark.asyncio
async def test_setup_room_inserts_row(client, server_id, admin_headers, db_pool):
    res = client.post(
        "/api/classroom/setup",
        json={"server_id": server_id, "room_name": "ห้องวิทย์ ม.4/1", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT room_name FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id
        )
    assert row is not None
    assert row["room_name"] == "ห้องวิทย์ ม.4/1"


@pytest.mark.asyncio
async def test_setup_room_upserts_name_on_conflict(client, server_id, admin_headers, db_pool):
    """Calling setup twice on the same server_id must update the name, not duplicate the row."""
    base = {"server_id": server_id, "user_name": "Admin"}
    client.post("/api/classroom/setup", json={**base, "room_name": "ชื่อเก่า"}, headers=admin_headers)
    client.post("/api/classroom/setup", json={**base, "room_name": "ชื่อใหม่"}, headers=admin_headers)

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM rooms WHERE server_id = $1", server_id)
        name = await conn.fetchval("SELECT room_name FROM rooms WHERE server_id = $1", server_id)

    assert count == 1
    assert name == "ชื่อใหม่"


@pytest.mark.asyncio
async def test_setup_room_writes_audit_log(client, server_id, admin_headers, db_pool):
    client.post(
        "/api/classroom/setup",
        json={"server_id": server_id, "room_name": "LogRoom", "user_name": "LogAdmin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", server_id)
        log = await conn.fetchrow(
            "SELECT action, user_name FROM audit_logs WHERE room_id = $1 AND action = 'Setup Room'",
            room_id,
        )
    assert log is not None
    assert log["user_name"] == "LogAdmin"


# ===========================================================================
# Section 2 – Get Room Data
# ===========================================================================

def test_get_room_data_returns_correct_shape(client, setup_room, admin_headers):
    res = client.get(f"/api/classroom/{setup_room}", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["server_id"] == setup_room
    assert "room_name" in data
    assert "announcement_channel_id" in data
    assert "notify_time" in data


def test_get_room_data_returns_404_for_unknown_server(client, admin_headers):
    res = client.get("/api/classroom/99999999999", headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 3 – Channel & Time Settings
# ===========================================================================

@pytest.mark.asyncio
async def test_set_channel_persists_to_db(client, setup_room, admin_headers, db_pool):
    res = client.put(
        f"/api/classroom/{setup_room}/channel",
        json={"channel_id": 555_001, "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        ch = await conn.fetchval(
            "SELECT announcement_channel_id FROM rooms WHERE server_id = $1", setup_room
        )
    assert ch == 555_001


def test_set_channel_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.put(
        f"/api/classroom/{setup_room}/channel",
        json={"channel_id": 555_001, "user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403
    assert "Access Denied" in res.json()["detail"]


def test_set_channel_returns_404_for_unknown_room(client, admin_headers):
    res = client.put(
        "/api/classroom/99999999/channel",
        json={"channel_id": 1, "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_set_notify_time_persists_to_db(client, setup_room, admin_headers, db_pool):
    res = client.put(
        f"/api/classroom/{setup_room}/time",
        json={"notify_time": "07:30", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        t = await conn.fetchval("SELECT notify_time FROM rooms WHERE server_id = $1", setup_room)
    assert t == "07:30"


@pytest.mark.parametrize("bad_time", ["25:00", "08:60", "abc", "", "007:30", "7:3"])
def test_set_notify_time_rejects_invalid_format(client, setup_room, admin_headers, bad_time):
    res = client.put(
        f"/api/classroom/{setup_room}/time",
        json={"notify_time": bad_time, "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 422


def test_set_notify_time_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.put(
        f"/api/classroom/{setup_room}/time",
        json={"notify_time": "07:00", "user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


# ===========================================================================
# Section 4 – Notification Targets
# ===========================================================================

@pytest.mark.asyncio
async def test_get_rooms_to_notify_includes_fully_configured_room(client, setup_room, admin_headers):
    """Room with both notify_time AND announcement_channel_id must appear."""
    client.put(f"/api/classroom/{setup_room}/channel", json={"channel_id": 999_001, "user_name": "Admin"}, headers=admin_headers)
    client.put(f"/api/classroom/{setup_room}/time", json={"notify_time": "06:15", "user_name": "Admin"}, headers=admin_headers)

    res = client.get("/api/classroom/notifications/targets?current_time=06:15", headers=admin_headers)
    assert res.status_code == 200
    assert setup_room in [r["server_id"] for r in res.json()]


def test_get_rooms_to_notify_excludes_room_without_channel(client, setup_room, admin_headers):
    """Room with notify_time but no channel must NOT appear."""
    client.put(f"/api/classroom/{setup_room}/time", json={"notify_time": "05:45", "user_name": "Admin"}, headers=admin_headers)
    # intentionally skip set_channel

    res = client.get("/api/classroom/notifications/targets?current_time=05:45", headers=admin_headers)
    assert setup_room not in [r["server_id"] for r in res.json()]


def test_get_rooms_to_notify_excludes_different_time(client, setup_room, admin_headers):
    """Room configured for 07:00 must not appear when querying 08:00."""
    client.put(f"/api/classroom/{setup_room}/channel", json={"channel_id": 999_002, "user_name": "Admin"}, headers=admin_headers)
    client.put(f"/api/classroom/{setup_room}/time", json={"notify_time": "07:00", "user_name": "Admin"}, headers=admin_headers)

    res = client.get("/api/classroom/notifications/targets?current_time=08:00", headers=admin_headers)
    assert setup_room not in [r["server_id"] for r in res.json()]


# ===========================================================================
# Section 5 – Default Schedule
# ===========================================================================

@pytest.mark.asyncio
async def test_set_default_schedule_persists(client, setup_room, admin_headers, db_pool):
    res = client.post(
        f"/api/classroom/{setup_room}/schedule/default",
        json={"day_of_week": "จันทร์", "attire": "ชุดนักเรียน", "subjects": "คณิต, ฟิสิกส์", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        row = await conn.fetchrow(
            "SELECT attire, subjects FROM default_schedules WHERE room_id = $1 AND day_of_week = 'จันทร์'",
            room_id,
        )
    assert row["attire"] == "ชุดนักเรียน"
    assert row["subjects"] == "คณิต, ฟิสิกส์"


@pytest.mark.asyncio
async def test_set_default_schedule_replaces_not_duplicates(client, setup_room, admin_headers, db_pool):
    """Setting the same day twice must replace the row, not create a second one."""
    base = {"day_of_week": "อังคาร", "user_name": "Admin"}
    client.post(f"/api/classroom/{setup_room}/schedule/default", json={**base, "attire": "เก่า", "subjects": "A"}, headers=admin_headers)
    client.post(f"/api/classroom/{setup_room}/schedule/default", json={**base, "attire": "ใหม่", "subjects": "B"}, headers=admin_headers)

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM default_schedules WHERE room_id = $1 AND day_of_week = 'อังคาร'", room_id
        )
        attire = await conn.fetchval(
            "SELECT attire FROM default_schedules WHERE room_id = $1 AND day_of_week = 'อังคาร'", room_id
        )
    assert count == 1
    assert attire == "ใหม่"


def test_set_default_schedule_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.post(
        f"/api/classroom/{setup_room}/schedule/default",
        json={"day_of_week": "พุธ", "attire": "ชุด", "subjects": "X", "user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


def test_set_default_schedule_returns_404_for_unknown_room(client, admin_headers):
    res = client.post(
        "/api/classroom/99999999/schedule/default",
        json={"day_of_week": "พุธ", "attire": "ชุด", "subjects": "X", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# ===========================================================================
# Section 6 – Schedule Override
# ===========================================================================

@pytest.mark.asyncio
async def test_set_override_persists(client, setup_room, admin_headers, db_pool):
    target = date.today() + timedelta(days=7)
    res = client.post(
        f"/api/classroom/{setup_room}/schedule/override",
        json={"target_date": str(target), "new_attire": "ชุดกีฬา", "note": "วันกีฬาสี", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        row = await conn.fetchrow(
            "SELECT new_attire, note FROM schedule_overrides WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
    assert row["new_attire"] == "ชุดกีฬา"
    assert row["note"] == "วันกีฬาสี"


@pytest.mark.asyncio
async def test_set_override_replaces_not_duplicates(client, setup_room, admin_headers, db_pool):
    target = date.today() + timedelta(days=14)
    base = {"target_date": str(target), "user_name": "Admin"}
    client.post(f"/api/classroom/{setup_room}/schedule/override", json={**base, "new_attire": "เก่า", "note": "A"}, headers=admin_headers)
    client.post(f"/api/classroom/{setup_room}/schedule/override", json={**base, "new_attire": "ใหม่", "note": "B"}, headers=admin_headers)

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM schedule_overrides WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
    assert count == 1


def test_set_override_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.post(
        f"/api/classroom/{setup_room}/schedule/override",
        json={"target_date": str(date.today()), "new_attire": "X", "note": "Y", "user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


def test_set_override_returns_404_for_unknown_room(client, admin_headers):
    res = client.post(
        "/api/classroom/99999999/schedule/override",
        json={"target_date": str(date.today()), "new_attire": "X", "note": "Y", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# ===========================================================================
# Section 7 – Tasks: Add
# ===========================================================================

@pytest.mark.asyncio
async def test_add_task_persists_and_calls_action_service(client, setup_room, admin_headers, uid, db_pool):
    with patch(
        "services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock
    ) as mock_notify:
        res = client.post(
            f"/api/classroom/{setup_room}/tasks",
            json={"task_name": f"คณิต_{uid}", "task_detail": "บทที่ 1", "due_date": str(date.today()), "user_name": "Admin"},
            headers=admin_headers,
        )
        assert res.status_code == 200
        mock_notify.assert_called_once()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT task_name, task_detail FROM tasks WHERE task_name = $1", f"คณิต_{uid}")
    assert row is not None
    assert row["task_detail"] == "บทที่ 1"


def test_add_task_rejects_invalid_date(client, setup_room, admin_headers, uid):
    res = client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"Task_{uid}", "due_date": "not-a-date", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 422


def test_add_task_returns_404_for_unknown_room(client, admin_headers, uid):
    res = client.post(
        "/api/classroom/99999999/tasks",
        json={"task_name": f"Task_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_add_task_writes_audit_log(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"AuditTask_{uid}", "due_date": str(date.today()), "user_name": "TestAdmin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        log = await conn.fetchrow(
            "SELECT action, detail FROM audit_logs WHERE room_id = $1 AND action = 'Add Task' AND detail LIKE $2",
            room_id, f"%AuditTask_{uid}%",
        )
    assert log is not None


# ===========================================================================
# Section 8 – Tasks: Get List & Get By ID
# ===========================================================================

@pytest.mark.asyncio
async def test_get_tasks_pending_excludes_done_tasks(client, setup_room, admin_headers, uid, db_pool):
    for name in [f"pending_{uid}", f"will_be_done_{uid}"]:
        client.post(
            f"/api/classroom/{setup_room}/tasks",
            json={"task_name": name, "due_date": str(date.today()), "user_name": "Admin"},
            headers=admin_headers,
        )

    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"will_be_done_{uid}")
    client.patch(f"/api/classroom/{setup_room}/tasks/{task_id}/done", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks?status=pending", headers=admin_headers)
    assert res.status_code == 200
    names = [t["task_name"] for t in res.json()]
    assert f"pending_{uid}" in names
    assert f"will_be_done_{uid}" not in names


@pytest.mark.asyncio
async def test_get_tasks_pending_excludes_soft_deleted(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"del_pending_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"del_pending_{uid}")
    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks?status=pending", headers=admin_headers)
    names = [t["task_name"] for t in res.json()]
    assert f"del_pending_{uid}" not in names


@pytest.mark.asyncio
async def test_get_tasks_done_status_filter(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"done_later_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"done_later_{uid}")
    client.patch(f"/api/classroom/{setup_room}/tasks/{task_id}/done", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks?status=done", headers=admin_headers)
    assert res.status_code == 200
    names = [t["task_name"] for t in res.json()]
    assert f"done_later_{uid}" in names


@pytest.mark.asyncio
async def test_get_task_by_id_returns_correct_task(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"single_{uid}", "task_detail": "รายละเอียด", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"single_{uid}")

    res = client.get(f"/api/classroom/{setup_room}/tasks/{task_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["task_name"] == f"single_{uid}"
    assert res.json()["task_detail"] == "รายละเอียด"
    assert res.json()["status"] == "pending"


def test_get_task_by_id_returns_404_for_unknown_id(client, setup_room, admin_headers):
    res = client.get(f"/api/classroom/{setup_room}/tasks/9_999_999", headers=admin_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_task_by_id_returns_404_for_deleted_task(client, setup_room, admin_headers, uid, db_pool):
    """get_task_by_id filters deleted_at IS NULL — deleted task must return 404."""
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"ghost_get_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"ghost_get_{uid}")
    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks/{task_id}", headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 9 – Tasks: Edit
# ===========================================================================

@pytest.mark.asyncio
async def test_edit_task_persists_all_fields(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"before_edit_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"before_edit_{uid}")

    new_due = str(date.today() + timedelta(days=3))
    res = client.put(
        f"/api/classroom/{setup_room}/tasks/{task_id}",
        json={"task_name": f"after_edit_{uid}", "task_detail": "แก้แล้ว", "due_date": new_due, "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT task_name, task_detail, due_date FROM tasks WHERE id = $1", task_id)
    assert row["task_name"] == f"after_edit_{uid}"
    assert row["task_detail"] == "แก้แล้ว"
    assert str(row["due_date"]) == new_due


def test_edit_task_returns_404_for_unknown_id(client, setup_room, admin_headers):
    res = client.put(
        f"/api/classroom/{setup_room}/tasks/9_999_999",
        json={"task_name": "X", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# ===========================================================================
# Section 10 – Tasks: Mark Done
# ===========================================================================

@pytest.mark.asyncio
async def test_mark_task_done_updates_status_and_calls_action_service(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"to_done_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"to_done_{uid}")

    with patch(
        "services.classroom_sync_service.ActionService.notify_task_done", new_callable=AsyncMock
    ) as mock_done:
        res = client.patch(
            f"/api/classroom/{setup_room}/tasks/{task_id}/done",
            json={"user_name": "Student A"},
            headers=admin_headers,
        )
        assert res.status_code == 200
        assert res.json()["task_name"] == f"to_done_{uid}"
        mock_done.assert_called_once()

    async with db_pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM tasks WHERE id = $1", task_id)
    assert status == "done"


def test_mark_task_done_returns_404_for_unknown_id(client, setup_room, admin_headers):
    res = client.patch(
        f"/api/classroom/{setup_room}/tasks/9_999_999/done",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# ===========================================================================
# Section 11 – Tasks: Soft Delete
# ===========================================================================

@pytest.mark.asyncio
async def test_delete_task_sets_deleted_at_and_returns_name(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"to_delete_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"to_delete_{uid}")

    res = client.request("DELETE", 
        f"/api/classroom/{setup_room}/tasks/{task_id}",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["task_name"] == f"to_delete_{uid}"

    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
    assert deleted_at is not None  # soft delete — row still exists


def test_delete_task_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.request("DELETE", 
        f"/api/classroom/{setup_room}/tasks/1",
        json={"user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_delete_task_returns_404_when_already_deleted(client, setup_room, admin_headers, uid, db_pool):
    """Soft-deleting the same task twice must return 404 on the second attempt."""
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"double_del_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"double_del_{uid}")

    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)
    res = client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 12 – Tasks: Get Deleted
# ===========================================================================

@pytest.mark.asyncio
async def test_get_deleted_tasks_shows_soft_deleted_with_deleted_at(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"ghost_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"ghost_{uid}")
    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks/deleted", headers=admin_headers)
    assert res.status_code == 200
    matching = [t for t in res.json() if t["task_name"] == f"ghost_{uid}"]
    assert len(matching) == 1
    assert matching[0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_get_deleted_tasks_does_not_show_active_tasks(client, setup_room, admin_headers, uid):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"still_alive_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    res = client.get(f"/api/classroom/{setup_room}/tasks/deleted", headers=admin_headers)
    names = [t["task_name"] for t in res.json()]
    assert f"still_alive_{uid}" not in names


# ===========================================================================
# Section 13 – Tasks: Restore
# ===========================================================================

@pytest.mark.asyncio
async def test_restore_task_clears_deleted_at(client, setup_room, admin_headers, uid, db_pool):
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"restore_me_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"restore_me_{uid}")

    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.patch(
        f"/api/classroom/{setup_room}/tasks/{task_id}/restore",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["task_name"] == f"restore_me_{uid}"

    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
    assert deleted_at is None  # restored → active again


@pytest.mark.asyncio
async def test_restore_active_task_returns_404(client, setup_room, admin_headers, uid, db_pool):
    """Restoring a task that has NOT been deleted must return 404."""
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"still_active_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"still_active_{uid}")

    res = client.patch(
        f"/api/classroom/{setup_room}/tasks/{task_id}/restore",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_restore_task_then_appears_in_active_list(client, setup_room, admin_headers, uid, db_pool):
    """Full lifecycle: add → delete → restore → must be visible in pending list again."""
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"lifecycle_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"lifecycle_{uid}")

    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)
    client.patch(f"/api/classroom/{setup_room}/tasks/{task_id}/restore", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/tasks?status=pending", headers=admin_headers)
    names = [t["task_name"] for t in res.json()]
    assert f"lifecycle_{uid}" in names


# ===========================================================================
# Section 14 – Daily Notes
# ===========================================================================

@pytest.mark.asyncio
async def test_add_daily_note_persists(client, setup_room, admin_headers, db_pool):
    target = date.today() + timedelta(days=1)
    res = client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "สมุด, ปากกา", "announcement": "ประชุมผู้ปกครอง", "user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        row = await conn.fetchrow(
            "SELECT bring_items, announcement FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL",
            room_id, target,
        )
    assert row["bring_items"] == "สมุด, ปากกา"
    assert row["announcement"] == "ประชุมผู้ปกครอง"


def test_add_daily_note_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(date.today()), "bring_items": "X", "announcement": "Y", "user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_add_daily_note_replaces_existing_for_same_date(client, setup_room, admin_headers, db_pool):
    """Posting a note for the same date twice must result in exactly 1 active row."""
    target = date.today() + timedelta(days=3)
    base = {"target_date": str(target), "user_name": "Admin"}
    client.post(f"/api/classroom/{setup_room}/notes", json={**base, "bring_items": "ของเก่า", "announcement": "A"}, headers=admin_headers)
    client.post(f"/api/classroom/{setup_room}/notes", json={**base, "bring_items": "ของใหม่", "announcement": "B"}, headers=admin_headers)

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL",
            room_id, target,
        )
        items = await conn.fetchval(
            "SELECT bring_items FROM daily_notes WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL",
            room_id, target,
        )
    assert count == 1
    assert items == "ของใหม่"


@pytest.mark.asyncio
async def test_delete_daily_note_soft_deletes_and_returns_content(client, setup_room, admin_headers, db_pool):
    target = date.today() + timedelta(days=5)
    client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "หนังสือ", "announcement": "แจ้งด่วน", "user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.request("DELETE", 
        f"/api/classroom/{setup_room}/notes/{target}",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["bring_items"] == "หนังสือ"
    assert res.json()["announcement"] == "แจ้งด่วน"

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1", setup_room)
        deleted_at = await conn.fetchval(
            "SELECT deleted_at FROM daily_notes WHERE room_id = $1 AND target_date = $2",
            room_id, target,
        )
    assert deleted_at is not None  # row still exists, just soft-deleted


def test_delete_daily_note_returns_404_when_not_found(client, setup_room, admin_headers):
    res = client.request("DELETE", 
        f"/api/classroom/{setup_room}/notes/2099-01-01",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    assert res.status_code == 404


def test_delete_daily_note_returns_403_for_non_admin(client, setup_room, user_headers):
    res = client.request("DELETE", 
        f"/api/classroom/{setup_room}/notes/{date.today()}",
        json={"user_name": "Student"},
        headers=user_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_delete_daily_note_already_deleted_returns_404(client, setup_room, admin_headers):
    target = date.today() + timedelta(days=9)
    client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "X", "announcement": "Y", "user_name": "Admin"},
        headers=admin_headers,
    )
    client.request("DELETE", f"/api/classroom/{setup_room}/notes/{target}", json={"user_name": "Admin"}, headers=admin_headers)
    res = client.request("DELETE", f"/api/classroom/{setup_room}/notes/{target}", json={"user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 15 – Daily Summary
# ===========================================================================

def test_daily_summary_returns_defaults_when_no_data(client, setup_room, admin_headers):
    """Summary for a day with nothing configured must use '-' for all fields."""
    res = client.get(f"/api/classroom/{setup_room}/summary?target_date=2099-01-01", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["attire"] == "-"
    assert data["subjects"] == "-"
    assert data["bring"] == "-"
    assert data["note"] == "-"
    assert data["tasks_due"] == []


@pytest.mark.asyncio
async def test_daily_summary_uses_default_schedule(client, setup_room, admin_headers):
    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_to_monday)

    client.post(
        f"/api/classroom/{setup_room}/schedule/default",
        json={"day_of_week": "จันทร์", "attire": "ชุดนักเรียน", "subjects": "คณิต, ฟิสิกส์", "user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={next_monday}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["attire"] == "ชุดนักเรียน"
    assert res.json()["subjects"] == "คณิต, ฟิสิกส์"
    assert res.json()["day"] == "จันทร์"


@pytest.mark.asyncio
async def test_daily_summary_override_takes_priority_over_default(client, setup_room, admin_headers):
    """Override attire must win over default and carry the 🚨 prefix."""
    target = date.today() + timedelta(days=10)
    day_name = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"][target.weekday()]

    client.post(
        f"/api/classroom/{setup_room}/schedule/default",
        json={"day_of_week": day_name, "attire": "ชุดปกติ", "subjects": "X", "user_name": "Admin"},
        headers=admin_headers,
    )
    client.post(
        f"/api/classroom/{setup_room}/schedule/override",
        json={"target_date": str(target), "new_attire": "ชุดกีฬา", "note": "กีฬาสี", "user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={target}", headers=admin_headers)
    assert res.status_code == 200
    attire = res.json()["attire"]
    assert "🚨" in attire
    assert "ชุดกีฬา" in attire
    assert "⚠️ กีฬาสี" in res.json()["note"]


@pytest.mark.asyncio
async def test_daily_summary_note_populates_bring_and_note_fields(client, setup_room, admin_headers):
    target = date.today() + timedelta(days=15)
    client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "แฟ้มสะสมงาน", "announcement": "ประชุม PTA", "user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={target}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["bring"] == "แฟ้มสะสมงาน"
    assert "📢 ประชุม PTA" in res.json()["note"]


@pytest.mark.asyncio
async def test_daily_summary_task_display_text_icons(client, setup_room, admin_headers, uid):
    """Verify the correct emoji icons for each urgency tier."""
    today = date.today()
    cases = [
        (f"overdue_{uid}", today - timedelta(days=2),  "🔴"),
        (f"today_{uid}",   today,                       "🔥"),
        (f"tmrw_{uid}",    today + timedelta(days=1),   "⚠️"),
        (f"future_{uid}",  today + timedelta(days=5),   "🟢"),
    ]
    for name, due, _ in cases:
        client.post(
            f"/api/classroom/{setup_room}/tasks",
            json={"task_name": name, "due_date": str(due), "user_name": "Admin"},
            headers=admin_headers,
        )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={today}", headers=admin_headers)
    assert res.status_code == 200
    by_name = {t["task_name"]: t["display_text"] for t in res.json()["tasks_due"]}

    for name, _, expected_icon in cases:
        assert expected_icon in by_name[name], f"Expected {expected_icon} in display_text for {name}"


@pytest.mark.asyncio
async def test_daily_summary_combines_override_note_and_daily_note(client, setup_room, admin_headers):
    """When both override and daily note exist, both must appear in 'note' joined by ' | '."""
    target = date.today() + timedelta(days=20)
    day_name = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"][target.weekday()]

    client.post(
        f"/api/classroom/{setup_room}/schedule/default",
        json={"day_of_week": day_name, "attire": "ปกติ", "subjects": "X", "user_name": "Admin"},
        headers=admin_headers,
    )
    client.post(
        f"/api/classroom/{setup_room}/schedule/override",
        json={"target_date": str(target), "new_attire": "ชุดพิเศษ", "note": "ข้อความ override", "user_name": "Admin"},
        headers=admin_headers,
    )
    client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "X", "announcement": "ข้อความประกาศ", "user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={target}", headers=admin_headers)
    note_text = res.json()["note"]
    assert "⚠️ ข้อความ override" in note_text
    assert "📢 ข้อความประกาศ" in note_text
    assert " | " in note_text


def test_daily_summary_returns_404_for_unknown_room(client, admin_headers):
    res = client.get("/api/classroom/99999999/summary?target_date=2099-01-01", headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 16 – Audit Logs
# ===========================================================================

@pytest.mark.asyncio
async def test_audit_logs_contain_mutations_from_session(client, setup_room, admin_headers, uid):
    """After adding a task, both Setup Room and Add Task must appear in logs."""
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"logged_{uid}", "due_date": str(date.today()), "user_name": "LogAdmin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/logs", headers=admin_headers)
    assert res.status_code == 200
    actions = {log["action"] for log in res.json()}
    assert "Setup Room" in actions
    assert "Add Task" in actions


@pytest.mark.asyncio
async def test_audit_logs_ordered_newest_first(client, setup_room, admin_headers, uid):
    client.put(f"/api/classroom/{setup_room}/channel", json={"channel_id": 1, "user_name": "Admin"}, headers=admin_headers)
    client.put(f"/api/classroom/{setup_room}/time", json={"notify_time": "08:00", "user_name": "Admin"}, headers=admin_headers)

    res = client.get(f"/api/classroom/{setup_room}/logs", headers=admin_headers)
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) >= 3  # setup + channel + time
    # The most recent action should be "Set Time"
    assert logs[0]["action"] == "Set Time"


def test_audit_logs_returns_404_for_unknown_room(client, admin_headers):
    res = client.get("/api/classroom/99999999/logs", headers=admin_headers)
    assert res.status_code == 404


# ===========================================================================
# Section 17 – Bug Regression Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_REGRESSION_get_daily_summary_must_not_show_deleted_note(client, setup_room, admin_headers):
    """
    BUG: classroom_sync_service.py line 268 — get_daily_summary queries daily_notes
    WITHOUT 'AND deleted_at IS NULL'. A soft-deleted note will therefore still appear
    in the summary response.

    Expected behaviour: after deleting a note, 'bring' and 'note' should revert to '-'.
    If this test FAILS → the bug is still present in the service.
    """
    target = date.today() + timedelta(days=25)
    client.post(
        f"/api/classroom/{setup_room}/notes",
        json={"target_date": str(target), "bring_items": "ควรหาย", "announcement": "ควรหาย", "user_name": "Admin"},
        headers=admin_headers,
    )
    client.request("DELETE", 
        f"/api/classroom/{setup_room}/notes/{target}",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )

    res = client.get(f"/api/classroom/{setup_room}/summary?target_date={target}", headers=admin_headers)
    assert res.status_code == 200
    # These will FAIL until the service adds 'AND deleted_at IS NULL' to the daily_notes query
    assert res.json()["bring"] == "-", "BUG: deleted note still populates 'bring' in summary"
    assert res.json()["note"] == "-", "BUG: deleted note still populates 'note' in summary"


@pytest.mark.asyncio
async def test_REGRESSION_edit_task_must_not_affect_deleted_tasks(client, setup_room, admin_headers, uid, db_pool):
    """
    BUG: classroom_sync_service.py line 158-160 — edit_task UPDATE has no
    'AND deleted_at IS NULL'. A soft-deleted task can be renamed/re-dated through
    the API, which violates data integrity.

    Expected behaviour: editing a deleted task returns 404.
    If this test FAILS → the bug is still present in the service.
    """
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"edit_deleted_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"edit_deleted_{uid}")

    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.put(
        f"/api/classroom/{setup_room}/tasks/{task_id}",
        json={"task_name": "แก้ชื่อ", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    # This will FAIL until the service adds 'AND deleted_at IS NULL' to the UPDATE
    assert res.status_code == 404, "BUG: edit_task allows editing of soft-deleted tasks"


@pytest.mark.asyncio
async def test_REGRESSION_mark_done_must_not_affect_deleted_tasks(client, setup_room, admin_headers, uid, db_pool):
    """
    BUG: classroom_sync_service.py line 170-172 — mark_task_done UPDATE has no
    'AND deleted_at IS NULL'. Status of a soft-deleted task can be changed.

    Expected behaviour: marking a deleted task as done returns 404.
    If this test FAILS → the bug is still present in the service.
    """
    client.post(
        f"/api/classroom/{setup_room}/tasks",
        json={"task_name": f"done_deleted_{uid}", "due_date": str(date.today()), "user_name": "Admin"},
        headers=admin_headers,
    )
    async with db_pool.acquire() as conn:
        task_id = await conn.fetchval("SELECT id FROM tasks WHERE task_name = $1", f"done_deleted_{uid}")

    client.request("DELETE", f"/api/classroom/{setup_room}/tasks/{task_id}", json={"user_name": "Admin"}, headers=admin_headers)

    res = client.patch(
        f"/api/classroom/{setup_room}/tasks/{task_id}/done",
        json={"user_name": "Admin"},
        headers=admin_headers,
    )
    # This will FAIL until the service adds 'AND deleted_at IS NULL' to the UPDATE
    assert res.status_code == 404, "BUG: mark_task_done allows marking soft-deleted tasks as done"
