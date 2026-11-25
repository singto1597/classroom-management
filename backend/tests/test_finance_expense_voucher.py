"""💸 [FIN-V2 / P4.1] ใบสำคัญจ่ายหลายบรรทัด (expense voucher)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 ใบ = N transactions + N journals + 1 PV + 3 signatures** — ไม่ใช่ journal
   รวมก้อนเดียว (งบประมาณอ่านยอดใช้ต่อหมวดจาก txn/journal ⇒ รวมแล้วยอดหมวดเพี้ยน)
2. **ยอดกระเป๋าลดแยกตามใบ** — สองบรรทัดคนละกระเป๋าต้องไม่ปนกัน
3. **PV 1 ใบต่อ voucher** — `legacy_transaction_id` = transaction บรรทัดแรก,
   `layout_version=2`, `idempotency_key='pv:{id}'`
4. **idempotency** — คีย์เดิม + payload เดิม ⇒ ใบเดิม (`reused=true`);
   payload ต่าง ⇒ **409** (ไม่ใช่ 400)
5. **ตรวจครบก่อนเขียน** — ยอดรวมไม่ตรง / เงินไม่พอ / หมวดผิด / กระเป๋า custody
   กับเงินห้อง ⇒ 400 และ **ไม่มีร่องรอย**
6. **atomic ทั้งใบ** — ล้มกลางทางที่บรรทัด 2 ⇒ rollback ทั้งใบ
7. **RBAC + ขอบเขตห้อง** — MANAGE_FINANCE เท่านั้น; ข้ามห้อง = 403/404
8. **งบประมาณรายงานยอดใช้ถูก** — 350 ไม่ใช่ 700 (dual-write ไม่นับซ้ำ)

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import importlib.util
import pathlib
import random
import string
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from services.finance.constants import THAI_TZ
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


# ═══════════════════════════════════════════════════════════════════ helpers
def _vouchers_url(room_id: int) -> str:
    # web ต้องส่ง `target_type=room` เสมอ (default ของ dependency คือ server)
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers?target_type=room"


def _voucher_url(room_id: int, voucher_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers/{voucher_id}?target_type=room"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    return f"{float(value):.2f}"


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


async def _insert_category(pool, room_id: int, name: str, cat_type: str = "expense") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, cat_type,
        )


async def _insert_account(
    pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0,
    is_custody: bool = False,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance, is_custody)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            room_id, name, balance, is_custody,
        )


async def _insert_person(pool, room_id: int, name: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people (room_id, person_type, display_name, roles, is_active)
               VALUES ($1, 'external', $2, ARRAY['pay']::TEXT[], TRUE) RETURNING id""",
            room_id, name,
        )


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


async def _count(pool, table: str, room_id: int) -> int:
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE room_id = $1", room_id,
        ))


def _line(
    amount: float, *, category_id: int, wallet_account_id: int,
    description: str = "รายการทดสอบ", budget_id=None,
    receipt_status: str = "none", funding_source: str = "room_fund",
    paper_bill_count: int = 0,
) -> dict:
    body = {
        "description": description,
        "amount": _money(amount),
        "category_id": category_id,
        "wallet_account_id": wallet_account_id,
        "receipt_status": receipt_status,
        "paper_bill_count": paper_bill_count,
        "funding_source": funding_source,
    }
    if budget_id is not None:
        body["budget_id"] = budget_id
    return body


def _payload(
    *, key: str | None = None, default_wallet_account_id: int,
    lines: list, payee_name: str = "ร้านวัสดุทดสอบ",
    payee_person_id=None, total_amount=None, approved_by_name: str = "ครูอนุมัติ",
    approved_by_person_id=None, voucher_date=None, note: str = "ใบสำคัญจ่ายทดสอบ",
) -> dict:
    body = {
        "idempotency_key": key or _new_key(),
        "default_wallet_account_id": default_wallet_account_id,
        "payee_name": payee_name,
        "note": note,
        # 🖊️ ไม่ส่ง user_name ⇒ service อ่านชื่อผู้จัดทำจากโปรไฟล์ (ผู้ใช้ admin fixture)
        "lines": lines,
    }
    if payee_person_id is not None:
        body["payee_person_id"] = payee_person_id
    if total_amount is not None:
        body["total_amount"] = _money(total_amount)
    if approved_by_name is not None:
        body["approved_by_name"] = approved_by_name
    if approved_by_person_id is not None:
        body["approved_by_person_id"] = approved_by_person_id
    if voucher_date is not None:
        body["voucher_date"] = voucher_date
    return body


async def _seed_two_wallets(client, db_pool, headers):
    """หมวดรายจ่าย 2 ใบ + กระเป๋า 2 ใบ (คนละ 500) — คืน (cat_a, cat_b, wallet_a, wallet_b)"""
    room = headers.room_id
    cat_a = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    cat_b = await _insert_category(db_pool, room, "ค่าขนส่ง")
    wallet_a = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)
    wallet_b = await _insert_account(db_pool, room, "ธนาคารห้อง", 500.0)
    return cat_a, cat_b, wallet_a, wallet_b


def _two_line_payload(cat_a, cat_b, wallet_a, wallet_b, key=None) -> dict:
    return _payload(
        key=key,
        default_wallet_account_id=wallet_a,
        lines=[
            _line(250.0, category_id=cat_a, wallet_account_id=wallet_a,
                  description="กระดาษ A4"),
            _line(100.0, category_id=cat_b, wallet_account_id=wallet_b,
                  description="ค่าขนส่ง"),
        ],
    )


def _money_lock_tests():
    """โหลด `test_finance_money_lock.py` เป็นโมดูล (tests/ ไม่ใช่ package)"""
    path = pathlib.Path(__file__).with_name("test_finance_money_lock.py")
    spec = importlib.util.spec_from_file_location("_money_lock_tests_for_p41", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ═══════════════════════ 1. 2 บรรทัด → 2 txn + 2 journal (Dr=Cr=350)
async def test_create_voucher_two_lines_creates_two_transactions_and_journals(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)

    res = client.post(
        _vouchers_url(room), json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    voucher_id = body["id"]
    assert _money(body["total_amount"]) == "350.00"
    assert body["line_count"] == 2
    assert body["reused"] is False

    async with db_pool.acquire() as conn:
        txns = await conn.fetch(
            """SELECT id, amount, category_id, account_id
               FROM finance_transactions
               WHERE room_id = $1 AND expense_voucher_id = $2 ORDER BY id""",
            room, voucher_id,
        )
        assert len(txns) == 2
        assert sorted(_money(t["amount"]) for t in txns) == ["100.00", "250.00"]

        lines = await conn.fetch(
            """SELECT line_no, finance_transaction_id, amount
               FROM finance_expense_lines WHERE voucher_id = $1 ORDER BY line_no""",
            voucher_id,
        )
        assert [row["line_no"] for row in lines] == [1, 2]
        # ทุกบรรทัดต้องมี txn ของตัวเอง
        assert all(row["finance_transaction_id"] is not None for row in lines)
        assert {row["finance_transaction_id"] for row in lines} == {t["id"] for t in txns}

        journals = await conn.fetch(
            """SELECT id FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'expense_voucher'
               ORDER BY id""",
            room,
        )
        assert len(journals) == 2
        for j in journals:
            totals = await conn.fetchrow(
                """SELECT SUM(debit) AS dr, SUM(credit) AS cr, COUNT(*) AS n
                   FROM journal_lines WHERE journal_entry_id = $1""",
                j["id"],
            )
            assert int(totals["n"]) == 2
            assert _money(totals["dr"]) == _money(totals["cr"])

        grand = await conn.fetchrow(
            """SELECT SUM(debit) AS dr, SUM(credit) AS cr
               FROM journal_lines WHERE journal_entry_id = ANY($1::uuid[])""",
            [j["id"] for j in journals],
        )
        assert _money(grand["dr"]) == "350.00"
        assert _money(grand["cr"]) == "350.00"


# ═══════════════════════ 2. ยอดกระเป๋าแยกตามบรรทัด
async def test_create_voucher_updates_each_wallet_balance(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)

    res = client.post(
        _vouchers_url(room), json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    assert _money(await _balance(db_pool, wallet_a)) == "250.00"
    assert _money(await _balance(db_pool, wallet_b)) == "400.00"


# ═══════════════════════ 3. PV 1 ใบต่อ voucher
async def test_create_voucher_issues_exactly_one_pv(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    res = client.post(
        _vouchers_url(room), json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, receipt_no, legacy_transaction_id, layout_version,
                      idempotency_key, amount
               FROM finance_receipts
               WHERE room_id = $1 AND doc_type = 'payment_voucher'""",
            room,
        )
        assert len(rows) == 1
        pv = rows[0]
        first_txn = await conn.fetchval(
            """SELECT MIN(id) FROM finance_transactions
               WHERE room_id = $1 AND expense_voucher_id = $2""",
            room, body["id"],
        )
        assert pv["id"] == body["pv_receipt_id"]
        assert pv["receipt_no"] == body["pv_receipt_no"]
        assert pv["legacy_transaction_id"] == first_txn
        assert pv["layout_version"] == 2
        assert pv["idempotency_key"] == f"pv:{body['id']}"
        assert _money(pv["amount"]) == "350.00"

        stored = await conn.fetchval(
            "SELECT pv_receipt_id FROM finance_expense_vouchers WHERE id = $1", body["id"],
        )
        assert stored == pv["id"]


# ═══════════════════════ 4. 3 ลายเซ็น
async def test_create_voucher_writes_three_signatures(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    payee = await _insert_person(db_pool, room, "ร้านวัสดุทดสอบ")

    payload = _two_line_payload(cat_a, cat_b, wallet_a, wallet_b)
    payload["payee_person_id"] = payee
    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        sigs = await conn.fetch(
            """SELECT role, sort_order, signer_name, person_id, signed_at
               FROM finance_document_signatures
               WHERE doc_type = 'payment_voucher' AND doc_id = $1
               ORDER BY sort_order""",
            res.json()["pv_receipt_id"],
        )
    assert [s["role"] for s in sigs] == ["prepared", "approved", "receiver"]
    assert [s["sort_order"] for s in sigs] == [0, 1, 2]
    assert all(s["signed_at"] is None for s in sigs)
    # receiver = ผู้รับเงิน (payee) ไม่ใช่ current user
    assert sigs[2]["signer_name"] == "ร้านวัสดุทดสอบ"
    assert sigs[2]["person_id"] == payee
    assert sigs[1]["signer_name"] == "ครูอนุมัติ"


# ═══════════════════════ 5. replay คีย์เดิม → ใบเดิม
async def test_create_voucher_replay_returns_same_documents(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    payload = _two_line_payload(cat_a, cat_b, wallet_a, wallet_b, key=_new_key())

    first = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert first.status_code == 200, first.text

    second = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["pv_receipt_no"] == first.json()["pv_receipt_no"]

    assert await _count(db_pool, "finance_expense_vouchers", room) == 1
    assert await _count(db_pool, "finance_transactions", room) == 2
    assert await _count(db_pool, "journal_entries", room) == 2
    # ยอดกระเป๋าถูกหักครั้งเดียวเท่านั้น
    assert _money(await _balance(db_pool, wallet_a)) == "250.00"
    assert _money(await _balance(db_pool, wallet_b)) == "400.00"


# ═══════════════════════ 6. คีย์เดิม payload ต่าง → 409
async def test_create_voucher_replay_with_different_payload_is_409(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    key = _new_key()

    first = client.post(
        _vouchers_url(room),
        json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b, key=key),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    changed = _payload(
        key=key, default_wallet_account_id=wallet_a,
        lines=[_line(300.0, category_id=cat_a, wallet_account_id=wallet_a)],
    )
    second = client.post(_vouchers_url(room), json=changed, headers=admin_headers)
    assert second.status_code == 409, second.text

    assert await _count(db_pool, "finance_expense_vouchers", room) == 1


# ═══════════════════════ 7. ยอดรวมไม่ตรง → 400
async def test_create_voucher_rejects_total_mismatch(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    payload = _two_line_payload(cat_a, cat_b, wallet_a, wallet_b)
    payload["total_amount"] = "999.00"

    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0


# ═══════════════════════ 8. เงินไม่พอ → 400 ก่อนเขียน
async def test_create_voucher_rejects_insufficient_balance_before_writing(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 100.0)

    payload = _payload(
        default_wallet_account_id=wallet,
        lines=[_line(150.0, category_id=cat, wallet_account_id=wallet)],
    )
    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text

    assert await _count(db_pool, "finance_expense_vouchers", room) == 0
    assert await _count(db_pool, "finance_transactions", room) == 0
    assert await _count(db_pool, "journal_entries", room) == 0
    assert _money(await _balance(db_pool, wallet)) == "100.00"


# ═══════════════════════ 9. หมวดรายรับ → 400
async def test_create_voucher_rejects_income_category(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    income_cat = await _insert_category(db_pool, room, "รายรับอื่น", cat_type="income")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)

    payload = _payload(
        default_wallet_account_id=wallet,
        lines=[_line(100.0, category_id=income_cat, wallet_account_id=wallet)],
    )
    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0


# ═══════════════════════ 10. กระเป๋า custody + เงินห้อง → 400
async def test_create_voucher_rejects_custody_wallet_with_room_fund(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    custody = await _insert_account(pool=db_pool, room_id=room, name="เงินถือนายก", balance=500.0, is_custody=True)

    payload = _payload(
        default_wallet_account_id=custody,
        lines=[_line(100.0, category_id=cat, wallet_account_id=custody,
                     funding_source="room_fund")],
    )
    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0


# ═══════════════════════ 11. ล้มกลางทาง → rollback ทั้งใบ
async def test_create_voucher_rolls_back_all_lines_on_midway_failure(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)

    original = FinanceService._insert_journal_entry
    calls = {"n": 0}

    async def _fail_on_second(cls_, conn, room_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("ล้มกลางทาง (ทดสอบ)")
        return await original(conn, room_id, **kwargs)

    with patch.object(FinanceService, "_insert_journal_entry", new=classmethod(_fail_on_second)):
        res = client.post(
            _vouchers_url(room), json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b),
            headers=admin_headers,
        )

    assert res.status_code == 400, res.text
    assert calls["n"] == 2
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0
    assert await _count(db_pool, "finance_transactions", room) == 0
    assert await _count(db_pool, "journal_entries", room) == 0
    assert _money(await _balance(db_pool, wallet_a)) == "500.00"
    assert _money(await _balance(db_pool, wallet_b)) == "500.00"


# ═══════════════════════ 12. ต้องมี MANAGE_FINANCE → 403
async def test_create_voucher_requires_manage_finance(
    client, db_pool, member_headers,
):
    room = member_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)

    payload = _payload(
        default_wallet_account_id=wallet,
        lines=[_line(100.0, category_id=cat, wallet_account_id=wallet)],
    )
    res = client.post(_vouchers_url(room), json=payload, headers=member_headers)
    assert res.status_code == 403, res.text
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0


# ═══════════════════════ 13. ขอบเขตห้อง
async def test_create_voucher_is_room_scoped(
    client, db_pool, admin_headers, finance_manager_headers,
):
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    other_cat = await _insert_category(db_pool, other_room, "วัสดุสำนักงาน")
    other_wallet = await _insert_account(db_pool, other_room, "เงินสดห้อง", 500.0)

    payload = _payload(
        default_wallet_account_id=other_wallet,
        lines=[_line(100.0, category_id=other_cat, wallet_account_id=other_wallet)],
    )

    # เหรัญญิกของห้อง A ยิงเข้าห้อง B ⇒ ไม่มีสิทธิ์
    forbidden = client.post(
        _vouchers_url(other_room), json=payload, headers=finance_manager_headers,
    )
    assert forbidden.status_code == 403, forbidden.text

    # admin ของห้อง A อ้างกระเป๋าของห้อง B ⇒ ไม่พบในห้อง ⇒ 404
    not_found = client.post(
        _vouchers_url(admin_headers.room_id), json=payload, headers=admin_headers,
    )
    assert not_found.status_code == 404, not_found.text

    assert await _count(db_pool, "finance_expense_vouchers", other_room) == 0
    assert await _count(db_pool, "finance_expense_vouchers", admin_headers.room_id) == 0


# ═══════════════════════ 14. เพดาน 50 บรรทัด
async def test_create_voucher_caps_lines_at_50(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 10000.0)

    payload = _payload(
        default_wallet_account_id=wallet,
        lines=[
            _line(1.0, category_id=cat, wallet_account_id=wallet)
            for _ in range(51)
        ],
    )
    res = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_expense_vouchers", room) == 0


# ═══════════════════════ 15. ขึ้นทะเบียนใน _MONEY_PATHS
async def test_money_path_list_includes_create_expense_voucher():
    money_lock = _money_lock_tests()
    assert ("expense_vouchers", "ExpenseVouchersMixin", "create_expense_voucher") in \
        money_lock._MONEY_PATHS


# ═══════════════════════ 16. list/detail shape
async def test_voucher_list_and_detail_shapes(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet_a, wallet_b = await _seed_two_wallets(client, db_pool, admin_headers)
    created = client.post(
        _vouchers_url(room), json=_two_line_payload(cat_a, cat_b, wallet_a, wallet_b),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    voucher_id = created.json()["id"]

    listing = client.get(_vouchers_url(room), headers=admin_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body["items"]) == 1
    assert _money(body["total"]) == "350.00"
    item = body["items"][0]
    assert item["id"] == voucher_id
    assert item["line_count"] == 2
    assert _money(item["total_amount"]) == "350.00"
    assert item["pv_receipt_no"] == created.json()["pv_receipt_no"]

    detail = client.get(_voucher_url(room, voucher_id), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["payee_name"] == "ร้านวัสดุทดสอบ"
    assert len(d["lines"]) == 2
    assert [row["line_no"] for row in d["lines"]] == [1, 2]
    assert d["lines"][0]["category_name"] == "วัสดุสำนักงาน"
    assert d["lines"][1]["wallet_name"] == "ธนาคารห้อง"
    assert len(d["signatures"]) == 3
    # 🧾 P4.2 — บรรทัด default `receipt_status='none'` ⇒ มี CERT พ่วง PV เสมอ
    assert d["cert_receipt_id"] is not None
    assert d["cert_receipt_no"].startswith("CERT-")
    assert d["cert_line_nos"] == [1, 2]
    assert _money(d["cert_amount"]) == "350.00"


# ═══════════════════════ 17. งบประมาณนับยอดใช้จากบรรทัด (ไม่นับซ้ำ)
async def test_budget_usage_counts_voucher_lines(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน")
    wallet_a = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)
    wallet_b = await _insert_account(db_pool, room, "ธนาคารห้อง", 500.0)

    today = datetime.now(THAI_TZ).date()
    budget = client.post(
        f"{API_PREFIX}/{room}/finance/budgets?target_type=room",
        json={
            "category_id": cat,
            "amount": 1000,
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
            "note": "งบทดสอบ P4.1",
            "user_name": "Tester",
        },
        headers=admin_headers,
    )
    assert budget.status_code == 200, budget.text
    async with db_pool.acquire() as conn:
        budget_id = await conn.fetchval(
            "SELECT id FROM finance_budgets WHERE room_id = $1 AND category_id = $2",
            room, cat,
        )

    payload = _payload(
        default_wallet_account_id=wallet_a,
        lines=[
            _line(250.0, category_id=cat, wallet_account_id=wallet_a, budget_id=budget_id),
            _line(100.0, category_id=cat, wallet_account_id=wallet_b, budget_id=budget_id),
        ],
    )
    created = client.post(_vouchers_url(room), json=payload, headers=admin_headers)
    assert created.status_code == 200, created.text

    overview = client.get(
        f"{API_PREFIX}/{room}/finance/budgets/overview?target_type=room",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
        headers=admin_headers,
    )
    assert overview.status_code == 200, overview.text
    item = next(i for i in overview.json()["items"] if i["budget_id"] == budget_id)
    # 350 = ผลรวมสองบรรทัด **ครั้งเดียว** — ถ้านับ txn+journal ซ้ำจะเป็น 700
    assert _money(item["used"]) == "350.00"
