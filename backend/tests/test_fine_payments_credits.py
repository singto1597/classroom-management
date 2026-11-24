"""⚖️ ค่าปรับ × การชำระเงิน/เครดิต/ย้อนรายการ — สถานะต้องตามยอดจริงทุกก้าว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **สถานะค่าปรับเป็นผลลัพธ์ ไม่ใช่ค่าที่คนพิมพ์** — `_sync_fine_status` ต้องพา
   issued → partially_paid → paid และถอยกลับได้เมื่อย้อนรายการ
2. **รับเงินต้องตัด AR 11002 ไม่ใช่รายได้** — รายได้ถูกรับรู้ตอนออกค่าปรับแล้ว
3. **ใช้เครดิตก็ตัด AR 11002** — Dr 2099 / Cr 11002 (ไม่ใช่ Dr 2099 / Cr 49001)
4. **ย้อนรายการต้องคืนสถานะ** — ทั้งยกเลิกการใช้เครดิตและ revert การชำระเงิน
5. **ค่าปรับที่ยกเว้น/ยกเลิก/คืนเงินแล้วห้ามย้อนรายการ** — ด่านนี้จะทำงานใน Phase 4
   (ที่นี่เทสต์เฉพาะเส้นทางปกติ)
"""
import json
import uuid

import pytest

from services.finance.constants import AR_FINE_CODE
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
FINE_PATH = API_PREFIX + "/{room}/finance/fines/{fine_id}"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"
CREDITS_PATH = API_PREFIX + "/{room}/finance/credits"
APPLY_PATH = API_PREFIX + "/{room}/finance/credits/apply"
UNDO_PATH = API_PREFIX + "/{room}/finance/credits/undo"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


async def _make_student(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            "ทดสอบ", "ค่าปรับ", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _insert_account(pool, room_id: int, balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, "กระเป๋ากลาง", balance,
        )


async def _issued_fine(client, headers, db_pool, *, amount: float = 20.0) -> dict:
    room_id = headers.room_id
    async with db_pool.acquire() as conn:
        await FinanceService.ensure_default_fine_types(conn, room_id)
        type_id = await conn.fetchval(
            "SELECT id FROM fine_types WHERE room_id = $1 AND name = 'อื่น ๆ (กรอกยอดเอง)'", room_id
        )
    student_id = await _make_student(db_pool, room_id)
    res = client.post(
        _url(FINES_PATH, room_id),
        json={
            "fine_type_id": type_id,
            "students": [{"student_id": student_id, "amount": amount}],
            "incident_date": "2026-11-20",
            "reason": "ทดสอบชำระ",
            "idempotency_key": uuid.uuid4().hex,
            "user_name": "Tester",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    fine = res.json()["fines"][0]
    fine["student_id_under_test"] = student_id
    return fine


async def _ar_balance(pool, room_id: int) -> float:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_code = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, AR_FINE_CODE,
        )
    return round(float(val), 2)


async def _fine_status(pool, fine_id: int) -> str:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM fines WHERE id = $1", fine_id)


def _pay(client, headers, payment_id: int, account_id: int, amount: float):
    return client.put(
        _url(PAY_PATH, headers.room_id, payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


def _top_up(client, headers, student_id: int, account_id: int, amount: float):
    return client.post(
        _url(CREDITS_PATH, headers.room_id),
        json={
            "student_id": student_id, "amount": amount,
            "paid_to_account_id": account_id,
            "idempotency_key": uuid.uuid4().hex, "user_name": "Tester",
        },
        headers=headers,
    )


def _apply(client, headers, student_id: int):
    return client.post(
        _url(APPLY_PATH, headers.room_id),
        json={"student_ids": [student_id], "user_name": "Tester"},
        headers=headers,
    )


def _undo(client, headers, credit_entry_id: int):
    return client.post(
        _url(UNDO_PATH, headers.room_id),
        json={"credit_entry_id": credit_entry_id, "user_name": "Tester"},
        headers=headers,
    )


def _revert(client, headers, tx_id: int):
    return client.request(
        "DELETE", _url(TRANSACTION_PATH, headers.room_id, tx_id=tx_id),
        json={"user_name": "Tester"}, headers=headers,
    )


async def test_partial_then_full_cash_payment_updates_status_and_ar(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)

    first = _pay(client, admin_headers, fine["student_payment_id"], account_id, 5.0)
    assert first.status_code == 200, first.text
    assert await _fine_status(db_pool, fine["id"]) == "partially_paid"
    assert await _ar_balance(db_pool, room_id) == 15.0

    second = _pay(client, admin_headers, fine["student_payment_id"], account_id, 15.0)
    assert second.status_code == 200, second.text
    assert await _fine_status(db_pool, fine["id"]) == "paid"
    assert await _ar_balance(db_pool, room_id) == 0.0

    # journal รับเงินต้อง Cr AR ค่าปรับ (collection_kind=fine) ไม่ใช่รายได้
    async with db_pool.acquire() as conn:
        metas = await conn.fetch(
            """SELECT metadata FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'student_payment'
                 AND deleted_at IS NULL AND status <> 'voided'""",
            room_id,
        )
    assert len(metas) == 2
    for m in metas:
        meta = json.loads(m["metadata"]) if isinstance(m["metadata"], str) else m["metadata"]
        assert meta["collection_kind"] == "fine"


async def test_credit_application_pays_fine_and_undo_restores_status(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id)

    topup = _top_up(client, admin_headers, fine["student_id_under_test"], account_id, 50.0)
    assert topup.status_code == 200, topup.text

    applied = _apply(client, admin_headers, fine["student_id_under_test"])
    assert applied.status_code == 200, applied.text
    assert await _fine_status(db_pool, fine["id"]) == "paid"
    assert await _ar_balance(db_pool, room_id) == 0.0

    async with db_pool.acquire() as conn:
        entry_id = await conn.fetchval(
            """SELECT id FROM student_credits
               WHERE room_id = $1 AND student_id = $2 AND entry_type = 'apply'
                 AND deleted_at IS NULL ORDER BY id DESC LIMIT 1""",
            room_id, fine["student_id_under_test"],
        )
    assert entry_id is not None

    undone = _undo(client, admin_headers, entry_id)
    assert undone.status_code == 200, undone.text
    assert await _fine_status(db_pool, fine["id"]) == "issued"
    assert await _ar_balance(db_pool, room_id) == 20.0


async def test_revert_cash_payment_restores_fine_status(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)

    assert _pay(client, admin_headers, fine["student_payment_id"], account_id, 20.0).status_code == 200
    assert await _fine_status(db_pool, fine["id"]) == "paid"

    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            """SELECT id FROM finance_transactions
               WHERE room_id = $1 AND student_payment_id = $2 AND deleted_at IS NULL""",
            room_id, fine["student_payment_id"],
        )
    assert tx_id is not None

    res = _revert(client, admin_headers, tx_id)
    assert res.status_code == 200, res.text
    assert await _fine_status(db_pool, fine["id"]) == "issued"
    assert await _ar_balance(db_pool, room_id) == 20.0
