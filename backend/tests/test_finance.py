"""
Integration tests for FinanceService (services/finance_service.py)
ครอบคลุมครบทั้ง 24 methods: Accounts, Categories, Transactions, Transfer,
Fee Collections, Student Payments, Revert, Summary, Debts

Note: service-level tests — เรียก service โดยตรง (ไม่ผ่าน HTTP)
- require_permission / require_member เป็น RBAC จริง (owner = is_admin ผ่านฉลุย,
  member ต้องมี permissions ตามรายการ, member ธรรมดาอ่านได้เฉพาะ require_member)
- FinanceService ไม่แตะ Redis / ActionService → ไม่ต้อง mock
- Deep DB verification ทุก test ตาม docs/rules/testing.md
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


# === Fixtures & Setup ===


async def _insert_user(
    pool, *, email=None, first_name="Test", last_name="User", username=None
) -> int:
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
        # ผู้สร้างห้องเป็น admin ทันที
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
    pool, collection_id: int, student_id: int, status="pending", paid_amount=0.0, paid_to_account_id=None
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments (collection_id, student_id, status, paid_amount, paid_to_account_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            collection_id, student_id, status, paid_amount, paid_to_account_id,
        )


async def _insert_transaction(
    pool, room_id: int, account_id: int, amount: float, transaction_type: str = "income",
    category_id=None, description="test", recorded_by="Owner", deleted=False,
) -> int:
    async with pool.acquire() as conn:
        tx_id = await conn.fetchval(
            """
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, description, transaction_type, recorded_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            room_id, account_id, category_id, amount, description, transaction_type, recorded_by,
        )
        if deleted:
            await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", tx_id)
        return tx_id


async def _fetch_account(pool, account_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1", account_id)


async def _fetch_balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id))


async def _count_audit_logs(pool, entity_type: str, action: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE entity_type = $1 AND action = $2",
            entity_type, action,
        )


# === Section 1: Accounts (CREATE / READ) ===


async def test_create_account_creates_row_with_initial_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    result = await FinanceService.create_account(
        pool=db_pool,
        req=AccountCreate(account_name="กองกลาง", initial_balance=500.0, user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM finance_accounts WHERE room_id = $1 AND account_name = $2",
            room_id, "กองกลาง",
        )
        assert row is not None
        assert float(row["balance"]) == pytest.approx(500.0)
        assert row["deleted_at"] is None

    # deep: audit log
    assert await _count_audit_logs(db_pool, "FINANCE_ACCOUNT", "CREATE") == 1


async def test_create_account_default_zero_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    await FinanceService.create_account(
        pool=db_pool,
        req=AccountCreate(account_name="เงินสด", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    account_id = await _get_last_account_id(db_pool)
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def _get_last_account_id(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT MAX(id) FROM finance_accounts")


async def test_get_accounts_returns_room_accounts_ordered_by_id(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    a1 = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    a2 = await _insert_finance_account(db_pool, room_id, "เงินสด", 50.0)

    accounts = await FinanceService.get_accounts(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert [a["id"] for a in accounts] == [a1, a2]
    assert accounts[0]["account_name"] == "กองกลาง"
    assert float(accounts[1]["balance"]) == pytest.approx(50.0)


async def test_get_accounts_empty_returns_empty_list(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    accounts = await FinanceService.get_accounts(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert accounts == []


async def test_get_accounts_via_server_id(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)

    accounts = await FinanceService.get_accounts(
        pool=db_pool, client_source="test", actor_identifier="test",
        server_id=server_id, user_id=owner,
    )
    assert len(accounts) == 1


async def test_get_accounts_unknown_room_raises_roomnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    await _insert_room(db_pool, owner)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=999_999_999, user_id=owner,
        )


async def test_get_accounts_no_target_raises_valueerror(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")

    with pytest.raises(ValueError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            user_id=owner,
        )


# === Section 2: Categories (CREATE / READ) ===


async def test_create_category_creates_row_and_audit(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    result = await FinanceService.create_category(
        pool=db_pool,
        req=CategoryCreate(category_name="ค่าอาหาร", category_type="expense", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM finance_categories WHERE room_id = $1 AND category_name = $2",
            room_id, "ค่าอาหาร",
        )
        assert row is not None
        assert row["category_type"] == "expense"

    assert await _count_audit_logs(db_pool, "FINANCE_CATEGORY", "CREATE") == 1


async def test_get_categories_returns_all(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    cats = await FinanceService.get_categories(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert len(cats) == 2
    assert {c["category_type"] for c in cats} == {"expense", "income"}


async def test_get_categories_filtered_by_type(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    cats = await FinanceService.get_categories(
        pool=db_pool, client_source="test", actor_identifier="test",
        cat_type="expense", room_id=room_id, user_id=owner,
    )
    assert len(cats) == 1
    assert cats[0]["category_name"] == "ค่าอาหาร"


# === Section 3: Transactions (CREATE / READ / FILTERS) ===


async def test_add_income_transaction_increases_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    result = await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=100.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(100.0)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM finance_transactions WHERE room_id = $1 AND account_id = $2",
            room_id, account_id,
        )
        assert row is not None
        assert row["transaction_type"] == "income"
        assert float(row["amount"]) == pytest.approx(100.0)
        assert row["recorded_by"] == "Owner"
        assert row["deleted_at"] is None

    assert await _count_audit_logs(db_pool, "FINANCE_TRANSACTION", "CREATE") == 1


async def test_add_expense_transaction_decreases_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 500.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=200.0,
            description="ซื้ออาหาร", transaction_type="expense", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(300.0)


async def test_get_transactions_returns_all_ordered_desc(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    t1 = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat_id)
    t2 = await _insert_transaction(db_pool, room_id, account_id, 50.0, "income", cat_id)
    # กำหนด created_at ชัดเจนกัน race ระหว่าง INSERT ที่ติดกัน (ORDER BY created_at DESC)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_transactions SET created_at = '2026-01-01 10:00:00' WHERE id = $1", t1)
        await conn.execute("UPDATE finance_transactions SET created_at = '2026-01-02 10:00:00' WHERE id = $1", t2)

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 2
    # ORDER BY created_at DESC — t2 ใหม่กว่า ต้องมาก่อน
    assert [item["id"] for item in data["items"]] == [t2, t1]
    assert data["items"][0]["account_name"] == "กองกลาง"
    assert data["items"][0]["category_name"] == "เงินบริจาค"


async def test_get_transactions_filter_by_type(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", inc_cat)
    await _insert_transaction(db_pool, room_id, account_id, 30.0, "expense", exp_cat)

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        transaction_type="expense", room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 1
    assert data["items"][0]["transaction_type"] == "expense"


async def test_get_transactions_filter_by_account_and_category(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    a1 = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    a2 = await _insert_finance_account(db_pool, room_id, "เงินสด", 0.0)
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_transaction(db_pool, room_id, a1, 100.0, "income", cat)
    await _insert_transaction(db_pool, room_id, a2, 50.0, "income", cat)

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        account_id=a1, category_id=cat, room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 1
    # response schema ไม่มี account_id — verify ผ่าน account_name แทน
    assert data["items"][0]["account_name"] == "กองกลาง"
    assert data["items"][0]["amount"] == pytest.approx(100.0)


async def test_get_transactions_filter_by_date_range(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    t_in = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat)
    t_out = await _insert_transaction(db_pool, room_id, account_id, 200.0, "income", cat)

    async with db_pool.acquire() as conn:
        # ปรับ created_at ให้คนละช่วงวันที่
        await conn.execute("UPDATE finance_transactions SET created_at = '2026-01-15 10:00:00' WHERE id = $1", t_in)
        await conn.execute("UPDATE finance_transactions SET created_at = '2026-02-15 10:00:00' WHERE id = $1", t_out)

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 1
    assert data["items"][0]["id"] == t_in


async def test_get_transactions_excludes_soft_deleted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat, deleted=True)
    live = await _insert_transaction(db_pool, room_id, account_id, 200.0, "income", cat)

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 1
    assert data["items"][0]["id"] == live


async def test_get_transactions_pagination(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    ids = [await _insert_transaction(db_pool, room_id, account_id, float(i), "income", cat) for i in range(1, 6)]
    # กำหนด created_at ให้เรียงตามลำดับ id ชัดเจน (กัน tie จากการ INSERT ติดกัน)
    # คอลัมน์ TIMESTAMP ต้องส่ง datetime object (asyncpg ปฏิเสธ string)
    async with db_pool.acquire() as conn:
        for i, tx_id in enumerate(ids, start=1):
            await conn.execute(
                "UPDATE finance_transactions SET created_at = $2 WHERE id = $1",
                tx_id, datetime(2026, 1, i, 10, 0, 0),
            )

    data = await FinanceService.get_transactions(
        pool=db_pool, client_source="test", actor_identifier="test",
        limit=2, offset=1, room_id=room_id, user_id=owner,
    )
    assert data["total_count"] == 5
    # เรียง DESC: 5,4,3,2,1 — offset 1 limit 2 → [4, 3]
    assert [item["id"] for item in data["items"]] == [ids[3], ids[2]]


# === Section 4: Transfer Money ===


async def test_transfer_money_moves_balance_and_creates_two_legs(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "บัญชีหลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "บัญชีย่อย", 0.0)

    result = await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(
            from_account_id=from_acc, to_account_id=to_acc, amount=400.0,
            description="ฝากสำรอง", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(600.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(400.0)

    async with db_pool.acquire() as conn:
        legs = await conn.fetch(
            "SELECT * FROM finance_transactions WHERE transfer_group_id IS NOT NULL AND room_id = $1 ORDER BY id",
            room_id,
        )
        assert len(legs) == 2
        types = {l["transaction_type"] for l in legs}
        assert types == {"expense", "income"}
        assert legs[0]["transfer_group_id"] == legs[1]["transfer_group_id"]
        # ฝั่งออกต้องเป็น expense
        exp_leg = next(l for l in legs if l["transaction_type"] == "expense")
        assert exp_leg["account_id"] == from_acc
        assert "โอนออก" in exp_leg["description"]
        inc_leg = next(l for l in legs if l["transaction_type"] == "income")
        assert inc_leg["account_id"] == to_acc
        assert "รับโอน" in inc_leg["description"]

    assert await _count_audit_logs(db_pool, "FINANCE_TRANSFER", "CREATE") == 1


async def test_transfer_same_account_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    acc = await _insert_finance_account(db_pool, room_id, "บัญชีเดียว", 1000.0)

    with pytest.raises(ValueError):
        await FinanceService.transfer_money(
            pool=db_pool,
            req=TransferCreate(from_account_id=acc, to_account_id=acc, amount=100.0, description="x", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    # ไม่มีรายการโอนเกิดขึ้นเลย
    assert await _fetch_balance(db_pool, acc) == pytest.approx(1000.0)


async def test_transfer_insufficient_balance_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 100.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)

    with pytest.raises(ValueError):
        await FinanceService.transfer_money(
            pool=db_pool,
            req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=200.0, description="x", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(100.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.0)


async def test_transfer_from_account_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    from_acc = await _insert_finance_account(db_pool, room_a, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_b, "รอง", 0.0)

    # โอนจากบัญชีห้องอื่น → ต้องโดน RoomNotFoundError
    with pytest.raises(RoomNotFoundError):
        await FinanceService.transfer_money(
            pool=db_pool,
            req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=100.0, description="x", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_a,
        )


async def test_transfer_to_account_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    from_acc = await _insert_finance_account(db_pool, room_a, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_b, "รอง", 0.0)

    # โอนไปบัญชีต่างห้อง → ต้องโดน RoomNotFoundError (กันเงินหลุดข้ามห้อง)
    with pytest.raises(RoomNotFoundError):
        await FinanceService.transfer_money(
            pool=db_pool,
            req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=100.0, description="x", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_a,
        )
    # ยอดต้องไม่ถูกแตะ
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(1000.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.0)


# === Section 5: Fee Collections & Student Payments ===


async def test_create_collection_targets_all_active_students(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    # owner เป็น student_no=0, active → ต้องถูกรวมด้วย
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    s3 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Pending"), 3, status="pending")

    result = await FinanceService.create_fee_collection(
        pool=db_pool,
        req=FeeCollectionCreate(title="ค่าเทอม", amount=1000.0, due_date=date(2026, 12, 31), student_ids=None, user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert "3" in result["message"]

    async with db_pool.acquire() as conn:
        owner_student_id = await conn.fetchval(
            "SELECT id FROM students WHERE room_id = $1 AND user_id = $2", room_id, owner,
        )
        collection = await conn.fetchrow("SELECT * FROM fee_collections WHERE room_id = $1 AND title = $2", room_id, "ค่าเทอม")
        assert collection is not None
        payments = await conn.fetch("SELECT student_id, status FROM student_payments WHERE collection_id = $1", collection["id"])
        # เฉพาะสมาชิก active เท่านั้น (owner+s1+s2) — s3 pending ต้องไม่ถูกเก็บ
        assert {p["student_id"] for p in payments} == {owner_student_id, s1, s2}
        assert all(p["status"] == "pending" for p in payments)

    assert await _count_audit_logs(db_pool, "FEE_COLLECTION", "CREATE") == 1


async def test_create_collection_targets_selected_students(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)

    await FinanceService.create_fee_collection(
        pool=db_pool,
        req=FeeCollectionCreate(title="ทัศนศึกษา", amount=500.0, due_date=date(2026, 11, 30), student_ids=[s1], user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        collection = await conn.fetchrow("SELECT * FROM fee_collections WHERE room_id = $1 AND title = $2", room_id, "ทัศนศึกษา")
        payments = await conn.fetch("SELECT student_id FROM student_payments WHERE collection_id = $1", collection["id"])
        assert {p["student_id"] for p in payments} == {s1}


async def test_get_all_collections_returns_list_desc(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    c1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    c2 = await _insert_collection(db_pool, room_id, "ทัศนศึกษา", 500.0)

    cols = await FinanceService.get_all_collections(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert [c["id"] for c in cols] == [c2, c1]
    assert cols[0]["status"] == "active"


async def test_get_collection_status_returns_summary_and_students(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    p1 = await _insert_student_payment(db_pool, collection_id, s1, "pending", 0.0)
    p2 = await _insert_student_payment(db_pool, collection_id, s2, "pending", 0.0)

    # ให้ s1 จ่ายครบ
    await FinanceService.confirm_payment(
        pool=db_pool, payment_id=p1,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=1000.0, user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    data = await FinanceService.get_collection_status(
        pool=db_pool, collection_id=collection_id,
        client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert data["collection_id"] == collection_id
    assert data["summary"] == {"total": 2, "paid": 1, "pending": 1}
    by_pid = {s["payment_id"]: s for s in data["students"]}
    assert by_pid[p1]["status"] == "paid"
    assert float(by_pid[p1]["paid_amount"]) == pytest.approx(1000.0)
    assert float(by_pid[p2]["paid_amount"]) == pytest.approx(0.0)
    assert by_pid[p1]["total_amount"] == pytest.approx(1000.0)


async def test_confirm_payment_full_payment_updates_everything(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    result = await FinanceService.confirm_payment(
        pool=db_pool, payment_id=payment_id,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=1000.0, slip_image_url="https://x/slip.png", user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert "จ่ายครบแล้ว" in result["message"]
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(1000.0)

    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1", payment_id)
        assert sp["status"] == "paid"
        assert float(sp["paid_amount"]) == pytest.approx(1000.0)
        assert sp["paid_to_account_id"] == account_id
        assert sp["paid_at"] is not None
        assert sp["transaction_id"] is not None
        assert sp["recorded_by"] == "Owner"

        tx = await conn.fetchrow("SELECT * FROM finance_transactions WHERE student_payment_id = $1", payment_id)
        assert tx is not None
        assert tx["transaction_type"] == "income"
        assert float(tx["amount"]) == pytest.approx(1000.0)
        assert "ค่าเทอม" in tx["description"]
        assert tx["recorded_by"] == "Owner"

    assert await _count_audit_logs(db_pool, "STUDENT_PAYMENT", "UPDATE") == 1


async def test_confirm_payment_partial_payment_keeps_pending(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    result = await FinanceService.confirm_payment(
        pool=db_pool, payment_id=payment_id,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=400.0, user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )
    assert "ทยอยจ่าย" in result["message"]
    assert "600" in result["message"]

    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1", payment_id)
        assert sp["status"] == "pending"
        assert float(sp["paid_amount"]) == pytest.approx(400.0)


async def test_confirm_payment_account_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    account_b = await _insert_finance_account(db_pool, room_b, "เงินต่างห้อง", 0.0)
    student_id = await _insert_student(db_pool, room_a, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_a, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    with pytest.raises(ValueError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_b, paid_amount=1000.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_a,
        )


async def test_confirm_payment_already_fully_paid_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "paid", 1000.0)

    with pytest.raises(ValueError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=100.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_id,
        )


async def test_confirm_payment_nonexistent_raises_paymentnotfound(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)

    with pytest.raises(PaymentNotFoundError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=999_999_999,
            req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=100.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_id,
        )


# === Section 6: Updates & Mutations ===


async def test_update_account_renames(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)

    result = await FinanceService.update_account(
        pool=db_pool, account_id=account_id,
        req=AccountCreate(account_name="กองกลาง (ใหม่)", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    row = await _fetch_account(db_pool, account_id)
    assert row["account_name"] == "กองกลาง (ใหม่)"
    # balance ต้องไม่ถูกแตะ
    assert float(row["balance"]) == pytest.approx(100.0)
    assert await _count_audit_logs(db_pool, "FINANCE_ACCOUNT", "UPDATE") == 1


async def test_update_account_nonexistent_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.update_account(
            pool=db_pool, account_id=999_999_999,
            req=AccountCreate(account_name="ใหม่", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_update_category_renames(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    await FinanceService.update_category(
        pool=db_pool, category_id=cat_id,
        req=CategoryCreate(category_name="ค่ากิน", category_type="expense", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1", cat_id)
        assert row["category_name"] == "ค่ากิน"
        assert row["category_type"] == "expense"
    assert await _count_audit_logs(db_pool, "FINANCE_CATEGORY", "UPDATE") == 1


async def test_update_category_nonexistent_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.update_category(
            pool=db_pool, category_id=999_999_999,
            req=CategoryCreate(category_name="ใหม่", category_type="expense", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_update_collection_title_and_due_date(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0, date(2026, 12, 31))

    result = await FinanceService.update_collection(
        pool=db_pool, collection_id=collection_id,
        req=FeeCollectionUpdate(title="ค่าเทอม (เลื่อน)", due_date=date(2027, 1, 15), user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM fee_collections WHERE id = $1", collection_id)
        assert row["title"] == "ค่าเทอม (เลื่อน)"
        assert row["due_date"] == date(2027, 1, 15)
        assert float(row["amount"]) == pytest.approx(1000.0)  # amount ไม่เปลี่ยน
    assert await _count_audit_logs(db_pool, "FEE_COLLECTION", "UPDATE") == 1


async def test_update_collection_amount_before_payment_ok(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    await FinanceService.update_collection(
        pool=db_pool, collection_id=collection_id,
        req=FeeCollectionUpdate(amount=1200.0, user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT amount FROM fee_collections WHERE id = $1", collection_id)
        assert float(row["amount"]) == pytest.approx(1200.0)


async def test_update_collection_amount_blocked_after_payment(db_pool):
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
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT amount FROM fee_collections WHERE id = $1", collection_id)
        assert float(row["amount"]) == pytest.approx(1000.0)


async def test_update_collection_status_closed(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    await FinanceService.update_collection(
        pool=db_pool, collection_id=collection_id,
        req=FeeCollectionUpdate(status="closed", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM fee_collections WHERE id = $1", collection_id)
        assert row["status"] == "closed"


async def test_update_collection_no_changes_returns_success(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    result = await FinanceService.update_collection(
        pool=db_pool, collection_id=collection_id,
        req=FeeCollectionUpdate(user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["message"] == "ไม่มีข้อมูลให้เปลี่ยนแปลง"


async def test_update_collection_nonexistent_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.update_collection(
            pool=db_pool, collection_id=999_999_999,
            req=FeeCollectionUpdate(title="ใหม่", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_add_student_to_collection_success(db_pool):
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
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT * FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            collection_id, student_id,
        )
        assert sp is not None
        assert sp["status"] == "pending"


async def test_add_student_to_collection_duplicate_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    with pytest.raises(ValueError):
        await FinanceService.add_student_to_collection(
            pool=db_pool, collection_id=collection_id, student_id=student_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_add_student_to_collection_student_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    student_b = await _insert_student(db_pool, room_b, await _insert_user(db_pool, first_name="Kid", last_name="Other"), 1)
    collection_id = await _insert_collection(db_pool, room_a, "ค่าเทอม", 1000.0)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.add_student_to_collection(
            pool=db_pool, collection_id=collection_id, student_id=student_b,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_a,
        )


async def test_add_student_to_collection_closed_collection_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0, status="closed")

    with pytest.raises(ValueError):
        await FinanceService.add_student_to_collection(
            pool=db_pool, collection_id=collection_id, student_id=student_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


# === Section 7: Deletions (Revert / Remove / Hard Delete) ===


async def test_revert_expense_transaction_restores_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 500.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 200.0, "expense", cat_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_accounts SET balance = 300.0 WHERE id = $1", account_id)

    result = await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=tx_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["message"] == "ยกเลิกรายการ expense"
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(500.0)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id)
        assert row["deleted_at"] is not None
    assert await _count_audit_logs(db_pool, "FINANCE_TRANSACTION", "UPDATE") == 1


async def test_revert_income_transaction_deducts_balance(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat_id)

    await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=tx_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def test_revert_income_transaction_insufficient_balance_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    inc_tx = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", inc_cat)
    await _insert_transaction(db_pool, room_id, account_id, 100.0, "expense", exp_cat)
    # balance เป็น 0 แล้ว (เงิน 100 เข้า แล้วใช้จ่ายหมด)

    with pytest.raises(ValueError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=inc_tx,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )
    # transaction ต้องยังไม่ถูก soft-delete
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", inc_tx)
        assert row["deleted_at"] is None


async def test_revert_transfer_group_restores_both_balances(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)

    await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=400.0, description="ฝากสำรอง", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    # ดึงขา expense มายกเลิก
    async with db_pool.acquire() as conn:
        leg = await conn.fetchrow(
            "SELECT id FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL AND transaction_type = 'expense'",
            room_id,
        )

    result = await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=leg["id"],
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["message"] == "ยกเลิกรายการโอนเงิน"
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(1000.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.0)

    async with db_pool.acquire() as conn:
        deleted = await conn.fetch(
            "SELECT deleted_at FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL",
            room_id,
        )
        assert all(d["deleted_at"] is not None for d in deleted)


async def test_revert_transfer_group_destination_insufficient_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)

    await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=400.0, description="ฝากสำรอง", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    # ใช้เงินในบัญชีรับโอน (รอง) จนหมด → ยกเลิกโอนจะหักคืนไม่ได้
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(account_id=to_acc, category_id=exp_cat, amount=400.0, description="ใช้หมด", transaction_type="expense", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    async with db_pool.acquire() as conn:
        leg = await conn.fetchrow(
            "SELECT id FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL AND transaction_type = 'expense'",
            room_id,
        )
    with pytest.raises(ValueError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=leg["id"],
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )
    # rollback: ทั้งสองขายังไม่ถูกลบ, ยอดยังเท่าเดิม
    async with db_pool.acquire() as conn:
        deleted = await conn.fetch(
            "SELECT deleted_at FROM finance_transactions WHERE room_id = $1 AND transfer_group_id IS NOT NULL",
            room_id,
        )
        assert all(d["deleted_at"] is None for d in deleted)
    assert await _fetch_balance(db_pool, from_acc) == pytest.approx(600.0)
    assert await _fetch_balance(db_pool, to_acc) == pytest.approx(0.0)


async def test_revert_income_linked_to_payment_rolls_back_student_payment(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    await FinanceService.confirm_payment(
        pool=db_pool, payment_id=payment_id,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=400.0, user_name="Owner"),
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
        sp = await conn.fetchrow("SELECT paid_amount, status FROM student_payments WHERE id = $1", payment_id)
        assert float(sp["paid_amount"]) == pytest.approx(0.0)
        assert sp["status"] == "pending"
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)


async def test_revert_transaction_nonexistent_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(TransactionNotFoundError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=999_999_999,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_revert_transaction_already_deleted_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat_id, deleted=True)

    with pytest.raises(TransactionNotFoundError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=tx_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_delete_account_success(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าว่าง", 0.0)

    result = await FinanceService.delete_account(
        pool=db_pool, account_id=account_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"
    # hard delete — แถวหายไปจริง
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1", account_id)
        assert row is None
    assert await _count_audit_logs(db_pool, "FINANCE_ACCOUNT", "DELETE") == 1


async def test_delete_account_with_balance_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "มีเงิน", 500.0)

    with pytest.raises(ValueError):
        await FinanceService.delete_account(
            pool=db_pool, account_id=account_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1", account_id)
        assert row is not None


async def test_delete_account_linked_to_payment_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "มีประวัติ", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "paid", 1000.0, paid_to_account_id=account_id)

    with pytest.raises(ValueError):
        await FinanceService.delete_account(
            pool=db_pool, account_id=account_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_delete_account_nonexistent_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.delete_account(
            pool=db_pool, account_id=999_999_999,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_delete_category_success(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    result = await FinanceService.delete_category(
        pool=db_pool, category_id=cat_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1", cat_id)
        assert row is None
    assert await _count_audit_logs(db_pool, "FINANCE_CATEGORY", "DELETE") == 1


async def test_delete_category_in_use_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_transaction(db_pool, room_id, account_id, 100.0, "expense", cat_id)

    with pytest.raises(ValueError):
        await FinanceService.delete_category(
            pool=db_pool, category_id=cat_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1", cat_id)
        assert row is not None


async def test_remove_student_from_collection_success(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    result = await FinanceService.remove_student_from_collection(
        pool=db_pool, collection_id=collection_id, student_id=student_id,
        user_id=owner, client_source="test", actor_identifier="test",
        user_name="Owner", room_id=room_id,
    )
    assert result["status"] == "success"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1", payment_id)
        assert row is None  # hard delete
    assert await _count_audit_logs(db_pool, "STUDENT_PAYMENT", "DELETE") == 1


async def test_remove_student_from_collection_with_payment_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 300.0)

    with pytest.raises(ValueError):
        await FinanceService.remove_student_from_collection(
            pool=db_pool, collection_id=collection_id, student_id=student_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


async def test_remove_student_from_collection_not_found_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    with pytest.raises(PaymentNotFoundError):
        await FinanceService.remove_student_from_collection(
            pool=db_pool, collection_id=collection_id, student_id=student_id,
            user_id=owner, client_source="test", actor_identifier="test",
            user_name="Owner", room_id=room_id,
        )


# === Section 8: Summary & Debts (READ) ===


async def test_get_summary_current_month(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 1000.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_transaction(db_pool, room_id, account_id, 300.0, "income", inc_cat)
    await _insert_transaction(db_pool, room_id, account_id, 100.0, "expense", exp_cat)

    summary = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert float(summary["net_worth"]) == pytest.approx(1000.0)
    assert float(summary["total_income"]) == pytest.approx(300.0)
    assert float(summary["total_expense"]) == pytest.approx(100.0)
    assert summary["period"] == "current_month"
    assert len(summary["expense_breakdown"]) == 1
    assert summary["expense_breakdown"][0]["category_name"] == "ค่าอาหาร"
    assert float(summary["expense_breakdown"][0]["total_amount"]) == pytest.approx(100.0)


async def test_get_summary_excludes_transfer_legs(db_pool):
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

    summary = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    # ยอดโอนระหว่างบัญชีไม่นับเป็นรายรับ/รายจ่าย
    assert float(summary["total_income"]) == pytest.approx(0.0)
    assert float(summary["total_expense"]) == pytest.approx(0.0)
    assert float(summary["net_worth"]) == pytest.approx(1000.0)


async def test_get_summary_month_year_filter(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 500.0, "income", cat_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_transactions SET created_at = '2025-01-15 10:00:00' WHERE id = $1", tx_id)

    in_jan = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        month=1, year=2025, room_id=room_id, user_id=owner,
    )
    assert float(in_jan["total_income"]) == pytest.approx(500.0)
    assert in_jan["period"] == "2025-01"

    in_feb = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        month=2, year=2025, room_id=room_id, user_id=owner,
    )
    assert float(in_feb["total_income"]) == pytest.approx(0.0)


async def test_get_summary_pending_collection_amount(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    p1 = await _insert_student_payment(db_pool, collection_id, s1, "pending", 0.0)
    await _insert_student_payment(db_pool, collection_id, s2, "pending", 300.0)

    # s1 จ่ายครบ → ไม่นับ; s2 จ่ายไป 300 → ค้าง 700
    await FinanceService.confirm_payment(
        pool=db_pool, payment_id=p1,
        req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=1000.0, user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    summary = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert float(summary["pending_collection_amount"]) == pytest.approx(700.0)


async def test_get_summary_excludes_closed_collection_from_pending(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0, status="closed")
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    summary = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert float(summary["pending_collection_amount"]) == pytest.approx(0.0)


async def test_get_summary_empty_room(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    summary = await FinanceService.get_summary(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert float(summary["net_worth"]) == pytest.approx(0.0)
    assert float(summary["total_income"]) == pytest.approx(0.0)
    assert float(summary["total_expense"]) == pytest.approx(0.0)
    assert float(summary["pending_collection_amount"]) == pytest.approx(0.0)
    assert summary["expense_breakdown"] == []


async def test_get_student_debts_returns_pending_sorted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    c_active = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0, date(2026, 12, 31), status="active")
    c_closed = await _insert_collection(db_pool, room_id, "ค่าทัศนศึกษา", 500.0, date(2026, 10, 1), status="closed")
    await _insert_student_payment(db_pool, c_active, student_id, "pending", 400.0)
    await _insert_student_payment(db_pool, c_closed, student_id, "pending", 0.0)

    data = await FinanceService.get_student_debts(
        pool=db_pool, student_id=student_id,
        client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert data["student_id"] == student_id
    # service สร้างชื่อจาก first_name + nickname (ไม่รวม last_name)
    assert data["student_name"] == "Kid"
    assert float(data["total_pending_amount"]) == pytest.approx(1100.0)  # 600 + 500
    # ORDER BY FC.status ASC → 'active' ก่อน 'closed'
    assert data["debts"][0]["collection_status"] == "active"
    assert float(data["debts"][0]["amount"]) == pytest.approx(600.0)
    assert data["debts"][1]["collection_status"] == "closed"


async def test_get_student_debts_excludes_fully_paid(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "paid", 1000.0)

    data = await FinanceService.get_student_debts(
        pool=db_pool, student_id=student_id,
        client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert data["debts"] == []
    assert float(data["total_pending_amount"]) == pytest.approx(0.0)


async def test_get_student_debts_student_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    student_b = await _insert_student(db_pool, room_b, await _insert_user(db_pool, first_name="Kid", last_name="Other"), 1)

    with pytest.raises(RoomNotFoundError):
        await FinanceService.get_student_debts(
            pool=db_pool, student_id=student_b,
            client_source="test", actor_identifier="test",
            room_id=room_a, user_id=owner,
        )


async def test_get_all_debtors_returns_aggregate_sorted(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    c1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    c2 = await _insert_collection(db_pool, room_id, "ค่าทัศนศึกษา", 500.0)
    await _insert_student_payment(db_pool, c1, s1, "pending", 0.0)
    await _insert_student_payment(db_pool, c2, s1, "pending", 100.0)
    await _insert_student_payment(db_pool, c1, s2, "pending", 0.0)

    debtors = await FinanceService.get_all_debtors(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    # s1 ค้าง 1000+400=1400 (2 รายการ), s2 ค้าง 1000 (1 รายการ) — เรียง student_no
    assert [d["student_no"] for d in debtors] == [1, 2]
    assert debtors[0]["overdue_count"] == 2
    assert float(debtors[0]["total_pending_amount"]) == pytest.approx(1400.0)
    assert debtors[1]["overdue_count"] == 1
    assert float(debtors[1]["total_pending_amount"]) == pytest.approx(1000.0)


async def test_get_all_debtors_excludes_fully_paid(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, s1, "paid", 1000.0)
    await _insert_student_payment(db_pool, collection_id, s2, "pending", 0.0)

    debtors = await FinanceService.get_all_debtors(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert len(debtors) == 1
    assert debtors[0]["student_id"] == s2


async def test_get_all_debtors_empty(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)

    debtors = await FinanceService.get_all_debtors(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert debtors == []


async def test_get_active_students_returns_only_active_ordered(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Alpha", last_name="One"), 3)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Beta", last_name="Two"), 1)
    s3 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Gamma", last_name="Pending"), 2, status="pending")

    students = await FinanceService.get_active_students(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    # เรียง student_no ASC, เฉพาะ active — owner (student_no=0) ก็ active ด้วย
    assert [s["student_no"] for s in students] == [0, 1, 3]
    assert students[0]["first_name"] == "Admin"
    assert students[1]["first_name"] == "Beta"
    assert s3 not in [s["id"] for s in students]


# === Section 9: RBAC & Cross-room Isolation ===


async def test_member_can_read_accounts_but_not_write(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)

    # อ่านได้ (transparency)
    accounts = await FinanceService.get_accounts(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=member,
    )
    assert accounts == []

    # เขียนไม่ได้
    with pytest.raises(ForbiddenError):
        await FinanceService.create_account(
            pool=db_pool,
            req=AccountCreate(account_name="กองกลาง", user_name="Member"),
            user_id=member, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id)
        assert count == 0


async def test_member_with_manage_finance_permission_can_write(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    treasurer = await _insert_user(db_pool, first_name="Treasurer", last_name="Member")
    await _insert_student(db_pool, room_id, treasurer, 5, status="active", is_admin=False, permissions='["MANAGE_FINANCE"]')

    result = await FinanceService.create_account(
        pool=db_pool,
        req=AccountCreate(account_name="กองกลาง", user_name="Treasurer"),
        user_id=treasurer, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    assert result["status"] == "success"
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id)
        assert count == 1


async def test_non_member_cannot_read_accounts(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="User")
    # outsider ไม่ได้เป็นสมาชิกห้องนี้เลย

    with pytest.raises(ForbiddenError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_id, user_id=outsider,
        )


async def test_cross_room_read_blocked(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b, room_name="ห้อง B")
    await _insert_finance_account(db_pool, room_b, "เงินห้อง B", 999.0)
    member_a = await _insert_user(db_pool, first_name="Member", last_name="A")
    await _insert_student(db_pool, room_a, member_a, 1, status="active", is_admin=False)

    # สมาชิกห้อง A พยายามอ่านบัญชีห้อง B → โดน ForbiddenError
    with pytest.raises(ForbiddenError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_b, user_id=member_a,
        )


async def test_cross_room_write_blocked(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Admin", last_name="B"), room_name="ห้อง B")
    member_a = await _insert_user(db_pool, first_name="Member", last_name="A")
    await _insert_student(db_pool, room_a, member_a, 1, status="active", is_admin=False)

    with pytest.raises(ForbiddenError):
        await FinanceService.create_account(
            pool=db_pool,
            req=AccountCreate(account_name="แอบสร้าง", user_name="Member"),
            user_id=member_a, client_source="test", actor_identifier="test",
            room_id=room_b,
        )


async def test_inactive_member_cannot_read(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    pending = await _insert_user(db_pool, first_name="Pending", last_name="Member")
    await _insert_student(db_pool, room_id, pending, 5, status="pending", is_admin=False)

    with pytest.raises(ForbiddenError):
        await FinanceService.get_accounts(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_id, user_id=pending,
        )


async def test_plain_member_cannot_confirm_payment_mutation_via_transactions(db_pool):
    """
    ✅ FIXED: confirm_payment ตอนนี้มี RBAC (MANAGE_FINANCE)
    สมาชิกธรรมดา (ไม่ใช่ admin) ต้องโดน ForbiddenError
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    with pytest.raises(ForbiddenError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=1000.0, user_name="Member"),
            client_source="test", actor_identifier="test", room_id=room_id,
            user_id=member,
        )
    # Deep verify: ไม่มีเงินเข้าบัญชี / status ยัง pending
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT status FROM student_payments WHERE id = $1", payment_id)
        assert sp["status"] == "pending"


async def test_plain_member_cannot_revert_or_delete(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5, status="active", is_admin=False)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_transaction(db_pool, room_id, account_id, 100.0, "income", cat_id)

    with pytest.raises(ForbiddenError):
        await FinanceService.revert_transaction(
            pool=db_pool, transaction_id=tx_id,
            user_id=member, client_source="test", actor_identifier="test",
            user_name="Member", room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id)
        assert row["deleted_at"] is None


# === Section 10: Edge Cases & Validation ===


async def test_add_transaction_expense_exceeds_balance_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    with pytest.raises(ValueError):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(
                account_id=account_id, category_id=cat_id, amount=200.0,
                description="เกินวงเงิน", transaction_type="expense", user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    # ไม่มีรายการถูกบันทึก และยอดไม่เปลี่ยน
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(100.0)
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND description = 'เกินวงเงิน'",
            room_id,
        )
        assert count == 0


async def test_add_transaction_account_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    account_b = await _insert_finance_account(db_pool, room_b, "เงินต่างห้อง", 0.0)
    cat_id = await _insert_category(db_pool, room_a, "ค่าอาหาร", "expense")

    with pytest.raises(ValueError):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(
                account_id=account_b, category_id=cat_id, amount=50.0,
                description="ใช้บัญชีคนอื่น", transaction_type="expense", user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_a,
        )


async def test_add_transaction_category_not_in_room_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    account_id = await _insert_finance_account(db_pool, room_a, "กองกลาง", 100.0)
    cat_b = await _insert_category(db_pool, room_b, "หมวดต่างห้อง", "expense")

    with pytest.raises(ValueError):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(
                account_id=account_id, category_id=cat_b, amount=50.0,
                description="ใช้หมวดคนอื่น", transaction_type="expense", user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_a,
        )


async def test_add_transaction_category_type_mismatch_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    income_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    # ใช้หมวด income แต่บันทึกเป็น expense → ต้องโดน ValueError
    with pytest.raises(ValueError):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(
                account_id=account_id, category_id=income_cat, amount=50.0,
                description="หมวดไม่ตรง", transaction_type="expense", user_name="Owner",
            ),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )


async def test_create_collection_empty_student_ids_raises(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    with pytest.raises(ValueError):
        await FinanceService.create_fee_collection(
            pool=db_pool,
            req=FeeCollectionCreate(title="ค่าเทอม", amount=1000.0, due_date=date(2026, 12, 31), student_ids=[], user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test",
            room_id=room_id,
        )
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM fee_collections WHERE room_id = $1", room_id)
        assert count == 0


async def test_create_collection_silently_drops_invalid_student_ids(db_pool):
    """
    ⚠️ document: student_ids ที่ไม่ใช่สมาชิก active ของห้องจะถูก drop เงียบ ๆ
    (ไม่ error, ไม่แจ้งเตือน) — นี่คือพฤติกรรมปัจจุบันที่อาจต้องการ flag
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    s1 = await _insert_student(db_pool, room_a, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s_other_room = await _insert_student(db_pool, room_b, await _insert_user(db_pool, first_name="Other", last_name="Kid"), 1)
    s_pending = await _insert_student(db_pool, room_a, await _insert_user(db_pool, first_name="Pending", last_name="Kid"), 2, status="pending")

    result = await FinanceService.create_fee_collection(
        pool=db_pool,
        req=FeeCollectionCreate(
            title="ค่าเทอม", amount=1000.0, due_date=date(2026, 12, 31),
            student_ids=[s1, s_other_room, s_pending], user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_a,
    )
    assert "1" in result["message"]
    async with db_pool.acquire() as conn:
        collection = await conn.fetchrow("SELECT id FROM fee_collections WHERE room_id = $1 AND title = $2", room_a, "ค่าเทอม")
        payments = await conn.fetch("SELECT student_id FROM student_payments WHERE collection_id = $1", collection["id"])
        assert [p["student_id"] for p in payments] == [s1]


async def test_confirm_payment_overpay_now_blocked(db_pool):
    """
    ✅ FIXED: confirm_payment ตอนนี้ block overpay แล้ว
    current_paid 600 + paid_amount 500 = 1100 → เกินยอดจริง (1000) → ต้อง raise ValueError
    และไม่ให้เงินเข้าบัญชี / ไม่เปลี่ยน status
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 600.0)

    with pytest.raises(ValueError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_id, paid_amount=500.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_id,
        )
    # Deep verify: ไม่มีเงินเข้าบัญชี / status ยัง pending / ยอดเดิมยังอยู่
    assert await _fetch_balance(db_pool, account_id) == pytest.approx(0.0)
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow("SELECT paid_amount, status FROM student_payments WHERE id = $1", payment_id)
        assert float(sp["paid_amount"]) == pytest.approx(600.0)
        assert sp["status"] == "pending"


async def test_confirm_payment_to_other_room_account_raises(db_pool):
    """ป้องกันเงินเข้ากระเป๋าต่างห้องผ่าน confirm_payment"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_a = await _insert_room(db_pool, owner, room_name="ห้อง A")
    room_b = await _insert_room(db_pool, await _insert_user(db_pool, first_name="Other", last_name="Owner"), room_name="ห้อง B")
    account_b = await _insert_finance_account(db_pool, room_b, "กระเป๋าต่างห้อง", 0.0)
    student_id = await _insert_student(db_pool, room_a, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_a, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    with pytest.raises(ValueError):
        await FinanceService.confirm_payment(
            pool=db_pool, payment_id=payment_id,
            req=PaymentConfirm(paid_to_account_id=account_b, paid_amount=1000.0, user_name="Owner"),
            client_source="test", actor_identifier="test", room_id=room_a,
        )


# === Section 9: Seed ข้อมูลเริ่มต้น (สร้างห้องเท่านั้น) ===


async def test_raw_inserted_room_starts_without_finance_seed(db_pool):
    """ห้องที่ถูก INSERT ตรง ๆ (ไม่ผ่าน create_room) ต้องไม่มีหมวดหมู่/บัญชี seed —
    ยืนยันว่าการ seed เกิดจาก create_room เท่านั้น ไม่ใช่ schema/cron"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    async with db_pool.acquire() as conn:
        cats = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_categories WHERE room_id = $1", room_id
        )
        accs = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id
        )
    assert cats == 0
    assert accs == 0
