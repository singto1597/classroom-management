"""เทสสำหรับ refactor "ชื่อยึดภาษาอังกฤษเป็นหลัก (English-primary) / ไทยใช้แสดงผล"

ครอบคลุม:
1. dedupe identity ใช้ชื่ออังกฤษก่อน → fallback ไทย NFC (แก้ อำ/อํา match กันไม่เจอ)
2. NFC-normalize ตอนเก็บ (U+0E33 กับ U+0E32+U+0E4D = "ตัวเดียวกัน")
3. search_students ค้นชื่ออังกฤษเจอ
4. update_student / update_user_profile เขียน first_name_en/last_name_en ลง users
"""
import random
import string
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from models.auth_schemas import UserProfileUpdate
from services.auth_service import update_user_profile
from services.student_service import StudentService

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, first_name="Test", last_name="User", **kw) -> int:
    username = kw.pop("username", None) or f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (first_name, last_name, username)
            VALUES ($1, $2, $3) RETURNING id
            """,
            first_name, last_name, username,
        )


async def _insert_room(pool, owner_id: int) -> int:
    """สร้างห้อง + ใส่ owner เป็น admin/president ในห้อง (เหมือน create_room จริง)
    — ไม่งั้น require_permission(MANAGE_STUDENTS) จะโดน ForbiddenError"""
    async with pool.acquire() as conn:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            f"Room {code}", code, owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '["all"]'::jsonb)
            """,
            room_id, owner_id,
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
            room_id, user_id, student_no,
        )


# === 1. English-primary identity ===

async def test_add_student_english_name_is_primary_identity(db_pool):
    """คนที่ชื่ออังกฤษเหมือนกัน (แม้ชื่อไทยต่าง) ต้องเป็น user คนเดียวกัน — อังกฤษคือกุญแจ"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner)
    room_b = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="สมชาย", last_name="ใจดี",
        first_name_en="Somchai", last_name_en="Jaidee",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_a, actor_user_id=owner,
    )
    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="สมชาย", last_name="แซ่ลิ้ม",
        first_name_en="Somchai", last_name_en="Jaidee",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_b, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE first_name_en = 'Somchai' AND last_name_en = 'Jaidee' AND deleted_at IS NULL"
        )
        assert len(users) == 1, "ชื่ออังกฤษเดียวกันต้อง dedupe เป็น user เดียว"
        user_id = users[0]["id"]
        students = await conn.fetch(
            "SELECT id FROM students WHERE user_id = $1", user_id
        )
        assert len(students) == 2, "user เดียวกันผูก 2 ห้อง"


async def test_add_student_with_english_backfills_into_existing_thai_user(db_pool):
    """เพิ่มด้วยชื่อไทยก่อน (ไม่มีอังกฤษ) แล้วเพิ่มซ้ำด้วยไทย+อังกฤษ → ต้องไม่สร้าง user ซ้ำ (fallback ไทย)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner)
    room_b = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="สมชาย", last_name="ใจดี",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_a, actor_user_id=owner,
    )
    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="สมชาย", last_name="ใจดี",
        first_name_en="Somchai", last_name_en="Jaidee",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_b, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE first_name = 'สมชาย' AND last_name = 'ใจดี' AND deleted_at IS NULL"
        )
        assert count == 1, "อังกฤษหาไม่เจอต้อง fallback ไปเจอ user ไทยเดิม ไม่สร้างซ้ำ"


async def test_add_student_writes_english_to_ghost_user(db_pool):
    """ghost user ที่สร้างตอน add_student ต้องเก็บ first_name_en/last_name_en/nickname_en ด้วย"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room = await _insert_room(db_pool, owner)

    await StudentService.add_student(
        pool=db_pool, student_no=5, first_name="สมหญิง", last_name="สวยงาม",
        nickname="หนิง", first_name_en="Somying", last_name_en="Suyngam", nickname_en="Ning",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT first_name_en, last_name_en, nickname, nickname_en FROM users WHERE first_name = 'สมหญิง'"
        )
        assert row["first_name_en"] == "Somying"
        assert row["last_name_en"] == "Suyngam"
        assert row["nickname"] == "หนิง"
        assert row["nickname_en"] == "Ning"


# === 2. NFC normalization (อำ/อํา) ===

async def test_add_student_nfc_normalization_dedupes_thai_composition(db_pool):
    """อำ เขียนแบบ precomposed (U+0E33) กับ decomposed (U+0E32+U+0E4D) ต้อง dedupe เป็นคนเดียวกัน"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner)
    room_b = await _insert_room(db_pool, owner)

    precomposed = "อำ"   # อำ (U+0E33 = สระอำ)
    decomposed = "อาํ"  # อ + า (U+0E32) + นิคหิต (U+0E4D) — เดิม match กันไม่เจอ

    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name=precomposed, last_name="ใจดี",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_a, actor_user_id=owner,
    )
    await StudentService.add_student(
        pool=db_pool, student_no=2, first_name=decomposed, last_name="ใจดี",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room_b, actor_user_id=owner,
    )

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE last_name = 'ใจดี' AND deleted_at IS NULL"
        )
        assert count == 1, f"NFC ต้องทำให้อำ(2 รูปแบบ)เป็นคนเดียวกัน แต่ได้ {count}"


async def test_update_student_normalizes_thai_nfc(db_pool):
    """update_student ต้อง NFC-normalize ชื่อไทยก่อนเขียน (กันเก็บ อำ/อํา ต่างกัน)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room = await _insert_room(db_pool, owner)
    student_user = await _insert_user(db_pool, first_name="Old", last_name="Name")
    await _insert_student(db_pool, room, student_user, student_no=1)

    decomposed = "อาํ"  # อำ (decomposed)
    await StudentService.update_student(
        pool=db_pool, student_no=1,
        update_data={"first_name": decomposed, "last_name": "ใจดี"},
        updater_user_id=owner,
        client_source="test", actor_identifier="test", room_id=room,
    )

    async with db_pool.acquire() as conn:
        stored = await conn.fetchval("SELECT first_name FROM users WHERE id = $1", student_user)
        assert stored == "อำ", "ต้องเก็บเป็น NFC (precomposed U+0E33) ไม่ใช่ decomposed"


# === 3. Search ด้วยชื่ออังกฤษ ===

async def test_search_students_matches_english_name(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room = await _insert_room(db_pool, owner)
    await StudentService.add_student(
        pool=db_pool, student_no=1, first_name="สมชาย", last_name="ใจดี",
        first_name_en="Somchai", last_name_en="Jaidee",
        user_name="Owner", client_source="test", actor_identifier="test",
        room_id=room, actor_user_id=owner,
    )

    results = await StudentService.search_students(
        pool=db_pool, query="Somchai",
        client_source="test", actor_identifier="test", room_id=room, user_id=owner,
    )
    assert len(results) == 1
    assert results[0]["first_name"] == "สมชาย"


# === 4. Update เขียนชื่ออังกฤษ ===

async def test_update_student_writes_english_names(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room = await _insert_room(db_pool, owner)
    student_user = await _insert_user(db_pool, first_name="Somchai", last_name="Jaidee")
    await _insert_student(db_pool, room, student_user, student_no=1)

    await StudentService.update_student(
        pool=db_pool, student_no=1,
        update_data={"first_name_en": "Somchai", "last_name_en": "Jaidee", "nickname_en": "Om"},
        updater_user_id=owner,
        client_source="test", actor_identifier="test", room_id=room,
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT first_name_en, last_name_en, nickname_en FROM users WHERE id = $1", student_user
        )
        assert row["first_name_en"] == "Somchai"
        assert row["last_name_en"] == "Jaidee"
        assert row["nickname_en"] == "Om"


async def test_update_user_profile_writes_english_names(db_pool):
    """PATCH /me (onboarding) ต้องเก็บชื่ออังกฤษด้วย"""
    user_id = await _insert_user(db_pool, first_name="", last_name="")
    payload = UserProfileUpdate(
        prefix="นาย", first_name="สมชาย", last_name="ใจดี",
        nickname="โอม", nickname_en="Om", birthday="2005-05-05",
        phone_number="0812345678", line_id="om",
        address_house_no="1", address_sub_district="บางกะปิ",
        address_district="บางกะปิ", address_province="กรุงเทพฯ",
        address_post_code="10240",
        first_name_en="Somchai", last_name_en="Jaidee",
    )
    await update_user_profile(
        pool=db_pool, user_id=user_id, profile_data=payload,
        client_source="test", actor_identifier="test",
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT first_name, last_name, first_name_en, last_name_en, nickname, nickname_en FROM users WHERE id = $1", user_id
        )
        assert row["first_name"] == "สมชาย"
        assert row["last_name"] == "ใจดี"
        assert row["first_name_en"] == "Somchai"
        assert row["last_name_en"] == "Jaidee"
        assert row["nickname"] == "โอม"
        assert row["nickname_en"] == "Om"
