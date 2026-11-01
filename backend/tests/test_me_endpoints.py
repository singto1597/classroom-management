"""
Integration tests — "ของฉัน" (`routers/home_router.py` · P3.3)

สิ่งที่ล็อกไว้:
  1. ฟีดมีเฉพาะเหตุการณ์ที่ผูกกับผู้ใช้คนนี้ — ใบเสร็จของเพื่อน/กิจกรรมที่ยกเลิกไม่โผล่
  2. **keyset pagination ไม่ซ้ำไม่หาย** — เดินทั้งชุดด้วย limit=2 แล้วได้ครบทุกแถวครั้งเดียว
  3. cursor ผิดรูป = 400 ไม่ใช่ 500
  4. สถิติตัวเลขตรงกับ DB: จ่ายจริง/ค้าง/กิจกรรม/ชั่วโมง — และ `Decimal` ถูก cast เป็น float
  5. งานของห้องถูกแยกชื่อ (`room_*`) ไม่ปนกับ "ของฉัน"
  6. ผู้ใช้ที่ไม่มีแถวนักเรียน (SUPER_ADMIN bypass) = `has_profile: False` + ตัวเลขส่วนตัว 0
  7. คนนอกห้อง 403

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
ไม่ hardcode id และสุ่มรหัสห้องทุกครั้ง
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


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


async def _insert_room(pool, owner_id: int) -> tuple[int, int]:
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
        # 🔑 คืน **student id** ด้วย — ที่อื่นต้องใช้ id นี้ (ไม่ใช่ user id) เป็นเจ้าของ
        #    ใบเสร็จ/ผู้เข้าร่วม/บิล. สองตารางมีลำดับ id แยกกัน ⇒ ใช้แทนกันได้เฉพาะ
        #    ตอนที่ยังไม่มีข้อมูลอื่นใน DB เท่านั้น (เทสต์ที่รันไฟล์เดียวจะไม่จับ)
        owner_student_id = await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)
            RETURNING id
            """,
            room_id,
            owner_id,
        )
        return room_id, owner_student_id


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


async def _insert_task(pool, room_id: int, name: str, status: str = "pending") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO tasks (room_id, task_name, due_date, status) VALUES ($1, $2, $3, $4) RETURNING id",
            room_id,
            name,
            date.today(),
            status,
        )


async def _insert_collection(pool, room_id: int, title: str, amount: float) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO fee_collections (room_id, title, amount, due_date) VALUES ($1, $2, $3, $4) RETURNING id",
            room_id,
            title,
            amount,
            date.today(),
        )


async def _insert_payment(pool, collection_id: int, student_id: int, paid: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
            VALUES ($1, $2, 'pending', $3)
            RETURNING id
            """,
            collection_id,
            student_id,
            paid,
        )


async def _insert_receipt(
    pool,
    room_id: int,
    student_id: int,
    receipt_no: str,
    amount: float,
    event_at: datetime,
    doc_type: str = "receipt",
    status: str = "active",
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_receipts
                (room_id, receipt_no, doc_type, year_be, seq, student_id, amount,
                 paid_total_after, event_at, issued_at, status, deleted_at)
            -- ⚠️ `chk_receipt_voided_is_deleted`: เอกสารที่ไม่ใช่ active ต้องมี deleted_at เสมอ
            --    (การยกเลิก = soft delete ที่ระดับ DB ไม่ใช่แค่เปลี่ยน status)
            -- ⚠️ cast $7 เป็น varchar ทั้งสองที่: `status` (varchar) กับเทียบ 'active' (text)
            --    ทำให้ Postgres สรุปชนิดของพารามิเตอร์เดียวกันขัดกัน (AmbiguousParameterError)
            VALUES ($1, $2, $3, 2569, 1, $4, $5, $5, $6, $6, $7::varchar,
                    CASE WHEN $7::varchar = 'active' THEN NULL ELSE NOW() END)
            RETURNING id
            """,
            room_id,
            receipt_no,
            doc_type,
            student_id,
            amount,
            event_at,
            status,
        )


async def _insert_activity(
    pool, room_id: int, title: str, activity_date: date, description: str = "รายละเอียด"
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO activities (room_id, title, description, activity_date, created_by)
            VALUES ($1, $2, $3, $4, 'tester')
            RETURNING id
            """,
            room_id,
            title,
            description,
            activity_date,
        )


async def _insert_participant(
    pool,
    activity_id: int,
    student_id: int,
    status: str = "confirmed",
    hours: float = 0.0,
    created_at: datetime | None = None,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO activity_participants
                (activity_id, student_id, status, earned_hours, recorded_by, created_at)
            VALUES ($1, $2, $3, $4, 'tester', COALESCE($5, NOW()))
            RETURNING id
            """,
            activity_id,
            student_id,
            status,
            hours,
            created_at,
        )


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int, path: str, query: str = "") -> str:
    base = f"/api/classroom/{room_id}{path}?target_type=room"
    return f"{base}&{query}" if query else base


def _ts(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


# ── 1. ฟีด ─────────────────────────────────────────────────────────────────
async def test_activity_feed_lists_my_payment_and_activity(client, db_pool):
    owner = await _insert_user(db_pool, "เจ้าของ")
    room_id, owner_student = await _insert_room(db_pool, owner)

    collection = await _insert_collection(db_pool, room_id, "ค่าห้อง", 500)
    await _insert_receipt(db_pool, room_id, owner_student, "REC-2569-0001", 500, _ts(2))

    activity_id = await _insert_activity(db_pool, room_id, "ค่ายลูกเสือ", date.today())
    await _insert_participant(db_pool, activity_id, owner_student, hours=4.5)

    body = client.get(_api(room_id, "/me/activity"), headers=_headers(owner)).json()

    assert body["has_more"] is False
    assert body["next_cursor"] is None
    kinds = [item["kind"] for item in body["items"]]
    assert kinds == ["activity", "payment"] or kinds == ["payment", "activity"]
    payment = next(item for item in body["items"] if item["kind"] == "payment")
    assert payment["amount"] == 500.0
    assert payment["reference"] == "REC-2569-0001"
    assert payment["url"] == "/finance/receipts/REC-2569-0001"

    joined = next(item for item in body["items"] if item["kind"] == "activity")
    assert joined["title"] == "ค่ายลูกเสือ"
    assert joined["entity_id"] == activity_id
    assert joined["url"] == f"/activities/{activity_id}"


async def test_activity_feed_excludes_other_students_and_cancelled(client, db_pool):
    owner = await _insert_user(db_pool, "ฉัน")
    room_id, owner_student = await _insert_room(db_pool, owner)
    friend_user = await _insert_user(db_pool, "เพื่อน")
    friend = await _insert_student(db_pool, room_id, friend_user, 2)

    # ของฉัน: 1 กิจกรรมเข้าร่วมจริง + 1 ใบเสร็จ
    my_activity = await _insert_activity(db_pool, room_id, "กิจกรรมของฉัน", date.today())
    await _insert_participant(db_pool, my_activity, owner_student)
    await _insert_receipt(db_pool, room_id, owner_student, "REC-2569-0101", 100, _ts(1))

    # ของเพื่อน: ใบเสร็จ + กิจกรรม (ไม่ควรโผล่ในฟีดฉัน)
    await _insert_receipt(db_pool, room_id, friend, "REC-2569-0102", 999, _ts(1))
    friend_activity = await _insert_activity(db_pool, room_id, "กิจกรรมของเพื่อน", date.today())
    await _insert_participant(db_pool, friend_activity, friend)

    # ของฉันแต่อกเลิก — ต้องไม่โผล่
    cancelled = await _insert_activity(db_pool, room_id, "กิจกรรมที่ยกเลิก", date.today())
    await _insert_participant(db_pool, cancelled, owner_student, status="cancelled")

    body = client.get(_api(room_id, "/me/activity"), headers=_headers(owner)).json()

    ids = {(item["kind"], item["entity_id"]) for item in body["items"]}
    assert ("activity", my_activity) in ids
    assert ("activity", cancelled) not in ids
    assert all(item["title"] != "กิจกรรมของเพื่อน" for item in body["items"])
    assert all(item["reference"] != "REC-2569-0102" for item in body["items"])


async def test_activity_feed_voided_receipt_hidden(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id, owner_student = await _insert_room(db_pool, owner)
    await _insert_receipt(db_pool, room_id, owner_student, "REC-2569-0201", 50, _ts(3))
    await _insert_receipt(
        db_pool, room_id, owner_student, "REC-2569-0202", 70, _ts(2), status="voided"
    )

    body = client.get(_api(room_id, "/me/activity"), headers=_headers(owner)).json()

    refs = [item["reference"] for item in body["items"] if item["kind"] == "payment"]
    assert refs == ["REC-2569-0201"]


# ── 2. แบ่งหน้า ─────────────────────────────────────────────────────────────
async def test_pagination_returns_every_row_exactly_once(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id, owner_student = await _insert_room(db_pool, owner)
    for index in range(5):
        await _insert_receipt(db_pool, room_id, owner_student, f"REC-P-{index}", 10 + index, _ts(index + 1))

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # เพดานกันลูปไม่จบ
        query = f"limit=2&cursor={cursor}" if cursor else "limit=2"
        body = client.get(_api(room_id, "/me/activity", query), headers=_headers(owner)).json()
        seen.extend(item["reference"] for item in body["items"])
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
    else:  # pragma: no cover - กันเทสต์ค้างเงียบ ๆ
        pytest.fail("has_more ไม่เคยเป็น False — pagination ไม่จบ")

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_invalid_cursor_returns_400(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = (await _insert_room(db_pool, owner))[0]

    resp = client.get(
        _api(room_id, "/me/activity", "cursor=not-a-cursor"), headers=_headers(owner)
    )
    assert resp.status_code == 400


# ── 3. สิทธิ์ ───────────────────────────────────────────────────────────────
async def test_non_member_gets_403(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = (await _insert_room(db_pool, owner))[0]
    outsider = await _insert_user(db_pool, "คนนอก")

    for path in ("/me/activity", "/me/stats"):
        resp = client.get(_api(room_id, path), headers=_headers(outsider))
        assert resp.status_code == 403, path


# ── 4. สถิติ ────────────────────────────────────────────────────────────────
async def test_stats_match_database(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id, owner_student = await _insert_room(db_pool, owner)
    friend_user = await _insert_user(db_pool, "เพื่อน")
    friend = await _insert_student(db_pool, room_id, friend_user, 2)

    # บิลของฉัน: A 500 จ่ายบางส่วน 300 (ค้าง 200) · B 500 ยังไม่จ่าย (ค้าง 500) · C 200 จ่ายครบ
    # ⚠️ `idx_student_payments_active` UNIQUE (collection_id, student_id) ⇒ "หนึ่งบิล" ของ
    #    นักเรียน 1 คน = 1 แถว ห้ามจำลองสองบิลด้วยการใส่สองแถวใน collection เดียว
    partial = await _insert_collection(db_pool, room_id, "ค่าทัศนศึกษา", 500)
    await _insert_payment(db_pool, partial, owner_student, paid=300)
    unpaid = await _insert_collection(db_pool, room_id, "ค่าหนังสือ", 500)
    await _insert_payment(db_pool, unpaid, owner_student, paid=0)
    paid_collection = await _insert_collection(db_pool, room_id, "ค่าอุปกรณ์", 200)
    paid_payment = await _insert_payment(db_pool, paid_collection, owner_student, paid=200)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE student_payments SET status = 'paid' WHERE id = $1", paid_payment)

    # เพื่อนมีหนี้ของตัวเอง — ต้องไม่ถูกนับในสถิติฉัน
    await _insert_payment(db_pool, partial, friend, paid=0)

    # ใบเสร็จ: ของฉัน 300 (active) + ใบที่ยกเลิกแล้ว 150 + ของเพื่อน 999
    await _insert_receipt(db_pool, room_id, owner_student, "REC-S-1", 300, _ts(5))
    await _insert_receipt(db_pool, room_id, owner_student, "REC-S-2", 150, _ts(4), status="voided")
    await _insert_receipt(db_pool, room_id, friend, "REC-S-3", 999, _ts(3))

    activity_id = await _insert_activity(db_pool, room_id, "ค่าย", date.today())
    await _insert_participant(db_pool, activity_id, owner_student, hours=3.25)
    second_activity = await _insert_activity(db_pool, room_id, "จิตอาสา", date.today())
    await _insert_participant(db_pool, second_activity, owner_student, hours=1.75)
    cancelled_activity = await _insert_activity(db_pool, room_id, "ยกเลิก", date.today())
    await _insert_participant(db_pool, cancelled_activity, owner_student, hours=9.0, status="cancelled")

    await _insert_task(db_pool, room_id, "งานเสร็จ", status="done")
    await _insert_task(db_pool, room_id, "งานค้าง", status="pending")

    body = client.get(_api(room_id, "/me/stats"), headers=_headers(owner)).json()

    assert body["has_profile"] is True
    assert body["term"] is None
    assert body["paid_total"] == 300.0
    # ค้าง = (500 − 300) + (500 − 0) = 700 ; ใบที่จ่ายครบแล้วไม่นับ
    assert body["outstanding"] == 700.0
    assert body["unpaid_bills"] == 2
    assert body["activities_joined"] == 2
    assert body["activity_hours"] == 5.0
    assert body["room_tasks_done"] == 1
    assert body["room_tasks_pending"] == 1


async def test_stats_without_student_profile_is_not_an_error(client, db_pool, monkeypatch):
    """SUPER_ADMIN bypass ผ่าน require_member ได้โดยไม่มีแถว students

    🔑 คนที่ไม่ใช่สมาชิกผ่าน `require_member` ได้ทางเดียวคือ SUPER_ADMIN (bypass)
    """
    owner = await _insert_user(db_pool)
    room_id = (await _insert_room(db_pool, owner))[0]
    admin_user = await _insert_user(db_pool, "ผู้ดูแลระบบ")
    monkeypatch.setattr(settings, "SUPER_ADMIN_ID", admin_user)

    await _insert_task(db_pool, room_id, "งานค้าง", status="pending")

    body = client.get(_api(room_id, "/me/stats"), headers=_headers(admin_user)).json()

    assert body["has_profile"] is False
    assert body["activities_joined"] == 0
    assert body["paid_total"] == 0.0
    assert body["outstanding"] == 0.0
    # ตัวเลขของห้องยังใช้ได้ — แต่ชื่อบอกชัดว่าไม่ใช่ของฉัน
    assert body["room_tasks_pending"] == 1
