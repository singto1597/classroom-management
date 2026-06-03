import pytest
import pytest_asyncio
import asyncpg
import random
import uuid
from decimal import Decimal
from datetime import date, timedelta, datetime
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from httpx import AsyncClient

from core.config import settings
from core.exceptions import ForbiddenError


# ==============================================================================
# 🛠️ BASE FIXTURES & MOCKS
# ==============================================================================


@pytest_asyncio.fixture(scope="function")
async def isolated_room(db_pool):
    """
    Seeds a fresh, isolated room and server_id for each test.
    Returns a dict with 'server_id' and 'room_id'.
    """
    server_id = random.randint(100000, 999999)
    # Generate a random room name using uuid4 for absolute uniqueness
    room_name = f"TestRoom_{uuid.uuid4().hex[:8]}"
    
    async with db_pool.acquire() as conn:
        # Assuming standard rooms table structure based on your service queries
        room_id = await conn.fetchval(
            "INSERT INTO rooms (server_id, room_name) VALUES ($1, $2) RETURNING id",
            server_id, room_name
        )
    
    return {"server_id": server_id, "room_id": room_id}

@pytest.fixture
def admin_headers():
    """Headers mimicking a Discord Bot request acting on behalf of an Admin."""
    return {
        "X-API-Key": settings.API_KEY,
        "X-Discord-Id": "111111111" # Admin Discord ID
    }

@pytest.fixture
def student_headers():
    """Headers mimicking a Discord Bot request acting on behalf of a Student."""
    return {
        "X-API-Key": settings.API_KEY,
        "X-Discord-Id": "999999999" # Student Discord ID
    }

@pytest.fixture(autouse=True)
def mock_rbac():
    """
    Mocks the RBAC dependency. 
    If the requester is '999999999' (student), raise ForbiddenError.
    Otherwise, allow.
    """
    async def mock_require_permission(conn, room_id, discord_id, perm):
        if discord_id == 999999999:
            raise ForbiddenError("You do not have MANAGE_FINANCE permissions.")
        return True

    with patch("services.finance_service.require_permission", new_callable=AsyncMock, side_effect=mock_require_permission) as mock:
        yield mock

@pytest.fixture(autouse=True)
def mock_audit_log():
    """Mocks the core.audit.log_action to verify audit trails without breaking on unknown logs DDL."""
    with patch("services.finance_service.log_action", new_callable=AsyncMock) as mock:
        yield mock


# ==============================================================================
# 🛠️ SETUP & FIXTURES (The Sandbox)
# ==============================================================================

@pytest_asyncio.fixture(scope="function")
async def seeded_finance_room(db_pool: asyncpg.Pool, admin_headers: dict):
    """
    Seeding the database with a controlled financial environment:
    - 1 Room
    - 3 Active Students (IDs: 1, 2, 3)
    - 2 Inactive Students (IDs: 4, 5)
    - 1 Target Finance Account (ID: 1, Balance: 1000.0)
    Returns a dictionary of these IDs for use in tests.
    """
    server_id = random.randint(1000000, 9999999)
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # 1. Create Room
            room_id = await conn.fetchval(
                "INSERT INTO rooms (server_id, room_name) VALUES ($1, $2) RETURNING id",
                server_id, "Test QA Room"
            )
            
            # 2. Create Students (3 active, 2 inactive)
            students = []
            for i in range(1, 6):
                status = 'active' if i <= 3 else 'inactive'
                student_id = await conn.fetchval(
                    """INSERT INTO students (room_id, student_no, first_name, last_name, status) 
                       VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                    room_id, i, f"FName{i}", f"LName{i}", status
                )
                students.append({"id": student_id, "status": status})

            # 3. Create Account
            account_id = await conn.fetchval(
                """INSERT INTO finance_accounts (room_id, account_name, balance) 
                   VALUES ($1, $2, $3) RETURNING id""",
                room_id, "Main Wallet", 1000.00
            )

            # 4. Create Income Category
            cat_id = await conn.fetchval(
                """INSERT INTO finance_categories (room_id, category_name, category_type) 
                   VALUES ($1, $2, $3) RETURNING id""",
                room_id, "Monthly Fee", "income"
            )

    yield {
        "server_id": server_id,
        "room_id": room_id,
        "account_id": account_id,
        "category_id": cat_id,
        "active_students": [s["id"] for s in students if s["status"] == "active"],
        "inactive_students": [s["id"] for s in students if s["status"] == "inactive"],
        "admin_headers": admin_headers
    }



# ==============================================================================
# 🛡️ FEATURE 1: GENERAL SECURITY & RBAC
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_missing_credentials(client: TestClient, isolated_room):
    """Test 1.1: Verify API rejects requests completely missing auth headers."""
    server_id = isolated_room["server_id"]
    response = client.get(f"/api/classroom/{server_id}/finance/accounts")
    
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]

@pytest.mark.asyncio
async def test_auth_forbidden_no_manage_finance_role(client: TestClient, isolated_room, student_headers, db_pool):
    """Test 1.2: Normal student attempting an admin finance action should be blocked."""
    server_id = isolated_room["server_id"]
    payload = {"account_name": "Hack Fund", "initial_balance": 5000}
    
    response = client.post(f"/api/classroom/{server_id}/finance/accounts", json=payload, headers=student_headers)
    
    assert response.status_code == 403
    assert "You do not have MANAGE_FINANCE" in response.json()["detail"]
    
    # Deep DB Verification: Assert the hacker failed to create the account
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", isolated_room["room_id"])
        assert count == 0


# ==============================================================================
# 🏦 FEATURE 2: ACCOUNTS MANAGEMENT
# ==============================================================================

@pytest.mark.asyncio
async def test_create_account_success(client: TestClient, isolated_room, admin_headers, db_pool, mock_audit_log):
    """Test 2.1: Admin successfully creates an account."""
    server_id = isolated_room["server_id"]
    payload = {"account_name": "Class Vault", "initial_balance": 1000.50, "user_name": "Admin Tester"}
    
    response = client.post(f"/api/classroom/{server_id}/finance/accounts", json=payload, headers=admin_headers)
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        account = await conn.fetchrow("SELECT account_name, balance FROM finance_accounts WHERE room_id = $1", isolated_room["room_id"])
        assert account is not None
        assert account["account_name"] == "Class Vault"
        assert float(account["balance"]) == 1000.50
        
    # Verify Audit Trail was triggered
    mock_audit_log.assert_called_once()
    assert "สร้างบัญชี Class Vault" in mock_audit_log.call_args[0][4]

@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_balance", [-500.0, -0.01])
async def test_create_account_negative_balance(client: TestClient, isolated_room, admin_headers, db_pool, invalid_balance):
    """Test 2.2: Pydantic rejects negative initial balances."""
    server_id = isolated_room["server_id"]
    payload = {"account_name": "Debt Account", "initial_balance": invalid_balance}
    
    response = client.post(f"/api/classroom/{server_id}/finance/accounts", json=payload, headers=admin_headers)
    
    assert response.status_code == 422 # Unprocessable Entity
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", isolated_room["room_id"])
        assert count == 0

@pytest.mark.asyncio
async def test_get_accounts_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 2.3: Retrieve account list successfully."""
    room_id = isolated_room["room_id"]
    
    # Seed Data directly via DB
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc 1', 100), ($1, 'Acc 2', 200)", room_id)
        
    response = client.get(f"/api/classroom/{isolated_room['server_id']}/finance/accounts", headers=admin_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["account_name"] == "Acc 1"
    assert data[1]["balance"] == 200.0

@pytest.mark.asyncio
async def test_update_account_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 2.4: Admin updates an existing account name."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Old Name', 0) RETURNING id", room_id)
        
    response = client.patch(f"/api/classroom/{isolated_room['server_id']}/finance/accounts/{acc_id}", json={"account_name": "New Name"}, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        new_name = await conn.fetchval("SELECT account_name FROM finance_accounts WHERE id = $1", acc_id)
        assert new_name == "New Name"

@pytest.mark.asyncio
async def test_update_non_existent_account(client: TestClient, isolated_room, admin_headers):
    """Test 2.5: Updating an account that doesn't exist returns 404."""
    response = client.patch(f"/api/classroom/{isolated_room['server_id']}/finance/accounts/99999", json={"account_name": "Ghost Account"}, headers=admin_headers)
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_delete_account_success_zero_balance(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 2.6: Successfully delete an unused account with 0 balance."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Empty Vault', 0) RETURNING id", room_id)
        
    response = client.request("DELETE", f"/api/classroom/{isolated_room['server_id']}/finance/accounts/{acc_id}", headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE id = $1", acc_id)
        assert count == 0

@pytest.mark.asyncio
async def test_delete_account_with_existing_balance(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 2.7: Prevent deletion of an account that still holds funds."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Loaded Vault', 500) RETURNING id", room_id)
        
    response = client.request("DELETE", f"/api/classroom/{isolated_room['server_id']}/finance/accounts/{acc_id}", headers=admin_headers)
    assert response.status_code == 400
    assert "ยังมีเงินคงเหลืออยู่" in response.json()["detail"]
    
    # Deep DB Verification: Ensure it wasn't deleted
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE id = $1", acc_id)
        assert count == 1

@pytest.mark.asyncio
async def test_delete_account_linked_to_student_payments(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 2.8: Prevent deletion of an account (even with 0 balance) if it's tied to payment history."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        # Seed Account
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Tied Vault', 0) RETURNING id", room_id)
        # Seed Student
        stu_id = await conn.fetchval("INSERT INTO students (room_id, student_no, first_name, status) VALUES ($1, 1, 'John', 'active') RETURNING id", room_id)
        # Seed Collection & Payment tied to this account
        col_id = await conn.fetchval("INSERT INTO fee_collections (room_id, title, amount, due_date) VALUES ($1, 'Camp', 100, '2030-01-01') RETURNING id", room_id)
        await conn.execute("INSERT INTO student_payments (collection_id, student_id, status, paid_to_account_id) VALUES ($1, $2, 'paid', $3)", col_id, stu_id, acc_id)
        
    response = client.request("DELETE", f"/api/classroom/{isolated_room['server_id']}/finance/accounts/{acc_id}", headers=admin_headers)
    assert response.status_code == 400
    assert "มีประวัติการรับเงิน" in response.json()["detail"]
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_accounts WHERE id = $1", acc_id)
        assert count == 1


# ==============================================================================
# 🗂️ FEATURE 3: CATEGORIES MANAGEMENT
# ==============================================================================

@pytest.mark.asyncio
async def test_create_category_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 3.1: Successfully create a valid expense category."""
    server_id = isolated_room["server_id"]
    payload = {"category_name": "Snacks", "category_type": "expense"}
    
    response = client.post(f"/api/classroom/{server_id}/finance/categories", json=payload, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        cat = await conn.fetchrow("SELECT category_name, category_type FROM finance_categories WHERE room_id = $1", isolated_room["room_id"])
        assert cat is not None
        assert cat["category_name"] == "Snacks"
        assert cat["category_type"] == "expense"

@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_type", ["transfer", "unknown", "", "INCOME"])
async def test_create_category_invalid_type(client: TestClient, isolated_room, admin_headers, db_pool, invalid_type):
    """Test 3.2: Pydantic rejects invalid category types via regex validation."""
    server_id = isolated_room["server_id"]
    payload = {"category_name": "Bad Category", "category_type": invalid_type}
    
    response = client.post(f"/api/classroom/{server_id}/finance/categories", json=payload, headers=admin_headers)
    assert response.status_code == 422
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE room_id = $1", isolated_room["room_id"])
        assert count == 0

@pytest.mark.asyncio
async def test_delete_category_success_unused(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 3.3: Successfully delete a category that has never been used."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'To Delete', 'income') RETURNING id", room_id)
        
    response = client.request("DELETE", f"/api/classroom/{isolated_room['server_id']}/finance/categories/{cat_id}", headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE id = $1", cat_id)
        assert count == 0

@pytest.mark.asyncio
async def test_delete_category_in_use_by_transaction(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 3.4: Prevent deletion of a category if a transaction is actively using it."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Used Cat', 'expense') RETURNING id", room_id)
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc', 100) RETURNING id", room_id)
        
        # Seed a Transaction using the Category
        await conn.execute(
            "INSERT INTO finance_transactions (room_id, account_id, category_id, amount, description, transaction_type) VALUES ($1, $2, $3, 10, 'Test', 'expense')",
            room_id, acc_id, cat_id
        )
        
    response = client.request("DELETE", f"/api/classroom/{isolated_room['server_id']}/finance/categories/{cat_id}", headers=admin_headers)
    assert response.status_code == 400
    assert "มีประวัติรายรับ/รายจ่ายที่ใช้หมวดหมู่นี้อยู่" in response.json()["detail"]
    
    # Deep DB Verification: Category must survive
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_categories WHERE id = $1", cat_id)
        assert count == 1

# ==============================================================================
# 🗂️ FEATURE 3 (CONTINUED): CATEGORIES PATCH & GET FILTERS
# ==============================================================================

@pytest.mark.asyncio
async def test_update_category_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 3.5: Successfully update an existing category's name."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        cat_id = await conn.fetchval(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Old Food', 'expense') RETURNING id", 
            room_id
        )
        
    payload = {"category_name": "New Groceries", "user_name": "Admin Tester"}
    response = client.patch(f"/api/classroom/{server_id}/finance/categories/{cat_id}", json=payload, headers=admin_headers)
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        new_name = await conn.fetchval("SELECT category_name FROM finance_categories WHERE id = $1", cat_id)
        assert new_name == "New Groceries"

@pytest.mark.asyncio
async def test_update_non_existent_category(client: TestClient, isolated_room, admin_headers):
    """Test 3.6: Attempting to update a category that does not exist yields 404."""
    server_id = isolated_room["server_id"]
    payload = {"category_name": "Ghost Cat", "user_name": "Admin"}
    
    response = client.patch(f"/api/classroom/{server_id}/finance/categories/999999", json=payload, headers=admin_headers)
    assert response.status_code == 404
    assert "ไม่พบหมวดหมู่" in response.json()["detail"]

@pytest.mark.asyncio
async def test_get_categories_with_filters(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 3.7: Fetch categories with and without 'cat_type' filters."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    # Seed 2 Income and 1 Expense category
    async with db_pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3)",
            [
                (room_id, "Donations", "income"),
                (room_id, "Sales", "income"),
                (room_id, "Supplies", "expense")
            ]
        )
        
    # 1. Fetch All (No filter)
    res_all = client.get(f"/api/classroom/{server_id}/finance/categories", headers=admin_headers)
    assert res_all.status_code == 200
    assert len(res_all.json()) == 3

    # 2. Fetch Only Income
    res_inc = client.get(f"/api/classroom/{server_id}/finance/categories?cat_type=income", headers=admin_headers)
    assert res_inc.status_code == 200
    assert len(res_inc.json()) == 2
    assert all(c["category_type"] == "income" for c in res_inc.json())

    # 3. Fetch Only Expense
    res_exp = client.get(f"/api/classroom/{server_id}/finance/categories?cat_type=expense", headers=admin_headers)
    assert res_exp.status_code == 200
    assert len(res_exp.json()) == 1
    assert res_exp.json()[0]["category_name"] == "Supplies"

@pytest.mark.asyncio
async def test_get_categories_with_type_filter(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test: Retrieve categories filtered by 'income' or 'expense'."""
    room_id = isolated_room["room_id"]
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Cat A', 'income')", room_id)
        await conn.execute("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Cat B', 'expense')", room_id)
        
    # ดึงเฉพาะ Income
    res = client.get(f"/api/classroom/{isolated_room['server_id']}/finance/categories?cat_type=income", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["category_name"] == "Cat A"

# ==============================================================================
# 💸 FEATURE 4: CORE TRANSACTIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_add_income_transaction_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.1: Successfully add an income transaction and strictly verify math."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    # Seed Account & Category
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 0.0) RETURNING id", room_id)
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Donation', 'income') RETURNING id", room_id)
        
    payload = {
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 500.0,
        "description": "Monthly Subs",
        "transaction_type": "income",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transactions", json=payload, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification: Math and Integrity
    async with db_pool.acquire() as conn:
        # Check Balance
        new_balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(new_balance) == 500.0
        
        # Check Transaction Log
        trans = await conn.fetchrow("SELECT amount, transaction_type FROM finance_transactions WHERE account_id = $1", acc_id)
        assert trans is not None
        assert float(trans["amount"]) == 500.0
        assert trans["transaction_type"] == "income"

@pytest.mark.asyncio
async def test_add_expense_transaction_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.2: Successfully add an expense transaction and strictly verify decrement math."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 500.0) RETURNING id", room_id)
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Server Bill', 'expense') RETURNING id", room_id)
        
    payload = {
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 200.0,
        "description": "AWS Bill",
        "transaction_type": "expense",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transactions", json=payload, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification: Assert exact decrement
    async with db_pool.acquire() as conn:
        new_balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(new_balance) == 300.0

@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_amount", [0.0, -50.0])
async def test_add_transaction_zero_or_negative_amount(client: TestClient, isolated_room, admin_headers, db_pool, invalid_amount):
    """Test 4.3: Pydantic rejects amounts <= 0. DB must remain untouched."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 100.0) RETURNING id", room_id)
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Misc', 'income') RETURNING id", room_id)
        
    payload = {
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": invalid_amount,
        "description": "Hack Attempt",
        "transaction_type": "income",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transactions", json=payload, headers=admin_headers)
    assert response.status_code == 422
    
    # Deep DB Verification: State unaltered
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(balance) == 100.0
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id)
        assert count == 0

@pytest.mark.asyncio
async def test_add_transaction_overdraft_protection(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.4: Prevent spending more than the available balance."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 500.0) RETURNING id", room_id)
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Gear', 'expense') RETURNING id", room_id)
        
    payload = {
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 1000.0, # Exceeds balance
        "description": "Overdraft Attempt",
        "transaction_type": "expense",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transactions", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "เงินไม่พอ" in response.json()["detail"]
    
    # Deep DB Verification: No money lost, no transaction written
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(balance) == 500.0
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id)
        assert count == 0

@pytest.mark.asyncio
async def test_add_transaction_category_mismatch(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.5: Prevent logging an expense using an income category (or vice versa)."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 500.0) RETURNING id", room_id)
        cat_id = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Donation', 'income') RETURNING id", room_id) # Type is INCOME
        
    payload = {
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "description": "Mismatch",
        "transaction_type": "expense", # Type is EXPENSE
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transactions", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "ไม่ตรงกับประเภทการบันทึก" in response.json()["detail"]
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id)
        assert count == 0

@pytest.mark.asyncio
async def test_revert_standard_transaction_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.6: Reverting an expense transaction successfully restores the balance."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        # Initial state: We had 1000, spent 200, so current balance is 800
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 800.0) RETURNING id", room_id)
        trans_id = await conn.fetchval(
            "INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, recorded_by) VALUES ($1, $2, $3, $4, 'expense', 'System') RETURNING id",
            room_id, acc_id, 200.0, "Old Expense"
        )
        
    response = client.request("DELETE", f"/api/classroom/{server_id}/finance/transactions/{trans_id}", json={"user_name": "Admin Tester"}, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        # Check soft delete
        deleted_at = await conn.fetchval("SELECT deleted_at FROM finance_transactions WHERE id = $1", trans_id)
        assert deleted_at is not None
        # Check balance restored to 1000
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(balance) == 1000.0

@pytest.mark.asyncio
async def test_revert_income_transaction_insufficient_balance(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 4.7: Reverting an income fails if the account doesn't have enough money to return."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        # Received 1000 in the past, but current balance is only 200 (spent 800 elsewhere)
        acc_id = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Main Vault', 200.0) RETURNING id", room_id)
        trans_id = await conn.fetchval(
            "INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, recorded_by) VALUES ($1, $2, $3, $4, 'income', 'System') RETURNING id",
            room_id, acc_id, 1000.0, "Old Huge Income"
        )
        
    response = client.request("DELETE", f"/api/classroom/{server_id}/finance/transactions/{trans_id}", json={"user_name": "Admin Tester"}, headers=admin_headers)
    assert response.status_code == 400
    assert "ยอดเงินในบัญชีไม่พอหักคืน" in response.json()["detail"]
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        # Ensure it wasn't deleted
        deleted_at = await conn.fetchval("SELECT deleted_at FROM finance_transactions WHERE id = $1", trans_id)
        assert deleted_at is None
        # Balance must remain untouched
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_id)
        assert float(balance) == 200.0

@pytest.mark.asyncio
async def test_get_transactions_with_filters(client: TestClient, seeded_finance_room):
    """Test: Filter transactions by type and pagination."""
    env = seeded_finance_room
    # สร้าง income 1 รายการ, expense 2 รายการ
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={"account_id": env['account_id'], "category_id": env['category_id'], "amount": 100, "description": "Inc", "transaction_type": "income", "user_name": "A"}, headers=env['admin_headers'])
    
    # Filter เฉพาะ income
    res = client.get(f"/api/classroom/{env['server_id']}/finance/transactions?transaction_type=income", headers=env['admin_headers'])
    assert res.status_code == 200
    data = res.json()
    
    # ต้องเจอแค่ 1 รายการที่เพิ่งสร้าง
    assert data["total_count"] == 1
    assert data["items"][0]["transaction_type"] == "income"

# ==============================================================================
# 📊 FEATURE 4 (CONTINUED): TRANSACTIONS PAGINATION & FILTRATION
# ==============================================================================

from datetime import datetime # 🚨 อย่าลืมเช็คด้านบนสุดของไฟล์นะว่ามี import ตัวนี้หรือยัง!

@pytest_asyncio.fixture
async def seeded_transactions(db_pool, isolated_room):
    """Helper fixture to seed a complex matrix of transactions for filter testing."""
    room_id = isolated_room["room_id"]
    
    async with db_pool.acquire() as conn:
        acc1 = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc 1', 1000) RETURNING id", room_id)
        acc2 = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc 2', 500) RETURNING id", room_id)
        
        cat_inc = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Inc', 'income') RETURNING id", room_id)
        cat_exp = await conn.fetchval("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, 'Exp', 'expense') RETURNING id", room_id)
        
        # Seed 15 transactions with specific spread of dates, accounts, and categories
        # ✅ แก้ String เป็น datetime object ทั้งหมด
        tx_data = [
            (room_id, acc1, cat_inc, 100, "T1", "income", datetime(2023, 1, 5, 10, 0, 0)),
            (room_id, acc1, cat_exp, 50, "T2", "expense", datetime(2023, 1, 15, 12, 0, 0)),
            (room_id, acc2, cat_inc, 200, "T3", "income", datetime(2023, 2, 1, 9, 0, 0)),
            (room_id, acc2, cat_exp, 20, "T4", "expense", datetime(2023, 2, 15, 14, 0, 0)),
            (room_id, acc1, cat_exp, 30, "T5", "expense", datetime(2023, 3, 1, 16, 0, 0)),
        ]
        
        # Add 10 generic transactions on the current date for pagination testing
        for i in range(10):
            # ✅ แก้ String เป็น datetime object
            tx_data.append((room_id, acc1, cat_inc, 10, f"Bulk {i}", "income", datetime(2023, 4, 1, 10, 0, 0)))
            
        for tx in tx_data:
            # ✅ เอา ::timestamp ออกจาก $7
            await conn.execute(
                """INSERT INTO finance_transactions 
                   (room_id, account_id, category_id, amount, description, transaction_type, created_at) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                *tx
            )
            
    return {"acc1": acc1, "acc2": acc2, "cat_inc": cat_inc, "cat_exp": cat_exp}

@pytest.mark.asyncio
async def test_get_transactions_pagination(client: TestClient, isolated_room, admin_headers, seeded_transactions):
    """Test 4.8: Verify limit, offset, and total_count functionality."""
    server_id = isolated_room["server_id"]
    
    # 1. Fetch first page (limit=10)
    res_page1 = client.get(f"/api/classroom/{server_id}/finance/transactions?limit=10&offset=0", headers=admin_headers)
    data1 = res_page1.json()
    
    assert res_page1.status_code == 200
    assert data1["total_count"] == 15
    assert len(data1["items"]) == 10
    
    # 2. Fetch second page (limit=10, offset=10)
    res_page2 = client.get(f"/api/classroom/{server_id}/finance/transactions?limit=10&offset=10", headers=admin_headers)
    data2 = res_page2.json()
    
    assert len(data2["items"]) == 5
    assert data2["total_count"] == 15

@pytest.mark.asyncio
async def test_get_transactions_date_filters(client: TestClient, isolated_room, admin_headers, seeded_transactions):
    """Test 4.9: Verify start_date and end_date correctly bound the SQL WHERE clauses."""
    server_id = isolated_room["server_id"]
    
    # Target January 2023 (Should only catch T1 and T2 from our seed)
    res = client.get(f"/api/classroom/{server_id}/finance/transactions?start_date=2023-01-01&end_date=2023-01-31", headers=admin_headers)
    data = res.json()
    
    assert res.status_code == 200
    assert data["total_count"] == 2
    assert len(data["items"]) == 2
    # Ensure items returned actually belong to January
    descriptions = [i["description"] for i in data["items"]]
    assert "T1" in descriptions and "T2" in descriptions

@pytest.mark.asyncio
async def test_get_transactions_attribute_filters(client: TestClient, isolated_room, admin_headers, seeded_transactions):
    """Test 4.10: Verify filtering by account_id, category_id, and transaction_type."""
    server_id = isolated_room["server_id"]
    acc2_id = seeded_transactions["acc2"]
    cat_exp_id = seeded_transactions["cat_exp"]
    
    # 1. Filter by Account (acc2 has exactly 2 transactions in our seed)
    res_acc = client.get(f"/api/classroom/{server_id}/finance/transactions?account_id={acc2_id}", headers=admin_headers)
    assert res_acc.json()["total_count"] == 2
    
    # 2. Filter by Category & Type
    res_cat = client.get(f"/api/classroom/{server_id}/finance/transactions?category_id={cat_exp_id}&transaction_type=expense", headers=admin_headers)
    data_cat = res_cat.json()
    
    # We seeded exactly 3 expense transactions
    assert data_cat["total_count"] == 3
    assert all(i["transaction_type"] == "expense" for i in data_cat["items"])


# ==============================================================================
# 🔄 FEATURE 5: TRANSFERS
# ==============================================================================

@pytest.mark.asyncio
async def test_transfer_money_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 5.1: Complete transfer linking via transfer_group_id and exact math."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_a = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc A', 500.0) RETURNING id", room_id)
        acc_b = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc B', 100.0) RETURNING id", room_id)
        
    payload = {
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 300.0,
        "description": "Internal Move",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transfer", json=payload, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        # Assert math balances
        bal_a = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_a)
        bal_b = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_b)
        assert float(bal_a) == 200.0  # 500 - 300
        assert float(bal_b) == 400.0  # 100 + 300
        
        # Assert dual-entry transaction records linked properly
        transactions = await conn.fetch("SELECT * FROM finance_transactions WHERE room_id = $1 ORDER BY id ASC", room_id)
        assert len(transactions) == 2
        
        # Assert group IDs match exactly
        group_id_1 = transactions[0]["transfer_group_id"]
        group_id_2 = transactions[1]["transfer_group_id"]
        assert group_id_1 is not None
        assert group_id_1 == group_id_2
        
        # Determine roles
        expense_leg = next(t for t in transactions if t["transaction_type"] == "expense")
        income_leg = next(t for t in transactions if t["transaction_type"] == "income")
        
        assert expense_leg["account_id"] == acc_a
        assert float(expense_leg["amount"]) == 300.0
        assert income_leg["account_id"] == acc_b
        assert float(income_leg["amount"]) == 300.0

@pytest.mark.asyncio
async def test_transfer_money_same_account(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 5.2: Cannot transfer to the exact same account."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_a = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc A', 500.0) RETURNING id", room_id)
        
    payload = {
        "from_account_id": acc_a,
        "to_account_id": acc_a, # Same ID
        "amount": 100.0,
        "description": "Loopback",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transfer", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "โอนเงินเข้าบัญชีเดิมไม่ได้" in response.json()["detail"]
    
    # Verify no rogue transactions
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id)
        assert count == 0

@pytest.mark.asyncio
async def test_transfer_money_overdraft_protection(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 5.3: Prevent transfer if source account lacks funds."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    async with db_pool.acquire() as conn:
        acc_a = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc A', 500.0) RETURNING id", room_id)
        acc_b = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc B', 0.0) RETURNING id", room_id)
        
    payload = {
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 1000.0, # More than Acc A has
        "description": "Overdraft Transfer",
        "user_name": "Admin Tester"
    }
    
    response = client.post(f"/api/classroom/{server_id}/finance/transfer", json=payload, headers=admin_headers)
    assert response.status_code == 400
    assert "ไม่เพียงพอ" in response.json()["detail"]
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        bal_a = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_a)
        assert float(bal_a) == 500.0
        count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id)
        assert count == 0

@pytest.mark.asyncio
async def test_revert_transfer_transaction_success(client: TestClient, isolated_room, admin_headers, db_pool):
    """Test 5.4: Reverting one leg of a transfer gracefully reverts BOTH legs and math."""
    room_id = isolated_room["room_id"]
    server_id = isolated_room["server_id"]
    
    # Setup via actual API to get genuine transfer_group_id linkages
    async with db_pool.acquire() as conn:
        acc_a = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc A', 200.0) RETURNING id", room_id)
        acc_b = await conn.fetchval("INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'Acc B', 400.0) RETURNING id", room_id)
        
    # Send valid transfer 200.0 A -> B
    client.post(f"/api/classroom/{server_id}/finance/transfer", json={
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 200.0,
        "description": "Initial Transfer",
        "user_name": "Admin"
    }, headers=admin_headers)
    
    # Fetch the generated transaction ID for one of the legs (e.g. the expense side)
    async with db_pool.acquire() as conn:
        trans_record = await conn.fetchrow("SELECT id FROM finance_transactions WHERE account_id = $1", acc_a)
        target_trans_id = trans_record["id"]
        
    # Revert it
    response = client.request("DELETE", f"/api/classroom/{server_id}/finance/transactions/{target_trans_id}", json={"user_name": "Admin Tester"}, headers=admin_headers)
    assert response.status_code == 200
    
    # Deep DB Verification
    async with db_pool.acquire() as conn:
        # Check both legs are marked as deleted
        transactions = await conn.fetch("SELECT deleted_at FROM finance_transactions WHERE room_id = $1", room_id)
        assert len(transactions) == 2
        for t in transactions:
            assert t["deleted_at"] is not None
            
        # Verify balances were accurately restored to pre-transfer states
        bal_a = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_a)
        bal_b = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", acc_b)
        assert float(bal_a) == 200.0
        assert float(bal_b) == 400.0

        










# ==============================================================================
# 🧪 FEATURE 3.1: CREATE COLLECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_3_1_1_create_collection_filters_inactive(client, db_pool, seeded_finance_room):
    """Assert that only 'active' students are automatically billed."""
    env = seeded_finance_room
    payload = {
        "title": "September Tuition",
        "amount": 500.0,
        "due_date": "2026-10-01",
        "user_name": "QA Admin"
    }

    res = client.post(f"/api/classroom/{env['server_id']}/finance/collections", json=payload, headers=env['admin_headers'])
    assert res.status_code == 200
    assert "ข้ามคน Inactive 2 คน" in res.json()["message"]

    # Deep DB Verification
    async with db_pool.acquire() as conn:
        col = await conn.fetchrow("SELECT id, amount FROM fee_collections WHERE room_id = $1", env['room_id'])
        assert col is not None
        
        # Verify exactly 3 pending payments were created
        payments = await conn.fetch("SELECT student_id, status FROM student_payments WHERE collection_id = $1", col["id"])
        assert len(payments) == 3
        for p in payments:
            assert p["student_id"] in env["active_students"]
            assert p["status"] == "pending"

@pytest.mark.asyncio
async def test_3_1_2_create_collection_unauthorized(client, seeded_finance_room):
    """Assert missing headers/API Key block collection creation."""
    env = seeded_finance_room
    payload = {"title": "Hack", "amount": 100.0, "due_date": "2026-10-01", "user_name": "Hacker"}

    # No API Key / Discord ID
    res = client.post(f"/api/classroom/{env['server_id']}/finance/collections", json=payload)
    assert res.status_code in [401, 403]

# ==============================================================================
# 🧪 FEATURE 3.2: LATE ENROLLMENT
# ==============================================================================

@pytest.mark.asyncio
async def test_3_2_1_add_new_student_to_collection(client, db_pool, seeded_finance_room):
    env = seeded_finance_room
    # Pre-create a collection
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Camp Fee", "amount": 200, "due_date": "2026-12-01"}, 
                headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")

    # Add an inactive student (simulating late enrollment / manual override)
    target_student = env['inactive_students'][0]
    res = client.post(
        f"/api/classroom/{env['server_id']}/finance/collections/{col_id}/students/{target_student}",
        headers=env['admin_headers'], json={"user_name": "Admin"}
    )
    assert res.status_code == 200

    # Deep DB Check
    async with db_pool.acquire() as conn:
        payment = await conn.fetchrow(
            "SELECT status FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            col_id, target_student
        )
        assert payment is not None
        assert payment["status"] == "pending"

@pytest.mark.asyncio
async def test_3_2_2_add_duplicate_student_conflict(client, db_pool, seeded_finance_room):
    env = seeded_finance_room
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Camp Fee", "amount": 200, "due_date": "2026-12-01"}, 
                headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")
    
    # Active students are already added. Attempting to add one again MUST fail.
    target_student = env['active_students'][0]
    res = client.post(
        f"/api/classroom/{env['server_id']}/finance/collections/{col_id}/students/{target_student}",
        headers=env['admin_headers'], json={"user_name": "Admin"}
    )
    assert res.status_code == 400
    assert "เพื่อนคนนี้มีชื่อในรายการนี้อยู่แล้ว" in res.json()["detail"]

# ==============================================================================
# 🧪 FEATURE 3.3: EDIT PROTECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_3_3_3_edit_amount_blocked_after_payment(client, db_pool, seeded_finance_room):
    """Critical: Once money touches a collection, its mathematical target MUST lock."""
    env = seeded_finance_room
    
    # 1. Create 100 THB collection
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Lock Test", "amount": 100.0, "due_date": "2026-12-01"}, 
                headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")
        payment_id = await conn.fetchval("SELECT id FROM student_payments WHERE collection_id = $1 LIMIT 1", col_id)

    # 2. Make a tiny partial payment (1 THB)
    res_pay = client.put(f"/api/classroom/{env['server_id']}/finance/payments/{payment_id}/pay",
                         json={"paid_to_account_id": env['account_id'], "paid_amount": 1.0, "user_name": "Student A"},
                         headers=env['admin_headers'])
    assert res_pay.status_code == 200

    # 3. Admin tries to raise the collection amount to 150 THB
    res_update = client.put(f"/api/classroom/{env['server_id']}/finance/collections/{col_id}",
                            json={"amount": 150.0, "user_name": "Greedy Admin"},
                            headers=env['admin_headers'])
    
    # 4. Must strictly block
    assert res_update.status_code == 400
    assert "ไม่สามารถแก้จำนวนเงินได้ เนื่องจากมีเพื่อนโอนเงิน/ทยอยจ่ายเข้ามาแล้ว!" in res_update.json()["detail"]

@pytest.mark.asyncio
async def test_update_collection_metadata_success(client: TestClient, db_pool, seeded_finance_room):
    """Test: Can safely update title and due_date."""
    env = seeded_finance_room
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", json={"title": "Old Camp", "amount": 200, "due_date": "2026-12-01"}, headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")
        
    res = client.put(f"/api/classroom/{env['server_id']}/finance/collections/{col_id}", json={"title": "New Camp"}, headers=env['admin_headers'])
    assert res.status_code == 200
    
    async with db_pool.acquire() as conn:
        new_title = await conn.fetchval("SELECT title FROM fee_collections WHERE id = $1", col_id)
        assert new_title == "New Camp"

# ==============================================================================
# 🧪 FEATURE 3.4: PARTIAL PAYMENT LOGIC (THE FINTECH ENGINE)
# ==============================================================================

@pytest_asyncio.fixture(scope="function")
async def active_bill_env(client, db_pool, seeded_finance_room):
    """Helper fixture to set up a collection specifically for payment testing."""
    env = seeded_finance_room
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Math Test", "amount": 100.0, "due_date": "2026-12-01"}, 
                headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")
        # Get one specific student's payment record
        student_id = env['active_students'][0]
        payment_id = await conn.fetchval(
            "SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2", 
            col_id, student_id
        )
    env["payment_id"] = payment_id
    env["student_id"] = student_id
    return env


@pytest.mark.asyncio
async def test_3_4_1_pay_full_amount_exact(client, db_pool, active_bill_env):
    """Case 1: Pay strictly the total amount at once."""
    env = active_bill_env
    
    # 1. Pay 100 on a 100 bill
    res = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 100.0, "user_name": "Test User"},
        headers=env['admin_headers']
    )
    assert res.status_code == 200
    assert "จ่ายครบแล้ว" in res.json()["message"]

    # Deep DB Verification
    async with db_pool.acquire() as conn:
        # Check student state
        p = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        assert p["status"] == "paid"
        assert p["paid_amount"] == Decimal("100.0")

        # Check transaction creation
        t = await conn.fetchrow("SELECT amount, transaction_type FROM finance_transactions WHERE student_payment_id = $1", env['payment_id'])
        assert t is not None
        assert t["amount"] == Decimal("100.0")
        assert t["transaction_type"] == "income"

        # Check account balance (Started at 1000.0, should now be 1100.0)
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal == Decimal("1100.0")

@pytest.mark.asyncio
async def test_3_4_2_and_3_partial_payment_accumulation(client, db_pool, active_bill_env):
    """Cases 2 & 3: Floating point accumulation and threshold status flip."""
    env = active_bill_env
    
    # ---------------- INSTALLMENT 1 ----------------
    # Pay 33.33 (Float precision test)
    res_1 = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 33.33, "user_name": "User"},
        headers=env['admin_headers']
    )
    assert res_1.status_code == 200
    assert "ทยอยจ่าย" in res_1.json()["message"]

    async with db_pool.acquire() as conn:
        p = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        assert p["status"] == "pending" # Still pending!
        assert p["paid_amount"] == Decimal("33.33")
        bal_1 = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal_1 == Decimal("1033.33")

    # ---------------- INSTALLMENT 2 (FINAL) ----------------
    # Pay the remaining 66.67
    res_2 = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 66.67, "user_name": "User"},
        headers=env['admin_headers']
    )
    assert res_2.status_code == 200
    assert "จ่ายครบแล้ว" in res_2.json()["message"]

    async with db_pool.acquire() as conn:
        p = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        assert p["status"] == "paid" # Flipped!
        assert p["paid_amount"] == Decimal("100.00") # Exact float resolution
        
        # Balance must perfectly reflect both payments (1000 + 33.33 + 66.67)
        bal_2 = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal_2 == Decimal("1100.00")
        
        # Verify exactly 2 distinct transactions exist for this payment
        trans_count = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions WHERE student_payment_id = $1", env['payment_id'])
        assert trans_count == 2

@pytest.mark.asyncio
async def test_3_4_4_overpayment_protection(client, db_pool, active_bill_env):
    """Case 4: Attempting to pay an already 'paid' bill MUST be blocked to prevent orphaned money."""
    env = active_bill_env
    
    # Full payment
    client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 100.0, "user_name": "User"},
        headers=env['admin_headers']
    )

    # Attempt second payment
    res_over = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 5.0, "user_name": "User"},
        headers=env['admin_headers']
    )
    
    assert res_over.status_code == 400
    assert "บิลนี้จ่ายครบไปเรียบร้อยแล้วครับ!" in res_over.json()["detail"]

    # Deep DB Check: Ensure the 5.0 THB never hit the account
    async with db_pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal == Decimal("1100.0")

# ==============================================================================
# 🚨 EDGE CASES (BEYOND THE PLAN)
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_negative_and_zero_payments(client, active_bill_env):
    """Pydantic schema (PaymentConfirm) should strictly catch gt=0.0."""
    env = active_bill_env
    
    # 1. Zero Payment
    res_zero = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": 0.0, "user_name": "Hacker"},
        headers=env['admin_headers']
    )
    assert res_zero.status_code == 422 # Unprocessable Entity (Pydantic validation failure)
    
    # 2. Negative Payment
    res_neg = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": env['account_id'], "paid_amount": -50.0, "user_name": "Hacker"},
        headers=env['admin_headers']
    )
    assert res_neg.status_code == 422

@pytest.mark.asyncio
async def test_edge_invalid_destination_account(client, db_pool, active_bill_env):
    """Attempting to pay into a non-existent or wrong-room account MUST abort."""
    env = active_bill_env
    invalid_account_id = 999999

    res = client.put(
        f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
        json={"paid_to_account_id": invalid_account_id, "paid_amount": 50.0, "user_name": "User"},
        headers=env['admin_headers']
    )
    
    assert res.status_code == 400
    assert "กระเป๋าเงินที่เลือกรับเงิน ไม่มีอยู่" in res.json()["detail"]

    # Deep DB Check: Ensure payment status did not mutate
    async with db_pool.acquire() as conn:
        p = await conn.fetchrow("SELECT paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        assert p["paid_amount"] == Decimal("0.0")
    

# ==============================================================================
# 🧪 PHASE 3 SUPPLEMENT: COLLECTIONS (READ & UPDATE)
# ==============================================================================

@pytest.mark.asyncio
async def test_get_all_collections_sorting_and_schema(client, seeded_finance_room):
    """
    Verify GET /collections returns the correct schema and sorts by ID DESC.
    Dashboards expect the newest collections at the top.
    """
    env = seeded_finance_room
    
    # 1. Create two distinct collections
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", json={
        "title": "Older Campaign", "amount": 100.0, "due_date": "2026-01-01"
    }, headers=env['admin_headers'])
    
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", json={
        "title": "Newer Campaign", "amount": 250.0, "due_date": "2026-12-01"
    }, headers=env['admin_headers'])

    # 2. Fetch all collections
    res = client.get(f"/api/classroom/{env['server_id']}/finance/collections", headers=env['admin_headers'])
    assert res.status_code == 200
    
    data = res.json()
    assert len(data) >= 2
    
    # Verify Sorting (DESC by default per service logic)
    assert data[0]["title"] == "Newer Campaign"
    assert data[1]["title"] == "Older Campaign"
    
    # Verify Schema
    assert "id" in data[0]
    assert "status" in data[0]
    assert data[0]["amount"] == 250.0

@pytest.mark.asyncio
async def test_get_collection_status_summary_accuracy(client, db_pool, seeded_finance_room):
    """
    Verify GET /collections/{id} accurately rolls up 'paid' vs 'pending' statuses.
    """
    env = seeded_finance_room
    
    # 1. Create a collection (Billed to 3 active students by default)
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", json={
        "title": "Status Test", "amount": 100.0, "due_date": "2026-12-01"
    }, headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections ORDER BY id DESC LIMIT 1")
        # Get one specific student payment to fulfill
        payment_id = await conn.fetchval("SELECT id FROM student_payments WHERE collection_id = $1 LIMIT 1", col_id)

    # 2. Pay strictly ONE student's bill in full
    client.put(f"/api/classroom/{env['server_id']}/finance/payments/{payment_id}/pay", json={
        "paid_to_account_id": env['account_id'], "paid_amount": 100.0, "user_name": "QA"
    }, headers=env['admin_headers'])

    # 3. Fetch Status Endpoint
    res = client.get(f"/api/classroom/{env['server_id']}/finance/collections/{col_id}", headers=env['admin_headers'])
    assert res.status_code == 200
    
    data = res.json()
    
    # Deep Verification: The Summary Node
    assert data["summary"]["total"] == 3
    assert data["summary"]["paid"] == 1
    assert data["summary"]["pending"] == 2
    
    # Deep Verification: The Students Array
    assert len(data["students"]) == 3
    paid_student = next(s for s in data["students"] if s["payment_id"] == payment_id)
    assert paid_student["status"] == "paid"
    assert paid_student["paid_amount"] == 100.0

@pytest.mark.asyncio
async def test_update_collection_metadata_happy_path(client, db_pool, seeded_finance_room):
    """
    Verify PUT /collections/{id} allows changing title, date, and status 
    without triggering the payment-lockout safeguards.
    """
    env = seeded_finance_room
    
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", json={
        "title": "Original Title", "amount": 100.0, "due_date": "2026-01-01"
    }, headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections ORDER BY id DESC LIMIT 1")

    # Update metadata (Title and Status)
    res = client.put(f"/api/classroom/{env['server_id']}/finance/collections/{col_id}", json={
        "title": "Updated Title", "status": "closed", "user_name": "Admin"
    }, headers=env['admin_headers'])
    
    assert res.status_code == 200
    
    # Deep DB Check
    async with db_pool.acquire() as conn:
        col = await conn.fetchrow("SELECT title, status, amount FROM fee_collections WHERE id = $1", col_id)
        assert col["title"] == "Updated Title"
        assert col["status"] == "closed"
        assert col["amount"] == Decimal("100.0") # Ensure unaffected fields remain strictly untouched

@pytest.mark.asyncio
async def test_get_collection_and_status(client: TestClient, active_bill_env):
    """Test: Fetch all collections and specific collection status."""
    env = active_bill_env
    server_id = env['server_id']
    
    # 1. เทสต์ GET all collections
    res_all = client.get(f"/api/classroom/{server_id}/finance/collections", headers=env['admin_headers'])
    assert res_all.status_code == 200
    assert len(res_all.json()) >= 1
    
    col_id = res_all.json()[0]["id"]
    
    # 2. เทสต์ GET status ของ Collection นั้น
    res_status = client.get(f"/api/classroom/{server_id}/finance/collections/{col_id}", headers=env['admin_headers'])
    assert res_status.status_code == 200
    status_data = res_status.json()
    
    # ต้องมีสรุปยอดจ่าย และรายชื่อเด็ก
    assert "summary" in status_data
    assert "students" in status_data
    assert isinstance(status_data["students"], list)

# ==============================================================================
# 🛠️ SETUP & FIXTURES (For Phase 4)
# ==============================================================================

@pytest_asyncio.fixture(scope="function")
async def revert_env(client, db_pool, seeded_finance_room):
    """
    Sets up an environment specifically for Time Machine testing.
    Includes secondary accounts and categories to test transfers and reverts.
    """
    env = seeded_finance_room
    
    async with db_pool.acquire() as conn:
        # Create an expense category
        expense_cat_id = await conn.fetchval(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
            env['room_id'], "Equipment", "expense"
        )
        # Create a second account for transfer testing
        account2_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            env['room_id'], "Reserve Wallet", 500.00
        )
        
    env['expense_category_id'] = expense_cat_id
    env['account2_id'] = account2_id
    return env

# ==============================================================================
# 🧪 FEATURE 4.1: REVERT SIMPLE TRANSACTIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_4_1_1_revert_expense_refunds_money(client, db_pool, revert_env):
    """Reverting an expense must strictly increment the account balance back."""
    env = revert_env
    
    # 1. Create an expense of 300 (Account goes from 1000 -> 700)
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={
        "account_id": env['account_id'], "category_id": env['expense_category_id'],
        "amount": 300.0, "description": "Buy gear", "transaction_type": "expense", "user_name": "Admin"
    }, headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        trans_id = await conn.fetchval("SELECT id FROM finance_transactions WHERE amount = 300 LIMIT 1")
    
    # 2. Revert the expense
    res = client.request("DELETE", f"/api/classroom/{env['server_id']}/finance/transactions/{trans_id}", 
                         json={"user_name": "Admin Reverter"}, headers=env['admin_headers'])
    assert res.status_code == 200

    # 3. Time Machine Verification
    async with db_pool.acquire() as conn:
        t = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", trans_id)
        assert t["deleted_at"] is not None  # Soft-deleted

        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal == Decimal("1000.0")  # Mathematically refunded

@pytest.mark.asyncio
async def test_4_1_2_and_3_revert_income_and_overdraft_protection(client, db_pool, revert_env):
    """
    TC4.1.2: Standard revert clawbacks money. 
    TC4.1.3: If spent, clawback is blocked to prevent negative balances.
    """
    env = revert_env
    
    # 1. Inject an income of 500 (Balance: 1000 -> 1500)
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={
        "account_id": env['account_id'], "category_id": env['category_id'],
        "amount": 500.0, "description": "Sponsor", "transaction_type": "income", "user_name": "Admin"
    }, headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        trans_id = await conn.fetchval("SELECT id FROM finance_transactions WHERE transaction_type = 'income' ORDER BY id DESC LIMIT 1")

    # 2. Drain the account to 100 (Create expense of 1400)
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={
        "account_id": env['account_id'], "category_id": env['expense_category_id'],
        "amount": 1400.0, "description": "Drain", "transaction_type": "expense", "user_name": "Admin"
    }, headers=env['admin_headers'])

    # 3. Attempt to revert the 500 income (TC4.1.3 Overdraft Lock)
    res_fail = client.request("DELETE", f"/api/classroom/{env['server_id']}/finance/transactions/{trans_id}", 
                              json={"user_name": "Admin"}, headers=env['admin_headers'])
    assert res_fail.status_code == 400
    assert "ไม่พอหักคืน" in res_fail.json()["detail"]

    # Verify Rollback integrity
    async with db_pool.acquire() as conn:
        t = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", trans_id)
        assert t["deleted_at"] is None  # Must NOT be deleted
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal == Decimal("100.0")  # Balance strictly untouched

# ==============================================================================
# 🧪 FEATURE 4.2: REVERT TRANSFERS (LINKED LEGS)
# ==============================================================================

@pytest.mark.asyncio
async def test_4_2_1_revert_full_transfer_success(client, db_pool, revert_env):
    """Reverting one leg of a transfer MUST reverse both accounts and soft-delete both logs."""
    env = revert_env
    
    # Account 1: 1000, Account 2: 500
    client.post(f"/api/classroom/{env['server_id']}/finance/transfer", json={
        "from_account_id": env['account_id'], "to_account_id": env['account2_id'],
        "amount": 400.0, "description": "Move funds", "user_name": "Admin"
    }, headers=env['admin_headers'])

    async with db_pool.acquire() as conn:
        # Get the income leg of the transfer
        inc_trans = await conn.fetchrow("SELECT id, transfer_group_id FROM finance_transactions WHERE transaction_type = 'income' AND transfer_group_id IS NOT NULL")
    
    # Revert targeting just the income leg
    res = client.request("DELETE", f"/api/classroom/{env['server_id']}/finance/transactions/{inc_trans['id']}", 
                         json={"user_name": "Admin"}, headers=env['admin_headers'])
    assert res.status_code == 200

    # Deep Time Machine Verification
    async with db_pool.acquire() as conn:
        # Both legs must be soft-deleted
        legs = await conn.fetch("SELECT deleted_at FROM finance_transactions WHERE transfer_group_id = $1", inc_trans['transfer_group_id'])
        assert len(legs) == 2
        assert all(leg['deleted_at'] is not None for leg in legs)

        # Balances restored precisely to 1000 and 500
        bal1 = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        bal2 = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account2_id'])
        assert bal1 == Decimal("1000.0")
        assert bal2 == Decimal("500.0")

# ==============================================================================
# 🧪 FEATURE 4.3: REVERT STUDENT PAYMENTS
# ==============================================================================

@pytest_asyncio.fixture(scope="function")
async def payment_revert_env(client, db_pool, revert_env):
    """Fixture to set up a bill and partial payments for revert testing."""
    env = revert_env
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Revert Math", "amount": 100.0, "due_date": "2026-12-01"}, 
                headers=env['admin_headers'])
    
    async with db_pool.acquire() as conn:
        col_id = await conn.fetchval("SELECT id FROM fee_collections LIMIT 1")
        student_id = env['active_students'][0]
        payment_id = await conn.fetchval("SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2", col_id, student_id)
    
    env["payment_id"] = payment_id
    return env

@pytest.mark.asyncio
async def test_4_3_1_and_2_revert_partial_and_final_payments(client, db_pool, payment_revert_env):
    """
    TC4.3.1: Reverting a partial payment drops paid_amount but leaves status 'pending'.
    TC4.3.2: Reverting the final payment drops paid_amount AND flips status from 'paid' back to 'pending'.
    """
    env = payment_revert_env
    
    # 1. Make Payment A (40.0)
    client.put(f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
               json={"paid_to_account_id": env['account_id'], "paid_amount": 40.0, "user_name": "Stu"},
               headers=env['admin_headers'])
    
    # 2. Make Payment B (60.0) -> Reaches 100.0, flips to 'paid'
    client.put(f"/api/classroom/{env['server_id']}/finance/payments/{env['payment_id']}/pay",
               json={"paid_to_account_id": env['account_id'], "paid_amount": 60.0, "user_name": "Stu"},
               headers=env['admin_headers'])

    async with db_pool.acquire() as conn:
        trans_a = await conn.fetchval("SELECT id FROM finance_transactions WHERE amount = 40.0")
        trans_b = await conn.fetchval("SELECT id FROM finance_transactions WHERE amount = 60.0")

    # --- TEST TC4.3.2: Revert Payment B (The final one) ---
    res_b = client.request("DELETE", f"/api/classroom/{env['server_id']}/finance/transactions/{trans_b}", 
                           json={"user_name": "Admin"}, headers=env['admin_headers'])
    assert res_b.status_code == 200

    async with db_pool.acquire() as conn:
        p = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        # Deep Assert: Flipped backward accurately
        assert p['status'] == 'pending'
        assert p['paid_amount'] == Decimal("40.0")
        
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal == Decimal("1040.0") # 1000 base + 40 (Payment A)

    # --- TEST TC4.3.1: Revert Payment A (The partial one) ---
    res_a = client.request("DELETE", f"/api/classroom/{env['server_id']}/finance/transactions/{trans_a}", 
                           json={"user_name": "Admin"}, headers=env['admin_headers'])
    assert res_a.status_code == 200

    async with db_pool.acquire() as conn:
        p_final = await conn.fetchrow("SELECT status, paid_amount FROM student_payments WHERE id = $1", env['payment_id'])
        # Deep Assert: Math perfection
        assert p_final['status'] == 'pending'
        assert p_final['paid_amount'] == Decimal("0.0")
        
        bal_final = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", env['account_id'])
        assert bal_final == Decimal("1000.0") # Restored to absolute zero state

# ==============================================================================
# 🧪 FEATURE 4.4: ANALYTICS & DASHBOARDS
# ==============================================================================

@pytest.mark.asyncio
async def test_4_4_1_dashboard_excludes_soft_deleted(client, db_pool, revert_env):
    """The Analytics Dashboard MUST mathematically ignore ghost (soft-deleted) records."""
    env = revert_env
    
    # Create valid income (100) and expense (50)
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={"account_id": env['account_id'], "category_id": env['category_id'], "amount": 100.0, "description": "Good", "transaction_type": "income", "user_name": "A"}, headers=env['admin_headers'])
    client.post(f"/api/classroom/{env['server_id']}/finance/transactions", json={"account_id": env['account_id'], "category_id": env['expense_category_id'], "amount": 50.0, "description": "Good", "transaction_type": "expense", "user_name": "A"}, headers=env['admin_headers'])

    # Inject ghost records directly via SQL to simulate reverted states
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, transaction_type, deleted_at)
            VALUES ($1, $2, $3, 9999.0, 'income', NOW()), 
                   ($1, $2, $4, 8888.0, 'expense', NOW())
        """, env['room_id'], env['account_id'], env['category_id'], env['expense_category_id'])

    # Fetch Summary
    res = client.get(f"/api/classroom/{env['server_id']}/finance/summary", headers=env['admin_headers'])
    assert res.status_code == 200
    data = res.json()

    # Ghost records completely ignored
    assert data["total_income"] == 100.0
    assert data["total_expense"] == 50.0
    assert data["net_worth"] == 1050.0 # 1000 base + 100 - 50

@pytest.mark.asyncio
async def test_4_4_2_and_3_student_debts_float_precision(client, db_pool, revert_env):
    """
    TC4.4.2 & TC4.4.3: Verify exact decimal math when accumulating debts for endpoints.
    Test float anomaly handling (e.g. 99.99 + 0.01).
    """
    env = revert_env
    student_id = env['active_students'][0]

    # Create Bill 1: 99.99
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Float Bill 1", "amount": 99.99, "due_date": "2026-11-01"}, 
                headers=env['admin_headers'])
    
    # Create Bill 2: 50.00
    client.post(f"/api/classroom/{env['server_id']}/finance/collections", 
                json={"title": "Bill 2", "amount": 50.00, "due_date": "2026-11-02"}, 
                headers=env['admin_headers'])

    async with db_pool.acquire() as conn:
        pay1_id = await conn.fetchval("SELECT id FROM student_payments WHERE student_id = $1 ORDER BY id ASC LIMIT 1", student_id)

    # Pay exactly 0.01 on the 99.99 bill. Pending amount for this bill should be 99.98.
    client.put(f"/api/classroom/{env['server_id']}/finance/payments/{pay1_id}/pay",
               json={"paid_to_account_id": env['account_id'], "paid_amount": 0.01, "user_name": "Stu"},
               headers=env['admin_headers'])

    # --- Verify Individual Debt Profile (get_student_debts) ---
    res_profile = client.get(f"/api/classroom/{env['server_id']}/finance/students/{student_id}/debts", headers=env['admin_headers'])
    assert res_profile.status_code == 200
    profile = res_profile.json()
    
    # Expect: 99.98 (Bill 1) + 50.00 (Bill 2) = 149.98
    assert profile["total_pending_amount"] == 149.98
    assert len(profile["debts"]) == 2
    assert profile["debts"][0]["amount"] == 99.98

    # --- Verify Global Debtors Array (get_all_debtors) ---
    res_debtors = client.get(f"/api/classroom/{env['server_id']}/finance/debtors", headers=env['admin_headers'])
    assert res_debtors.status_code == 200
    debtors = res_debtors.json()

    # Find our specific student in the aggregated list
    target_debtor = next(d for d in debtors if d["student_id"] == student_id)
    
    assert target_debtor is not None
    # Ensure they appear as a SINGLE object with aggregated counts
    assert target_debtor["overdue_count"] == 2
    assert target_debtor["total_pending_amount"] == 149.98

# ==============================================================================
# 🧪 PHASE 4 SUPPLEMENT: DASHBOARD ANALYTICS WITH TIME FILTERS
# ==============================================================================

@pytest.mark.asyncio
async def test_get_summary_with_historical_date_filters(client, db_pool, seeded_finance_room):
    """
    Verify GET /summary?month=X&year=Y strictly scopes the mathematical aggregation 
    to the requested time period, isolating it from current transactions.
    """
    env = seeded_finance_room
    
    # 1. Inject Historical Transactions natively via SQL (Bypassing API to set specific created_at dates)
    async with db_pool.acquire() as conn:
        # Create an income category for testing
        cat_id = env['category_id'] 
        
        # Inject records for August 2025
        await conn.execute("""
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, transaction_type, created_at)
            VALUES 
            ($1, $2, $3, 1000.0, 'income', '2025-08-15 10:00:00'),
            ($1, $2, $3, 250.0, 'expense', '2025-08-20 10:00:00')
        """, env['room_id'], env['account_id'], cat_id)

        # Inject records for September 2025 (Should be ignored by the query)
        await conn.execute("""
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, transaction_type, created_at)
            VALUES ($1, $2, $3, 5000.0, 'income', '2025-09-01 10:00:00')
        """, env['room_id'], env['account_id'], cat_id)

    # 2. Query Dashboard strictly for August 2025
    res = client.get(
        f"/api/classroom/{env['server_id']}/finance/summary", 
        params={"month": 8, "year": 2025},
        headers=env['admin_headers']
    )
    
    assert res.status_code == 200
    data = res.json()
    
    # 3. Verify absolute isolation of historical data
    assert data["period"] == "2025-08"
    assert data["total_income"] == 1000.0   # The 5000.0 from Sept MUST be ignored
    assert data["total_expense"] == 250.0
    
    # Note: net_worth is a cumulative current state of accounts, 
    # so it does not (and theoretically shouldn't) scope to the month filter.
    # It will reflect the actual current balance of the DB.
    assert "net_worth" in data

@pytest.mark.asyncio
async def test_get_summary_with_month_year_filter(client: TestClient, db_pool, revert_env):
    """Test: Fetch dashboard summary for a specific past month and year."""
    env = revert_env
    server_id = env['server_id']
    
    # ยัด Transaction สมมติว่าเกิดเดือน 5 ปี 2025
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO finance_transactions (room_id, account_id, category_id, amount, transaction_type, created_at)
            VALUES ($1, $2, $3, 5000.0, 'income', '2025-05-15 10:00:00')
        """, env['room_id'], env['account_id'], env['category_id'])
        
    # ดึงยอดของเดือน 5 ปี 2025
    res = client.get(f"/api/classroom/{server_id}/finance/summary?month=5&year=2025", headers=env['admin_headers'])
    assert res.status_code == 200
    data = res.json()
    
    # ต้องจับยอด 5000 ที่เราเพิ่งยัดไปได้
    assert data["total_income"] == 5000.0
    assert data["period"] == "2025-05"