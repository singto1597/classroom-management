"""
Edge-case & bug-regression tests for FinanceService.

ครอบคลุมบั๊กที่ชุดเทสเดิม (test_finance.py) ยังไม่จับ:
  BUG-1  Decimal vs float comparison:
         - add_transaction:  balance=Decimal('0.1'), amount=0.1 (float) → Decimal < float = True
           → เงินพอแต่ระบบห้ามตัดเงิน (false insufficient)  [finance_service.py L165]
         - update_collection: current=Decimal('1000.1') != 1000.1 (float) = True
           → เปลี่ยนค่าเท่าเดิมก็ถือว่า "เปลี่ยน" → ห้ามแก้  [L908]
         - revert_transaction:  curr_bal=Decimal('0.1') < amount=0.1 (float) = True
           → ห้าม revert ทั้งที่เงินพอ  [L656/L663]
  BUG-2  add_student_to_collection ไม่เช็ค students.status='active'
         → เพิ่มนักเรียน pending/left เข้าแคมเปญเก็บเงินได้
  BUG-3  delete_account hard-delete → finance_transactions.account_id = NULL (ประวัติหาย)
         (delete_category เช็ค finance_transactions แต่ delete_account ไม่เช็คเลย)
  BUG-4  create_fee_collection student_ids ซ้ำกัน → UniqueViolation 500 แทน 400
  BUG-5  get_summary month โดยไม่มี year → params ผิดตำแหน่ง SQL error 500
  BUG-6  confirm_payment รับเงินแคมเปญที่ status='closed' ได้
  BUG-7  revert income ที่มาจาก confirm_payment: student_payments.status paid→pending,
         paid_at/transaction_id/slip/recorded_by ต้องถูก rollback ครบ

เทสเหล่านี้ใช้ pattern เดียวกับ test_finance.py: service-level, RBAC จริง, deep-DB verify
"""
import random
import string
import uuid
from datetime import date, datetime

import pytest

from core.exceptions import (
    ForbiddenError,
    PaymentNotFoundError,
    RoomNotFoundError,
    TransactionNotFoundError,
)
from models.finance_schemas import (
    AccountCreate,
    CategoryCreate,
    FeeCollectionCreate,
    FeeCollectionUpdate,
    PaymentConfirm,
    TransactionCreate,
    TransferCreate,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Shared helpers (same as test_finance.py) ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", username=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            email, first_name, last_name, username,
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
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(
    pool, room_id: int, user_id: int, student_no: int,
    *, status="active", is_admin=False, permissions="[]",
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
            room_id, user_id, student_no, final_status, is_admin, permissions,
        )


async def _insert_finance_account(pool, room_id: int, account_name="กระเป๋ากลาง", balance=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_accounts (room_id, account_name, balance)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, account_name, balance,
        )


async def _insert_category(pool, room_id: int, category_name="ค่าอาหาร", category_type="expense") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_categories (room_id, category_name, category_type)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, category_name, category_type,
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


async def _insert_student_payment(
    pool, collection_id: int, student_id: int, status="pending", paid_amount=0.0, paid_to_account_id=None,
    *, slip_image_url=None, recorded_by=None, paid_at=None, transaction_id=None,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments
                (collection_id, student_id, status, paid_amount, paid_to_account_id, slip_image_url, recorded_by, paid_at, transaction_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            collection_id, student_id, status, paid_amount, paid_to_account_id,
            slip_image_url, recorded_by, paid_at, transaction_id,
        )


async def _insert_transaction(
    pool, room_id: int, account_id: int, amount: float, transaction_type: str = "income",
    category_id=None, description="test", recorded_by="Owner",
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, description, transaction_type, recorded_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            room_id, account_id, category_id, amount, description, transaction_type, recorded_by,
        )


async def _fetch_balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id))


async def _fetch_account_row(pool, account_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1", account_id)


# =====================================================================
# BUG-1: Decimal vs float เปรียบเทียบ
# =====================================================================


async def test_add_expense_allowed_when_decimal_balance_slightly_higher(db_pool):
    """
    BUG-1 regression: balance=Decimal('0.1'), amount=0.1 (float).
    Decimal('0.1') < 0.1 = True → โค้ดเดิม raise "เงินไม่พอ!" ทั้งที่เงินพอเป๊ะ ๆ
    (ผลลัพธ์ที่ถูกต้อง: ตัดเงินได้)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    # ฝากเงิน 0.1 เข้าบัญชีโดยตรง (ผ่าน float param = ค่าเดียวกับ amount ที่ client จะส่ง)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = $1 WHERE id = $2", 0.1, account_id)

    # ถ้าบั๊ก Decimal vs float ยังมีอยู่: Decimal('0.1') < 0.1 = True → จะ raise "เงินไม่พอ!"
    result = await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=0.1,
            description="ซื้อของ 10 สตางค์", transaction_type="expense", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def test_add_expense_allowed_when_decimal_balance_1_1_amount_1_1(db_pool):
    """Decimal('1.1') < 1.1 = True → โค้ดเดิมห้ามตัดเงิน ทั้งที่เงินพอ"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = $1 WHERE id = $2", 1.1, account_id)

    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=1.1,
            description="ใช้เงินสตางค์", transaction_type="expense", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def test_add_expense_still_blocked_when_truly_insufficient(db_pool):
    """Sanity: บั๊ก Decimal/float ต้องไม่ไปทำให้ false-negative (ยอมให้ติดลบ)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = 0.05 WHERE id = $1", account_id)

    with pytest.raises(ValueError):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(
                account_id=account_id, category_id=cat_id, amount=0.1,
                description="เกินจริง", transaction_type="expense", user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.05)


async def test_update_collection_same_amount_not_treated_as_change(db_pool):
    """
    BUG-1 regression: update_collection เปรียบเทียบ `req.amount != current_data['amount']`
    ต้อง cast Decimal(str(...)) ทั้งสองฝั่ง — ไม่งั้น float 1000.1 กับ DECIMAL(1000.1) ไม่เท่ากัน
    → ส่ง amount ค่าเดิม (เท่ากับที่เก็บไว้) ต้องไม่ถูกห้ามแม้มีคนจ่ายไปแล้ว
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.1)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 300.0)

    # ดึง amount ที่เก็บจริงใน DB (Decimal('1000.1')) แล้วส่งค่าที่แปลงเป็น float กลับไป
    async with db_pool.acquire() as conn:
        db_amount = await conn.fetchval("SELECT amount FROM fee_collections WHERE id = $1", collection_id)
    assert float(db_amount) == pytest.approx(1000.1)

    # ส่ง amount = ค่าที่เท่ากับของเดิม (เป็น float 1000.1) → ต้องไม่ถูกห้าม
    result = await FinanceService.update_collection(
        pool=db_pool, collection_id=collection_id,
        req=FeeCollectionUpdate(amount=1000.1, user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT amount FROM fee_collections WHERE id = $1", collection_id)
        assert float(row["amount"]) == pytest.approx(1000.1)


async def test_update_collection_amount_change_still_blocked_after_payment(db_pool):
    """Sanity: การเปลี่ยน amount จริงหลังมีเงินโอนต้องยังถูกห้าม"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 300.0)

    with pytest.raises(ValueError):
        await FinanceService.update_collection(
            pool=db_pool, collection_id=collection_id,
            req=FeeCollectionUpdate(amount=1500.0, user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_revert_income_allowed_when_balance_decimal_equal_amount(db_pool):
    """
    BUG-1 regression: revert_transaction L663 `curr_bal < t['amount']`
    balance = amount เท่ากัน → ต้องหักคืนได้ (ไม่ raise "ไม่พอหักคืน")
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 0.1, "income", cat_id)
    # balance = amount เดียวกัน (ผ่าน float param เหมือน asyncpg เก็บใน transaction)
    # → เงินที่รับเข้ายังอยู่ครบ เท่ากับจำนวนที่จะหักคืนเป๊ะ ๆ
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = $1 WHERE id = $2", 0.1, account_id)

    result = await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=tx_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def test_revert_income_still_blocked_when_truly_insufficient(db_pool):
    """Sanity: หักคืนไม่ได้จริง ๆ (balance ต่ำกว่า) ต้องยังโดนห้าม"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 0.1, "income", cat_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = 0.09 WHERE id = $1", account_id)

    with pytest.raises(ValueError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=tx_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


# =====================================================================
# BUG-2: add_student_to_collection ไม่เช็ค students.status
# =====================================================================


async def test_add_pending_student_to_collection_is_blocked(db_pool):
    """
    BUG-2 regression: add_student_to_collection ต้องเช็ค status='active'
    ปัจจุบันเพิ่ม pending student เข้าแคมเปญได้ (ผิด) — ต้องถูกห้าม
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    pending_student = await _insert_student(
        db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Pending"),
        1, status="pending",
    )
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    # ตรรกะที่ถูกต้อง: student ไม่ใช่ active → ต้องโดนห้าม (RoomNotFoundError หรือ ValueError)
    # ปัจจุบัน (ยังไม่ได้แก้): insert สำเร็จ — เทสนี้ FAIL เพื่อ flag bug
    with pytest.raises((ValueError, RoomNotFoundError)):
        await FinanceService.add_student_to_collection(
            pool=db_pool, collection_id=collection_id, student_id=pending_student,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )

    # deep verify: ต้องไม่มี student_payments เกิดขึ้นเลย
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            collection_id, pending_student,
        )
    assert sp is None, "BUG: add_student_to_collection รับ pending student เข้าแคมเปญได้"


async def test_add_left_student_to_collection_is_blocked(db_pool):
    """นักเรียนที่ลาออก (left) ก็ต้องโดนห้ามเหมือนกัน"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    left_student = await _insert_student(
        db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Left"),
        1, status="left",
    )
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    with pytest.raises((ValueError, RoomNotFoundError)):
        await FinanceService.add_student_to_collection(
            pool=db_pool, collection_id=collection_id, student_id=left_student,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )

    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            collection_id, left_student,
        )
    assert sp is None, "BUG: add_student_to_collection รับ left student เข้าแคมเปญได้"


async def test_add_active_student_to_collection_ok(db_pool):
    """Sanity: active student ยังเพิ่มได้ตามปกติ"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    result = await FinanceService.add_student_to_collection(
        pool=db_pool, collection_id=collection_id, student_id=student_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"


# =====================================================================
# BUG-3: delete_account ทำลายประวัติ finance_transactions
# =====================================================================


async def test_delete_account_with_history_orphans_transaction_histories(db_pool):
    """
    BUG-3 regression: delete_account hard-delete โดยไม่เช็ค finance_transactions
    → transactions ของบัญชีนั้นถูก ON DELETE SET NULL → account_id กลายเป็น NULL
    → ประวัติรายรับ/รายจ่ายหาย (บัญชีไม่มีแล้ว)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat_id)

    # delete_account หลังแก้: ต้องถูก block เพราะมี transaction history (ValueError)
    with pytest.raises(ValueError):
        await FinanceService.delete_account(
            pool=db_pool, account_id=account_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )

    # deep verify: บัญชียังอยู่ + transaction ยังชี้ account เดิม (ไม่หาย)
    async with db_pool.acquire() as conn:
        account_row = await conn.fetchrow("SELECT id FROM finance_accounts WHERE id = $1", account_id)
        tx = await conn.fetchrow("SELECT account_id FROM finance_transactions WHERE id = $1", tx_id)
    assert account_row is not None
    assert tx["account_id"] == account_id, (
        "BUG: delete_account ปล่อยให้ hard-delete บัญชีที่มีประวัติ "
        "→ finance_transactions.account_id กลายเป็น NULL (ประวัติหาย)"
    )


# =====================================================================
# BUG-4: create_fee_collection student_ids ซ้ำ → UniqueViolation 500
# =====================================================================


async def test_create_collection_duplicate_student_ids_handled_gracefully(db_pool):
    """
    BUG-4 regression: student_ids=[s1, s1] → INSERT ซ้ำ → UniqueViolationError (500)
    ควรกรองซ้ำก่อน executemany หรือจับ error → message ควรบอกจำนวนนักเรียนจริง
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)

    try:
        result = await FinanceService.create_fee_collection(
            pool=db_pool,
            req=FeeCollectionCreate(
                title="ค่าเทอม", amount=1000.0, due_date=date(2026, 12, 31),
                student_ids=[s1, s1], user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
        # ถ้าถึงตรงนี้: สร้างสำเร็จ → ตรวจว่าไม่มีการ duplicate row
        async with db_pool.acquire() as conn:
            collection = await conn.fetchrow(
                "SELECT id FROM fee_collections WHERE room_id = $1 AND title = $2",
                room_id, "ค่าเทอม",
            )
            payments = await conn.fetch(
                "SELECT student_id FROM student_payments WHERE collection_id = $1",
                collection["id"],
            )
            assert len(payments) == 1, (
                "BUG: student_ids ซ้ำกันสร้าง student_payments ซ้ำ (UniqueViolation 500) "
                "— ควรกรองซ้ำก่อน executemany"
            )
    except Exception as e:  # noqa: BLE001 — จับทุกอย่างเพื่อแยก 500 ออกจาก logic error
        # UniqueViolationError ควรถูกเปลี่ยนเป็น ValueError (400) ไม่ใช่ปล่อย 500
        assert not isinstance(e, __import__("asyncpg").exceptions.UniqueViolationError), (
            "BUG: student_ids ซ้ำกันปล่อย UniqueViolationError ออกมา (500)"
        )
        raise


# =====================================================================
# BUG-5: get_summary month โดยไม่มี year
# =====================================================================


async def test_get_summary_with_month_but_no_year(db_pool):
    """
    BUG-5 regression: month=6, year=None → params=[room_id, 6] แต่ SQL ใช้ $2,$3
    → SQL error (500) แทนที่จะคืน summary
    (แก้แล้ว: ต้อง raise ValueError("ต้องระบุทั้ง month และ year") — ไม่ crash SQL)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 500.0, "income", cat_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_transactions SET created_at = '2025-06-15 10:00:00' WHERE id = $1", tx_id)

    with pytest.raises(ValueError):
        await FinanceService.get_summary(
            pool=db_pool, client_source="test", actor_identifier="test",
            month=6, room_id=room_id, user_id=owner,
        )


# =====================================================================
# BUG-6: confirm_payment รับเงินแคมเปญ closed
# =====================================================================


async def test_confirm_payment_on_closed_collection_should_be_blocked(db_pool):
    """
    BUG-6 regression: confirm_payment ไม่เช็ค FC.status = 'active'
    → แคมเปญที่ปิดแล้วยังรับเงินได้ ต้องโดนห้าม (หรือ document ว่าเป็น bug)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0, status="closed")
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    # ตรรกะที่ถูกต้อง: แคมเปญปิด → ต้องห้ามรับเงิน (PaymentNotFoundError ตาม query ที่ filter active)
    with pytest.raises(PaymentNotFoundError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=500.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_id,
        )

    # deep verify: ต้องไม่มีเงินเข้าบัญชี / ไม่มี transaction / status ยัง pending
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", payment_id)
        assert sp["status"] == "pending"
        assert float(sp["paid_amount"]) == pytest.approx(0.0)
        tx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE student_payment_id = $1", payment_id
        )
        assert tx_count == 0, "BUG: confirm_payment สร้าง transaction ให้แคมเปญ closed"


# =====================================================================
# BUG-7: revert income ที่มาจาก confirm_payment — rollback ครบทุก field
# =====================================================================


async def test_revert_payment_income_rolls_back_student_payment_fields(db_pool):
    """
    BUG-7 regression: revert income ที่มาจาก confirm_payment
    ต้อง rollback student_payments ครบ: paid_amount, status, paid_at, transaction_id, slip, recorded_by
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    await FinanceService.confirm_payment(
        pool=db_pool, payment_id=payment_id,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=1000.0, slip_image_url="https://x/slip.png", user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval("SELECT id FROM finance_transactions WHERE student_payment_id = $1", payment_id)

    await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=tx_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1", payment_id)
        assert float(sp["paid_amount"]) == pytest.approx(0.0)
        assert sp["status"] == "pending"
        assert sp["paid_at"] is None
        assert sp["transaction_id"] is None
        assert sp["slip_image_url"] is None
        assert sp["recorded_by"] is None
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


# =====================================================================
# Additional edge cases: transfer sanity (ไม่มี regression จาก Decimal fix)
# =====================================================================


async def test_transfer_exact_balance_decimal_vs_float(db_pool):
    """
    transfer_money L224 `current_balance < req.amount`:
    Decimal('0.1') < 0.1 = True → โค้ดเดิมห้ามโอน ทั้งที่เงินพอเป๊ะ
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 0.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = $1 WHERE id = $2", 0.1, from_acc)

    result = await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=0.1, description="โอนสตางค์", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(0.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.1)


# =====================================================================
# Overpay / เกินยอด collection (อีกช่องว่างที่ confirm_payment ไม่ปิด)
# =====================================================================


async def test_confirm_payment_overpay_exact_total_after_partial(db_pool):
    """
    confirm_payment: จ่ายทีหลังจนพอดี total_amount → ต้องได้ status=paid
    (ต่างจาก test_overpay ที่จ่ายเกิน 1100 — อันนี้จ่ายพอดี 400+600=1000)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 600.0)

    result = await FinanceService.confirm_payment(
        pool=db_pool, payment_id=payment_id,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=400.0, user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert "จ่ายครบแล้ว" in result["message"]
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", payment_id)
        assert sp["status"] == "paid"
        assert float(sp["paid_amount"]) == pytest.approx(1000.0)


# =====================================================================
# delete_account: บัญชีที่ถูกใช้เป็น paid_to_account (ใน student_payments)
# =====================================================================


async def test_delete_account_linked_to_payment_history_still_breaks(db_pool):
    """
    delete_account ต้องบล็อกถ้าบัญชีถูกใช้เป็น paid_to_account_id
    (มีประวัติการรับเงินจากแคมเปญ) — ปัจจุบันโค้ดเช็คแล้ว แต่ยืนยันว่า
    การลบ account ที่ balance=0 แต่มี payment history ยังต้องโดนห้าม
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "paid", 1000.0, paid_to_account_id=account_id)

    with pytest.raises(ValueError):
        await FinanceService.delete_account(
            pool=db_pool, account_id=account_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1", account_id)
    assert row is not None  # ยังไม่ถูกลบ


# =====================================================================
# revert_transaction: ยกเลิกขา income ของ transfer
# =====================================================================


async def test_revert_transfer_income_leg_restores_both(db_pool):
    """
    revert_transaction ด้วย transaction_id ของขา income (ฝั่งรับโอน)
    → ต้องคืนยอดทั้งสองบัญชีเหมือนยกเลิกจากขา expense
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)

    await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=400.0, description="ฝาก", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    # ยกเลิกจากขา income (ฝั่งรับโอน)
    async with db_pool.acquire() as conn:
        income_leg = await conn.fetchrow(
            "SELECT id FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL AND transaction_type = 'income'",
            room_id,
        )

    result = await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=income_leg["id"],
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(1000.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.0)
    async with db_pool.acquire() as conn:
        deleted = await conn.fetch(
            "SELECT deleted_at FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL",
            room_id,
        )
        assert all(d["deleted_at"] is not None for d in deleted)
