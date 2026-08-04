"""
HTTP-layer integration tests for finance_router.py.

ครอบคลุมการทำงานผ่าน HTTP (TestClient) ที่ชุดเทสเดิม (test_finance.py / test_finance_edge_cases.py)
ซึ่งเป็น service-level ยังไม่จับ:
  - Auth path ทั้งสอง: Discord bot (X-API-Key + X-Discord-Id) และ Web (JWT Bearer)
  - Status-code mapping ของ router (400/403/404/401)
  - target_type=room/server resolution ผ่าน URL path
  - Response schema (response_model) ฟิลเตอร์ secret fields
  - Footgun: get_target default target_type='server' → ต้องส่ง ?target_type=room สำหรับ web เสมอ

Pattern ตาม docs/rules/testing.md: mock ActionService/aioredis เพื่อไม่แตะ Redis จริง,
deep DB verification หลัง HTTP call
"""
import random
import string
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Fixtures: HTTP client with real auth ===


async def _insert_user(
    pool, *, email=None, first_name="Test", last_name="User", username=None, discord_id=None,
) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email, first_name, last_name, username, discord_id,
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


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, status="active") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', $4, FALSE, '[]'::jsonb)
            RETURNING id
            """,
            room_id, user_id, student_no, status,
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


async def _insert_collection(pool, room_id: int, title="ค่าเทอม", amount=1000.0, status="active") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO fee_collections (room_id, title, amount, due_date, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_id, title, amount, date(2026, 12, 31), status,
        )


async def _insert_student_payment(pool, collection_id: int, student_id: int, status="pending", paid_amount=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            collection_id, student_id, status, paid_amount,
        )


# Auth helpers


def _make_bot_headers(discord_id: int) -> dict:
    return {
        "X-API-Key": settings.API_KEY,
        "X-Discord-Id": str(discord_id),
    }


def _make_web_headers(user_id: int) -> dict:
    from jose import jwt
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _room_api(target_id: int, path: str, target_type: str = "room") -> str:
    """สร้าง URL finance API โดยผูก target_type ตามจริง (web=room, bot=server)"""
    return f"/api/classroom/{target_id}{path}?target_type={target_type}"


async def _fetch_count(db_pool, sql: str, *args) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


# =====================================================================
# Section A: Authentication
# =====================================================================


async def test_web_endpoint_requires_auth(client, db_pool):
    """ไม่ส่ง token → 401"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(_room_api(room_id, "/finance/accounts"))
    assert resp.status_code == 401


async def test_bot_endpoint_requires_api_key(client, db_pool):
    """ส่งแค่ X-Discord-Id ไม่มี X-API-Key → 401"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(_room_api(room_id, "/finance/accounts"), headers={"X-Discord-Id": "111"})
    assert resp.status_code == 401


async def test_bot_api_key_without_discord_id_is_400(client, db_pool):
    """มี API Key แต่ไม่มี X-Discord-Id → 400 (ต้องการระบุตัวตน)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(_room_api(room_id, "/finance/accounts"), headers={"X-API-Key": settings.API_KEY})
    assert resp.status_code == 400


async def test_bot_unknown_discord_id_404(client, db_pool):
    """API Key ถูก แต่ discord_id ไม่มีในระบบ → 404"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        _room_api(room_id, "/finance/accounts"),
        headers=_make_bot_headers(999_999_999),
    )
    assert resp.status_code == 404


async def test_bot_invalid_discord_id_format_400(client, db_pool):
    """X-Discord-Id ไม่ใช่ตัวเลข → 400"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        _room_api(room_id, "/finance/accounts"),
        headers={"X-API-Key": settings.API_KEY, "X-Discord-Id": "abc"},
    )
    assert resp.status_code == 400


# =====================================================================
# Section B: Read endpoints (bot path) — status mapping
# =====================================================================


async def test_bot_get_accounts_200(client, db_pool):
    discord_id = 775500
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=discord_id)
    room_id = await _insert_room(db_pool, owner)
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)

    resp = client.get(
        _room_api(room_id, "/finance/accounts"),
        headers=_make_bot_headers(discord_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["account_name"] == "กองกลาง"
    assert float(data[0]["balance"]) == pytest.approx(100.0)
    # response_model=AccountResponse — ต้องไม่มี field เกิน (room_id/deleted_at ถูกฟิลเตอร์)
    assert "room_id" not in data[0]
    assert "deleted_at" not in data[0]


async def test_bot_get_accounts_room_not_found_404(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    await _insert_room(db_pool, owner)

    resp = client.get(
        _room_api(999999999, "/finance/accounts"),
        headers=_make_bot_headers(owner),
    )
    assert resp.status_code == 404


async def test_bot_get_accounts_cross_room_blocked_403(client, db_pool):
    """สมาชิกห้อง A ขอดูบัญชีห้อง B → 403 (require_member)"""
    discord_member = 775501
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b, room_name="ห้อง B")
    member_a = await _insert_user(db_pool, first_name="Member", last_name="A", discord_id=discord_member)
    await _insert_student(db_pool, room_a, member_a, 1)
    await _insert_finance_account(db_pool, room_b, "เงินห้อง B", 999.0)

    resp = client.get(
        _room_api(room_b, "/finance/accounts"),
        headers=_make_bot_headers(discord_member),
    )
    assert resp.status_code == 403


# =====================================================================
# Section C: Mutations (web path) — create/read roundtrip
# =====================================================================


async def test_web_create_account_200_and_readback(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    headers = _make_web_headers(owner)

    resp = client.post(
        _room_api(room_id, "/finance/accounts"),
        json={"account_name": "กองกลาง", "initial_balance": 500.0},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # deep DB verify
    assert await _fetch_count(
        db_pool, "SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id
    ) == 1


async def test_web_create_account_member_forbidden_403(client, db_pool):
    """member ธรรมดาไม่มี MANAGE_FINANCE → 403"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool, first_name="Plain", last_name="Member")
    await _insert_student(db_pool, room_id, member, 5)

    resp = client.post(
        _room_api(room_id, "/finance/accounts"),
        json={"account_name": "แอบสร้าง", "initial_balance": 0.0},
        headers=_make_web_headers(member),
    )
    assert resp.status_code == 403
    assert await _fetch_count(
        db_pool, "SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id
    ) == 0


async def test_web_create_account_invalid_payload_422(client, db_pool):
    """amount ลบ / เกิน max_length → 422 (Pydantic)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # negative initial_balance → 422
    resp = client.post(
        _room_api(room_id, "/finance/accounts"),
        json={"account_name": "บัญชี", "initial_balance": -1.0},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 422

    # account_name เกิน 100 chars → 422
    resp = client.post(
        _room_api(room_id, "/finance/accounts"),
        json={"account_name": "x" * 101, "initial_balance": 0.0},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 422


# =====================================================================
# Section D: HTTP roundtrip for each mutation type
# =====================================================================


async def test_web_add_transaction_roundtrip(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    resp = client.post(
        _room_api(room_id, "/finance/transactions"),
        json={
            "account_id": account_id,
            "category_id": cat_id,
            "amount": 100.0,
            "description": "รับบริจาค",
            "transaction_type": "income",
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # read back via HTTP
    resp = client.get(
        _room_api(room_id, "/finance/transactions"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert float(data["items"][0]["amount"]) == pytest.approx(100.0)
    assert data["items"][0]["transaction_type"] == "income"
    assert data["items"][0]["account_name"] == "กองกลาง"


async def test_web_add_transaction_expense_over_balance_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    resp = client.post(
        _room_api(room_id, "/finance/transactions"),
        json={
            "account_id": account_id,
            "category_id": cat_id,
            "amount": 200.0,
            "description": "เกินวงเงิน",
            "transaction_type": "expense",
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_add_transaction_category_mismatch_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    income_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    resp = client.post(
        _room_api(room_id, "/finance/transactions"),
        json={
            "account_id": account_id,
            "category_id": income_cat,
            "amount": 50.0,
            "description": "หมวดไม่ตรง",
            "transaction_type": "expense",
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_transfer_roundtrip(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "หลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "รอง", 0.0)

    resp = client.post(
        _room_api(room_id, "/finance/transfer"),
        json={
            "from_account_id": from_acc,
            "to_account_id": to_acc,
            "amount": 400.0,
            "description": "ฝากสำรอง",
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # deep verify balance
    async with db_pool.acquire() as conn:
        f = float(await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", from_acc))
        t = float(await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", to_acc))
    assert f == pytest.approx(600.0)
    assert t == pytest.approx(400.0)


async def test_web_transfer_same_account_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    acc = await _insert_finance_account(db_pool, room_id, "บัญชีเดียว", 1000.0)

    resp = client.post(
        _room_api(room_id, "/finance/transfer"),
        json={
            "from_account_id": acc,
            "to_account_id": acc,
            "amount": 100.0,
            "description": "x",
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_create_collection_roundtrip(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)

    resp = client.post(
        _room_api(room_id, "/finance/collections"),
        json={
            "title": "ค่าเทอม",
            "amount": 1000.0,
            "due_date": "2026-12-31",
            "student_ids": [s1],
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # read back via HTTP
    resp = client.get(
        _room_api(room_id, "/finance/collections"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    cols = resp.json()
    assert len(cols) == 1
    assert cols[0]["title"] == "ค่าเทอม"
    assert float(cols[0]["amount"]) == pytest.approx(1000.0)


async def test_web_create_collection_empty_student_ids_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        _room_api(room_id, "/finance/collections"),
        json={
            "title": "ค่าเทอม",
            "amount": 1000.0,
            "due_date": "2026-12-31",
            "student_ids": [],
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_confirm_payment_roundtrip(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    resp = client.put(
        _room_api(room_id, f"/finance/payments/{payment_id}/pay"),
        json={
            "paid_to_account_id": account_id,
            "paid_amount": 1000.0,
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert "จ่ายครบแล้ว" in resp.json()["message"]

    # read collection status via HTTP
    resp = client.get(
        _room_api(room_id, f"/finance/collections/{collection_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 1
    assert data["summary"]["paid"] == 1
    assert data["students"][0]["status"] == "paid"


async def test_web_confirm_payment_fully_paid_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    payment_id = await _insert_student_payment(db_pool, collection_id, student_id, "paid", 1000.0)

    resp = client.put(
        _room_api(room_id, f"/finance/payments/{payment_id}/pay"),
        json={
            "paid_to_account_id": account_id,
            "paid_amount": 100.0,
            "user_name": "Owner",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_revert_transaction_roundtrip(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    # create income 100 → balance 200
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=100.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            "SELECT id FROM finance_transactions WHERE room_id = $1 AND deleted_at IS NULL",
            room_id,
        )

    resp = client.delete(
        _room_api(room_id, f"/finance/transactions/{tx_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert "ยกเลิก" in resp.json()["message"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id)
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert row["deleted_at"] is not None
    assert float(bal) == pytest.approx(100.0)


# =====================================================================
# Section E: bot path mutations (X-Discord-Id) — same behaviour
# =====================================================================


async def test_bot_create_account_via_discord(client, db_pool):
    """บอท (X-API-Key + X-Discord-Id) สร้างบัญชีได้เหมือน web"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=777000)
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        _room_api(room_id, "/finance/accounts"),
        json={"account_name": "กองกลาง", "initial_balance": 0.0},
        headers=_make_bot_headers(777000),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert await _fetch_count(
        db_pool, "SELECT COUNT(*) FROM finance_accounts WHERE room_id = $1", room_id
    ) == 1


# =====================================================================
# Section F: URL target resolution
# =====================================================================


async def test_bot_server_target_type_resolves_room(client, db_pool):
    """target_type=server → server_id → resolve ไป room"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner", discord_id=778001)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)

    resp = client.get(
        _room_api(server_id, "/finance/accounts", target_type="server"),
        headers=_make_bot_headers(778001),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_bot_server_target_not_found_404(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        _room_api(random.randint(10000000, 99999999), "/finance/accounts", target_type="server"),
        headers=_make_bot_headers(owner),
    )
    assert resp.status_code == 404


async def test_missing_target_type_defaults_to_room_200(client, db_pool):
    """
    Regression: get_target default เปลี่ยนเป็น target_type='room' (ตาม resolve_target_to_room_id)
    → ไม่ส่ง ?target_type=room ก็ treat id เป็น room_id → 200 (ไม่ 404 งง ๆ เหมือนเดิม)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)

    resp = client.get(
        f"/api/classroom/{room_id}/finance/accounts",
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# =====================================================================
# Section G: Error mapping edge cases (router catch ValueError)
# =====================================================================


async def test_web_delete_account_with_balance_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "มีเงิน", 500.0)

    resp = client.delete(
        _room_api(room_id, f"/finance/accounts/{account_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_delete_account_not_found_404(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.delete(
        _room_api(room_id, "/finance/accounts/999999999"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 404


async def test_web_delete_category_in_use_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=10.0,
            description="ซื้อ", transaction_type="expense", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    resp = client.delete(
        _room_api(room_id, f"/finance/categories/{cat_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_get_summary_and_debtors_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=300.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    resp = client.get(
        _room_api(room_id, "/finance/summary"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["net_worth"]) == pytest.approx(400.0)
    assert float(data["total_income"]) == pytest.approx(300.0)

    resp = client.get(
        _room_api(room_id, "/finance/debtors"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_web_get_student_debts_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    resp = client.get(
        _room_api(room_id, f"/finance/students/{student_id}/debts"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["total_pending_amount"]) == pytest.approx(1000.0)


async def test_web_add_student_to_collection_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    resp = client.post(
        _room_api(room_id, f"/finance/collections/{collection_id}/students/{student_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert await _fetch_count(
        db_pool, "SELECT COUNT(*) FROM student_payments WHERE collection_id = $1 AND student_id = $2",
        collection_id, student_id,
    ) == 1


async def test_web_remove_student_from_collection_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    await _insert_student_payment(db_pool, collection_id, student_id, "pending", 0.0)

    resp = client.delete(
        _room_api(room_id, f"/finance/collections/{collection_id}/students/{student_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert await _fetch_count(
        db_pool, "SELECT COUNT(*) FROM student_payments WHERE collection_id = $1 AND student_id = $2",
        collection_id, student_id,
    ) == 0


async def test_web_update_collection_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    collection_id = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)

    resp = client.put(
        _room_api(room_id, f"/finance/collections/{collection_id}"),
        json={"title": "ค่าเทอม (เลื่อน)", "due_date": "2027-01-15"},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT title FROM fee_collections WHERE id = $1", collection_id)
    assert row["title"] == "ค่าเทอม (เลื่อน)"


async def test_web_update_category_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    resp = client.patch(
        _room_api(room_id, f"/finance/categories/{cat_id}"),
        json={"category_name": "ค่ากิน", "category_type": "expense"},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT category_name FROM finance_categories WHERE id = $1", cat_id)
    assert row["category_name"] == "ค่ากิน"
