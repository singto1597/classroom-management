"""
Integration tests — สรุปหน้าหลัก (`routers/home_router.py`, P3)

สิ่งที่ล็อกไว้:
  1. **ตัวเลขทุกก้อนนับด้วย predicate เดียวกับลิสต์ปลายทาง** — งานค้าง/วันนี้/เลยกำหนด
     แยกจาก `done` และจากงานที่ `deleted_at` แล้ว
  2. **ตัวอย่างไม่ใช่ความยาวของตัวเลข** — `items` มีเพดาน 3 แต่ `pending_total` นับทั้งหมด
  3. **"วันนี้" คือวันที่ไทย** — งานที่ครบกำหนดวันนี้ตาม Bangkok ต้องถูกนับ แม้ UTC จะยังเป็นเมื่อวาน
  4. **การเงินเป็นของตัวเองเท่านั้น** — บิลของเพื่อนไม่ถูกรวมในยอดของฉัน
  5. **ไม่มีแถวนักเรียน = has_profile False** ไม่ใช่ 403 (แอดมินยังเปิดหน้าหลักได้)
  6. **ประกาศที่ยังไม่อ่าน = แถวแจ้งเตือนของผู้ใช้เอง** และใบที่เก็บถาวรแล้วไม่ถูกนับ
  7. **คนนอกห้อง 403** แม้จะถือ JWT ที่ยังไม่หมดอายุ

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
ไม่ hardcode id และสุ่มรหัสห้องทุกครั้ง
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio

THAI_TZ = ZoneInfo("Asia/Bangkok")
THAI_DAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")


def _today() -> date:
    return datetime.now(THAI_TZ).date()


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _insert_user(pool, first_name: str = "Test", last_name: str = "User") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            f"{uuid.uuid4().hex[:12]}@example.com",
            first_name,
            last_name,
            f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('Test Room', $1, $2) RETURNING id",
            code,
            owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)
            """,
            room_id,
            owner_id,
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)
            RETURNING id
            """,
            room_id,
            user_id,
            student_no,
        )


async def _insert_task(pool, room_id: int, name: str, due: date, status: str = "pending") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO tasks (room_id, task_name, due_date, status) VALUES ($1, $2, $3, $4) RETURNING id",
            room_id,
            name,
            due,
            status,
        )


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int, path: str = "/home/summary") -> str:
    return f"/api/classroom/{room_id}{path}?target_type=room"


# ── 1–2. งาน ────────────────────────────────────────────────────────────────
async def test_task_counts_match_the_list_predicate(client, db_pool):
    owner = await _insert_user(db_pool, "สมชาย", "ใจดี")
    room_id = await _insert_room(db_pool, owner)
    today = _today()

    await _insert_task(db_pool, room_id, "งานวันนี้ A", today)
    await _insert_task(db_pool, room_id, "งานวันนี้ B", today)
    await _insert_task(db_pool, room_id, "เลยกำหนด", today - timedelta(days=2))
    await _insert_task(db_pool, room_id, "งานอนาคต", today + timedelta(days=3))
    # งานที่เสร็จแล้วไม่ถูกนับในก้อนไหน (การ์ดทุกใบพาไปที่ filter=pending/today/overdue)
    await _insert_task(db_pool, room_id, "เสร็จแล้ว", today, status="done")
    # งานที่ถูกลบ (soft delete) ต้องไม่ถูกนับ
    deleted_id = await _insert_task(db_pool, room_id, "ถูกลบ", today)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET deleted_at = NOW() WHERE id = $1", deleted_id)

    response = client.get(_api(room_id), headers=_headers(owner))
    assert response.status_code == 200, response.text
    body = response.json()

    # 4 งานค้าง + 1 งานเสร็จ = 5 (งานที่ soft-delete แล้วไม่ถูกนับในก้อนไหนเลย)
    assert body["tasks"]["total"] == 5
    assert body["tasks"]["pending_total"] == 4
    assert body["tasks"]["due_today"] == 2
    assert body["tasks"]["overdue"] == 1

    items = body["tasks"]["items"]
    assert [item["task_name"] for item in items][0] == "เลยกำหนด", "เรียงตามกำหนดส่ง ใกล้ก่อน"
    assert len(items) == 3, "ตัวอย่างมีเพดาน 3 รายการ แต่ตัวเลขยังนับทั้งหมด"


# ── 3. วันนี้ตามเวลาไทย ────────────────────────────────────────────────────
async def test_today_uses_bangkok_date(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    today = _today()

    await _insert_task(db_pool, room_id, "กำหนดวันนี้", today)

    body = client.get(_api(room_id), headers=_headers(owner)).json()
    assert body["today"] == today.isoformat()
    assert body["tasks"]["due_today"] == 1
    assert body["tasks"]["overdue"] == 0


# ── 4. โน้ต / กิจกรรม / ตาราง ──────────────────────────────────────────────
async def test_note_activities_and_schedule(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    today = _today()
    day_name = THAI_DAYS[today.weekday()]

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO daily_notes (room_id, target_date, bring_items, announcement) VALUES ($1, $2, $3, $4)",
            room_id,
            today,
            "สมุด + ดินสอ",
            "พรุ่งนี้เลิกเร็ว",
        )
        await conn.execute(
            "INSERT INTO default_schedules (room_id, day_of_week, attire, subjects) VALUES ($1, $2, $3, $4)",
            room_id,
            day_name,
            "ชุดนักเรียน",
            "คณิต · วิทย์",
        )
        await conn.execute(
            "INSERT INTO schedule_overrides (room_id, target_date, new_attire, note) VALUES ($1, $2, $3, $4)",
            room_id,
            today,
            "ชุดพละ",
            "ซ้อมกีฬาสี",
        )
        # กิจกรรม: เปิดรับวันนี้ · อนาคต · ผ่านไปแล้ว · ยกเลิก
        await conn.execute(
            "INSERT INTO activities (room_id, title, activity_date, status, base_hours, created_by) VALUES ($1, $2, $3, 'upcoming', 3.5, 't')",
            room_id,
            "วันนี้",
            today,
        )
        await conn.execute(
            "INSERT INTO activities (room_id, title, activity_date, status, base_hours, created_by) VALUES ($1, $2, $3, 'upcoming', 2, 't')",
            room_id,
            "อีกสัปดาห์",
            today + timedelta(days=7),
        )
        await conn.execute(
            "INSERT INTO activities (room_id, title, activity_date, status, base_hours, created_by) VALUES ($1, $2, $3, 'upcoming', 1, 't')",
            room_id,
            "ผ่านไปแล้ว",
            today - timedelta(days=1),
        )
        await conn.execute(
            "INSERT INTO activities (room_id, title, activity_date, status, base_hours, created_by) VALUES ($1, $2, $3, 'cancelled', 1, 't')",
            room_id,
            "ยกเลิก",
            today + timedelta(days=2),
        )

    body = client.get(_api(room_id), headers=_headers(owner)).json()

    assert body["note"] == {"bring_items": "สมุด + ดินสอ", "announcement": "พรุ่งนี้เลิกเร็ว"}
    assert [a["title"] for a in body["activities"]] == ["วันนี้", "อีกสัปดาห์"]
    assert body["activities"][0]["base_hours"] == 3.5

    assert body["schedule"]["day_of_week"] == day_name
    assert body["schedule"]["attire"] == "🚨 ชุดพละ (กรณีพิเศษ)"
    assert body["schedule"]["subjects"] == "คณิต · วิทย์"
    assert body["schedule"]["override_note"] == "ซ้อมกีฬาสี"


async def test_note_is_null_when_absent(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    body = client.get(_api(room_id), headers=_headers(owner)).json()
    assert body["note"] is None
    assert body["activities"] == []


# ── 5. การเงินของฉันเท่านั้น ──────────────────────────────────────────────
async def test_finance_counts_only_my_pending_bills(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    me = await _insert_user(db_pool, "ฉัน", "เอง")
    friend = await _insert_user(db_pool, "เพื่อน", "ข้างห้อง")
    my_student_id = await _insert_student(db_pool, room_id, me, 1)
    friend_student_id = await _insert_student(db_pool, room_id, friend, 2)

    async with db_pool.acquire() as conn:
        # ⚠️ unique index `idx_student_payments_active` = 1 แถวต่อ (collection, student)
        # ⇒ "สองบิลของฉัน" ต้องเป็นสองรายการเก็บเงิน ไม่ใช่สองแถวในรายการเดียวกัน
        term_id = await conn.fetchval(
            "INSERT INTO fee_collections (room_id, title, amount, status) VALUES ($1, 'ค่าเทอม', 500, 'active') RETURNING id",
            room_id,
        )
        trip_id = await conn.fetchval(
            "INSERT INTO fee_collections (room_id, title, amount, status) VALUES ($1, 'ค่าทัศนศึกษา', 500, 'active') RETURNING id",
            room_id,
        )
        await conn.execute(
            "INSERT INTO student_payments (collection_id, student_id, status, paid_amount) VALUES ($1, $2, 'pending', 200)",
            term_id,
            my_student_id,
        )
        await conn.execute(
            "INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, 'pending')",
            trip_id,
            my_student_id,
        )
        # บิลของเพื่อน — ต้องไม่หลุดเข้ามาในยอดของฉัน
        await conn.execute(
            "INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, 'pending')",
            term_id,
            friend_student_id,
        )

    body = client.get(_api(room_id), headers=_headers(me)).json()
    assert body["finance"]["has_profile"] is True
    # 500-200 + 500 = 800 (ของเพื่อนอีก 500 ไม่ถูกนับ)
    assert body["finance"]["outstanding"] == 800.0
    assert body["finance"]["unpaid_bills"] == 2


async def test_finance_without_student_profile_is_not_an_error(client, db_pool, monkeypatch):
    """แอดมินที่ไม่มีแถวนักเรียนยังเปิดหน้าหลักได้ — ต้องได้ has_profile False ไม่ใช่ 404

    🔑 คนที่ไม่ใช่สมาชิกผ่าน `require_member` ได้ทางเดียวคือ SUPER_ADMIN (bypass)
    ⇒ ต้องตั้ง SUPER_ADMIN_ID ให้เป็นผู้ใช้คนนี้ก่อน ไม่งั้นจะได้ 403 ไม่ใช่ 200
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    monkeypatch.setattr(settings, "SUPER_ADMIN_ID", owner)
    # ลบแถว students ของเจ้าของออก เพื่อจำลอง "ผู้ดูแลที่ไม่ได้อยู่ในทะเบียนนักเรียน"
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM students WHERE room_id = $1", room_id)

    response = client.get(_api(room_id), headers=_headers(owner))
    assert response.status_code == 200, response.text
    assert response.json()["finance"] == {
        "has_profile": False,
        "outstanding": 0.0,
        "unpaid_bills": 0,
    }


# ── 6. ประกาศยังไม่อ่าน ───────────────────────────────────────────────────
async def test_unread_announcements_count(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    reader = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, reader, 1)

    async with db_pool.acquire() as conn:
        unread_id = await conn.fetchval(
            "INSERT INTO announcements (room_id, title, body, created_by) VALUES ($1, 'ยังไม่อ่าน', '', $2) RETURNING id",
            room_id,
            owner,
        )
        read_id = await conn.fetchval(
            "INSERT INTO announcements (room_id, title, body, created_by) VALUES ($1, 'อ่านแล้ว', '', $2) RETURNING id",
            room_id,
            owner,
        )
        archived_id = await conn.fetchval(
            "INSERT INTO announcements (room_id, title, body, archived_at, created_by) VALUES ($1, 'เก็บถาวร', '', NOW(), $2) RETURNING id",
            room_id,
            owner,
        )
        for announcement_id, read_at in (
            (unread_id, None),
            (read_id, "NOW()"),
            (archived_id, None),
        ):
            await conn.execute(
                """
                INSERT INTO notifications
                    (room_id, user_id, group_type, type, title, entity_type, entity_id, read_at)
                VALUES ($1, $2, 'announcement', 'announcement', 'ประกาศ', 'announcement', $3,
                        CASE WHEN $4 = 'NOW()' THEN NOW() ELSE NULL END)
                """,
                room_id,
                reader,
                str(announcement_id),
                read_at,
            )

    body = client.get(_api(room_id), headers=_headers(reader)).json()
    # ยังไม่อ่าน 1 ใบ (ใบเก็บถาวรไม่นับ) และแถวของตัวเองเท่านั้น
    assert body["announcements"]["unread_count"] == 1


# ── 7. คนนอกห้อง ───────────────────────────────────────────────────────────
async def test_outsider_gets_403(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, "คนนอก", "ห้อง")

    response = client.get(_api(room_id), headers=_headers(outsider))
    assert response.status_code == 403
