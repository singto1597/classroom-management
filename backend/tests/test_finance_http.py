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
import io
import random
import string
import uuid
from datetime import date, datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient

from core.config import settings
from services.finance.receipts import ReceiptsMixin
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


async def _provision_opening_balance(db_pool, room_id: int, account_id: int, amount: float):
    """[DOUBLE-ENTRY] สร้าง 'ยอดยกมา' (opening balance) ให้บัญชี — เลียนแบบ migrate_phase2_5_opening_balance.py.

    เงินตั้งต้นของบัญชีที่เกิดก่อนยุคบัญชีคู่ (ก่อน CUTOFF_DATE) จะไม่อยู่ใน journal
    → ต้องแปลงเป็น journal reference_type='opening_balance' (asset Dr / equity Cr)
    แล้ว Net Worth (v2 ซึ่งรวม asset สะสมจาก journal) จึงจะนับเงินส่วนนั้นได้
    (ยอดยกมาไม่ถูกนับเป็นรายได้ของงวด เพราะถูกกรอง reference_type<>'opening_balance')
    """
    import json
    async with db_pool.acquire() as conn:
        asset_ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND legacy_account_id = $2",
            room_id, account_id,
        )
        if not asset_ledger_id:
            account_name = await conn.fetchval(
                "SELECT account_name FROM finance_accounts WHERE id = $1", account_id
            )
            asset_ledger_id = await conn.fetchval(
                """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description)
                   VALUES ($1, $2, $3, 'asset', $4, 'test') RETURNING id""",
                room_id, f"1{account_id:04d}", account_name, account_id,
            )
        equity_ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND account_code = '3000'", room_id
        )
        if not equity_ledger_id:
            equity_ledger_id = await conn.fetchval(
                """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description)
                   VALUES ($1, '3000', 'ทุน-ยอดยกมา', 'equity', 'test') RETURNING id""", room_id
            )
        entry_id = await conn.fetchval(
            """INSERT INTO journal_entries (room_id, reference_type, description, recorded_by, metadata)
               VALUES ($1, 'opening_balance', 'ตั้งยอดยกมา (ระบบบัญชีคู่)', 'SYSTEM', $2::jsonb)
               RETURNING id""",
            room_id, json.dumps({"note": "test"}),
        )
        await conn.execute(
            "INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description) VALUES ($1, $2, $3, 0, 'ยอดยกมา')",
            entry_id, asset_ledger_id, amount,
        )
        await conn.execute(
            "INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description) VALUES ($1, $2, 0, $3, 'ทุน')",
            entry_id, equity_ledger_id, amount,
        )
        await conn.execute("UPDATE journal_entries SET transaction_date = '2026-09-01 00:00:00' WHERE id = $1", entry_id)


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
            # [F6] ใบรับเงินพิมพ์ชื่อ "ผู้จ่ายเงิน" ลงกระดาษ ⇒ service บังคับให้ระบุ
            "payee_name": "ผู้ปกครองทดสอบ",
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
            # 🔴 [F6] **ต้องมีบรรทัดนี้ ไม่งั้นเทสต์นี้กลายเป็น false positive**:
            #    มันคาด 400 จาก "ยอดเกินวงเงิน" แต่ถ้าไม่ส่ง `payee_name` มันจะได้ 400
            #    จากด่านผู้เบิกแทน ⇒ **เลิกทดสอบสิ่งที่มันตั้งใจทดสอบ** โดยที่ status
            #    ยังเป็น 400 เหมือนเดิม = เทสต์ที่ไม่มีวันจับ regression ของด่านยอดเงินได้อีก
            "payee_name": "ผู้เบิกทดสอบ",
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
            # 🔴 [F6] เหตุผลเดียวกับเทสต์ "ยอดเกินวงเงิน" ข้างบน: ถ้าไม่ส่ง `payee_name`
            #    จะได้ 400 จากด่านผู้เบิก แล้ว **ด่าน "หมวดไม่ตรง" จะไม่ถูกทดสอบอีกเลย**
            "payee_name": "ผู้เบิกทดสอบ",
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
        payee_name="คู่กรณีทดสอบ",
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
        payee_name="คู่กรณีทดสอบ",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    resp = client.delete(
        _room_api(room_id, f"/finance/categories/{cat_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


async def test_web_revert_pre_cutoff_transaction_400(client, db_pool):
    """[FIX B] web ลองยกเลิกรายการที่สร้างก่อน 1 ก.ย. → 400 (freeze legacy) + DB ไม่เปลี่ยน"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            """INSERT INTO finance_transactions (room_id, account_id, category_id, amount, description, transaction_type, recorded_by, created_at)
               VALUES ($1, $2, $3, 100.0, 'ของเก่าก่อนบัญชีคู่', 'income', 'Owner', '2026-08-01 10:00:00')
               RETURNING id""",
            room_id, account_id, cat_id,
        )
        await conn.execute("UPDATE finance_accounts SET balance = 200.0 WHERE id = $1", account_id)

    resp = client.delete(
        _room_api(room_id, f"/finance/transactions/{tx_id}"),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id)
        assert row["deleted_at"] is None
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert float(bal) == pytest.approx(200.0)


async def test_web_get_summary_and_debtors_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 100.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    from models.finance_schemas import TransactionCreate

    # [DOUBLE-ENTRY] เดือนปัจจุบันเลย CUTOFF_DATE → /summary อ่านจาก journal (v2)
    # เงินตั้งต้น 100 ต้องมี 'ยอดยกมา' ใน journal (เหมือน migration จริง) จึงจะรวมใน Net Worth
    await _provision_opening_balance(db_pool, room_id, account_id, 100.0)

    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=300.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        payee_name="คู่กรณีทดสอบ",
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
    # Net Worth (v2) = ยอดยกมา 100 + รายได้ 300; total_income ไม่นับยอดยกมา
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


# =====================================================================
# Section: Export Excel (ประวัติการเงิน)
# =====================================================================


async def test_web_export_finance_excel_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=300.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        payee_name="คู่กรณีทดสอบ",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )

    resp = client.post(
        _room_api(room_id, "/finance/export"),
        json={},  # ไม่ระบุช่วงเวลา → ทั้งหมด
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["content-disposition"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == [
        "สรุปยอด", "ประวัติรายการ", "สรุปรายหมวดหมู่",
        "สรุปโปรเจคเก็บเงิน (Fee)", "ทะเบียนลูกหนี้ (AR)",
        "สรุปรายเดือน (Monthly)",
    ]
    ws_data = wb["ประวัติรายการ"]
    rows = list(ws_data.values)
    assert len(rows) == 2  # header + 1 รายการ


async def test_web_export_finance_excel_month_filter(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=100.0,
            description="ม.ค.", transaction_type="income", user_name="Owner",
        payee_name="คู่กรณีทดสอบ",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=200.0,
            description="ก.พ.", transaction_type="income", user_name="Owner",
        payee_name="คู่กรณีทดสอบ",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM finance_transactions WHERE room_id = $1 ORDER BY id", room_id)
        # คอลัมน์ TIMESTAMP ต้องส่ง datetime object (asyncpg ปฏิเสธ string — ตาม docs/skills.md)
        await conn.execute(
            "UPDATE finance_transactions SET created_at = $2 WHERE id = $1",
            rows[1]["id"], datetime(2026, 2, 10, 10, 0, 0),
        )

    resp = client.post(
        _room_api(room_id, "/finance/export"),
        json={"month": 2, "year": 2026},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows_out = list(wb["ประวัติรายการ"].values)
    assert len(rows_out) == 2  # header + 1 รายการ (เฉพาะ ก.พ.)
    assert "ก.พ." in rows_out[1][6]


async def test_web_export_finance_excel_cross_room_forbidden(client, db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b, room_name="ห้อง B")
    member_a = await _insert_user(db_pool, first_name="Member", last_name="A")
    await _insert_student(db_pool, room_a, member_a, 1, status="active")

    resp = client.post(
        _room_api(room_b, "/finance/export"),
        json={},
        headers=_make_web_headers(member_a),
    )
    assert resp.status_code == 403


async def test_web_export_finance_excel_bad_period_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    # month โดยไม่มี year → 422 (Pydantic validator)
    resp = client.post(
        _room_api(room_id, "/finance/export"),
        json={"month": 2},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 422

    # start_date หลัง end_date → 400
    resp = client.post(
        _room_api(room_id, "/finance/export"),
        json={"start_date": "2026-02-01", "end_date": "2026-01-01"},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


# === GET /{target_id}/finance/export/journal (สมุดรายวันสำหรับนักบัญชี) ===


async def test_web_export_journal_excel_200(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    from models.finance_schemas import TransactionCreate
    await FinanceService.add_transaction(
        pool=db_pool,
        req=TransactionCreate(
            account_id=account_id, category_id=cat_id, amount=300.0,
            description="รับบริจาค", transaction_type="income", user_name="Owner",
        payee_name="คู่กรณีทดสอบ",
        ),
        user_id=owner, client_source="test", actor_identifier="test",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-10' WHERE room_id = $1", room_id
        )

    resp = client.get(
        _room_api(room_id, "/finance/export/journal") + "&month=10&year=2026",
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["content-disposition"]
    assert "finance_journal_" in resp.headers["content-disposition"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == [
        "Financial Dashboard", "งบแสดงฐานะการเงิน (BS)",
        "งบกำไรขาดทุน (Income Statement)", "งบทดลอง (Trial Balance)",
        "สมุดบัญชีแยกประเภท (GL)", "สมุดรายวันทั่วไป (GJ)",
    ]
    rows = list(wb["สมุดรายวันทั่วไป (GJ)"].values)
    # header (แถวที่ 3 — title/subtitle อยู่แถว 1-2) มีคอลัมน์ตามสเปค
    header = rows[2]
    assert header[0] == "วันที่" and header[6] == "เดบิต (Dr.)" and header[7] == "เครดิต (Cr.)"


async def test_web_export_journal_excel_cross_room_forbidden(client, db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b, room_name="ห้อง B")
    member_a = await _insert_user(db_pool, first_name="Member", last_name="A")
    await _insert_student(db_pool, room_a, member_a, 1, status="active")

    resp = client.get(
        _room_api(room_b, "/finance/export/journal"),
        headers=_make_web_headers(member_a),
    )
    assert resp.status_code == 403


async def test_web_export_journal_excel_month_without_year_400(client, db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        _room_api(room_id, "/finance/export/journal") + "&month=10",
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400


# =====================================================================
# Section: รับเงินรวบยอด (Batch) — ปิดหนี้หลายบิลในครั้งเดียว
# (yield Discord notification รอบเดียว ไม่เด้งหลาย embed)
# =====================================================================


async def _batch_payload(payment_ids, account_id, amounts=None, user_name="Owner"):
    """สร้าง payload BatchPaymentConfirm สำหรับยิง /finance/payments/batch"""
    if amounts is None:
        amounts = [None] * len(payment_ids)
    return {
        "items": [
            {"payment_id": pid, "paid_amount": amt or 500.0}
            for pid, amt in zip(payment_ids, amounts)
        ],
        "paid_to_account_id": account_id,
        "user_name": user_name,
    }


async def test_batch_confirm_payments_roundtrip(client, db_pool):
    """รับเงินรวบยอด 2 บิลของนักเรียนคนเดียวกัน → 200, ทุกบิล paid, balance = ผลรวม"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    # ห้องจริงมีหมวดหมู่ '📥 เก็บเงินห้องปกติ' จาก seed (room_service) — เทสนี้ insert ตรง จึงต้อง seed เอง
    # เพื่อให้ dual-write สร้าง journal revenue ได้ครบฝั่ง
    await _insert_category(db_pool, room_id, "📥 เก็บเงินห้องปกติ", "income")
    col1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 500.0)
    col2 = await _insert_collection(db_pool, room_id, "ค่าเสื้อ", 500.0)
    pay1 = await _insert_student_payment(db_pool, col1, student_id, "pending", 0.0)
    pay2 = await _insert_student_payment(db_pool, col2, student_id, "pending", 0.0)

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload([pay1, pay2], account_id),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert "2 รายการ" in resp.json()["message"]

    # 🧠 Deep DB verify: ทั้ง 2 บิล paid + balance = ผลรวม + transaction ครบ
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT status, paid_amount FROM student_payments WHERE id = ANY($1) ORDER BY id", [pay1, pay2])
        assert all(r["status"] == "paid" for r in rows)
        assert all(float(r["paid_amount"]) == 500.0 for r in rows)
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
        assert float(bal) == 1000.0
        tx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND student_payment_id IS NOT NULL AND deleted_at IS NULL",
            room_id,
        )
        assert tx_count == 2
        # [DUAL-WRITE] journal ต้องมี 2 หัวบิล (ขา student_payment) ครบ
        j_count = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries JE
               WHERE JE.room_id = $1 AND JE.reference_type = 'student_payment' AND JE.status <> 'voided'""",
            room_id,
        )
        assert j_count == 2


async def test_batch_confirm_payments_overpay_rolls_back(client, db_pool):
    """บิลหนึ่ง overpay → 400 และทั้งชุด rollback (atomic): ไม่มีบิลไหนโดน commit"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    col1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 1000.0)
    col2 = await _insert_collection(db_pool, room_id, "ค่าเสื้อ", 500.0)
    pay1 = await _insert_student_payment(db_pool, col1, student_id, "pending", 0.0)
    pay2 = await _insert_student_payment(db_pool, col2, student_id, "pending", 0.0)

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload([pay1, pay2], account_id, amounts=[2000.0, 500.0]),  # บิลแรกจ่ายเกิน
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400
    assert "เกิน" in resp.json()["detail"]

    # 🧠 Deep DB verify: บิลที่ถูกต้อง (pay2) ก็ต้องไม่โดน commit เช่นกัน → atomicity
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT status, paid_amount FROM student_payments WHERE id = ANY($1) ORDER BY id", [pay1, pay2])
        assert all(r["status"] == "pending" for r in rows)
        assert all(float(r["paid_amount"]) == 0.0 for r in rows)
        bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
        assert float(bal) == 0.0
        tx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND student_payment_id IS NOT NULL",
            room_id,
        )
        assert tx_count == 0


async def test_batch_confirm_payments_different_students_rejected(client, db_pool):
    """บิลต่างคนกันใน batch เดียว → 400 (กันแจ้งเตือนรวมงง / จ่ายข้ามคน)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    stu1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    stu2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)
    col1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 500.0)
    col2 = await _insert_collection(db_pool, room_id, "ค่าเสื้อ", 500.0)
    pay1 = await _insert_student_payment(db_pool, col1, stu1, "pending", 0.0)
    pay2 = await _insert_student_payment(db_pool, col2, stu2, "pending", 0.0)

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload([pay1, pay2], account_id),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400
    assert "คนเดียวกัน" in resp.json()["detail"]


async def test_batch_confirm_payments_non_admin_forbidden(client, db_pool):
    """member ธรรมดา (ไม่ใช่ admin) → 403"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    member = await _insert_user(db_pool, first_name="Member", last_name="One")
    await _insert_student(db_pool, room_id, member, 5, status="active")
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    col = await _insert_collection(db_pool, room_id, "ค่าเทอม", 500.0)
    pay = await _insert_student_payment(db_pool, col, student_id, "pending", 0.0)

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload([pay], account_id),
        headers=_make_web_headers(member),
    )
    assert resp.status_code == 403


async def test_batch_confirm_payments_publishes_once(client, db_pool):
    """publish แจ้งเตือนครั้งเดียว (ไม่เด้งหลาย embed) พร้อม items ครบ + total ถูก"""
    from services.action_service import ActionService
    from unittest.mock import patch, AsyncMock

    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    col1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 300.0)
    col2 = await _insert_collection(db_pool, room_id, "ค่าเสื้อ", 200.0)
    pay1 = await _insert_student_payment(db_pool, col1, student_id, "pending", 0.0)
    pay2 = await _insert_student_payment(db_pool, col2, student_id, "pending", 0.0)

    with patch.object(ActionService, "notify_payments_confirmed", new_callable=AsyncMock) as mock_notify:
        resp = client.put(
            _room_api(room_id, "/finance/payments/batch"),
            json=await _batch_payload([pay1, pay2], account_id, amounts=[300.0, 200.0]),
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    mock_notify.assert_awaited_once()
    kwargs = mock_notify.await_args.kwargs
    assert kwargs["server_id"] == server_id
    assert len(kwargs["items"]) == 2
    assert kwargs["total_amount"] == 500.0
    assert all("title" in item and "amount" in item for item in kwargs["items"])


# =====================================================================
# Section: [F5/PR-2] เคลียร์หนี้แล้วออกใบเสร็จให้ทุกรายการในรอบเดียว
# (คำขอเดิมของผู้ใช้: "กดเคลียร์หนี้ แล้วอยากให้มันออกใบเสร็จมาพร้อมกันหมดเลย")
# =====================================================================


async def _seed_batch_scenario(db_pool, bill_amounts, *, server_id=None):
    """สร้างห้อง + กระเป๋า + นักเรียน 1 คน + บิลหลายใบ (ยอดต่างกันได้) + หมวดรายได้

    ⚠️ ต้อง seed หมวด '📥 เก็บเงินห้องปกติ' เอง — เทสต์นี้ INSERT ตรง (ไม่ผ่าน room_service)
       แต่เส้นทางรับเงินเขียน journal ผ่าน `_resolve_default_income_ledger` ซึ่งหา **ตามชื่อ**
       ⇒ ขาดแล้ว dual-write raise (ไม่ใช่ข้ามเงียบ ๆ — ตั้งใจให้เป็นแบบนั้น)
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    account_id = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    student_id = await _insert_student(
        db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1,
    )
    await _insert_category(db_pool, room_id, "📥 เก็บเงินห้องปกติ", "income")
    payment_ids = []
    for idx, amount in enumerate(bill_amounts, start=1):
        col = await _insert_collection(db_pool, room_id, f"ค่าใช้จ่าย {idx}", amount)
        payment_ids.append(
            await _insert_student_payment(db_pool, col, student_id, "pending", 0.0)
        )
    return owner, room_id, account_id, student_id, payment_ids


async def _current_year_be(conn) -> int:
    """ปี พ.ศ. ของ 'ตอนนี้' **จากนาฬิกาของ DB** — สูตรเดียวกับ `_assert_receipt_seq_budget`

    🔴 ห้ามใช้ `datetime.now()` ของ Python: เทสต์กับ service ต้องอ่านนาฬิกาเรือนเดียวกัน
       ไม่งั้นเทสต์จะพังเฉพาะช่วงข้ามปี (ซึ่งเป็นตอนที่ไม่มีใครอยู่ดู)
    """
    return await conn.fetchval(
        "SELECT EXTRACT(YEAR FROM (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Bangkok'))::int + 543"
    )


@pytest.mark.parametrize("bill_count", [1, 2, 100])
async def test_batch_confirm_payments_issues_one_receipt_per_bill(client, db_pool, bill_count):
    """🔑 เคลียร์หนี้ N บิล → ได้ใบเสร็จ N ใบ (เลขต่อเนื่อง) + ชุดอัตโนมัติเมื่อ ≥ 2 ใบ

    ยอดแต่ละบิล **ตั้งใจให้ไม่เท่ากัน** — ถ้าโค้ดเอา "ยอดที่รับรวม" ไปออกใบเสร็จทุกใบ
    (ซึ่งเป็นความผิดพลาดที่ดูสมเหตุสมผลที่สุด) ยอดบนใบจะเท่ากันหมดแล้วเทสต์นี้จับได้
    """
    amounts = [float(100 + 10 * i) for i in range(bill_count)]
    owner, room_id, account_id, student_id, payment_ids = await _seed_batch_scenario(
        db_pool, amounts,
    )
    payload = await _batch_payload(payment_ids, account_id, amounts=amounts)

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"), json=payload,
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # ── ระดับ HTTP ────────────────────────────────────────────────────────────
    assert body["issued_count"] == bill_count
    assert body["reused_count"] == 0
    assert len(body["receipts"]) == bill_count
    assert f"รับเงินรวบยอด {bill_count} รายการสำเร็จ" in body["message"]
    assert f"ออกใบเสร็จ {bill_count} ใบ" in body["message"]
    nos = [r["receipt_no"] for r in body["receipts"]]
    assert len(set(nos)) == bill_count, "เลขที่เอกสารต้องไม่ซ้ำกัน"
    assert all(r["doc_type"] == "receipt" for r in body["receipts"])
    # 🔴 `response_model` ต้องไม่ตัดฟิลด์ทิ้ง (บทเรียน docs/skills.md) — ตรวจว่ามีจริง
    assert all(r["receipt_no"] and r["amount"] > 0 for r in body["receipts"])

    async with db_pool.acquire() as conn:
        # ── 🧠 Deep DB verify: ใบเสร็จในตารางผูกกับงวดรับเงินของ "บิลนั้น ๆ" จริง ──
        rows = await conn.fetch(
            """SELECT R.receipt_no, R.student_payment_id, R.legacy_transaction_id,
                      R.amount, R.status, R.batch_id, FT.amount AS tx_amount
               FROM finance_receipts R
               JOIN finance_transactions FT ON FT.id = R.legacy_transaction_id
               WHERE R.room_id = $1 AND R.doc_type = 'receipt' AND R.deleted_at IS NULL
               ORDER BY R.seq""",
            room_id,
        )
        assert len(rows) == bill_count
        assert [r["student_payment_id"] for r in rows] == payment_ids, \
            "ใบเสร็จต้องเรียงตามบิลที่ส่งมา และผูกกับบิลนั้นจริง"
        # ยอดบนใบ = ยอดที่รับของ **บิลนั้น** ไม่ใช่ยอดรวม (บิลต่างยอดกัน ⇒ ตรวจได้)
        assert [float(r["amount"]) for r in rows] == amounts, \
            "ยอดบนใบเสร็จต้องเป็นยอดของบิลนั้น ไม่ใช่ยอดที่รับรวมทั้งชุด"
        assert [float(r["tx_amount"]) for r in rows] == amounts
        assert all(r["status"] == "active" for r in rows)
        # เลขต่อเนื่องไม่มีช่องว่าง (เลขถูกจองในธุรกรรมเดียวและไม่มีใครแทรก)
        seqs = [int(n.split("-")[-1]) for n in nos]
        assert seqs == list(range(seqs[0], seqs[0] + bill_count))

        # ── 📚 ชุดอัตโนมัติ: ≥ 2 ใบเท่านั้น ──────────────────────────────────
        batch_ids = {r["batch_id"] for r in rows}
        if bill_count >= 2:
            assert len(batch_ids) == 1 and None not in batch_ids, \
                "ออกหลายใบในรอบเดียวต้องได้ชุดเดียว และทุกใบต้องอยู่ในชุด"
            batch_id = batch_ids.pop()
            assert body["batch_id"] == batch_id
            # 🔴 ชุดต้องเป็นของห้องนี้ (คอลัมน์ room_id ตรง) — composite FK คุมไว้อีกชั้น
            assert await conn.fetchval(
                "SELECT room_id FROM finance_receipt_batches WHERE id = $1", batch_id,
            ) == room_id
            # ใบทุกใบในคำตอบต้องบอกชุดเดียวกัน — ไม่งั้นจอจะโชว์ "ไม่ได้จัดกลุ่ม"
            # ทั้งที่เพิ่งจัดให้ แล้วผู้ใช้ต้องยิง GET ซ้ำเพื่อดูความจริง
            assert {r["batch_id"] for r in body["receipts"]} == {batch_id}
        else:
            assert batch_ids == {None}, "ใบเดียวไม่ต้องมีชุด"
            assert body["batch_id"] is None
            assert await conn.fetchval(
                "SELECT COUNT(*) FROM finance_receipt_batches WHERE room_id = $1", room_id,
            ) == 0, "ใบเดียวต้องไม่สร้างแถวชุดทิ้งไว้"

        # ── เงินยังเข้าเหมือนเดิม (diff นี้ต้องไม่แตะเส้นทางเงิน) ─────────────
        assert float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id,
        )) == sum(amounts)
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions"
            " WHERE room_id = $1 AND student_payment_id IS NOT NULL AND deleted_at IS NULL",
            room_id,
        ) == bill_count


async def test_batch_confirm_payments_opt_out_issue_receipts(client, db_pool):
    """ติ๊กปิด "ออกใบเสร็จ" → ไม่มีใบเสร็จเลย และ **ไม่แตะ `receipt_sequences`**

    ⚠️ ข้อหลังสำคัญ: ถ้าโค้ดเผลอจองเลขก่อนเช็คติ๊ก เลขจะหายไป 1-2 หมายเลขทุกครั้ง
       ที่มีคนปิดติ๊ก ซึ่งตรวจไม่เจอจากหน้าจอเลย (แค่เลขกระโดด)
    """
    owner, room_id, account_id, _, payment_ids = await _seed_batch_scenario(
        db_pool, [500.0, 500.0],
    )
    payload = await _batch_payload(payment_ids, account_id)
    payload["issue_receipts"] = False

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"), json=payload,
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["receipts"] == []
    assert body["issued_count"] == 0 and body["batch_id"] is None
    # 📌 ข้อความต้องเหมือนเดิมเป๊ะเมื่อไม่มีใบเสร็จ (ไม่มี " · ออกใบเสร็จ 0 ใบ" ต่อท้าย)
    assert body["message"] == "รับเงินรวบยอด 2 รายการสำเร็จ"

    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id,
        ) == 0
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1", room_id,
        ) == 0, "ปิดติ๊กแล้วต้องไม่มีการจองเลขเลย"
        # เงินยังต้องเข้า 100% — ติ๊กนี้ปิดแค่ "เอกสาร" ไม่ใช่ "การรับเงิน"
        assert float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id,
        )) == 1000.0


async def _force_seq_last(conn, room_id: int, last_seq: int) -> None:
    """ดัน `receipt_sequences.last_seq` ของปีนี้ให้เป็นค่าที่กำหนด (จำลองเลขใกล้เต็ม)"""
    await conn.execute(
        """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
           VALUES ($1, $2, 'receipt', $3)
           ON CONFLICT (room_id, year_be, doc_type)
           DO UPDATE SET last_seq = EXCLUDED.last_seq""",
        room_id, await _current_year_be(conn), last_seq,
    )


async def test_batch_confirm_payments_seq_overflow_does_not_take_money(client, db_pool):
    """🔑 เลขเอกสารไม่พอ → 400 และ **เงินไม่ถูกแตะเลย** (พิสูจน์ว่า "ใน transaction เดียวกัน" จริง)

    นี่คือเทสต์ที่มีค่าที่สุดของงานนี้: ถ้ามีใครย้ายการออกใบเสร็จไป **นอก**
    `conn.transaction()` (หรือ commit เงินก่อน) เทสต์นี้จะล้มทันที เพราะเงินจะถูกบันทึกไปแล้ว
    """
    owner, room_id, account_id, _, payment_ids = await _seed_batch_scenario(
        db_pool, [500.0, 500.0],
    )
    async with db_pool.acquire() as conn:
        await _force_seq_last(conn, room_id, 9999)  # เหลือ 0 เลข

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload(payment_ids, account_id),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400, resp.text
    assert "เลขเอกสาร" in resp.json()["detail"]

    async with db_pool.acquire() as conn:
        # ── เงิน: ไม่ขยับแม้แต่บาทเดียว ──────────────────────────────────────
        rows = await conn.fetch(
            "SELECT status, paid_amount FROM student_payments WHERE id = ANY($1)", payment_ids,
        )
        assert all(r["status"] == "pending" for r in rows)
        assert all(float(r["paid_amount"]) == 0.0 for r in rows)
        assert float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id,
        )) == 0.0
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id,
        ) == 0
        # ── เอกสาร: ไม่มีใบถูกออก และเลขไม่ถูกเผา ───────────────────────────
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id,
        ) == 0
        assert await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = 'receipt'",
            room_id,
        ) == 9999, "ล้มแล้วต้องไม่กินเลข (rollback ต้องคืนเลขที่จองไป)"


async def test_batch_confirm_payments_receipt_failure_takes_no_money(
    client, db_pool, monkeypatch,
):
    """🔑 ออกใบเสร็จล้ม **กลางทาง** (ใบที่ 2) → เงินต้องไม่ถูกบันทึกเลย

    🎯 ทำไมต้องบังคับให้ล้ม (fault injection) แทนที่จะใช้เคส "เลขเอกสารไม่พอ":
       เคส "เลขไม่พอ" ถูกด่านล่วงหน้า `_assert_receipt_seq_budget` ดักไว้ **ก่อน** เงินถูกแตะ
       ⇒ เทสต์ overflow (`..._seq_overflow_does_not_take_money`) จึงตอบได้แค่
       "ด่านล่วงหน้าทำงาน" ไม่ได้ตอบคำถามที่ต่างออกไปว่า
       **"ถ้าการออกใบเสร็จล้ม *หลัง* เงินถูกเขียนไปแล้ว ระบบยังถอยกลับทั้งก้อนไหม"**
       ⇒ นี่คือเหตุผลที่ mutant M2 (ย้ายการออกใบเสร็จไป **หลัง commit**) รอดเทสต์ overflow
       มาตลอด — มันถูกด่านล่วงหน้าบังอยู่

    ⇒ เทสต์นี้คือเทสต์เดียวที่แยก "ออกใบเสร็จในธุรกรรม" ออกจาก "ออกหลัง commit" ได้จริง
       (พิสูจน์แล้วกับ mutant M2 — ก่อนมีเทสต์นี้ M2 รอดทั้งไฟล์: `53 passed`)
    """
    real_issue_one = ReceiptsMixin._issue_one
    calls = {"n": 0}

    async def flaky_issue_one(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # ⚠️ ต้องเป็น ValueError ⇒ router แปลเป็น 400
            #    (ถ้าเป็น exception อื่นจะกลายเป็น 500 และ TestClient โยนกลับในเทสต์)
            raise ValueError("จำลอง: ออกใบเสร็จใบที่ 2 ไม่สำเร็จ")
        return await real_issue_one(*args, **kwargs)

    monkeypatch.setattr(ReceiptsMixin, "_issue_one", flaky_issue_one)

    owner, room_id, account_id, _, payment_ids = await _seed_batch_scenario(
        db_pool, [500.0, 700.0],
    )
    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload(payment_ids, account_id, amounts=[500.0, 700.0]),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400, resp.text
    # ถ้าไม่ได้ล้มที่ใบที่ 2 จริง เทสต์นี้ไม่ได้ทดสอบอะไรเลย ⇒ ต้องยืนยัน
    assert calls["n"] == 2, f"คาดว่าล้มที่ใบที่ 2 แต่ถูกเรียก {calls['n']} ครั้ง"

    async with db_pool.acquire() as conn:
        # ── เงินต้องไม่ขยับ แม้ใบแรกจะออกสำเร็จไปแล้วก่อนล้ม ────────────────
        rows = await conn.fetch(
            "SELECT status, paid_amount FROM student_payments WHERE id = ANY($1)", payment_ids,
        )
        assert all(r["status"] == "pending" for r in rows)
        assert all(float(r["paid_amount"]) == 0.0 for r in rows)
        assert float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id,
        )) == 0.0
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id,
        ) == 0
        # ── ใบที่ออกไปแล้วก่อนล้ม ต้องถูก rollback ด้วย (ไม่เหลือใบครึ่งทาง) ──
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id,
        ) == 0, "ใบที่ 1 ออกสำเร็จแล้วแต่ต้องถูก rollback พร้อมทั้งธุรกรรม"
        assert await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = 'receipt'",
            room_id,
        ) in (None, 0), "ล้มแล้วต้องไม่กินเลข (rollback ต้องคืนเลขที่จองไป)"


async def test_batch_confirm_payments_seq_budget_precheck_names_the_shortfall(client, db_pool):
    """ด่านล่วงหน้าต้องบอก **ตัวเลขที่ขาด** และยืนยันว่า "ยังไม่มีรายการใดถูกบันทึก"

    🎯 เทสต์นี้คือด่านที่จับ mutant "ถอด `_assert_receipt_seq_budget` ออก":
       ถ้าไม่มีด่านนี้ ระบบยังได้ 400 เหมือนกัน (ด่านจริงใน `_issue_one` ยังอยู่)
       และ DB สุดท้ายก็เหมือนกันเป๊ะเพราะ rollback ทั้งคู่ ⇒ **สิ่งเดียวที่ต่างคือข้อความ**
       ที่ครูเห็นตอนถือเงินสดอยู่หน้าห้อง ⇒ ข้อความจึงเป็นสัญญาที่ต้องล็อกไว้ ไม่ใช่ของประดับ

    💡 เลขที่เหลือ 1 < ต้องใช้ 3 ⇒ ถ้าด่านนี้ถูกถอด ข้อความจะกลายเป็นข้อความกว้าง ๆ
       ของ `_issue_one` แทน (ซึ่งไม่บอกจำนวนที่ขาด และไม่บอกว่าเงินยังไม่ถูกแตะ)
    """
    owner, room_id, account_id, _, payment_ids = await _seed_batch_scenario(
        db_pool, [100.0, 200.0, 300.0],
    )
    async with db_pool.acquire() as conn:
        await _force_seq_last(conn, room_id, 9998)  # เหลือ 9999-9998 = 1 เลข แต่ต้องใช้ 3

    resp = client.put(
        _room_api(room_id, "/finance/payments/batch"),
        json=await _batch_payload(payment_ids, account_id, amounts=[100.0, 200.0, 300.0]),
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "(ต้องใช้ 3 เลข แต่เหลือ 1 เลข)" in detail, detail
    assert "ยังไม่มีรายการใดถูกบันทึก" in detail, detail

    async with db_pool.acquire() as conn:
        # ข้อความสัญญาว่า "ยังไม่มีรายการใดถูกบันทึก" — ต้องเป็นความจริง ไม่ใช่คำปลอบใจ
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id,
        ) == 0
        assert float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id,
        )) == 0.0
