"""
Integration tests สำหรับ F2 — ระบบงบประมาณ (finance_budgets)

ชุดนี้มีสองส่วนที่น้ำหนักไม่เท่ากัน:

  [ERA ROUTING] ★ ส่วนที่มีค่าที่สุด — พิสูจน์ว่า "ใช้ไป" ของงบอ่าน `finance_transactions`
     อย่างเดียว **และไม่นับซ้ำ** ทั้งที่ตารางนั้นถูก dual-write คู่กับ journal ทุกครั้ง
     บทพิสูจน์หลักคือ `used == Y` **ไม่ใช่ `2Y`** ในเทสต์ที่สร้างรายการผ่าน API จริง
     (ถ้าวันหนึ่งมีคน "แก้" ให้ F2 อ่าน journal เสริม เทสต์ชุดนี้จะจับได้ทันที)

  [CRUD + GUARDS] สร้าง/อ่าน/แก้/ลบ + soft delete + RBAC + audit + ขอบเขตวันไทย

หลักการ seeding ที่ต้องเข้าใจก่อนอ่านเทสต์:
  1. **`finance_transactions.created_at` เป็น `TIMESTAMP` naive ที่เก็บเวลา UTC**
     (ไม่ใช่ timestamptz) → seed ด้วย naive datetime ที่หมายถึง UTC ตรง ๆ
     การเทียบขอบเขตวันไทยใน service ทำด้วย `AT TIME ZONE 'Asia/Bangkok' AT TIME ZONE 'UTC'`
     ⇒ เทสต์ขอบวันจึงต้องคำนวณ "เวลาไทย" แล้วแปลงกลับเป็น UTC เอง (ดู `_thai_day_utc`)
  2. **`add_transaction` ไม่มีฟิลด์วันที่** — ทั้ง `created_at` และ `transaction_date`
     ตกลงที่ `CURRENT_TIMESTAMP` ⇒ เทสต์ที่ต้องคุมวันต้อง INSERT ตรงเท่านั้น
     ส่วนเทสต์ที่ต้องพิสูจน์ dual-write ต้องใช้ API จริง (แล้วอ่านวันเกิดจาก DB แทนการ hardcode
     → เทสต์ไม่เน่าเมื่อรันคนละเดือน)
  3. **`finance_categories` ไม่มี ledger ให้เอง** — `accounting_ledgers` ถูกสร้างโดย dual-write
     (`create_category`/`create_account`) เท่านั้น ห้องที่ INSERT ตรงจะมี ledger 0 แถว
     ⇒ เทสต์ที่ต้องใช้ journal ต้อง provision ผ่าน service หรือ INSERT เองพร้อม `legacy_*_id`

หมายเหตุ: conftest fixture สร้าง user + room + students row ของตัวเองทุกเทสต์ (function-scoped
เพราะ `clean_database` เป็น autouse) — ห้องไม่ผูก `server_id` จึงไม่มีการเรียก Redis เลย
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from services.finance.constants import DEFAULT_INCOME_CATEGORIES, THAI_TZ
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# =====================================================================
# ค่าคงที่ / helpers
# =====================================================================

# ⚠️ finance router ถูก mount ด้วย prefix `/api/classroom` (backend/main.py:79)
API_PREFIX = "/api/classroom"
BUDGETS_PATH = API_PREFIX + "/{room}/finance/budgets"
OVERVIEW_PATH = API_PREFIX + "/{room}/finance/budgets/overview"
BUDGET_PATH = API_PREFIX + "/{room}/finance/budgets/{budget_id}"
CATEGORY_PATH = API_PREFIX + "/{room}/finance/categories/{category_id}"
CATEGORIES_PATH = API_PREFIX + "/{room}/finance/categories"
ACCOUNTS_PATH = API_PREFIX + "/{room}/finance/accounts"
TRANSACTIONS_PATH = API_PREFIX + "/{room}/finance/transactions"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"
TRANSFER_PATH = API_PREFIX + "/{room}/finance/transfer"
COLLECTIONS_PATH = API_PREFIX + "/{room}/finance/collections"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"

# ยุคที่ใช้ตัดสินใจเรื่อง era routing (ดูหัวไฟล์ service)
PRE_CUTOFF_DAY = date(2026, 6, 15)     # ก่อน CUTOFF_DATE = 2026-09-01 แน่นอน ตลอดกาล


def _url(template: str, room_id: int, **kwargs) -> str:
    """สร้าง URL ของ finance API — web ต้องส่ง `target_type=room` เสมอ (default คือ server)."""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


def _thai_day_utc(d: date, hour: int = 12) -> datetime:
    """คืน naive datetime (UTC) ที่ตรงกับเวลา `hour` น. ของวันไทย `d`.

    ใช้ seed รายการให้ตกอยู่ในวันไทยที่ต้องการ — ค่าเริ่มต้น 12:00 น. ไทย = 05:00 UTC
    ซึ่งห่างจากขอบวันทั้งสองฝั่ง 7 ชม. จึงไม่กำกวม
    """
    return (
        datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=THAI_TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def _thai_month_bounds(thai_day: date) -> tuple:
    """วันแรก/วันสุดท้ายของเดือนไทยที่ `thai_day` อยู่."""
    start = thai_day.replace(day=1)
    if thai_day.month == 12:
        end = date(thai_day.year, 12, 31)
    else:
        end = date(thai_day.year, thai_day.month + 1, 1) - timedelta(days=1)
    return start, end


async def _thai_day_of_latest_tx(pool, room_id: int) -> date:
    """อ่าน `created_at` (naive UTC) ของรายการล่าสุดของห้อง แล้วแปลงเป็นวันไทย.

    ใช้แทนการ hardcode "วันนี้" เพื่อให้เทสต์ไม่เน่าเมื่อรันคนละเดือน/คนละปี
    — การแปลงเป็นไปตามกฎโปรเจกต์: naive UTC → `.replace(tzinfo=utc).astimezone(THAI_TZ)`
    """
    async with pool.acquire() as conn:
        ts = await conn.fetchval(
            "SELECT created_at FROM finance_transactions WHERE room_id = $1 ORDER BY id DESC LIMIT 1",
            room_id,
        )
    assert ts is not None, "ต้องมีรายการใน finance_transactions ก่อนเรียก helper นี้"
    return ts.replace(tzinfo=timezone.utc).astimezone(THAI_TZ).date()


# ---------------------------------------------------------------- seeding


async def _insert_category(pool, room_id: int, name: str, cat_type: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, cat_type,
        )


async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, balance,
        )


async def _seed_legacy_tx(
    pool, room_id: int, *, category_id, transaction_type: str, amount: float,
    created_at: datetime, account_id=None, transfer_group_id=None, student_payment_id=None,
) -> int:
    """INSERT แถว legacy ตรง ๆ พร้อม `created_at` ที่คุมได้ (naive UTC).

    ⚠️ **ไม่** สร้าง journal คู่ให้ — เจตนา: จำลองแถว "ยุค legacy" ที่มีอยู่ก่อน dual-write
    F2 อ่านตารางนี้ตารางเดียว จึงยังถูกต้องครบ; แต่ **ห้าม** ใช้ helper นี้กับเทสต์ที่
    ต้อง cross-check ฝั่ง journal (นั้นต้องสร้างผ่าน API จริงเท่านั้น)
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_transactions
                   (room_id, account_id, category_id, amount, description, transaction_type,
                    transfer_group_id, created_at, student_payment_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
            room_id, account_id, category_id, amount, f"seed {transaction_type}",
            transaction_type, transfer_group_id, created_at, student_payment_id,
        )


async def _post_journal(
    pool, room_id: int, *, ledger_lines, reference_type: str,
    transaction_date: datetime, status: str = "posted",
) -> str:
    """สร้าง journal_entries + journal_lines ตรง ๆ (ledger_lines = [(ledger_id, dr, cr), ...]).

    ⚠️ `transaction_date` เป็น timestamptz → ต้องส่ง **aware** datetime (หรือ naive ที่ตั้งใจให้เป็น UTC)
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            entry_id = await conn.fetchval(
                """INSERT INTO journal_entries (room_id, reference_type, description, recorded_by, status, transaction_date)
                   VALUES ($1, $2, 'seed entry', 'TEST', $3, $4::timestamptz) RETURNING id""",
                room_id, reference_type, status, transaction_date,
            )
            for ledger_id, dr, cr in ledger_lines:
                await conn.execute(
                    """INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                       VALUES ($1, $2, $3, $4, 'seed')""",
                    entry_id, ledger_id, dr, cr,
                )
            return entry_id


async def _insert_ledger(
    pool, room_id: int, *, account_name: str, account_type: str,
    legacy_category_id=None, legacy_account_id=None, account_code=None,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers
                   (room_id, account_code, account_name, account_type, legacy_category_id, legacy_account_id, is_active)
               VALUES ($1, $2, $3, $4, $5, $6, TRUE) RETURNING id""",
            room_id, account_code, account_name, account_type, legacy_category_id, legacy_account_id,
        )


async def _insert_student(pool, room_id: int, user_id: int, student_no: int = 90) -> int:
    """⚠️ `student_no` ต้องไม่ชนกับคนอื่นในห้อง — conftest fixture จองเลข 1 ไว้แล้ว
    (`idx_students_room_no_active` เป็น unique) จึงใช้เลขสูง ๆ เป็นค่าปกติ."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _insert_user(pool, first_name: str = "Kid", last_name: str = "One") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, last_name, f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_collection(pool, room_id: int, title: str = "ค่าเทอม", amount: float = 1000.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, date(2026, 12, 31),
        )


async def _insert_student_payment(pool, collection_id: int, student_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0.0) RETURNING id""",
            collection_id, student_id,
        )


# ---------------------------------------------------------------- API wrappers


def _create_budget(client, headers, *, category_id, amount, start_date, end_date, note=None):
    return client.post(
        _url(BUDGETS_PATH, headers.room_id),
        json={
            "category_id": category_id,
            "amount": amount,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "note": note,
            "user_name": "Tester",
        },
        headers=headers,
    )


async def _create_budget_ok(client, db_pool, headers, *, category_id, amount, start_date, end_date, note=None) -> int:
    """สร้างงบผ่าน API แล้วคืน budget_id ที่อ่านจาก DB (ไม่พึ่ง response body)."""
    res = _create_budget(client, headers, category_id=category_id, amount=amount,
                         start_date=start_date, end_date=end_date, note=note)
    assert res.status_code == 200, res.text
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM finance_budgets WHERE room_id = $1 AND category_id = $2 ORDER BY id DESC LIMIT 1",
            headers.room_id, category_id,
        )


def _overview(client, headers, start_date: date, end_date: date):
    return client.get(
        _url(OVERVIEW_PATH, headers.room_id),
        params={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        headers=headers,
    )


def _item_of(body: dict, budget_id: int) -> dict:
    for it in body["items"]:
        if it["budget_id"] == budget_id:
            return it
    raise AssertionError(f"ไม่พบ budget_id={budget_id} ใน {[i['budget_id'] for i in body['items']]}")


async def _used_of(client, headers, budget_id: int, start_date: date, end_date: date) -> float:
    res = _overview(client, headers, start_date, end_date)
    assert res.status_code == 200, res.text
    return _item_of(res.json(), budget_id)["used"]


async def _create_tx_api(client, headers, *, account_id, category_id, amount, tx_type) -> None:
    res = client.post(
        _url(TRANSACTIONS_PATH, headers.room_id),
        json={
            "account_id": account_id,
            "category_id": category_id,
            "amount": amount,
            "description": f"api {tx_type}",
            "transaction_type": tx_type,
            "user_name": "Tester",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text


async def _latest_tx_id(pool, room_id: int, category_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM finance_transactions WHERE room_id = $1 AND category_id = $2 ORDER BY id DESC LIMIT 1",
            room_id, category_id,
        )


# =====================================================================
# 1) [ERA ROUTING] ★ หัวใจของเฟสนี้ — prove ว่าไม่นับซ้ำ
# =====================================================================


async def test_overview_counts_legacy_rows(client, db_pool, admin_headers):
    """แถวยุค legacy (INSERT ตรง ไม่มี journal) → นับเข้าหนึ่งครั้งตามปกติ."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    for day in (10, 11, 12):
        await _seed_legacy_tx(
            db_pool, room_id, category_id=cat, transaction_type="expense", amount=100.0,
            created_at=_thai_day_utc(date(2026, 6, day)), account_id=acc,
        )

    start, end = date(2026, 6, 1), date(2026, 6, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(300.0)


async def test_overview_does_not_double_count_dual_write_rows(client, db_pool, admin_headers):
    """🎯 เทสต์สำคัญที่สุดของ F2 — รายการที่สร้างผ่าน API มี **ทั้ง** legacy row และ journal.

    ถ้ามีใครแก้ให้ F2 อ่าน journal เสริม (หรืออ่านทั้งสองฝั่งรวมกัน) เทสต์นี้จะได้ 1000
    แล้ว fail ทันที — และนั่นคือเจตนา: `finance_transactions` เป็น mirror ที่ครบสองยุค
    อ่านคู่กับ journal = นับซ้ำเป็น 2 เท่า
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    acc = await _insert_account(db_pool, room_id, balance=0.0)

    await _create_tx_api(client, admin_headers, account_id=acc, category_id=cat,
                         amount=500.0, tx_type="income")

    # ยืนยันก่อนว่าฝั่ง journal มีอยู่จริง — ไม่งั้นเทสต์ผ่านเพราะ seed ไม่ครบ ไม่ใช่เพราะไม่นับซ้ำ
    async with db_pool.acquire() as conn:
        journal_rows = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'manual_transaction'
                 AND deleted_at IS NULL AND status <> 'voided'""",
            room_id,
        )
        legacy_rows = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND category_id = $2",
            room_id, cat,
        )
    assert journal_rows == 1, "dual-write ต้องสร้าง journal คู่กับ legacy row"
    assert legacy_rows == 1

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    start, end = _thai_month_bounds(thai_day)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=5000, start_date=start, end_date=end)

    used = await _used_of(client, admin_headers, budget_id, start, end)
    assert used == pytest.approx(500.0), f"ต้องเป็น 500 (ไม่ใช่ 1000) — ได้ {used}"


async def test_overview_straddling_cutoff_sums_both_eras(client, db_pool, admin_headers):
    """งบที่คร่อม CUTOFF_DATE ต้องเห็นยอดจาก **ทั้งสองยุค** รวมกันพอดี ไม่มีรู ไม่มีเบิ้ล.

    ยุค legacy: seed ตรงในเดือน มิ.ย. 2026 (ก่อน cutoff)
    ยุค dual-write: สร้างผ่าน API "ตอนนี้" (หลัง cutoff เสมอ) โดยอ่านเดือนไทยจาก DB
                   แทนการ hardcode → เทสต์ไม่เน่าเมื่อรันคนละเดือน
    ช่วงงบ: 2026-06-01 → วันสุดท้ายของเดือนไทยปัจจุบัน
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=300.0, created_at=_thai_day_utc(PRE_CUTOFF_DAY), account_id=acc)
    await _create_tx_api(client, admin_headers, account_id=acc, category_id=cat,
                         amount=200.0, tx_type="expense")

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    _, month_end = _thai_month_bounds(thai_day)
    start, end = date(2026, 6, 1), month_end
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=5000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(500.0)


async def test_overview_excludes_rows_outside_budget_period(client, db_pool, admin_headers):
    """รายการที่อยู่นอกช่วงของงบต้องไม่ถูกนับ — แม้จะเป็นหมวดเดียวกัน."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=100.0, created_at=_thai_day_utc(date(2026, 9, 15)), account_id=acc)
    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=999.0, created_at=_thai_day_utc(date(2026, 10, 1)), account_id=acc)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(100.0)


async def test_overview_excludes_other_category(client, db_pool, admin_headers):
    """หมวดอื่นต้องไม่ถูกเหมารวม — เทสต์กันการ JOIN หลุดเงื่อนไข."""
    room_id = admin_headers.room_id
    cat_a = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    cat_b = await _insert_category(db_pool, room_id, "ค่าเดินทาง", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    await _seed_legacy_tx(db_pool, room_id, category_id=cat_b, transaction_type="expense",
                          amount=777.0, created_at=_thai_day_utc(date(2026, 9, 10)), account_id=acc)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat_a, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_overview_excludes_soft_deleted_transactions(client, db_pool, admin_headers):
    """รายการที่ถูกลบ (soft delete) ต้องไม่ถูกนับ."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    tx_id = await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                                  amount=400.0, created_at=_thai_day_utc(date(2026, 9, 10)), account_id=acc)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", tx_id)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


# =====================================================================
# 2) [ERA ROUTING] ขาโอนเงิน / opening_balance / adjustment ต้องไม่ขยับงบ
# =====================================================================


async def test_transfer_money_does_not_move_budget_used(client, db_pool, admin_headers):
    """โอนเงินระหว่างกระเป๋าไม่ใช่การใช้จ่าย → ยอดงบต้องไม่ขยับเลย."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc_a = await _insert_account(db_pool, room_id, "กระเป๋า A", 1000.0)
    acc_b = await _insert_account(db_pool, room_id, "กระเป๋า B", 0.0)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    res = client.post(
        _url(TRANSFER_PATH, room_id),
        json={"from_account_id": acc_a, "to_account_id": acc_b, "amount": 300.0,
              "description": "ย้ายเงิน", "user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    # ยืนยันว่า "มีแถวเกิดขึ้นจริง" ก่อน — ไม่งั้นเทสต์ผ่านเพราะโอนไม่สำเร็จ
    async with db_pool.acquire() as conn:
        legs = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL",
            room_id,
        )
    assert legs == 2

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_transfer_legs_carrying_category_are_still_excluded(client, db_pool, admin_headers):
    """🎯 พิสูจน์ว่าเงื่อนไข `transfer_group_id IS NULL` **มีผลจริง** ไม่ใช่ของประดับ.

    ขาจริงของ `transfer_money` มี `category_id = NULL` อยู่แล้ว ⇒ ถ้าใช้แต่ข้อมูลจริง
    เงื่อนไขนั้น "ดูเหมือน" ไม่จำเป็น (เทสต์ก่อนหน้าจะผ่านแม้ลบเงื่อนไขทิ้ง)
    เทสต์นี้จึง seed แถวที่ถือ **ทั้ง** `category_id` และ `transfer_group_id` พร้อมกัน
    ซึ่งเป็นรูปเดียวที่ทำให้เงื่อนไขมีผล — ถ้าลบเงื่อนไขออก ยอดจะกลายเป็น 250
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    async with db_pool.acquire() as conn:
        group_id = await conn.fetchval("SELECT nextval('transfer_group_id_seq')")

    for tx_type, amount in (("expense", 250.0), ("income", 250.0)):
        await _seed_legacy_tx(
            db_pool, room_id, category_id=cat, transaction_type=tx_type, amount=amount,
            created_at=_thai_day_utc(date(2026, 9, 10)), account_id=acc,
            transfer_group_id=group_id,
        )

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_opening_balance_does_not_move_budget_used(client, db_pool, admin_headers):
    """`opening_balance` เป็น journal-only (ไม่มีแถว legacy) → ไม่ใช่งบที่ใช้ไป."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=0.0)
    asset_ledger = await _insert_ledger(db_pool, room_id, account_name="เงินสด",
                                        account_type="asset", legacy_account_id=acc, account_code="1001")
    equity_ledger = await _insert_ledger(db_pool, room_id, account_name="ทุน-ยอดยกมา",
                                         account_type="equity", account_code="3000")

    await _post_journal(db_pool, room_id, reference_type="opening_balance",
                        transaction_date=_thai_day_utc(date(2026, 9, 10)),
                        ledger_lines=[(asset_ledger, 5000.0, 0), (equity_ledger, 0, 5000.0)])

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_reconcile_adjustment_on_mapped_ledger_does_not_move_budget_used(client, db_pool, admin_headers):
    """🎯 `adjustment` จาก reconcile ที่ **แตะ ledger ของหมวดที่มีงบ** ต้องยังไม่ถูกนับ.

    เคสนี้จัดฉากให้รุนแรงที่สุด: adjustment เครดิต revenue ledger ที่ `legacy_category_id`
    ชี้ตรงไปที่หมวดของงบ (คือรูปที่ branch (ข) จะคว้าไปนับ ถ้าเผลอลบเงื่อนไข
    `JE.reference_type = 'student_payment'` ออก) — ยอดต้องยังเป็น 0
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    acc = await _insert_account(db_pool, room_id, "กองกลาง", 0.0)
    asset_ledger = await _insert_ledger(db_pool, room_id, account_name="กองกลาง",
                                        account_type="asset", legacy_account_id=acc, account_code="1001")
    revenue_ledger = await _insert_ledger(db_pool, room_id, account_name="เงินบริจาค",
                                          account_type="revenue", legacy_category_id=cat, account_code="4001")

    await _post_journal(db_pool, room_id, reference_type="adjustment",
                        transaction_date=_thai_day_utc(date(2026, 9, 10)),
                        ledger_lines=[(asset_ledger, 900.0, 0), (revenue_ledger, 0, 900.0)])

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_revert_transaction_zeroes_budget_used(client, db_pool, admin_headers):
    """บันทึก → ยกเลิก → ยอดงบกลับเป็น 0 และ **ทั้งสองฝั่ง**ถูก mark (legacy + journal)."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    await _create_tx_api(client, admin_headers, account_id=acc, category_id=cat,
                         amount=450.0, tx_type="expense")
    tx_id = await _latest_tx_id(db_pool, room_id, cat)

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    start, end = _thai_month_bounds(thai_day)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)
    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(450.0)

    res = client.request(
        "DELETE", _url(TRANSACTION_PATH, room_id, tx_id=tx_id),
        json={"user_name": "Tester"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    # deep verification ทั้งสองฝั่ง — ไม่เชื่อ HTTP อย่างเดียว
    async with db_pool.acquire() as conn:
        legacy = await conn.fetchrow(
            "SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id
        )
        journal = await conn.fetchrow(
            """SELECT status, deleted_at FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'manual_transaction'
                 AND metadata->>'legacy_transaction_id' = $2""",
            room_id, str(tx_id),
        )
    assert legacy["deleted_at"] is not None, "ฝั่ง legacy ต้องถูก soft delete"
    assert journal is not None, "ต้องมี journal คู่กับรายการนี้"
    assert journal["status"] == "voided"
    assert journal["deleted_at"] is not None

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


# =====================================================================
# 3) [ERA ROUTING] รายรับจาก student_payments — disjointness
# =====================================================================


async def _provision_collection_income(client, db_pool, headers, *, amount: float) -> int:
    """จัดฉากรับเงินจาก student_payment ครบวง แล้วคืน category_id ของหมวดรายรับค่าเริ่มต้น.

    ลำดับ (ใช้ API จริงทุกขั้นเพื่อให้ dual-write ทำงานครบ):
      1. `create_category` ชื่อ `DEFAULT_INCOME_CATEGORIES[0]` → ได้ revenue ledger ที่มี
         `legacy_category_id` ชี้มาที่หมวดนี้ (นี่คือกุญแจของ branch (ข))
      2. `create_account` → ได้ asset ledger ที่มี `legacy_account_id`
      3. `confirm_payment` → legacy row **ที่ไม่มี category_id** + journal `student_payment`
    """
    room_id = headers.room_id
    res = client.post(
        _url(API_PREFIX + "/{room}/finance/categories", room_id),
        json={"category_name": DEFAULT_INCOME_CATEGORIES[0], "category_type": "income",
              "user_name": "Tester"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    res = client.post(
        _url(ACCOUNTS_PATH, room_id),
        json={"account_name": "กองกลาง", "initial_balance": 0.0, "user_name": "Tester"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        cat_id = await conn.fetchval(
            "SELECT id FROM finance_categories WHERE room_id = $1 AND category_name = $2",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
        acc_id = await conn.fetchval(
            "SELECT id FROM finance_accounts WHERE room_id = $1 ORDER BY id DESC LIMIT 1", room_id
        )

    student_user = await _insert_user(db_pool)
    student_id = await _insert_student(db_pool, room_id, student_user)
    collection_id = await _insert_collection(db_pool, room_id, amount=amount)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id)

    res = client.put(
        _url(PAY_PATH, room_id, payment_id=payment_id),
        json={"paid_to_account_id": acc_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return cat_id


async def test_student_payment_income_counted_exactly_once(client, db_pool, admin_headers):
    """🎯 บทพิสูจน์ disjointness — รับเงิน 1,000 ต้องได้ used == 1,000 **ไม่ใช่ 2,000**.

    เคสนี้เป็นเคสที่อันตรายที่สุดของการอ่านสองแหล่ง: แถว legacy ของการรับเงินมี
    `category_id = NULL` ⇒ branch (ก) มองไม่เห็น ส่วน journal มี ⇒ branch (ข) เห็น
    ถ้าเปิด branch (ก) ให้กว้างขึ้น (เช่นเลิกบังคับ category_id) ทั้งสอง branch
    จะจับเงินก้อนเดียวกัน = 2,000
    """
    cat_id = await _provision_collection_income(client, db_pool, admin_headers, amount=1000.0)
    room_id = admin_headers.room_id

    # ยืนยันข้อเท็จจริงที่ทำให้ disjoint: แถว legacy ของ student_payment ไม่มี category_id
    async with db_pool.acquire() as conn:
        legacy_cat = await conn.fetchval(
            "SELECT category_id FROM finance_transactions WHERE room_id = $1 AND student_payment_id IS NOT NULL",
            room_id,
        )
        journal_count = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1 AND reference_type = 'student_payment'",
            room_id,
        )
    assert legacy_cat is None, "ถ้าวันหนึ่ง dual-write เริ่มใส่ category_id เทสต์นี้ต้องถูกทบทวน"
    assert journal_count == 1

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    start, end = _thai_month_bounds(thai_day)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat_id, amount=5000, start_date=start, end_date=end)

    used = await _used_of(client, admin_headers, budget_id, start, end)
    assert used == pytest.approx(1000.0), f"ต้องเป็น 1000 (ไม่ใช่ 2000) — ได้ {used}"


async def test_student_payment_does_not_leak_into_other_income_category(client, db_pool, admin_headers):
    """🎯 กันการ JOIN หลุด: งบของหมวดรายรับ *อื่น* ต้องไม่เห็นเงินจาก student_payment.

    ถ้าเผลอตัดเงื่อนไข `AL.legacy_category_id = B.category_id` ออก เงิน 1,000
    จะไปโผล่ในงบของทุกหมวดรายรับพร้อมกัน
    """
    await _provision_collection_income(client, db_pool, admin_headers, amount=1000.0)
    room_id = admin_headers.room_id
    other_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    start, end = _thai_month_bounds(thai_day)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=other_cat, amount=5000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


async def test_student_payment_voided_is_excluded(client, db_pool, admin_headers):
    """journal ของ student_payment ที่ถูก void ต้องไม่ถูกนับ (เงื่อนไข `status <> 'voided'`)."""
    cat_id = await _provision_collection_income(client, db_pool, admin_headers, amount=1000.0)
    room_id = admin_headers.room_id

    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE journal_entries SET status = 'voided', deleted_at = NOW()
               WHERE room_id = $1 AND reference_type = 'student_payment'""",
            room_id,
        )

    thai_day = await _thai_day_of_latest_tx(db_pool, room_id)
    start, end = _thai_month_bounds(thai_day)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat_id, amount=5000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(0.0)


# =====================================================================
# 4) [BOUNDARY] ขอบเขตวันไทย — จุดที่ `::date` แบบ UTC จะพัง
# =====================================================================


async def test_budget_period_boundaries_are_inclusive(client, db_pool, admin_headers):
    """รายการวันที่เท่า `start_date`/`end_date` ต้องถูกนับ; ห่างออกไป 1 วันต้องไม่ถูก."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    start, end = date(2026, 9, 10), date(2026, 9, 20)
    for day, amount in ((date(2026, 9, 9), 1.0), (start, 10.0), (end, 100.0), (date(2026, 9, 21), 1000.0)):
        await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                              amount=amount, created_at=_thai_day_utc(day), account_id=acc)

    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=5000, start_date=start, end_date=end)

    assert await _used_of(client, admin_headers, budget_id, start, end) == pytest.approx(110.0)


async def test_budget_boundary_uses_thai_calendar_not_utc(client, db_pool, admin_headers):
    """🎯 กับดักที่แผนเวอร์ชันแรกแนะนำผิด — ห้ามใช้ `created_at::date` (นั่นคือปฏิทิน UTC).

    seed รายการเวลา 00:30 น. ไทยของวันที่ 1 ก.ย. = 17:30 UTC ของวันที่ 31 ส.ค.
      - ถ้าใช้ `created_at::date` (UTC) → ได้ 2026-08-31 → **หลุดจากงบเดือน ก.ย.**
      - ที่ถูกต้อง (แปลงเป็นวันไทยก่อน) → 2026-09-01 → อยู่ในงบ
    เช่นเดียวกันกับปลายเดือน: 23:30 น. ไทยของ 30 ก.ย. = 16:30 UTC ของ 30 ก.ย.
      ซึ่งบังเอิญตรงกัน — เคสที่แยกได้จริงคือ *ต้นเดือน* เท่านั้น จึงทดสอบจุดนั้น
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    # 00:30 น. ไทย 1 ก.ย. 2026 == 2026-08-31 17:30 UTC
    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=250.0, created_at=_thai_day_utc(date(2026, 9, 1), hour=0) + timedelta(minutes=30),
                          account_id=acc)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000, start_date=start, end_date=end)

    used = await _used_of(client, admin_headers, budget_id, start, end)
    assert used == pytest.approx(250.0), (
        f"รายการเวลาไทย 00:30 ของ 1 ก.ย. ต้องอยู่ในงบเดือน ก.ย. — ได้ {used} "
        "(ถ้าได้ 0 แปลว่าเทียบขอบเขตด้วยปฏิทิน UTC อยู่)"
    )


async def test_overview_filter_window_clamps_each_budget_to_its_own_period(client, db_pool, admin_headers):
    """`get_budget_overview` วัดยอดเฉพาะ **ส่วนที่ทับ** ระหว่างช่วงของงบกับช่วงที่กรอง.

    งบ 1–30 ก.ย. มีรายจ่าย 100 บาทวันที่ 5 และ 200 บาทวันที่ 25
    → กรองแค่ 1–10 ก.ย. ต้องได้ 100 (ไม่ใช่ 300) แต่ยังต้องเห็นงบใบนั้นในผลลัพธ์
    (กรองแบบ overlap ไม่ใช่ containment)
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=1000.0)

    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=100.0, created_at=_thai_day_utc(date(2026, 9, 5)), account_id=acc)
    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=200.0, created_at=_thai_day_utc(date(2026, 9, 25)), account_id=acc)

    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=1000,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    narrow_start, narrow_end = date(2026, 9, 1), date(2026, 9, 10)
    res = _overview(client, admin_headers, narrow_start, narrow_end)
    assert res.status_code == 200, res.text
    body = res.json()
    item = _item_of(body, budget_id)
    assert item["used"] == pytest.approx(100.0)
    # ช่วงของ "งบ" ในผลลัพธ์ต้องเป็นช่วงของตัวมันเอง ไม่ใช่ช่วงที่กรอง
    assert item["period_start"] == "2026-09-01"
    assert item["period_end"] == "2026-09-30"
    assert body["start_date"] == "2026-09-01"
    assert body["end_date"] == "2026-09-10"


async def test_overview_excludes_budget_that_does_not_overlap_filter(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                            start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))

    res = _overview(client, admin_headers, date(2026, 9, 1), date(2026, 9, 30))
    assert res.status_code == 200, res.text
    assert res.json()["items"] == []
    assert res.json()["total_budget"] == pytest.approx(0.0)


# =====================================================================
# 5) [DERIVED] usage_pct / is_over / is_near + period derivation
# =====================================================================


@pytest.mark.parametrize("amount,spent,expect_pct,expect_over,expect_near", [
    (1000.0, 0.0,    0.0,   False, False),
    (1000.0, 799.0,  79.9,  False, False),
    (1000.0, 800.0,  80.0,  False, True),    # ขอบล่างของ "ใกล้เต็ม"
    (1000.0, 1000.0, 100.0, False, True),    # ใช้พอดีไม่นับว่าเกิน
    (1000.0, 1000.5, 100.05, True, False),   # เกินแล้ว → is_over ชนะ
    (200.0,  500.0,  250.0, True,  False),
])
async def test_usage_flags(client, db_pool, admin_headers, amount, spent, expect_pct, expect_over, expect_near):
    """ตารางความจริงของ is_over/is_near — ใช้เท่างบพอดีต้องไม่ขึ้นเตือนสีแดง."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    acc = await _insert_account(db_pool, room_id, balance=10000.0)

    await _seed_legacy_tx(db_pool, room_id, category_id=cat, transaction_type="expense",
                          amount=spent, created_at=_thai_day_utc(date(2026, 9, 10)), account_id=acc)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                        category_id=cat, amount=amount, start_date=start, end_date=end)

    res = _overview(client, admin_headers, start, end)
    item = _item_of(res.json(), budget_id)
    assert item["usage_pct"] == pytest.approx(expect_pct)
    assert item["is_over"] is expect_over
    assert item["is_near"] is expect_near
    assert item["remaining"] == pytest.approx(amount - spent)


async def test_overview_totals_and_counts(client, db_pool, admin_headers):
    """ยอดรวมและตัวนับบนหัวหน้าจอ ต้องตรงกับผลรวมของ items เอง."""
    room_id = admin_headers.room_id
    cat_a = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    cat_b = await _insert_category(db_pool, room_id, "ค่าเดินทาง", "expense")
    acc = await _insert_account(db_pool, room_id, balance=10000.0)

    # A: ใช้ 1200/1000 → เกิน
    await _seed_legacy_tx(db_pool, room_id, category_id=cat_a, transaction_type="expense",
                          amount=1200.0, created_at=_thai_day_utc(date(2026, 9, 10)), account_id=acc)
    # B: ใช้ 900/1000 → ใกล้เต็ม (90%)
    await _seed_legacy_tx(db_pool, room_id, category_id=cat_b, transaction_type="expense",
                          amount=900.0, created_at=_thai_day_utc(date(2026, 9, 11)), account_id=acc)

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    await _create_budget_ok(client, db_pool, admin_headers, category_id=cat_a, amount=1000,
                            start_date=start, end_date=end)
    await _create_budget_ok(client, db_pool, admin_headers, category_id=cat_b, amount=1000,
                            start_date=start, end_date=end)

    body = _overview(client, admin_headers, start, end).json()
    assert body["total_budget"] == pytest.approx(2000.0)
    assert body["total_used"] == pytest.approx(2100.0)
    assert body["over_count"] == 1
    assert body["warning_count"] == 1
    assert len(body["items"]) == 2


@pytest.mark.parametrize("start,end,expect_type,expect_year,expect_month", [
    (date(2026, 9, 1),  date(2026, 9, 30),  "monthly", 2026, 9),
    (date(2026, 2, 1),  date(2026, 2, 28),  "monthly", 2026, 2),   # ก.พ. ปีปกติ
    (date(2028, 2, 1),  date(2028, 2, 29),  "monthly", 2028, 2),   # ก.พ. ปีอธิกสุรทิน
    (date(2026, 12, 1), date(2026, 12, 31), "monthly", 2026, 12),  # ขอบเดือนสุดท้ายของปี
    (date(2026, 1, 1),  date(2026, 12, 31), "yearly",  2026, None),
    (date(2026, 9, 5),  date(2026, 9, 20),  "custom",  2026, None),
    (date(2026, 9, 1),  date(2026, 10, 31), "custom",  2026, None),  # 2 เดือน = custom
])
async def test_derive_period(start, end, expect_type, expect_year, expect_month):
    """`_derive_period` เป็น pure function — เทสต์ตรง ๆ ได้ ไม่ต้องแตะ DB.

    (ประกาศเป็น async เฉย ๆ เพราะทั้งไฟล์ถูก mark `pytest.mark.asyncio` ผ่าน `pytestmark`
     — ถ้าปล่อยเป็น sync จะได้ PytestWarning ทุกเคสโดยไม่ได้อะไรกลับมา)
    """
    assert FinanceService._derive_period(start, end) == (expect_type, expect_year, expect_month)


async def test_period_columns_are_derived_not_client_supplied(client, db_pool, admin_headers):
    """คอลัมน์ period_* ใน DB ต้องตรงกับช่วงวันที่จริง (client ไม่มีช่องส่งมาอยู่แล้ว)."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    for start, end, expect in (
        (date(2026, 9, 1), date(2026, 9, 30), ("monthly", 2026, 9)),
        (date(2026, 1, 1), date(2026, 12, 31), ("yearly", 2026, None)),
        (date(2026, 9, 5), date(2026, 9, 20), ("custom", 2026, None)),
    ):
        # หมวดใหม่ทุกครั้งเพื่อเลี่ยง unique index (room, category, start, end)
        c = await _insert_category(db_pool, room_id, f"หมวด {start}-{end}", "expense")
        budget_id = await _create_budget_ok(client, db_pool, admin_headers,
                                            category_id=c, amount=100, start_date=start, end_date=end)
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT period_type, period_year, period_month FROM finance_budgets WHERE id = $1",
                budget_id,
            )
        assert (row["period_type"], row["period_year"], row["period_month"]) == expect


# =====================================================================
# 6) [CRUD] สร้าง / อ่าน / แก้ / ลบ
# =====================================================================


async def test_create_budget_returns_and_persists(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    res = _create_budget(client, admin_headers, category_id=cat, amount=1500.0,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), note="งบเดือน ก.ย.")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "success"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT category_id, amount, start_date, end_date, note, created_by, deleted_at
               FROM finance_budgets WHERE room_id = $1""",
            room_id,
        )
    assert row["category_id"] == cat
    assert float(row["amount"]) == pytest.approx(1500.0)
    assert row["start_date"] == date(2026, 9, 1)
    assert row["end_date"] == date(2026, 9, 30)
    assert row["note"] == "งบเดือน ก.ย."
    assert row["created_by"] == admin_headers.user_id
    assert row["deleted_at"] is None


async def test_create_budget_writes_audit_log(client, db_pool, admin_headers):
    """Deep verification: audit ต้องถูกเขียนใน transaction เดียวกัน พร้อม new_values."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1500.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    async with db_pool.acquire() as conn:
        log = await conn.fetchrow(
            """SELECT action, entity_type, entity_id, status, new_values, user_id
               FROM audit_logs
               WHERE entity_type = 'FINANCE_BUDGET' AND entity_id = $1 AND action = 'CREATE'""",
            str(budget_id),
        )
    assert log is not None, "ต้องมี audit log ของการสร้างงบ"
    assert log["status"] == "success"
    assert log["user_id"] == admin_headers.user_id
    # ⚠️ JSONB กลับมาจาก asyncpg เป็น **สตริง** (ไม่มี codec registered ที่ pool) → ต้อง json.loads เอง
    new_values = json.loads(log["new_values"])
    assert float(new_values["amount"]) == pytest.approx(1500.0)
    assert new_values["budget_id"] == budget_id


async def test_list_budgets_returns_joined_category_info(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1200.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), note="n")

    res = client.get(_url(BUDGETS_PATH, room_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == budget_id
    assert row["category_name"] == "ค่าอาหาร"
    assert row["category_type"] == "expense"
    assert row["amount"] == pytest.approx(1200.0)
    assert row["period_type"] == "monthly"
    assert row["period_year"] == 2026
    assert row["period_month"] == 9
    assert row["note"] == "n"
    assert row["created_by_name"] == "Test User"


async def test_list_budgets_filters_by_overlap_and_category_type(client, db_pool, admin_headers):
    """กรองแบบ overlap (ไม่ใช่ containment) + กรองประเภทหมวดได้."""
    room_id = admin_headers.room_id
    exp = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    inc = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    # งบคร่อมขอบ: 1 มิ.ย. – 31 ต.ค. → ต้องโผล่แม้กรองแค่เดือน ก.ย.
    await _create_budget_ok(client, db_pool, admin_headers, category_id=exp, amount=5000,
                            start_date=date(2026, 6, 1), end_date=date(2026, 10, 31))
    # งบที่จบก่อนหน้าต่าง → ต้องไม่โผล่
    await _create_budget_ok(client, db_pool, admin_headers, category_id=inc, amount=1000,
                            start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))

    res = client.get(
        _url(BUDGETS_PATH, room_id),
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["category_name"] for r in rows] == ["ค่าอาหาร"]

    res = client.get(_url(BUDGETS_PATH, room_id), params={"category_type": "income"}, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert [r["category_name"] for r in res.json()] == ["เงินบริจาค"]

    res = client.get(_url(BUDGETS_PATH, room_id), params={"category_type": "bogus"}, headers=admin_headers)
    assert res.status_code == 422


async def test_update_budget_amount_only_leaves_other_columns_untouched(client, db_pool, admin_headers):
    """🎯 พิสูจน์ `model_dump(exclude_unset=True)` — ส่งแค่ amount แล้วคอลัมน์อื่นต้องนิ่ง."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), note="เดิม")

    res = client.patch(
        _url(BUDGET_PATH, room_id, budget_id=budget_id),
        json={"amount": 2500.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT amount, start_date, end_date, note, period_type, period_year, period_month
               FROM finance_budgets WHERE id = $1""",
            budget_id,
        )
    assert float(row["amount"]) == pytest.approx(2500.0)
    assert row["start_date"] == date(2026, 9, 1)
    assert row["end_date"] == date(2026, 9, 30)
    assert row["note"] == "เดิม"
    assert (row["period_type"], row["period_year"], row["period_month"]) == ("monthly", 2026, 9)


async def test_update_budget_period_is_rederived_when_dates_change(client, db_pool, admin_headers):
    """🎯 แก้วันที่แล้วป้าย period ต้องไม่ค้างเดือนเดิม (เหตุผลที่ derive ฝั่ง service)."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = client.patch(
        _url(BUDGET_PATH, room_id, budget_id=budget_id),
        json={"start_date": "2026-01-01", "end_date": "2026-12-31", "user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT period_type, period_year, period_month FROM finance_budgets WHERE id = $1", budget_id
        )
    assert (row["period_type"], row["period_year"], row["period_month"]) == ("yearly", 2026, None)


async def test_update_budget_writes_audit_with_old_and_new(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = client.patch(
        _url(BUDGET_PATH, room_id, budget_id=budget_id),
        json={"amount": 3000.0, "user_name": "Tester"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        log = await conn.fetchrow(
            """SELECT old_values, new_values FROM audit_logs
               WHERE entity_type = 'FINANCE_BUDGET' AND entity_id = $1 AND action = 'UPDATE'""",
            str(budget_id),
        )
    assert log is not None
    # JSONB → สตริง (ดูหมายเหตุในเทสต์ CREATE ด้านบน)
    assert float(json.loads(log["old_values"])["amount"]) == pytest.approx(1000.0)
    assert float(json.loads(log["new_values"])["amount"]) == pytest.approx(3000.0)


async def test_delete_budget_is_soft_and_row_survives(client, db_pool, admin_headers):
    """🎯 ห้ามลอก `delete_category` (hard delete) — งบที่ลบต้องยังตรวจย้อนได้."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000.0,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = client.request("DELETE", _url(BUDGET_PATH, room_id, budget_id=budget_id),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deleted_at, amount FROM finance_budgets WHERE id = $1", budget_id
        )
    assert row is not None, "แถวต้องยังอยู่ (soft delete ไม่ใช่ DELETE)"
    assert row["deleted_at"] is not None
    assert float(row["amount"]) == pytest.approx(1000.0)

    # หายจากรายการและจาก overview
    assert client.get(_url(BUDGETS_PATH, room_id), headers=admin_headers).json() == []
    body = _overview(client, admin_headers, date(2026, 9, 1), date(2026, 9, 30)).json()
    assert body["items"] == []


# =====================================================================
# 7) [GUARDS] validation, unique, 404, category ownership
# =====================================================================


@pytest.mark.parametrize("amount", [0, -1, -100.5])
async def test_create_budget_rejects_non_positive_amount(client, db_pool, admin_headers, amount):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    res = _create_budget(client, admin_headers, category_id=cat, amount=amount,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 422, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_budgets WHERE room_id = $1", room_id) == 0


async def test_create_budget_rejects_reversed_period(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    res = _create_budget(client, admin_headers, category_id=cat, amount=1000,
                         start_date=date(2026, 9, 30), end_date=date(2026, 9, 1))
    assert res.status_code == 422, res.text
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_budgets WHERE room_id = $1", room_id) == 0


async def test_create_budget_rejects_category_of_another_room(client, db_pool, admin_headers, member_headers):
    """หมวดของห้องอื่น → 400 (ไม่ใช่ 200 ที่สร้างงบข้ามห้อง)."""
    other_cat = await _insert_category(db_pool, member_headers.room_id, "ของห้องอื่น", "expense")

    res = _create_budget(client, admin_headers, category_id=other_cat, amount=1000,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_budgets WHERE category_id = $1", other_cat
        ) == 0


async def test_create_budget_rejects_unknown_category(client, db_pool, admin_headers):
    res = _create_budget(client, admin_headers, category_id=999999, amount=1000,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 400, res.text


async def test_create_budget_duplicate_period_is_400_and_writes_one_row(client, db_pool, admin_headers):
    """partial unique index ต้องถูกแปลงเป็น 400 ที่อ่านรู้เรื่อง ไม่ใช่ 500 ดิบ."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = _create_budget(client, admin_headers, category_id=cat, amount=2000,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 400, res.text
    assert "มีงบประมาณของหมวดนี้ในช่วงเวลานี้อยู่แล้ว" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_budgets WHERE room_id = $1 AND category_id = $2 AND deleted_at IS NULL",
            room_id, cat,
        )
    assert count == 1


async def test_soft_deleted_budget_frees_the_period_for_reuse(client, db_pool, admin_headers):
    """🎯 เหตุผลที่ unique index เป็น **partial** (`WHERE deleted_at IS NULL`).

    ถ้าไม่ partial การลบงบแล้วตั้งใหม่ช่วงเดิมจะทำไม่ได้ตลอดกาล
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    first = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                                    start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    client.request("DELETE", _url(BUDGET_PATH, room_id, budget_id=first),
                   json={"user_name": "Tester"}, headers=admin_headers)

    res = _create_budget(client, admin_headers, category_id=cat, amount=2000,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        alive = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_budgets
               WHERE room_id = $1 AND category_id = $2 AND deleted_at IS NULL""",
            room_id, cat,
        )
    assert alive == 1


async def test_update_and_delete_missing_budget_404(client, db_pool, admin_headers):
    url = _url(BUDGET_PATH, admin_headers.room_id, budget_id=999999)
    assert client.patch(url, json={"amount": 10.0, "user_name": "T"},
                        headers=admin_headers).status_code == 404
    assert client.request("DELETE", url, json={"user_name": "T"},
                          headers=admin_headers).status_code == 404


async def test_update_budget_reversed_effective_period_is_400(client, db_pool, admin_headers):
    """🎯 PATCH ส่งมาแค่ `start_date` ตัวเดียว — ต้องเทียบกับ `end_date` ที่มีอยู่ใน DB.

    Pydantic ตรวจไม่ได้ (ไม่รู้ค่าอีกฝั่ง) ⇒ service ต้องตรวจอีกชั้นแล้วคืน 400 ไม่ใช่ 500
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = client.patch(_url(BUDGET_PATH, room_id, budget_id=budget_id),
                       json={"start_date": "2026-12-01", "user_name": "Tester"},
                       headers=admin_headers)
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT start_date FROM finance_budgets WHERE id = $1", budget_id)
    assert row["start_date"] == date(2026, 9, 1), "ค่าต้องไม่ถูกแก้เมื่อ validation ล้มเหลว"


async def test_update_budget_cross_room_is_404(client, db_pool, admin_headers, finance_manager_headers):
    """งบของห้องอื่นต้องหาไม่เจอ (404) — ไม่ใช่แก้ข้ามห้องได้.

    ⚠️ ต้องใช้ `finance_manager_headers` (มี MANAGE_FINANCE) ในการสร้างงบฝั่ง "ห้องอื่น"
    ไม่ใช่ `member_headers` — ถ้าใช้ member การสร้างจะได้ 403 ตั้งแต่ต้น แล้วเทสต์จะ
    ตายที่ helper แทนที่จะได้ทดสอบเรื่อง cross-room จริง ๆ
    """
    other_cat = await _insert_category(db_pool, finance_manager_headers.room_id, "ของห้องอื่น", "expense")
    other_budget = await _create_budget_ok(client, db_pool, finance_manager_headers, category_id=other_cat,
                                           amount=1000, start_date=date(2026, 9, 1),
                                           end_date=date(2026, 9, 30))

    res = client.patch(_url(BUDGET_PATH, admin_headers.room_id, budget_id=other_budget),
                       json={"amount": 1.0, "user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 404, res.text

    async with db_pool.acquire() as conn:
        amount = await conn.fetchval("SELECT amount FROM finance_budgets WHERE id = $1", other_budget)
    assert float(amount) == pytest.approx(1000.0)


async def test_overview_reversed_range_is_400(client, db_pool, admin_headers):
    res = _overview(client, admin_headers, date(2026, 9, 30), date(2026, 9, 1))
    assert res.status_code == 400, res.text


async def test_overview_requires_both_dates(client, db_pool, admin_headers):
    res = client.get(_url(OVERVIEW_PATH, admin_headers.room_id),
                     params={"start_date": "2026-09-01"}, headers=admin_headers)
    assert res.status_code == 422


# =====================================================================
# 8) [RBAC]
# =====================================================================


async def test_member_can_read_but_not_write(client, db_pool, member_headers):
    """สมาชิกธรรมดา: อ่านได้ (require_member) แต่เขียนไม่ได้ (require_permission) → 403.

    ⚠️ สำคัญ: ต้องยืนยัน **DB ไม่เปลี่ยน** ไม่ใช่ดูแค่ status code
    """
    room_id = member_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    # อ่านได้ (ทั้งสอง endpoint)
    assert client.get(_url(BUDGETS_PATH, room_id), headers=member_headers).status_code == 200
    assert _overview(client, member_headers, date(2026, 9, 1), date(2026, 9, 30)).status_code == 200

    # เขียนไม่ได้
    res = _create_budget(client, member_headers, category_id=cat, amount=1000,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    assert res.status_code == 403, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_budgets WHERE room_id = $1", room_id) == 0


async def test_finance_manager_can_write_even_without_admin(client, db_pool, finance_manager_headers):
    """🎯 เหรัญญิก (`MANAGE_FINANCE`, `is_admin = FALSE`) ต้องเขียนได้จริง.

    เทสต์นี้แยกจาก admin โดยเจตนา — ถ้าใช้ admin เทสต์จะผ่านเพราะ is_admin bypass
    ไม่ได้พิสูจน์ว่า `require_permission` ทำงาน
    """
    room_id = finance_manager_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    budget_id = await _create_budget_ok(client, db_pool, finance_manager_headers, category_id=cat,
                                        amount=1000, start_date=date(2026, 9, 1),
                                        end_date=date(2026, 9, 30))
    assert budget_id is not None

    res = client.patch(_url(BUDGET_PATH, room_id, budget_id=budget_id),
                       json={"amount": 2000.0, "user_name": "Treasurer"}, headers=finance_manager_headers)
    assert res.status_code == 200, res.text

    res = client.request("DELETE", _url(BUDGET_PATH, room_id, budget_id=budget_id),
                         json={"user_name": "Treasurer"}, headers=finance_manager_headers)
    assert res.status_code == 200, res.text


async def test_non_member_gets_403_on_all_budget_routes(client, db_pool, admin_headers, member_headers):
    """คนนอกห้อง (ไม่ใช่สมาชิก) → 403 ทุก route ทั้งอ่านและเขียน."""
    other_cat = await _insert_category(db_pool, admin_headers.room_id, "ของห้อง ก", "expense")
    other_budget = await _create_budget_ok(client, db_pool, admin_headers, category_id=other_cat,
                                           amount=1000, start_date=date(2026, 9, 1),
                                           end_date=date(2026, 9, 30))

    room = admin_headers.room_id   # member_headers ไม่ได้เป็นสมาชิกห้องนี้
    assert client.get(_url(BUDGETS_PATH, room), headers=member_headers).status_code == 403
    res = client.get(
        _url(OVERVIEW_PATH, room),
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
        headers=member_headers,
    )
    assert res.status_code == 403, res.text
    assert client.post(_url(BUDGETS_PATH, room),
                       json={"category_id": other_cat, "amount": 1.0, "start_date": "2026-09-01",
                             "end_date": "2026-09-30", "user_name": "X"},
                       headers=member_headers).status_code == 403
    assert client.patch(_url(BUDGET_PATH, room, budget_id=other_budget),
                        json={"amount": 1.0, "user_name": "X"}, headers=member_headers).status_code == 403
    assert client.request("DELETE", _url(BUDGET_PATH, room, budget_id=other_budget),
                          json={"user_name": "X"}, headers=member_headers).status_code == 403


async def test_overview_of_room_that_does_not_exist_is_404(client, db_pool, admin_headers):
    res = client.get(
        _url(OVERVIEW_PATH, 99999999),
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# =====================================================================
# 9) [delete_category companion] FK RESTRICT ต้องไม่กลายเป็น 500
# =====================================================================


async def test_delete_category_blocked_when_budget_exists(client, db_pool, admin_headers):
    """🎯 กัน `ForeignKeyViolationError` ดิบทะลุเป็น 500 — ต้องได้ 400 ที่อ่านรู้เรื่อง."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    res = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert "งบประมาณ" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE id = $1", cat) == 1


async def test_delete_category_still_blocked_after_budget_soft_deleted(client, db_pool, admin_headers):
    """🎯 ลบงบ (soft) แล้วลบหมวด **ยังต้องไม่ได้ 400** — ไม่ใช่ 500 จาก FK.

    นี่คือเคสที่เทสต์ชุดนี้เคยจับบั๊กได้จริง: guard เวอร์ชันแรกกรอง `deleted_at IS NULL`
    ⇒ งบที่ถูกลบแล้วหลุดจาก guard → ไปชน `ON DELETE RESTRICT` ของ FK →
    `ForeignKeyViolationError` ทะลุเป็น HTTP 500 ที่ผู้ใช้อ่านไม่รู้เรื่อง
    (และหน้าจอก็ไม่เหลือร่องรอยงบให้เห็นด้วย ⇒ ยิ่งงงหนัก)

    สัญญาที่ถูกต้อง: FK เป็น NOT NULL + RESTRICT ⇒ หมวดที่ **เคย** มีงบ ลบไม่ได้ตลอดกาล
    guard จึงต้องนับทุกแถวให้ตรงกับ FK
    """
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _create_budget_ok(client, db_pool, admin_headers, category_id=cat, amount=1000,
                                        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    res = client.request("DELETE", _url(BUDGET_PATH, room_id, budget_id=budget_id),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        # ยืนยันว่าแถวยังอยู่จริง (soft delete) — นี่คือเหตุผลที่ FK ยังทำงาน
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_budgets WHERE id = $1", budget_id) == 1

    res = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert "งบประมาณ" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE id = $1", cat) == 1


# =====================================================================
# 10) delete_category = SOFT delete (เปลี่ยนจาก hard delete เมื่อ 2026-09-13)
# =====================================================================
#
# เดิม `delete_category` ยิง `DELETE FROM finance_categories` ตรง ๆ ⇒ แม้ guard จะกัน
# หมวดที่มีรายการ/งบไว้แล้ว แต่หมวดที่ "สร้างผิดแล้วยังไม่เคยใช้" ยังถูกลบถาวร
# ซึ่งตัดสาย `accounting_ledgers.legacy_category_id` (FK `ON DELETE SET NULL`) ทิ้ง
# ⇒ ledger กลายเป็น orphan และสร้างหมวดชื่อเดิมใหม่จะได้ ledger รหัสใหม่ซ้อนขึ้นมา
#
# ปลอดภัยเพราะ guard สองตัวใน service รับประกันว่าหมวดที่จะถูกลบไม่มีทั้ง
# `finance_transactions` และ `finance_budgets` ผูกอยู่ ⇒ พฤติกรรมเดียวที่เปลี่ยน
# คือการหายไปจาก `GET /finance/categories`


async def test_delete_category_is_soft_and_row_survives(client, db_pool, admin_headers):
    """🎯 ลบหมวดแล้วแถวต้องยังอยู่ + `deleted_at NOT NULL` — ไม่ใช่หายไปจากตาราง."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "หมวดที่สร้างผิด", "expense")

    res = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, category_name, category_type, deleted_at FROM finance_categories WHERE id = $1", cat
        )
        assert row is not None, "แถวหายไป = ยังเป็น hard delete อยู่"
        assert row["deleted_at"] is not None
        # ชื่อ/ประเภท ยังครบ — ประวัติที่อ้างหมวดนี้ต้องเล่าได้เหมือนเดิม
        assert row["category_name"] == "หมวดที่สร้างผิด"
        assert row["category_type"] == "expense"


async def test_soft_deleted_category_disappears_from_category_list(client, db_pool, admin_headers):
    """🎯 หมวดที่ลบแล้วต้องหลุดจาก `GET /finance/categories` — ไม่ใช่แค่ซ่อนฝั่ง frontend.

    ถ้ากรองแค่ฝั่ง UI ผู้ใช้จะยังเลือกหมวดนี้ได้จากที่อื่น แล้วสร้างรายการผูกกับหมวดที่มองไม่เห็น
    """
    room_id = admin_headers.room_id
    alive = await _insert_category(db_pool, room_id, "ยังใช้อยู่", "expense")
    dead = await _insert_category(db_pool, room_id, "ลบแล้ว", "expense")

    res = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=dead),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 200, res.text

    res = client.request("GET", _url(CATEGORIES_PATH, room_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    ids = [c["id"] for c in res.json()]
    assert alive in ids, "หมวดที่ยังไม่ถูกลบต้องยังอยู่"
    assert dead not in ids, "หมวดที่ถูกลบต้องไม่โผล่"

    # 🛡️ และต้องกรองที่ระดับ SQL จริง ไม่ใช่ถูกตัดทิ้งที่ชั้นอื่น
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE id = $1", dead) == 1


async def test_delete_category_twice_is_404_and_keeps_first_timestamp(client, db_pool, admin_headers):
    """🎯 ลบซ้ำต้องไม่สำเร็จเงียบ ๆ และ **ห้ามทับเวลาเดิม** (`AND deleted_at IS NULL` มีไว้เพื่อนี้)."""
    room_id = admin_headers.room_id
    cat = await _insert_category(db_pool, room_id, "ลบสองรอบ", "expense")

    first = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                           json={"user_name": "Tester"}, headers=admin_headers)
    assert first.status_code == 200, first.text

    async with db_pool.acquire() as conn:
        stamp1 = await conn.fetchval("SELECT deleted_at FROM finance_categories WHERE id = $1", cat)

    second = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                            json={"user_name": "Tester"}, headers=admin_headers)
    assert second.status_code == 404, second.text

    async with db_pool.acquire() as conn:
        stamp2 = await conn.fetchval("SELECT deleted_at FROM finance_categories WHERE id = $1", cat)
    assert stamp2 == stamp1, "deleted_at ถูกเขียนทับ = การลบไม่ idempotent"


async def test_soft_deleted_category_cannot_receive_new_transaction(client, db_pool, admin_headers):
    """🎯 หมวดที่ลบแล้วต้องสร้างรายการใหม่ไม่ได้ — 400 ไม่ใช่ 500 และ **ไม่มีแถวถูกเขียน**."""
    room_id = admin_headers.room_id
    acc = await _insert_account(db_pool, room_id, "กระเป๋ากลาง", balance=10000.0)
    cat = await _insert_category(db_pool, room_id, "หมวดที่จะลบ", "expense")

    res = client.request("DELETE", _url(CATEGORY_PATH, room_id, category_id=cat),
                         json={"user_name": "Tester"}, headers=admin_headers)
    assert res.status_code == 200, res.text

    res = client.request("POST", _url(TRANSACTIONS_PATH, room_id), headers=admin_headers, json={
        "account_id": acc, "category_id": cat, "amount": 100.0,
        "description": "ลองผูกหมวดที่ลบแล้ว", "transaction_type": "expense", "user_name": "Tester",
    })
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id
        ) == 0, "ต้องไม่มีแถวถูกเขียนเลย"


async def test_default_income_category_is_recreated_not_resurrected(db_pool, admin_headers):
    """🎯 หมวดรายได้เริ่มต้นที่ถูกลบ ต้องถูก **สร้างใหม่** ไม่ใช่ถูก "ฟื้น" กลับมาใช้.

    นี่คือบั๊กที่การเปลี่ยนเป็น soft delete จะสร้างขึ้นมาถ้าไม่กรอง `deleted_at IS NULL`
    ใน `_find_or_create_default_income_category`: ฟังก์ชัน find-or-create จะ SELECT
    เจอแถวที่ถูกลบ → คืน id นั้น → `confirm_payment` หลังจากนั้น dual-write ลง ledger
    ของหมวดที่ผู้ใช้ลบไปแล้ว แต่หมวดนั้นไม่โผล่ใน `get_categories` ⇒ เงินเข้าแต่หาหมวดไม่เจอ

    ⚠️ subquery ของ `WHERE NOT EXISTS` ก็ต้องกรองด้วย ไม่งั้นมันจะเห็นหมวดที่ลบว่า "มีอยู่"
    แล้วไม่ยอม INSERT → ตกไปคืน id ของหมวดที่ถูกลบเหมือนกัน
    """
    room_id = admin_headers.room_id
    async with db_pool.acquire() as conn:
        first = await FinanceService._find_or_create_default_income_category(conn, room_id)
        assert first is not None

        await conn.execute("UPDATE finance_categories SET deleted_at = NOW() WHERE id = $1", first)

        second = await FinanceService._find_or_create_default_income_category(conn, room_id)
        assert second is not None

    assert second != first, "คืน id ของหมวดที่ลบไปแล้ว = หมวดซอมบี้"

    async with db_pool.acquire() as conn:
        # แถวใหม่ต้องยังไม่ถูกลบ
        assert await conn.fetchval("SELECT deleted_at FROM finance_categories WHERE id = $1", second) is None
        # และแถวเก่าต้องยังอยู่ (soft delete) พร้อมชื่อเดิม
        old = await conn.fetchrow(
            "SELECT category_name, deleted_at FROM finance_categories WHERE id = $1", first
        )
        assert old is not None and old["deleted_at"] is not None
        assert old["category_name"] == DEFAULT_INCOME_CATEGORIES[0]
        # ต้องมีสองแถวชื่อเดียวกันจริง (แถวเก่าที่ลบ + แถวใหม่) — ไม่ใช่เขียนทับ
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_categories WHERE room_id = $1 AND category_name = $2",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        ) == 2
