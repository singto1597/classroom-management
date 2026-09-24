"""
H4 — `GET /{target_id}/students` ต้องให้อ่านรายชื่อเฉพาะสมาชิกที่ **`status = 'active'`**

## บั๊กที่เทสต์ชุดนี้ล็อก (พบจากการตรวจระบบ 2026-09-23)

`StudentService.get_all_students` เช็คสมาชิกด้วย

    SELECT 1 FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL

**ไม่มี `status`** ⇒ แถว `status = 'pending'` (คำเชิญที่ยังไม่รับ — มี `user_id` ผูกอยู่แล้ว
แต่ `identity_claimed = FALSE` ดู `RoomManagementService.accept_invite`) ผ่านด่านนี้ได้
⇒ คนที่แค่ "ถูกเชิญ" อ่าน **รายชื่อทั้งห้อง** ได้ ทั้งที่ยังไม่ได้เป็นสมาชิก

ที่สำคัญ route นี้ **ไม่มี `require_permission` ครอบ** (ดู `routers/student_router.py:132`)
⇒ การเช็คใน service คือด่านเดียวที่มีจริง ๆ ไม่มีชั้นอื่นรับอีก

## ทำไมการกรองนี้ไม่พังเส้นทาง invite

`/students/me` (`get_student_by_user_id`) **ไม่ถูกแก้โดยเจตนา** — มัน match ด้วย `u.id = $2`
จึงคืนได้แค่แถวของเจ้าตัวเอง (ไม่ใช่ข้อมูลคนอื่น) และผู้ถูกเชิญอาจต้องเห็นสถานะคำเชิญของตัวเอง
⇒ เทสต์ข้อสุดท้ายล็อกพฤติกรรมนี้ไว้ ไม่ให้มีใครเผลอ "แก้ให้สอดคล้องกัน" แล้วทำ invite พัง

Pattern ตาม docs/rules/testing.md: randomized discord_id, deep-DB verify, ไม่แตะ Redis
(ห้องที่สร้างไม่ผูก `server_id` ⇒ `ActionService._add_transaction` ไม่ถูกเรียกเลย)
"""
import random
import string
import uuid

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


# === Helpers ===


async def _insert_user(pool, *, first_name="Test", last_name="User") -> tuple[int, int]:
    """คืน `(user_id, discord_id)` — discord_id สุ่ม 7 หลักตามกฎห้าม hardcode ID"""
    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            first_name, last_name, f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
    return user_id, discord_id


async def _insert_room(pool, owner_id: int) -> int:
    """สร้างห้อง + เจ้าของเป็นสมาชิก `active` (สิทธิ์ `["all"]` เหมือนผู้สร้างห้องจริง)"""
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            "Test Room", code, owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, identity_claimed)
            VALUES ($1, $2, 1, 'president', 'active', TRUE, '["all"]'::jsonb, TRUE)
            """,
            room_id, owner_id,
        )
    return room_id


async def _add_member(
    pool, room_id: int, student_no: int, *, status: str, added_by: int | None = None
) -> tuple[int, int]:
    """เพิ่มสมาชิก 1 คนพร้อมบัญชี `users` ของเขา

    ⚠️ ชื่อ-นามสกุล **ไม่ได้อยู่บน `students`** — `BASE_STUDENT_SELECT` ดึงมาจาก `users`
       ผ่าน `LEFT JOIN users u ON s.user_id = u.id` ⇒ ถ้าสร้างแถว `students` ลอย ๆ
       โดยไม่มี `user_id` รายชื่อจะได้ `first_name = NULL` ซึ่งไม่เหมือนข้อมูลจริง

    - `status='active'` → สมาชิกเต็มตัว (สิทธิ์ `'[]'` โดยเจตนา — อยากพิสูจน์ว่า
      route นี้ไม่ต้องมี permission ใด ๆ แค่เป็นสมาชิกก็พอ)
    - `status='pending'` → คำเชิญที่ยังไม่รับ (`identity_claimed=FALSE`)
    """
    user_id, discord_id = await _insert_user(
        pool, first_name="Student", last_name=f"No{student_no}"
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, identity_claimed, added_by)
            VALUES ($1, $2, $3, 'student', $4, $5, $6)
            """,
            room_id, user_id, student_no, status, status == "active", added_by,
        )
    return user_id, discord_id


def _headers(discord_id: int) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


def _roster_url(room_id: int) -> str:
    return f"/api/classroom/{room_id}/students?target_type=room"


# === เทสต์ ===


async def test_pending_invitee_is_denied_the_roster(client, db_pool):
    """🔴 หัวใจของ H4 — 'ถูกเชิญ' ไม่เท่ากับ 'เป็นสมาชิก'"""
    owner_id, _ = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner_id)
    for no in range(2, 5):
        await _add_member(db_pool, room_id, no, status="active")
    _, invitee_discord = await _add_member(
        db_pool, room_id, 5, status="pending", added_by=owner_id
    )

    resp = client.get(_roster_url(room_id), headers=_headers(invitee_discord))

    assert resp.status_code == 403, resp.text

    # deep-DB verify: แถวยังอยู่จริงและยังเป็น pending (ไม่ได้ถูกลบ/เปลี่ยนสถานะโดยเทสต์)
    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM students WHERE room_id = $1 AND student_no = 5", room_id
        )
    assert status == "pending"


async def test_active_member_still_sees_the_full_roster(client, db_pool):
    """กัน over-filtering — สมาชิก active ต้องเห็นรายชื่อครบเหมือนเดิม"""
    owner_id, owner_discord = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner_id)
    for no in range(2, 5):
        await _add_member(db_pool, room_id, no, status="active")

    resp = client.get(_roster_url(room_id), headers=_headers(owner_discord))

    assert resp.status_code == 200, resp.text
    assert sorted(row["student_no"] for row in resp.json()) == [1, 2, 3, 4]


async def test_invitee_gains_access_after_accepting(client, db_pool):
    """🔑 ตัวตัดสิน — พิสูจน์ว่าด่านนี้ผูกกับ `status` ไม่ใช่ `identity_claimed` หรืออย่างอื่น

    ถ้าวันหนึ่งมีคนเผลอเปลี่ยนไปเช็ค `identity_claimed` หรือเพิ่มเงื่อนไขอื่น
    เทสต์นี้จะจับได้ เพราะมันเดินเส้นทาง invite → accept จริง
    """
    owner_id, _ = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner_id)
    await _add_member(db_pool, room_id, 2, status="active")
    user_id, discord_id = await _add_member(
        db_pool, room_id, 3, status="pending", added_by=owner_id
    )

    # 1) ยังไม่รับคำเชิญ → ห้ามอ่าน
    assert client.get(_roster_url(room_id), headers=_headers(discord_id)).status_code == 403

    # 2) กดรับคำเชิญ (เส้นทางเดียวกับ RoomManagementService.accept_invite)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE students SET status = 'active', identity_claimed = TRUE WHERE user_id = $1 AND room_id = $2",
            user_id, room_id,
        )

    # 3) รับแล้ว → อ่านได้
    resp = client.get(_roster_url(room_id), headers=_headers(discord_id))
    assert resp.status_code == 200, resp.text
    assert sorted(row["student_no"] for row in resp.json()) == [1, 2, 3]


async def test_pending_invitee_can_still_read_own_profile(client, db_pool):
    """เอกสารพฤติกรรมที่ **ตั้งใจคงไว้** — ผู้ถูกเชิญเห็นโปรไฟล์ตัวเองได้

    `/students/me` match ด้วย `u.id = $2` ⇒ คืนได้แค่แถวของเจ้าตัว (ไม่ใช่ข้อมูลคนอื่น)
    และขั้นตอนรับคำเชิญต้องให้เขาเห็นว่ากำลังจะเข้าร่วมห้องไหน
    ⚠️ ถ้ามีใครเพิ่ม `status = 'active'` ที่นี่ด้วย "เพื่อความสอดคล้อง" เทสต์นี้จะเตือน
    """
    owner_id, _ = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner_id)
    _, invitee_discord = await _add_member(
        db_pool, room_id, 5, status="pending", added_by=owner_id
    )

    resp = client.get(
        f"/api/classroom/{room_id}/students/me?target_type=room",
        headers=_headers(invitee_discord),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["student_no"] == 5
