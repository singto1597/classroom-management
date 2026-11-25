"""📊 [FIN-V2 / P6.4] เงินของห้องตอนนี้ (money ownership) — snapshot ปัจจุบัน

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **กระเป๋า vs เงินผู้รับถือ** — `room_wallets` ต้องไม่นับ custody และกลับกัน
2. **เครดิตใช้ `balance_after` แถวล่าสุดต่อคน** — ไม่ใช่ `SUM(amount)` (มี reverse/soft delete)
3. **ยอดค้างรับสูตร 3 พจน์** — ต้องเท่ากับ aging `grand_total` เป๊ะ (รวมบิลที่ถูก write-off)
4. **สมการไม่ clamp** — `net_room_money = total_cash − credit_liability` แม้ติดลบ
5. **`by_receiver`** — เฉพาะ custodial account ที่มีเจ้าของ + ใช้ `display_name` + เรียง desc
6. **RBAC** — สมาชิกอ่านได้ (require_member) คนนอกได้ 403 ไม่ใช่ตัวเลขศูนย์
7. **อ่านอย่างเดียว** — journal/balance ไม่ขยับหลังเรียก

⚠️ ทุกอย่างยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import itertools
import random
import string
import uuid

import pytest

from services.finance.dashboard import QUICK_ACTIONS

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
OWNERSHIP_PATH = API_PREFIX + "/{room}/finance/dashboard/ownership"
AGING_PATH = API_PREFIX + "/{room}/finance/receivables/aging"


def _url(template: str, room_id: int) -> str:
    return template.format(room=room_id) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seeding
async def _insert_user(pool, first_name: str = "Kid") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "Test", f"u{uuid.uuid4().hex[:12]}",
        )


# 🔢 เลขที่นักเรียนต้องไม่ชนกันในห้อง (unique partial index) — ห้องถูก TRUNCATE
#    ก่อนทุกเทสต์ ⇒ ใช้ตัวนับร่วมกันได้ และไม่ชนกับ admin_headers (student_no=1)
_student_no = itertools.count(1000)


async def _insert_student(pool, room_id: int, *, student_no: int | None = None) -> int:
    user_id = await _insert_user(pool)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no or next(_student_no),
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id)
               VALUES ('ห้องอื่น', $1, $2) RETURNING id""",
            code, owner_id,
        )


async def _insert_person(pool, room_id: int, name: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people (room_id, person_type, display_name, roles, is_active)
               VALUES ($1, 'teacher', $2, ARRAY['receive']::TEXT[], TRUE) RETURNING id""",
            room_id, name,
        )


async def _insert_account(
    pool, room_id: int, name: str, balance: float = 0,
    *, is_custody: bool = False, owner_person_id: int | None = None,
    deleted: bool = False,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts
                   (room_id, account_name, balance, is_custody, owner_person_id, deleted_at)
               VALUES ($1, $2, $3, $4, $5, CASE WHEN $6 THEN NOW() ELSE NULL END)
               RETURNING id""",
            room_id, name, balance, is_custody, owner_person_id, deleted,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *,
    amount: float = 100.0, paid: float = 0.0, written_off: float = 0.0,
    status: str = "pending",
) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, f"ค่าห้อง {uuid.uuid4().hex[:6]}", amount,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            collection_id, student_id, status, paid, written_off,
        )


async def _insert_credit(
    pool, room_id: int, student_id: int, *,
    entry_type: str = "topup", amount: float, balance_after: float,
    deleted: bool = False,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after, deleted_at)
               VALUES ($1, $2, $3, $4, $5, CASE WHEN $6 THEN NOW() ELSE NULL END)
               RETURNING id""",
            room_id, student_id, entry_type, amount, balance_after, deleted,
        )


async def _provision_user_headers(pool, first_name: str) -> tuple[int, dict]:
    """user ใหม่ + headers ที่ยิง API ได้ (ยังไม่ผูกห้อง)"""
    from core.config import settings

    discord_id = random.randint(1_000_000, 9_999_999)
    user_id = await _insert_user(pool, first_name)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET discord_id = $1 WHERE id = $2", discord_id, user_id
        )
    return user_id, {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


async def _provision_member_of(pool, room_id: int, first_name: str = "Member") -> dict:
    """user ที่เป็น **สมาชิกของห้องที่กำหนด** (ไม่มีสิทธิ์การเงิน) — คืน headers"""
    user_id, headers = await _provision_user_headers(pool, first_name)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 99, 'student', 'active', FALSE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return headers


async def _provision_outsider(pool) -> tuple[int, dict]:
    """user + room ของตัวเอง (ไม่ใช่สมาชิกห้องที่กำลังทดสอบ) — ใช้ยิงแบบคนนอก"""
    user_id, headers = await _provision_user_headers(pool, "Outsider")
    room_id = await _insert_room(pool, user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 1, 'student', 'active', FALSE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return room_id, headers


def _get(client, room_id: int, headers) -> dict:
    res = client.get(_url(OWNERSHIP_PATH, room_id), headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


# ═══════════════════════════════════════════════════════════ 1–3 กระเป๋า/custody
async def test_room_wallets_excludes_custody_accounts(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมชาย")
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 5000)
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 1500,
        is_custody=True, owner_person_id=person_id,
    )

    body = _get(client, room_id, admin_headers)

    assert body["room_wallets"] == 5000.0
    assert body["custody_held"] == 1500.0


async def test_custody_held_sums_only_custody_accounts(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    p1 = await _insert_person(db_pool, room_id, "ครูสมชาย")
    p2 = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 5000)
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 1500,
        is_custody=True, owner_person_id=p1,
    )
    await _insert_account(
        db_pool, room_id, "ครูสมหญิง (เงินสดรอส่งมอบ)", 700,
        is_custody=True, owner_person_id=p2,
    )

    body = _get(client, room_id, admin_headers)

    assert body["custody_held"] == 2200.0
    assert body["room_wallets"] == 5000.0


async def test_total_cash_is_sum_of_wallets_and_custody(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมชาย")
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 12000)
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 1500,
        is_custody=True, owner_person_id=person_id,
    )

    body = _get(client, room_id, admin_headers)

    assert body["total_cash"] == body["room_wallets"] + body["custody_held"]
    assert body["total_cash"] == 13500.0


# ═══════════════════════════════════════════════════ 4–6 เครดิต (balance_after)
async def test_credit_liability_uses_latest_balance_after_per_student(
    client, db_pool, admin_headers
):
    """เติม 2 รอบ + หัก → ต้องได้ยอดของแถวล่าสุด (1300) ไม่ใช่ SUM(amount)=1700"""
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id)
    await _insert_credit(db_pool, room_id, student_id, amount=1000, balance_after=1000)
    await _insert_credit(db_pool, room_id, student_id, amount=500, balance_after=1500)
    await _insert_credit(
        db_pool, room_id, student_id, entry_type="apply", amount=200, balance_after=1300
    )

    body = _get(client, room_id, admin_headers)

    assert body["credit_liability"] == 1300.0


async def test_credit_liability_excludes_soft_deleted_rows(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id)
    await _insert_credit(db_pool, room_id, student_id, amount=1000, balance_after=1000)
    # แถวที่ถูก soft delete ต้องไม่ถูกนับ — แม้ id จะใหม่กว่า
    await _insert_credit(
        db_pool, room_id, student_id, amount=300, balance_after=1300, deleted=True
    )

    body = _get(client, room_id, admin_headers)

    assert body["credit_liability"] == 1000.0


async def test_credit_liability_ignores_other_rooms(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_a = await _insert_student(db_pool, room_id)
    await _insert_credit(db_pool, room_id, student_a, amount=800, balance_after=800)

    # ห้องอื่นมีเครดิต 9999 — ต้องไม่โผล่ในห้องนี้
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    student_b = await _insert_student(db_pool, other_room)
    await _insert_credit(db_pool, other_room, student_b, amount=9999, balance_after=9999)

    body = _get(client, room_id, admin_headers)

    assert body["credit_liability"] == 800.0


# ═══════════════════════════════════ 7–8 ยอดค้างรับ (สูตร 3 พจน์ + parity aging)
async def test_receivable_total_matches_aging_grand_total(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    s1 = await _insert_student(db_pool, room_id)
    s2 = await _insert_student(db_pool, room_id)
    await _insert_bill(db_pool, room_id, s1, amount=1000, paid=200)       # 800
    await _insert_bill(db_pool, room_id, s2, amount=500, paid=500, status="paid")  # ปิดแล้ว
    await _insert_bill(db_pool, room_id, s2, amount=400, written_off=400)  # ตัดครบ
    await _insert_bill(db_pool, room_id, s1, amount=250)                   # 250

    body = _get(client, room_id, admin_headers)
    aging = client.get(_url(AGING_PATH, room_id), headers=admin_headers)
    assert aging.status_code == 200, aging.text

    assert body["receivable_total"] == 1050.0
    assert body["receivable_total"] == aging.json()["grand_total"]


async def test_receivable_total_excludes_written_off_from_outstanding(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id)
    await _insert_bill(
        db_pool, room_id, student_id, amount=1000, paid=200, written_off=500
    )

    body = _get(client, room_id, admin_headers)

    assert body["receivable_total"] == 300.0


# ══════════════════════════════════════════════════ 9–10 สมการ net_room_money
async def test_net_room_money_equation(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมชาย")
    student_id = await _insert_student(db_pool, room_id)
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 12000)
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 1500,
        is_custody=True, owner_person_id=person_id,
    )
    await _insert_credit(db_pool, room_id, student_id, amount=800, balance_after=800)

    body = _get(client, room_id, admin_headers)

    assert body["total_cash"] == 13500.0
    assert body["credit_liability"] == 800.0
    assert body["net_room_money"] == body["total_cash"] - body["credit_liability"]
    assert body["net_room_money"] == 12700.0


async def test_net_room_money_can_be_negative_and_is_not_clamped(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id)
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 100)
    await _insert_credit(db_pool, room_id, student_id, amount=500, balance_after=500)

    body = _get(client, room_id, admin_headers)

    assert body["net_room_money"] == -400.0


# ═══════════════════════════════════════════════════════════ 11–13 by_receiver
async def test_by_receiver_uses_display_name_and_orders_desc(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    p_small = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    p_big = await _insert_person(db_pool, room_id, "ครูสมชาย")
    await _insert_account(
        db_pool, room_id, "ครูสมหญิง (เงินสดรอส่งมอบ)", 100,
        is_custody=True, owner_person_id=p_small,
    )
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 900,
        is_custody=True, owner_person_id=p_big,
    )

    body = _get(client, room_id, admin_headers)

    assert [r["name"] for r in body["by_receiver"]] == ["ครูสมชาย", "ครูสมหญิง"]
    assert [r["held"] for r in body["by_receiver"]] == [900.0, 100.0]


async def test_by_receiver_excludes_custody_without_owner(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _insert_account(db_pool, room_id, "กล่องกลาง", 600, is_custody=True)

    body = _get(client, room_id, admin_headers)

    assert body["by_receiver"] == []
    # ยังนับเป็นเงินสดที่ห้องถืออยู่ — แค่ไม่มีเจ้าของให้แสดง
    assert body["custody_held"] == 600.0


async def test_soft_deleted_account_excluded(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 500)
    await _insert_account(db_pool, room_id, "กระเป๋าเก่า", 999, deleted=True)

    body = _get(client, room_id, admin_headers)

    assert body["room_wallets"] == 500.0


# ═══════════════════════════════════════════════════════ 14–16 empty/RBAC/scope
async def test_empty_room_returns_zeros_not_null(client, admin_headers):
    body = _get(client, admin_headers.room_id, admin_headers)

    assert body["room_wallets"] == 0.0
    assert body["custody_held"] == 0.0
    assert body["total_cash"] == 0.0
    assert body["credit_liability"] == 0.0
    assert body["receivable_total"] == 0.0
    assert body["net_room_money"] == 0.0
    assert body["by_receiver"] == []
    assert body["quick_actions"] == list(QUICK_ACTIONS)


async def test_member_can_read_non_member_forbidden(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 500)

    # สมาชิกของห้องนี้ (ไม่มีสิทธิ์การเงิน) อ่านได้ — แดชบอร์ดโปร่งใส
    member_headers = await _provision_member_of(db_pool, room_id)
    assert _get(client, room_id, member_headers)["room_wallets"] == 500.0

    _, outsider_headers = await _provision_outsider(db_pool)
    res = client.get(_url(OWNERSHIP_PATH, room_id), headers=outsider_headers)
    assert res.status_code == 403, res.text


async def test_cross_room_isolation(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    person_id = await _insert_person(db_pool, other_room, "ครูห้องอื่น")
    await _insert_account(db_pool, other_room, "กระเป๋าห้องอื่น", 7777)
    await _insert_account(
        db_pool, other_room, "ครูห้องอื่น (เงินสดรอส่งมอบ)", 888,
        is_custody=True, owner_person_id=person_id,
    )

    body = _get(client, room_id, admin_headers)

    assert body["room_wallets"] == 0.0
    assert body["custody_held"] == 0.0


# ═══════════════════════════════════════════════════════════ 17–18 read-only/const
async def test_endpoint_is_read_only(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมชาย")
    student_id = await _insert_student(db_pool, room_id)
    await _insert_account(db_pool, room_id, "กระเป๋าหลัก", 12000)
    await _insert_account(
        db_pool, room_id, "ครูสมชาย (เงินสดรอส่งมอบ)", 1500,
        is_custody=True, owner_person_id=person_id,
    )
    await _insert_bill(db_pool, room_id, student_id, amount=1000, paid=200)
    await _insert_credit(db_pool, room_id, student_id, amount=800, balance_after=800)

    async with db_pool.acquire() as conn:
        before = {
            "journal_entries": await conn.fetchval("SELECT COUNT(*) FROM journal_entries"),
            "journal_lines": await conn.fetchval("SELECT COUNT(*) FROM journal_lines"),
            "account_total": await conn.fetchval(
                "SELECT COALESCE(SUM(balance), 0) FROM finance_accounts WHERE room_id = $1",
                room_id,
            ),
        }

    _get(client, room_id, admin_headers)

    async with db_pool.acquire() as conn:
        after = {
            "journal_entries": await conn.fetchval("SELECT COUNT(*) FROM journal_entries"),
            "journal_lines": await conn.fetchval("SELECT COUNT(*) FROM journal_lines"),
            "account_total": await conn.fetchval(
                "SELECT COALESCE(SUM(balance), 0) FROM finance_accounts WHERE room_id = $1",
                room_id,
            ),
        }

    assert after == before


async def test_quick_actions_constant(client, admin_headers):
    assert QUICK_ACTIONS == ("receive", "expense", "income", "handover", "report")

    body = _get(client, admin_headers.room_id, admin_headers)
    assert body["quick_actions"] == ["receive", "expense", "income", "handover", "report"]
