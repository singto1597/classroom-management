"""👜 [FIN-V2 / P3.1] เงินสดรอส่งมอบ (custody) — กระเป๋าผู้ถือ + ส่งมอบ + เคลื่อนไหว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 กระเป๋าต่อคนต่อห้อง** — เรียกซ้ำได้ใบเดิม ไม่สร้างซ้ำ และ **ห้ามตั้ง is_primary**
2. **handover = asset→asset** — balance ขยับสองฝั่ง, journal Dr ปลายทาง / Cr ต้นทาง,
   **ไม่มี** `finance_transactions` ใหม่ (ไม่ใช่รายรับ/รายจ่าย)
3. **negative-balance guard ก่อน UPDATE** — ยอดไม่พอต้องไม่เหลือร่องรอย
4. **idempotency ผ่าน journal metadata** — คีย์เดิมได้ผลเดิม, payload ต่างได้ 409
5. **void คืนยอดสองฝั่ง + void journal เดิม + journal กลับรายการ**
6. **void guard** — เงินปลายทางถูกใช้ไปแล้วต้อง 409 ไม่ใช่ 400
7. **room scope** — กระเป๋า/คนของห้องอื่นต้อง 404 ไม่รั่วข้ามห้อง

⚠️ ทุกอย่างยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import random
import string
import uuid

import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
PERSON_ROLES_RECEIVE = ["receive"]


# ═══════════════════════════════════════════════════════════════════ helpers
def _custody_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/custody"


def _accounts_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/custody/accounts"


def _handover_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/custody/handover"


def _void_url(room_id: int, handover_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/custody/handovers/{handover_id}/void"


def _movements_url(room_id: int, person_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/custody/{person_id}/movements"


def _new_key() -> str:
    return uuid.uuid4().hex


async def _insert_person(pool, room_id: int, name: str, roles=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people
                   (room_id, person_type, display_name, roles, is_active)
               VALUES ($1, 'teacher', $2, $3::TEXT[], TRUE)
               RETURNING id""",
            room_id, name, roles or PERSON_ROLES_RECEIVE,
        )


async def _insert_account(pool, room_id: int, name: str, balance: float = 0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, balance,
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


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


async def _ledger_id(pool, account_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_account_id = $1",
            account_id,
        )


async def _create_custody(client, room_id: int, headers, person_id: int) -> dict:
    res = client.post(
        _accounts_url(room_id),
        json={"owner_person_id": person_id, "account_kind": "cash"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _handover_payload(from_id: int, to_id: int, amount: float, key: str | None = None) -> dict:
    return {
        "idempotency_key": key or _new_key(),
        "from_account_id": from_id,
        "to_account_id": to_id,
        "amount": amount,
        "note": "ส่งมอบเงินทดสอบ",
    }


# ═══════════════════════════════════════════════ 1. กระเป๋า custody 1 ใบต่อคน
async def test_create_custody_account_is_unique_per_person(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")

    first = await _create_custody(client, room_id, admin_headers, person_id)
    second = await _create_custody(client, room_id, admin_headers, person_id)

    assert first["account_id"] == second["account_id"]
    assert first["account_name"] == "ครูสมหญิง (เงินสดรอส่งมอบ)"
    assert first["is_custody"] is True

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_accounts
               WHERE room_id = $1 AND owner_person_id = $2
                 AND is_custody AND deleted_at IS NULL""",
            room_id, person_id,
        )
        is_primary = await conn.fetchval(
            "SELECT is_primary FROM finance_accounts WHERE id = $1",
            first["account_id"],
        )
    assert count == 1
    assert is_primary is False


async def test_create_custody_account_requires_receive_role(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูจ่ายเงิน", roles=["pay"])

    res = client.post(
        _accounts_url(room_id),
        json={"owner_person_id": person_id},
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert "บทบาทรับเงิน" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_accounts
               WHERE room_id = $1 AND owner_person_id = $2 AND is_custody""",
            room_id, person_id,
        )
    assert count == 0


async def test_custody_write_requires_manage_finance(client, db_pool, member_headers):
    room_id = member_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")

    res = client.post(
        _accounts_url(room_id),
        json={"owner_person_id": person_id},
        headers=member_headers,
    )
    assert res.status_code == 403, res.text


# ═══════════════════════════════════════════════════ 2. ส่งมอบ main → custody
async def test_handover_moves_balance_and_writes_balanced_journal(
    client, db_pool, finance_manager_headers
):
    room_id = finance_manager_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=5000)
    custody_id = (await _create_custody(
        client, room_id, finance_manager_headers, person_id
    ))["account_id"]

    res = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 1500),
        headers=finance_manager_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "active"
    assert body["amount"] == 1500.0

    assert await _balance(db_pool, main_id) == 3500.0
    assert await _balance(db_pool, custody_id) == 1500.0

    async with db_pool.acquire() as conn:
        handover = await conn.fetchrow(
            "SELECT status, amount FROM finance_custody_handovers WHERE id = $1",
            body["id"],
        )
        assert handover["status"] == "active"
        assert float(handover["amount"]) == 1500.0

        lines = await conn.fetch(
            """SELECT jl.ledger_id, jl.debit, jl.credit
               FROM journal_lines jl WHERE jl.journal_entry_id = $1""",
            body["journal_entry_id"],
        )
        tx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id
        )

    assert len(lines) == 2
    assert sum(float(l["debit"]) for l in lines) == 1500.0
    assert sum(float(l["credit"]) for l in lines) == 1500.0
    ledger_custody = await _ledger_id(db_pool, custody_id)
    ledger_main = await _ledger_id(db_pool, main_id)
    debit_ledger = next(l["ledger_id"] for l in lines if float(l["debit"]) > 0)
    credit_ledger = next(l["ledger_id"] for l in lines if float(l["credit"]) > 0)
    assert debit_ledger == ledger_custody
    assert credit_ledger == ledger_main
    # 🔴 handover ไม่ใช่รายรับ/รายจ่าย ⇒ ห้ามมี finance_transactions
    assert tx_count == 0


async def test_handover_custody_to_main_is_debit_main_credit_custody(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก")
    # เติม custody ก่อนโดยตรง (seed) — เทสต์นี้สนใจทิศ journal ของ custody→main
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_accounts SET balance = 800 WHERE id = $1", custody_id
        )

    res = client.post(
        _handover_url(room_id),
        json=_handover_payload(custody_id, main_id, 800),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert await _balance(db_pool, custody_id) == 0.0
    assert await _balance(db_pool, main_id) == 800.0

    async with db_pool.acquire() as conn:
        lines = await conn.fetch(
            """SELECT ledger_id, debit, credit FROM journal_lines
               WHERE journal_entry_id = $1""",
            body["journal_entry_id"],
        )
    ledger_main = await _ledger_id(db_pool, main_id)
    ledger_custody = await _ledger_id(db_pool, custody_id)
    debit_ledger = next(l["ledger_id"] for l in lines if float(l["debit"]) > 0)
    credit_ledger = next(l["ledger_id"] for l in lines if float(l["credit"]) > 0)
    assert debit_ledger == ledger_main
    assert credit_ledger == ledger_custody


async def test_handover_rejects_insufficient_balance_and_leaves_no_trace(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_accounts SET balance = 100 WHERE id = $1", custody_id
        )
        journal_before = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id
        )

    res = client.post(
        _handover_url(room_id),
        json=_handover_payload(custody_id, main_id, 150),
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert "ไม่พอ" in res.json()["detail"]

    assert await _balance(db_pool, custody_id) == 100.0
    assert await _balance(db_pool, main_id) == 0.0
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_custody_handovers WHERE room_id = $1", room_id
        )
        journal_after = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id
        )
    assert count == 0
    assert journal_after == journal_before


# ═══════════════════════════════════════════════════ 3. idempotency
async def test_handover_idempotent_same_key_returns_same_row(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=2000)

    key = _new_key()
    payload = _handover_payload(main_id, custody_id, 500, key=key)
    first = client.post(_handover_url(room_id), json=payload, headers=admin_headers)
    second = client.post(_handover_url(room_id), json=payload, headers=admin_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_custody_handovers WHERE room_id = $1", room_id
        )
    assert count == 1
    assert await _balance(db_pool, main_id) == 1500.0
    assert await _balance(db_pool, custody_id) == 500.0


async def test_handover_idempotency_conflict_returns_409(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=3000)

    key = _new_key()
    first = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 500, key=key),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 700, key=key),
        headers=admin_headers,
    )
    assert second.status_code == 409, second.text

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_custody_handovers WHERE room_id = $1", room_id
        )
    assert count == 1
    assert await _balance(db_pool, main_id) == 2500.0


# ═══════════════════════════════════════════════════ 4. void
async def test_handover_void_restores_balances_and_voids_original_journal(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=5000)

    created = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 1500),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    handover_id = created.json()["id"]
    original_journal = created.json()["journal_entry_id"]

    res = client.post(
        _void_url(room_id, handover_id),
        json={"reason": "นับเงินผิด"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    assert await _balance(db_pool, main_id) == 5000.0
    assert await _balance(db_pool, custody_id) == 0.0

    async with db_pool.acquire() as conn:
        handover = await conn.fetchrow(
            """SELECT status, voided_at, void_reason FROM finance_custody_handovers
               WHERE id = $1""",
            handover_id,
        )
        original = await conn.fetchrow(
            "SELECT status, deleted_at FROM journal_entries WHERE id = $1",
            original_journal,
        )
        reversal = await conn.fetchrow(
            """SELECT id FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'custody_handover_void'
                 AND reference_id = $2""",
            room_id, str(handover_id),
        )
        reversal_lines = await conn.fetch(
            """SELECT ledger_id, debit, credit FROM journal_lines
               WHERE journal_entry_id = $1""",
            reversal["id"],
        )
    assert handover["status"] == "voided"
    assert handover["voided_at"] is not None
    assert handover["void_reason"] == "นับเงินผิด"
    assert original["status"] == "voided"
    assert original["deleted_at"] is not None

    ledger_main = await _ledger_id(db_pool, main_id)
    ledger_custody = await _ledger_id(db_pool, custody_id)
    debit_ledger = next(l["ledger_id"] for l in reversal_lines if float(l["debit"]) > 0)
    credit_ledger = next(l["ledger_id"] for l in reversal_lines if float(l["credit"]) > 0)
    # กลับทาง: Dr ต้นทาง / Cr ปลายทาง
    assert debit_ledger == ledger_main
    assert credit_ledger == ledger_custody


async def test_handover_void_rejected_when_destination_spent(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=5000)

    created = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 1500),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    handover_id = created.json()["id"]

    # ใช้จ่ายจาก custody 1000 — seed ทั้งรายการเงินและ balance
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_transactions
                   (room_id, account_id, amount, description, transaction_type)
               VALUES ($1, $2, 1000, 'จ่ายค่าอาหาร', 'expense')""",
            room_id, custody_id,
        )
        await conn.execute(
            "UPDATE finance_accounts SET balance = balance - 1000 WHERE id = $1",
            custody_id,
        )

    res = client.post(
        _void_url(room_id, handover_id),
        json={"reason": "ยกเลิก"},
        headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "ถูกใช้ไปแล้ว" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM finance_custody_handovers WHERE id = $1", handover_id
        )
    assert status == "active"


# ═══════════════════════════════════════════════════ 5. รายการเคลื่อนไหว
async def test_custody_movements_include_handover_and_expense(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูสมหญิง")
    custody_id = (await _create_custody(
        client, room_id, admin_headers, person_id
    ))["account_id"]
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=5000)

    created = client.post(
        _handover_url(room_id),
        json=_handover_payload(main_id, custody_id, 1500),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text

    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_transactions
                   (room_id, account_id, amount, description, transaction_type)
               VALUES ($1, $2, 1000, 'จ่ายค่าอาหาร', 'expense')""",
            room_id, custody_id,
        )
        await conn.execute(
            "UPDATE finance_accounts SET balance = balance - 1000 WHERE id = $1",
            custody_id,
        )

    res = client.get(_movements_url(room_id, person_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["person_id"] == person_id
    assert body["account_id"] == custody_id
    items = body["items"]
    assert len(items) == 2

    # ใหม่ → เก่า: expense (seed ทีหลัง) มาก่อน
    assert items[0]["kind"] == "expense"
    assert items[0]["amount"] == -1000.0
    assert items[1]["kind"] == "handover_in"
    assert items[1]["amount"] == 1500.0


# ══════════════════════════════════════ 6. สัญญาล็อกห้อง + room scope
async def test_money_lock_paths_covers_custody_writes():
    """รันตัวตรวจ completeness ของ P2.1 ฯลฯ ใหม่ — ต้องเห็น 3 เมธอด custody"""
    from test_finance_money_lock import (
        test_money_path_list_covers_every_manage_finance_entry_point,
    )
    await test_money_path_list_covers_every_manage_finance_entry_point()


async def test_custody_endpoints_are_room_scoped(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    other_room_id = await _insert_room(db_pool, admin_headers.user_id)
    other_person = await _insert_person(db_pool, other_room_id, "ครูห้องอื่น")
    other_account = await _insert_account(
        db_pool, other_room_id, "กระเป๋าห้องอื่น", balance=1000
    )
    main_id = await _insert_account(db_pool, room_id, "กระเป๋าหลัก", balance=1000)

    # คนของห้องอื่น → 404 (ไม่รั่วข้ามห้อง)
    res = client.post(
        _accounts_url(room_id),
        json={"owner_person_id": other_person},
        headers=admin_headers,
    )
    assert res.status_code == 404, res.text

    # กระเป๋าของห้องอื่นเป็นต้นทาง → 404 และยอดไม่ขยับ
    res = client.post(
        _handover_url(room_id),
        json=_handover_payload(other_account, main_id, 100),
        headers=admin_headers,
    )
    assert res.status_code == 404, res.text
    assert await _balance(db_pool, other_account) == 1000.0

    # movements ของคนห้องอื่น (ผ่านห้องนี้) → 404
    res = client.get(_movements_url(room_id, other_person), headers=admin_headers)
    assert res.status_code == 404, res.text
