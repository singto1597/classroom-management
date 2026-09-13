"""
HTTP integration tests สำหรับ F4 — `GET /{target_id}/finance/me/debts` (หนี้ค้างของตัวเอง)

ทำไมต้องมี endpoint นี้: บอท Discord รู้แค่ `X-Discord-Id` **ไม่รู้ `student_id`**
แต่ `get_student_debts` ต้องรับ `student_id` ⇒ ต้องมีจุดที่แปลง "ตัวผู้เรียก" เป็น
`students.id` ให้ ซึ่งเป็นงานที่ทำฝั่งบอทไม่ได้ (บอทห้ามแตะ DB)

สิ่งที่ชุดนี้พิสูจน์ (ตามเกณฑ์ตรวจรับของ F4):
  1. นักเรียนมีบิลค้าง → 200 + ยอดตรงกับ DB จริง (**deep verification** ไม่เชื่อแค่ HTTP status)
  2. ไม่เคยผูกโปรไฟล์นักเรียน → **404** พร้อมคำแนะนำ `/sync_room` (ไม่ใช่ 403 ที่ชี้ทางแก้ผิด / ไม่ใช่ 500)
  3. อยู่ต่างห้อง → **403** · ถูกถอดออกจากห้องแล้ว → **403**
  4. 0 หนี้ → **200 + `debts == []`** ไม่ใช่ 404
  5. เส้นทาง `target_type=server` ที่บอทใช้จริง (ไม่ใช่ `room` ที่เว็บใช้)

Note: fixture `*_headers` สร้าง user + room + students row ของตัวเองทุกเทสต์
(function-scoped เพราะ `clean_database` เป็น autouse) — ดู `conftest.py`
"""
import random
import string
import uuid
from datetime import date

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio

# ⚠️ finance router ถูก mount ด้วย prefix `/api/classroom` (ดู `backend/main.py:79`)
# ลืม prefix นี้แล้วจะได้ 404 `{"detail":"Not Found"}` **ของ FastAPI เอง** (ไม่ใช่ 404 ของโดเมน)
# ซึ่งอ่านไม่ออกเลยว่าตกลง route หายหรือห้องหาย ⇒ ใช้ค่าคงที่แทนการพิมพ์ซ้ำ
# (ตามแบบเดียวกับ `test_finance_statements.py` — `TRIAL_BALANCE_PATH` ฯลฯ)
API_PREFIX = "/api/classroom"
MY_DEBTS_PATH = API_PREFIX + "/{room}/finance/me/debts"
STUDENT_DEBTS_PATH = API_PREFIX + "/{room}/finance/students/{student}/debts"


# === Helpers (สร้างข้อมูลการเงินขั้นต่ำ — ไม่มี ledger/journal เพราะ endpoint นี้ไม่แตะ) ===


async def _insert_user(pool, *, discord_id=None, first_name="Test", last_name="User") -> int:
    """สร้าง users row ตรง ๆ (ไม่ผ่าน conftest fixture) สำหรับเคสที่ต้องคุมโปรไฟล์เอง."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username, discord_id) VALUES ($1, $2, $3, $4) RETURNING id",
            first_name, last_name, f"u{uuid.uuid4().hex[:12]}", discord_id,
        )


def _bot_headers(discord_id: int) -> dict:
    """headers เส้นทางบอท (X-API-Key + X-Discord-Id) — เหมือน `api_client` ฝั่งบอทเป๊ะ."""
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


async def _insert_room(pool, owner_id: int, *, room_name="Test Room", server_id=None) -> int:
    """ห้องเพิ่มเติม — `room_code` มี UNIQUE จึงต้องสุ่มและเช็คก่อน (กฎ ห้าม hardcode ID)."""
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id, server_id) VALUES ($1, $2, $3, $4) RETURNING id",
            room_name, code, owner_id, server_id,
        )


async def _insert_collection(pool, room_id: int, title="ค่าเทอม", amount=1000.0, due_date=None, status="active") -> int:
    if due_date is None:
        due_date = date(2026, 12, 31)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO fee_collections (room_id, title, amount, due_date, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_id, title, amount, due_date, status,
        )


async def _insert_payment(pool, collection_id: int, student_id: int, *, status="pending", paid_amount=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            collection_id, student_id, status, paid_amount,
        )


async def _db_pending_total(pool, student_id: int) -> float:
    """ยอดค้างที่ "ถูกต้อง" คำนวณสด ๆ จาก DB — ใช้เป็นแหล่งความจริงในการเทียบ."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT (FC.amount - COALESCE(SP.paid_amount, 0)) AS pending
            FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE SP.student_id = $1 AND SP.status = 'pending'
            """,
            student_id,
        )
    return float(sum(r["pending"] for r in rows))


# =============================================================================
# 1) happy path + deep DB verification
# =============================================================================


async def test_my_debts_lists_pending_bills_and_total_matches_db(client, db_pool, member_headers):
    """นักเรียน (ไม่ใช่ admin) มี 2 บิลค้าง → 200 + ยอดรวมตรงกับ DB เป๊ะ."""
    col_a = await _insert_collection(db_pool, member_headers.room_id, title="ค่าอาหาร", amount=750.0)
    col_b = await _insert_collection(db_pool, member_headers.room_id, title="ค่าทัศนศึกษา", amount=1250.5)
    await _insert_payment(db_pool, col_a, member_headers.student_id)
    await _insert_payment(db_pool, col_b, member_headers.student_id)

    res = client.get(
        MY_DEBTS_PATH.format(room=member_headers.room_id),
        params={"target_type": "room"},
        headers=member_headers,
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["student_id"] == member_headers.student_id
    assert body["total_pending_amount"] == pytest.approx(2000.5)
    assert len(body["debts"]) == 2
    assert {d["title"] for d in body["debts"]} == {"ค่าอาหาร", "ค่าทัศนศึกษา"}

    # 🔍 deep verification: ยอดที่ API คืนต้องเท่ากับที่คำนวณสด ๆ จาก DB
    assert body["total_pending_amount"] == pytest.approx(await _db_pending_total(db_pool, member_headers.student_id))


async def test_my_debts_counts_partial_payment_as_remainder(client, db_pool, member_headers):
    """จ่ายบางส่วน (paid_amount > 0 แต่ยัง pending) → หนี้ต้องเป็น **ส่วนที่เหลือ** ไม่ใช่ยอดเต็ม."""
    col = await _insert_collection(db_pool, member_headers.room_id, title="ค่าชุดพละ", amount=1000.0)
    await _insert_payment(db_pool, col, member_headers.student_id, status="pending", paid_amount=400.0)

    res = client.get(
        MY_DEBTS_PATH.format(room=member_headers.room_id),
        params={"target_type": "room"},
        headers=member_headers,
    )

    assert res.status_code == 200, res.text
    assert res.json()["total_pending_amount"] == pytest.approx(600.0)

    async with db_pool.acquire() as conn:
        paid = await conn.fetchval("SELECT paid_amount FROM student_payments WHERE collection_id = $1", col)
    assert float(paid) == pytest.approx(400.0)  # ยืนยันว่าแถวใน DB ไม่ได้ถูกแก้


async def test_my_debts_ignores_paid_bills_and_other_students(client, db_pool, member_headers):
    """บิลที่จ่ายแล้ว และบิลของเพื่อน ต้องไม่โผล่ในหนี้ของตัวเอง (0 หนี้ → 200 ไม่ใช่ 404)."""
    mine_paid = await _insert_collection(db_pool, member_headers.room_id, title="จ่ายแล้ว", amount=500.0)
    await _insert_payment(db_pool, mine_paid, member_headers.student_id, status="paid", paid_amount=500.0)

    # เพื่อนร่วมห้องเดียวกันมีบิลค้าง — ต้องไม่ถูกนับ
    friend_user = await _insert_user(db_pool, first_name="เพื่อน")
    async with db_pool.acquire() as conn:
        friend_student = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            member_headers.room_id, friend_user,
        )
    friend_col = await _insert_collection(db_pool, member_headers.room_id, title="ของเพื่อน", amount=999.0)
    await _insert_payment(db_pool, friend_col, friend_student)

    res = client.get(
        MY_DEBTS_PATH.format(room=member_headers.room_id),
        params={"target_type": "room"},
        headers=member_headers,
    )

    assert res.status_code == 200, res.text
    assert res.json()["debts"] == []
    assert res.json()["total_pending_amount"] == 0.0


# =============================================================================
# 2) แยก "ยังไม่เคยผูกบัญชี" (404) ออกจาก "ไม่ใช่สมาชิกแล้ว" (403)
# =============================================================================


async def test_my_debts_without_student_row_is_404(client, db_pool, admin_headers):
    """ผู้ใช้ที่ไม่เคยมีแถว `students` เลย → 404 พร้อมข้อความบอกทางแก้.

    เคสจริงที่พบบ่อยที่สุดของคำสั่งนี้: นักเรียนใน guild พิมพ์ `/finance my-debts`
    **ก่อน** `/sync_room` ⇒ ต้องได้ 404 + คำแนะนำ `/sync_room` ไม่ใช่ 403
    "คุณไม่ได้เป็นสมาชิกของห้องนี้" (ซึ่งชี้ทางแก้ผิด) และไม่ใช่ 500
    """
    discord_id = 7_000_001
    await _insert_user(db_pool, discord_id=discord_id, first_name="ไม่มี", last_name="โปรไฟล์")

    res = client.get(
        MY_DEBTS_PATH.format(room=admin_headers.room_id),
        params={"target_type": "room"},
        headers=_bot_headers(discord_id),
    )

    assert res.status_code == 404, res.text
    assert "/sync_room" in res.json()["detail"]  # ข้อความต้องบอกทางแก้ ไม่ใช่แค่ "ไม่พบ"


async def test_my_debts_with_removed_student_is_403_not_404(client, db_pool):
    """สมาชิกที่ถูกถอดออกจากห้อง (แถว `students` ถูก soft delete) → **403** ไม่ใช่ 404.

    เหตุผลที่ชั้นตรวจ "เคยมีโปรไฟล์ไหม" **ไม่กรอง `deleted_at`**: คนที่เคยมีโปรไฟล์ต้องได้
    "ไม่ใช่สมาชิกแล้ว" ส่วน 404 สงวนไว้ให้คนที่ไม่เคยผูกบัญชีจริง ๆ — ถ้ากรอง `deleted_at`
    เขาจะได้ 404 แล้วบอทจะบอกให้ไป `/sync_room` ซึ่งเป็นการวินิจฉัยที่ผิด
    """
    discord_id = 7_000_002
    user_id = await _insert_user(db_pool, discord_id=discord_id, first_name="ถูกลบ", last_name="แล้ว")
    room_id = await _insert_room(db_pool, user_id, room_name="ห้องที่ถูกถอด")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions, deleted_at)
               VALUES ($1, $2, 1, 'student', 'active', FALSE, '[]'::jsonb, NOW())""",
            room_id, user_id,
        )

    res = client.get(
        MY_DEBTS_PATH.format(room=room_id),
        params={"target_type": "room"},
        headers=_bot_headers(discord_id),
    )

    assert res.status_code == 403, res.text
    assert res.json()["detail"]  # ต้องมีข้อความอธิบาย ไม่ใช่ 403 เปล่า ๆ


# =============================================================================
# 3) ต่างห้อง → 403 · ห้องไม่มีจริง → 404
# =============================================================================


async def test_my_debts_from_another_room_is_403(client, member_headers, admin_headers):
    """สมาชิกห้อง A ยิงไปห้อง B → **403** (ไม่ใช่ 404) — พิสูจน์ว่า `require_member` ถูกเช็คจริง.

    ถ้าโค้ดหาก่อนว่า "ผู้ใช้มีแถว students ในห้องเป้าหมายไหม" แล้วค่อยตอบ จะได้ 404
    ซึ่งขัดกับ `get_student_debts` (พี่น้องของมัน ตอบ 403) และทำให้ client แยกไม่ออกว่า
    ควร "ขอสิทธิ์" หรือ "ผูกบัญชี"
    """
    res = client.get(
        MY_DEBTS_PATH.format(room=admin_headers.room_id),
        params={"target_type": "room"},
        headers=member_headers,  # สมาชิกห้องอื่น (มีโปรไฟล์นักเรียนของตัวเองแล้ว)
    )

    assert res.status_code == 403, res.text


async def test_my_debts_unknown_room_is_404(client, member_headers):
    """room_id ที่ไม่มีจริง → 404 (ไม่ใช่ 403/500)."""
    res = client.get(
        MY_DEBTS_PATH.format(room=999999),
        params={"target_type": "room"},
        headers=member_headers,
    )

    assert res.status_code == 404, res.text
    # 🔒 ต้องเป็น 404 **ของโดเมน** ไม่ใช่ `{"detail":"Not Found"}` ของ FastAPI
    # (บั๊กจริงที่เคยเกิดในไฟล์นี้: ลืม prefix `/api/classroom` แล้วเทสต์นี้ "ผ่าน"
    #  ทั้งที่ route ไม่ถูกเรียกเลย — เทสต์ที่ผ่านด้วยเหตุผลผิดอันตรายกว่าเทสต์ที่ fail)
    assert res.json()["detail"] == "ไม่พบห้องเรียนนี้"


async def test_student_debts_cross_room_is_403(client, member_headers, admin_headers):
    """[regression] `students/{id}/debts` เดิมไม่ดัก `ForbiddenError` ⇒ คนนอกห้องได้ **500**.

    ทุก route การเงินตัวอื่น map `ForbiddenError` → 403 อยู่แล้ว ตัวนี้เป็นตัวเดียวที่ตกหล่น
    ⇒ เทสต์นี้ล็อกไม่ให้ถอยกลับ (แก้พร้อมกับ F4 เพราะอยู่ไฟล์/router เดียวกัน)
    """
    res = client.get(
        STUDENT_DEBTS_PATH.format(room=admin_headers.room_id, student=admin_headers.student_id),
        params={"target_type": "room"},
        headers=member_headers,
    )

    assert res.status_code == 403, res.text


# =============================================================================
# 4) เส้นทางที่บอทใช้จริง: target_type=server
# =============================================================================


async def test_my_debts_via_server_target_matches_the_bot_path(client, db_pool, member_headers):
    """บอทส่ง `guild_id` + `target_type=server` — ต้องได้ผลเหมือนเส้นทาง room.

    ⚠️ เป็นเทสต์ที่คุ้มที่สุดของ F4: `get_target` มี default เป็น `"room"` (สำหรับเว็บ)
    ถ้าบอทลืมส่ง `target_type=server` จะได้ 404 "ไม่พบห้อง" ทั้งที่ห้องมีอยู่ — เส้นทางนี้
    จึงต้องถูกพิสูจน์ ไม่ใช่สมมติ (และคู่กับ `_server_params()` ใน `finance_api.py` ฝั่งบอท)

    ⚠️ เลือก guild_id ให้ **พอดี int32** โดยตั้งใจ: guild จริงของ Discord เป็น snowflake
    ~19 หลัก ซึ่งเกินช่วง `rooms.id` (SERIAL/int4) ⇒ เส้นทาง "ลืม target_type" จะไม่คืน 404
    แต่จะไปตายที่ asyncpg `OverflowError` → **HTTP 500** (บั๊กเดิมของ `resolve_room_id`
    ที่บันทึกเป็นงานแยกไว้ — ดู `docs/skills.md`) เทสต์นี้ตั้งใจพิสูจน์ *กับดัก target_type*
    ไม่ใช่พิสูจน์บั๊กนั้น จึงใช้ค่าที่อยู่ในช่วงเพื่อให้ assertion สื่อความหมายเดียว
    """
    server_id = 1_234_567_890  # < 2^31-1 ⇒ ตีความเป็น room_id ได้ (แล้วไม่พบ) ไม่ใช่ overflow
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, member_headers.room_id)

    col = await _insert_collection(db_pool, member_headers.room_id, title="ค่าเรียนพิเศษ", amount=333.0)
    await _insert_payment(db_pool, col, member_headers.student_id)

    res = client.get(
        MY_DEBTS_PATH.format(room=server_id),
        params={"target_type": "server"},
        headers=member_headers,
    )

    assert res.status_code == 200, res.text
    assert res.json()["total_pending_amount"] == pytest.approx(333.0)

    # 🚨 ยืนยันกับดัก: guild_id เดียวกันแต่ **ไม่ส่ง** target_type → ตีความเป็น room_id → 404
    res_wrong = client.get(MY_DEBTS_PATH.format(room=server_id), headers=member_headers)
    assert res_wrong.status_code == 404, res_wrong.text
    assert res_wrong.json()["detail"] == "ไม่พบห้องเรียนนี้"  # 404 ของโดเมน ไม่ใช่ของ FastAPI
