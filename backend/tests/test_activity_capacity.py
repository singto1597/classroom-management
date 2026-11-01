"""
ความจุกิจกรรม + คิวสำรอง (P4.1) — integration tests

ครอบคลุมตาม docs/rules/testing.md:
  - Real Postgres (test_db) + clean_database fixture → state isolation
  - Randomized server_id / room_code — ห้าม hardcode id
  - Deep DB verification: assert หลัง service call → query DB ตรง ๆ พิสูจน์ mutation
  - Mock ActionService (กันแตะ Redis) + ตรวจ `notifications` จริงใน DB

สิ่งที่ต้องพิสูจน์ (DoD ของ P4):
  ✓ กิจกรรมเต็มแล้ว **ไม่ error** — คนเกินได้ `waitlisted` พร้อมเลขคิว
  ✓ ยกเลิก/ลบผู้เข้าร่วม → คิวเลื่อนขึ้น **ใน transaction เดียว** + มีแจ้งเตือน
  ✓ capacity ไม่เพี้ยนเมื่อหลายคำขอพร้อมกัน (concurrency)
  ✓ `attended` ไม่ถูกเด้งลงคิว · ลดความจุต่ำกว่าคนที่ยืนยันแล้ว → 400
"""
import asyncio
import json
import random
import string
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import ValidationError
from services.action_service import ActionService
from services.activity_service import ActivityService
from services.activity.capacity import plan_seats

pytestmark = pytest.mark.asyncio


# === Fixtures & helpers (pattern เดียวกับ test_activity.py) ===


async def _insert_user(pool, *, first_name="Test", last_name="User", email=None, discord_id=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}", discord_id,
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
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb, TRUE)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb, TRUE)
            RETURNING id
            """,
            room_id, user_id, student_no,
        )


async def _make_room(pool, student_count: int):
    """สร้างห้อง + เจ้าของ (admin) + นักเรียน n คน → (room_id, owner_id, [(student_id, user_id, student_no)])"""
    owner = await _insert_user(pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(pool, owner)
    students = []
    for no in range(1, student_count + 1):
        uid = await _insert_user(pool, first_name=f"นักเรียน{no}", last_name="ทดสอบ")
        sid = await _insert_student(pool, room_id, uid, no)
        students.append((sid, uid, no))
    return room_id, owner, students


async def _create_activity(pool, room_id, owner, *, capacity=None, participant_nos=(), status="upcoming"):
    with patch.object(ActionService, "notify_new_activity", new_callable=AsyncMock):
        result = await ActivityService.create_activity(
            pool=pool,
            title="ค่ายทดสอบ",
            activity_date=date(2026, 12, 1),
            base_hours=6.0,
            status=status,
            capacity=capacity,
            metadata={},
            participants=[{"student_no": no} for no in participant_nos],
            user_name="ผู้ดูแล",
            client_source="WEB_APP",
            actor_identifier="user_id:1",
            room_id=room_id,
            actor_user_id=owner,
        )
    return result["activity_id"]


async def _rows(pool, activity_id: int):
    """สถานะผู้เข้าร่วมทั้งหมดของกิจกรรม → {student_no: (status, queue_position)}"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.student_no, ap.status, ap.queue_position
            FROM activity_participants ap
            JOIN students s ON s.id = ap.student_id
            WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL
            ORDER BY s.student_no
            """,
            activity_id,
        )
    return {r["student_no"]: (r["status"], r["queue_position"]) for r in rows}


def _web_headers(user_id: int) -> dict:
    from jose import jwt

    from core.config import settings

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _add(pool, room_id, owner, activity_id, student_no, **kw):
    return ActivityService.add_participant(
        pool=pool,
        activity_id=activity_id,
        student_no=student_no,
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
        **kw,
    )


# ================================================================
# 🧮 plan_seats — ตรรกะบริสุทธิ์ (ไม่แตะ DB) ต้องพิสูจน์แยกได้
#    (เป็น async def เปล่า ๆ เพื่อไม่ให้ module-level pytestmark.asyncio เตือน)
# ================================================================

async def test_plan_seats_without_capacity_seats_everyone():
    assert plan_seats(["confirmed", "attended"], None, seated=99, next_queue=1) == [
        ("confirmed", None),
        ("attended", None),
    ]


async def test_plan_seats_overflows_to_queue_in_order():
    assert plan_seats(
        ["confirmed", "confirmed", "confirmed"], capacity=2, seated=0, next_queue=1
    ) == [
        ("confirmed", None),
        ("confirmed", None),
        ("waitlisted", 1),
    ]


async def test_plan_seats_respects_existing_seats_and_queue_tail():
    """เพิ่มทีละคนตอนกิจกรรมมีคนนั่ง 1/2 อยู่แล้ว → คนแรกได้ที่นั่ง คนที่สองเข้าคิวต่อท้าย"""
    assert plan_seats(["confirmed", "confirmed"], capacity=2, seated=1, next_queue=4) == [
        ("confirmed", None),
        ("waitlisted", 4),
    ]


async def test_plan_seats_keeps_cancelled_and_explicit_waitlist():
    assert plan_seats(["cancelled", "waitlisted"], capacity=1, seated=0, next_queue=7) == [
        ("cancelled", None),
        ("waitlisted", 7),
    ]


# ================================================================
# 🎟️ สร้างกิจกรรม + จองที่นั่ง
# ================================================================

async def test_create_activity_without_capacity_confirms_everyone(db_pool):
    """capacity = NULL (แถวเดิมทั้งหมดเป็นแบบนี้) → พฤติกรรมเดิมไม่เปลี่ยน: ทุกคน confirmed"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, participant_nos=[1, 2, 3])

    assert await _rows(db_pool, activity_id) == {
        1: ("confirmed", None), 2: ("confirmed", None), 3: ("confirmed", None),
    }
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT capacity FROM activities WHERE id = $1", activity_id) is None


async def test_create_activity_capacity_splits_seats_and_queue(db_pool):
    """ความจุ 2 + เลือก 4 คน → 2 คนแรกได้ที่นั่ง อีก 2 คนเข้าคิว 1,2 (ตามลำดับที่ส่งมา)"""
    room_id, owner, _ = await _make_room(db_pool, 4)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[3, 1, 4, 2])

    assert await _rows(db_pool, activity_id) == {
        3: ("confirmed", None),
        1: ("confirmed", None),
        4: ("waitlisted", 1),
        2: ("waitlisted", 2),
    }
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT capacity FROM activities WHERE id = $1", activity_id) == 2


async def test_create_activity_seat_plan_written_to_audit_log(db_pool):
    """audit ต้องบอกความจุ ไม่ใช่ปล่อยให้ย้อนดูไม่ได้ว่าทำไมใครไปอยู่คิว"""
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2])

    async with db_pool.acquire() as conn:
        new_values = await conn.fetchval(
            "SELECT new_values FROM audit_logs "
            "WHERE entity_type = 'ACTIVITY' AND entity_id = $1 AND action = 'CREATE' ORDER BY id DESC LIMIT 1",
            str(activity_id),
        )
    data = json.loads(new_values) if isinstance(new_values, str) else new_values
    assert data["capacity"] == 1


# ================================================================
# ➕ เพิ่มผู้เข้าร่วมทีละคน / หลายคน
# ================================================================

async def test_add_participant_beyond_capacity_goes_to_waitlist(db_pool):
    """เพิ่มคนที่ 3 ทั้งที่ความจุ 2 → ไม่ error แต่ได้ waitlisted + เลขคิว 1"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[1, 2])

    result = await _add(db_pool, room_id, owner, activity_id, 3)

    assert result["participant_status"] == "waitlisted"
    assert result["queue_position"] == 1
    assert (await _rows(db_pool, activity_id))[3] == ("waitlisted", 1)

    async with db_pool.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT new_values FROM audit_logs WHERE entity_type = 'ACTIVITY_PARTICIPANT' "
            "AND entity_id = $1 AND endpoint_or_command = 'add_participant' ORDER BY id DESC LIMIT 1",
            str(result["participant_id"]),
        )
    data = json.loads(audit["new_values"]) if isinstance(audit["new_values"], str) else audit["new_values"]
    assert data["status"] == "waitlisted"
    assert data["queue_position"] == 1
    assert data["requested_status"] == "confirmed"  # ผู้ใช้ขอ confirmed แต่เต็มแล้ว


async def test_batch_add_beyond_capacity_splits_and_numbers_queue(db_pool):
    """batch เพิ่ม 4 คนเข้าความจุ 2 → 2 confirmed + 2 waitlisted เรียงคิว 1,2"""
    room_id, owner, _ = await _make_room(db_pool, 4)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[])

    result = await ActivityService.batch_add_participants(
        pool=db_pool,
        activity_id=activity_id,
        items=[{"student_no": no} for no in (1, 2, 3, 4)],
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
    )

    assert [(a["student_no"], a["participant_status"], a["queue_position"]) for a in result["added"]] == [
        (1, "confirmed", None),
        (2, "confirmed", None),
        (3, "waitlisted", 1),
        (4, "waitlisted", 2),
    ]
    assert await _rows(db_pool, activity_id) == {
        1: ("confirmed", None),
        2: ("confirmed", None),
        3: ("waitlisted", 1),
        4: ("waitlisted", 2),
    }


# ================================================================
# ⬆️ เลื่อนคิว: ยกเลิก / ลบ / เปลี่ยนสถานะ
# ================================================================

async def test_remove_confirmed_promotes_head_of_queue_and_notifies(db_pool):
    """ลบคนที่ได้ที่นั่ง → คนหัวคิวเลื่อนขึ้น + ได้แจ้งเตือนในระบบ (transaction เดียวกัน)"""
    room_id, owner, students = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2, 3])
    rows = await _rows(db_pool, activity_id)
    assert rows[1] == ("confirmed", None) and rows[2] == ("waitlisted", 1)

    async with db_pool.acquire() as conn:
        pid_1 = await conn.fetchval(
            "SELECT ap.id FROM activity_participants ap JOIN students s ON s.id = ap.student_id "
            "WHERE ap.activity_id = $1 AND s.student_no = 1",
            activity_id,
        )

    result = await ActivityService.remove_participant(
        pool=db_pool,
        activity_id=activity_id,
        participant_id=pid_1,
        user_name="ผู้ดูแล",
        user_id=owner,
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
    )

    assert [p["student_no"] for p in result["promoted"]] == [2]
    rows = await _rows(db_pool, activity_id)
    assert rows[2] == ("confirmed", None)
    assert rows[3] == ("waitlisted", 1)  # เลขคิวถูกอัดใหม่ ไม่มีรู

    # 🔔 แจ้งเตือนถึงเจ้าของคิวที่เพิ่งเลื่อนขึ้น
    promoted_user = students[1][1]
    async with db_pool.acquire() as conn:
        note = await conn.fetchrow(
            "SELECT group_type, type, title, entity_type, entity_id, url FROM notifications "
            "WHERE user_id = $1 ORDER BY id DESC LIMIT 1",
            promoted_user,
        )
    assert note is not None
    assert note["group_type"] == "activity"
    assert note["type"] == "activity_waitlist_promoted"
    assert note["entity_id"] == str(activity_id)
    assert note["url"] == f"/activities/{activity_id}"


async def test_cancel_status_promotes_head_of_queue(db_pool):
    """เปลี่ยนสถานะเป็น cancelled (ไม่ลบแถว) → ที่นั่งว่าง → คิวเลื่อน"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2, 3])

    async with db_pool.acquire() as conn:
        pid_1 = await conn.fetchval(
            "SELECT ap.id FROM activity_participants ap JOIN students s ON s.id = ap.student_id "
            "WHERE ap.activity_id = $1 AND s.student_no = 1",
            activity_id,
        )

    result = await ActivityService.update_participant_status(
        pool=db_pool,
        activity_id=activity_id,
        participant_id=pid_1,
        status="cancelled",
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
    )

    assert [p["student_no"] for p in result["promoted"]] == [2]
    rows = await _rows(db_pool, activity_id)
    assert rows[1] == ("cancelled", None)
    assert rows[2] == ("confirmed", None)
    assert rows[3] == ("waitlisted", 1)


async def test_promoting_waitlisted_into_full_activity_is_rejected(db_pool):
    """ดึงคนจากคิวขึ้นทั้งที่ไม่มีที่นั่งว่าง → 400 (ไม่ปล่อยให้เกินความจุเงียบ ๆ)"""
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2])

    async with db_pool.acquire() as conn:
        pid_2 = await conn.fetchval(
            "SELECT ap.id FROM activity_participants ap JOIN students s ON s.id = ap.student_id "
            "WHERE ap.activity_id = $1 AND s.student_no = 2",
            activity_id,
        )

    with pytest.raises(ValidationError, match="เต็ม"):
        await ActivityService.update_participant(
            pool=db_pool,
            activity_id=activity_id,
            participant_id=pid_2,
            update_data={"status": "confirmed"},
            user_name="ผู้ดูแล",
            client_source="WEB_APP",
            actor_identifier="user_id:1",
            room_id=room_id,
            actor_user_id=owner,
        )

    assert (await _rows(db_pool, activity_id))[2] == ("waitlisted", 1)


async def test_batch_cancel_frees_all_seats_and_promotes_queue(db_pool):
    """batch ยกเลิกกลุ่มใหญ่ → เลื่อนคิวเท่าที่นั่งว่างจริง (ไม่ปล่อยที่นั่งค้าง)"""
    room_id, owner, _ = await _make_room(db_pool, 4)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[1, 2, 3, 4])

    async with db_pool.acquire() as conn:
        pids = {
            row["student_no"]: row["id"]
            for row in await conn.fetch(
                "SELECT ap.id, s.student_no FROM activity_participants ap "
                "JOIN students s ON s.id = ap.student_id WHERE ap.activity_id = $1",
                activity_id,
            )
        }

    result = await ActivityService.batch_update_participants(
        pool=db_pool,
        activity_id=activity_id,
        items=[
            {"participant_id": pids[1], "status": "cancelled"},
            {"participant_id": pids[2], "status": "cancelled"},
        ],
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
    )

    assert sorted(p["student_no"] for p in result["promoted"]) == [3, 4]
    assert await _rows(db_pool, activity_id) == {
        1: ("cancelled", None),
        2: ("cancelled", None),
        3: ("confirmed", None),
        4: ("confirmed", None),
    }


# ================================================================
# 📝 แทนที่ทั้งชุด (PATCH กิจกรรม) — ห้ามเกินเพดาน และห้ามลดคนที่มาแล้ว
# ================================================================

async def test_reconcile_over_capacity_demotes_newest_confirmed(db_pool):
    """PATCH ส่งรายชื่อเกินความจุ → คนที่ถูกเพิ่มใหม่สุดลงคิว ไม่ใช่เด้งคนเดิมออก"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1])

    await ActivityService.update_activity(
        pool=db_pool,
        activity_id=activity_id,
        update_data={},
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
        participants=[{"student_no": 1}, {"student_no": 2}, {"student_no": 3}],
    )

    rows = await _rows(db_pool, activity_id)
    assert rows[1] == ("confirmed", None)
    assert rows[2] == ("waitlisted", 1)
    assert rows[3] == ("waitlisted", 2)


async def test_reconcile_never_demotes_attended(db_pool):
    """`attended` คือข้อเท็จจริงที่เกิดแล้ว — ต้องไม่ถูกย้ายลงคิวแม้เกินความจุ"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2])

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE activity_participants ap SET status = 'attended' "
            "FROM students s WHERE s.id = ap.student_id AND ap.activity_id = $1 AND s.student_no = 1",
            activity_id,
        )

    await ActivityService.update_activity(
        pool=db_pool,
        activity_id=activity_id,
        update_data={},
        user_name="ผู้ดูแล",
        client_source="WEB_APP",
        actor_identifier="user_id:1",
        room_id=room_id,
        actor_user_id=owner,
        participants=[
            {"student_no": 1, "status": "attended"},
            {"student_no": 2, "status": "confirmed"},
            {"student_no": 3, "status": "confirmed"},
        ],
    )

    rows = await _rows(db_pool, activity_id)
    assert rows[1] == ("attended", None)
    # seated = 3 (attended + confirmed 2 คน) เกินความจุ 1 ⇒ ลดเฉพาะ confirmed ใหม่สุด
    assert rows[3][0] == "waitlisted"
    assert rows[2][0] in ("confirmed", "waitlisted")


# ================================================================
# 🔧 แก้ความจุ (PATCH)
# ================================================================

async def test_patch_capacity_below_seated_is_rejected(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=3, participant_nos=[1, 2])

    with pytest.raises(ValidationError, match="น้อยกว่าจำนวนผู้เข้าร่วมที่ยืนยันแล้ว"):
        await ActivityService.update_activity(
            pool=db_pool, activity_id=activity_id, update_data={"capacity": 1},
            user_name="ผู้ดูแล", client_source="WEB_APP", actor_identifier="user_id:1",
            room_id=room_id, actor_user_id=owner,
        )

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT capacity FROM activities WHERE id = $1", activity_id) == 3


async def test_patch_capacity_up_promotes_waitlist(db_pool):
    """เพิ่มความจุ 1 → 3 → คนในคิวต้องเลื่อนขึ้นทันที (ที่นั่งว่างต้องไม่ค้าง)"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2, 3])
    assert (await _rows(db_pool, activity_id))[2] == ("waitlisted", 1)

    await ActivityService.update_activity(
        pool=db_pool, activity_id=activity_id, update_data={"capacity": 3},
        user_name="ผู้ดูแล", client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )

    assert await _rows(db_pool, activity_id) == {
        1: ("confirmed", None), 2: ("confirmed", None), 3: ("confirmed", None),
    }


async def test_patch_capacity_zero_removes_limit(db_pool):
    """capacity = 0 คือ "ยกเลิกเพดาน" → NULL และคิวถูกล้าง"""
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2, 3])

    await ActivityService.update_activity(
        pool=db_pool, activity_id=activity_id, update_data={"capacity": 0},
        user_name="ผู้ดูแล", client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT capacity FROM activities WHERE id = $1", activity_id) is None
    assert await _rows(db_pool, activity_id) == {
        1: ("confirmed", None), 2: ("confirmed", None), 3: ("confirmed", None),
    }


# ================================================================
# 📋 ลิสต์กิจกรรม — ตัวเลขที่นั่ง/คิวมาจาก SQL (ไม่ต้องดึงผู้เข้าร่วมทั้งหมด)
# ================================================================

async def test_list_activities_exposes_confirmed_and_waitlisted_counts(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 4)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[1, 2, 3, 4])

    items = await ActivityService.list_activities(
        pool=db_pool, client_source="WEB_APP", actor_identifier="user_id:1",
        room_id=room_id, user_id=owner,
    )

    item = next(a for a in items if a["id"] == activity_id)
    assert item["capacity"] == 2
    assert item["confirmed_count"] == 2
    assert item["waitlisted_count"] == 2


async def test_get_activity_exposes_counts_from_participants(db_pool):
    room_id, owner, _ = await _make_room(db_pool, 3)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=1, participant_nos=[1, 2, 3])

    detail = await ActivityService.get_activity(
        pool=db_pool, activity_id=activity_id, client_source="WEB_APP",
        actor_identifier="user_id:1", room_id=room_id, user_id=owner,
    )

    assert detail["capacity"] == 1
    assert detail["confirmed_count"] == 1
    assert detail["waitlisted_count"] == 2
    assert detail["participant_count"] == 3
    queued = [p for p in detail["participants"] if p["status"] == "waitlisted"]
    assert [p["queue_position"] for p in queued] == [1, 2]


# ================================================================
# 🌐 HTTP — ลดความจุต่ำกว่าคนที่ยืนยันแล้วต้องได้ 400 ไม่ใช่ 500
# ================================================================

async def test_http_patch_capacity_below_seated_returns_400(client, db_pool):
    room_id, owner, _ = await _make_room(db_pool, 2)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[1, 2])

    resp = client.patch(
        f"/api/classroom/{room_id}/activities/{activity_id}?target_type=room",
        json={"capacity": 1, "user_name": "ผู้ดูแล"},
        headers=_web_headers(owner),
    )

    assert resp.status_code == 400
    assert "น้อยกว่าจำนวนผู้เข้าร่วมที่ยืนยันแล้ว" in resp.json()["detail"]


# ================================================================
# 🏃 Concurrency — DoD: capacity ต้องไม่เพี้ยนเมื่อมีคำขอพร้อมกัน
# ================================================================

async def test_concurrent_adds_never_exceed_capacity(db_pool):
    """เพิ่ม 5 คนพร้อมกันเข้าความจุ 2 → confirmed 2 · waitlisted 3 · เลขคิว 1..3 ไม่ซ้ำ"""
    room_id, owner, _ = await _make_room(db_pool, 5)
    activity_id = await _create_activity(db_pool, room_id, owner, capacity=2, participant_nos=[])

    results = await asyncio.gather(
        *[_add(db_pool, room_id, owner, activity_id, no) for no in range(1, 6)],
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"คำขอที่ควรสำเร็จกลับ error: {errors}"

    rows = await _rows(db_pool, activity_id)
    assert len(rows) == 5
    confirmed = [no for no, (st, _q) in rows.items() if st == "confirmed"]
    waitlisted = {no: q for no, (st, q) in rows.items() if st == "waitlisted"}

    assert len(confirmed) == 2, f"confirmed เกินความจุ: {rows}"
    assert len(waitlisted) == 3
    assert sorted(waitlisted.values()) == [1, 2, 3], f"เลขคิวต้องต่อเนื่องไม่ซ้ำ: {waitlisted}"

    async with db_pool.acquire() as conn:
        seated = await conn.fetchval(
            "SELECT COUNT(*) FROM activity_participants "
            "WHERE activity_id = $1 AND deleted_at IS NULL AND status IN ('confirmed', 'attended')",
            activity_id,
        )
    assert seated == 2
