"""💸 คืนเงินค่าปรับ — ขอ → อนุมัติ (ห้ามอนุมัติตัวเอง) → เงินสด −, PV-, journal, revert guard

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **คืนเงินคือเงินสดออก ไม่ใช่การเปิดหนี้ใหม่** — ไม่แตะ AR 11002/paid_amount;
   journal Dr 49003 / Cr บัญชีสินทรัพย์ + ยอดกระเป๋าลดจริง
2. **ออกใบสำคัญจ่าย PV- ผูกกับ transaction ชนิด refund** — และหา revert ตรง ๆ ไม่ได้
   (ถ้าย้อนได้ `fines.refunded_amount` จะไม่ตรงกับเงินที่จ่ายจริง)
3. **เพดานยอดคืน** = `paid_amount - refunded_amount` ของค่าปรับนั้น
4. **เงินในบัญชีต้องพอ** — คืนเกินยอดคงเหลือของกระเป๋าไม่ได้
5. **ห้ามอนุมัติคำขอของตัวเอง/ค่าปรับที่ตัวเองออก** → 403
"""
import uuid

import pytest

from services.finance.constants import AR_FINE_CODE, FINE_REFUND_CODE
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
REFUNDS_PATH = API_PREFIX + "/{room}/finance/fine-refunds"
REFUND_APPROVE = REFUNDS_PATH + "/{refund_id}/approve"
REFUND_REJECT = REFUNDS_PATH + "/{refund_id}/reject"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"


class _H(dict):
    def __init__(self, headers: dict, room_id: int):
        super().__init__(headers)
        self.room_id = room_id


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


async def _make_student(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            "ทดสอบ", "คืนเงิน", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _make_finance_user(pool, room_id: int) -> _H:
    import random

    from core.config import settings

    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ('ผู้ตรวจ', 'การเงิน', $1, $2) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '["MANAGE_FINANCE"]'::jsonb)""",
            room_id, user_id, random.randint(10_000, 19_999),
        )
    return _H({"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}, room_id)


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
            "reason": "ทดสอบคืนเงิน",
            "idempotency_key": uuid.uuid4().hex,
            "user_name": "Tester",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["fines"][0]


def _pay(client, headers, fine: dict, account_id: int, amount: float):
    return client.put(
        _url(PAY_PATH, headers.room_id, payment_id=fine["student_payment_id"]),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


def _request(client, headers, fine_id: int, *, account_id: int, amount: float):
    return client.post(
        _url(FINES_PATH + "/{fine_id}/refunds", headers.room_id, fine_id=fine_id),
        json={
            "account_id": account_id, "amount": amount,
            "reason": "คืนเงินทดสอบ", "user_name": "Requester",
        },
        headers=headers,
    )


def _decide(client, headers, template: str, refund_id: int, note: str = ""):
    return client.post(
        _url(template, headers.room_id, refund_id=refund_id),
        json={"note": note, "user_name": "Approver"},
        headers=headers,
    )


async def _debit_net(pool, room_id: int, code: str) -> float:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_code = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, code,
        )
    return round(float(val), 2)


async def _asset_net(pool, room_id: int) -> float:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = 'asset'
                 AND AL.account_code NOT IN ($2, '11002')
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, AR_FINE_CODE,
        )
    return round(float(val), 2)


async def _fine_row(pool, fine_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM fines WHERE id = $1", fine_id)


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


async def test_full_refund_after_payment_issues_voucher_and_journal(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    assert _pay(client, admin_headers, fine, account_id, 20.0).status_code == 200

    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)

    created = _request(client, requester, fine["id"], account_id=account_id, amount=20.0)
    assert created.status_code == 200, created.text
    refund_id = created.json()["id"]

    decided = _decide(client, approver, REFUND_APPROVE, refund_id)
    assert decided.status_code == 200, decided.text
    assert decided.json()["refund"]["status"] == "approved"
    assert decided.json()["receipt_no"].startswith("PV-")

    row = await _fine_row(db_pool, fine["id"])
    assert row["status"] == "refunded"
    assert float(row["refunded_amount"]) == 20.0
    assert await _balance(db_pool, account_id) == 1000.0
    assert await _debit_net(db_pool, room_id, FINE_REFUND_CODE) == 20.0
    # 💰 รับเงิน +20 แล้วคืน −20 ⇒ สุทธิของสินทรัพย์ใน journal = 0
    assert await _asset_net(db_pool, room_id) == 0.0

    async with db_pool.acquire() as conn:
        tx = await conn.fetchrow(
            """SELECT id, transaction_type, amount FROM finance_transactions
               WHERE room_id = $1 AND transaction_type = 'refund' AND deleted_at IS NULL""",
            room_id,
        )
        doc = await conn.fetchrow(
            """SELECT doc_type, receipt_no, amount FROM finance_receipts
               WHERE legacy_transaction_id = $1 AND deleted_at IS NULL""",
            tx["id"],
        )
    assert tx is not None and float(tx["amount"]) == 20.0
    assert doc["doc_type"] == "payment_voucher"
    assert float(doc["amount"]) == 20.0

    # 🚫 revert ตรง ๆ ไม่ได้ — ต้องใช้หน้าค่าปรับเท่านั้น
    revert = client.request(
        "DELETE", _url(TRANSACTION_PATH, room_id, tx_id=tx["id"]),
        json={"user_name": "Tester"}, headers=admin_headers,
    )
    assert revert.status_code == 400, revert.text


async def test_partial_refund_keeps_fine_paid(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    assert _pay(client, admin_headers, fine, account_id, 20.0).status_code == 200

    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)
    refund_id = _request(
        client, requester, fine["id"], account_id=account_id, amount=5.0
    ).json()["id"]

    assert _decide(client, approver, REFUND_APPROVE, refund_id).status_code == 200
    row = await _fine_row(db_pool, fine["id"])
    assert row["status"] == "paid"
    assert float(row["refunded_amount"]) == 5.0
    assert await _balance(db_pool, account_id) == 1015.0


async def test_refund_ceiling_and_account_balance(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    assert _pay(client, admin_headers, fine, account_id, 20.0).status_code == 200
    requester = await _make_finance_user(db_pool, room_id)

    too_much = _request(client, requester, fine["id"], account_id=account_id, amount=25.0)
    assert too_much.status_code == 400, too_much.text

    # กระเป๋าเงินไม่พอคืน
    refund_id = _request(
        client, requester, fine["id"], account_id=account_id, amount=20.0
    ).json()["id"]
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_accounts SET balance = 0 WHERE id = $1", account_id
        )
    approver = await _make_finance_user(db_pool, room_id)
    res = _decide(client, approver, REFUND_APPROVE, refund_id)
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM fine_refunds WHERE id = $1", refund_id)
    assert status == "pending"


async def test_cannot_approve_own_refund_request(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    assert _pay(client, admin_headers, fine, account_id, 20.0).status_code == 200
    requester = await _make_finance_user(db_pool, room_id)

    refund_id = _request(
        client, requester, fine["id"], account_id=account_id, amount=20.0
    ).json()["id"]
    assert _decide(client, requester, REFUND_APPROVE, refund_id).status_code == 403
    assert _decide(client, admin_headers, REFUND_APPROVE, refund_id).status_code == 403

    row = await _fine_row(db_pool, fine["id"])
    assert float(row["refunded_amount"]) == 0.0


async def test_reject_refund_does_not_touch_cash(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    assert _pay(client, admin_headers, fine, account_id, 20.0).status_code == 200
    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)

    refund_id = _request(
        client, requester, fine["id"], account_id=account_id, amount=20.0
    ).json()["id"]
    res = _decide(client, approver, REFUND_REJECT, refund_id, note="ไม่คืน")
    assert res.status_code == 200, res.text
    assert res.json()["refund"]["status"] == "rejected"
    assert await _balance(db_pool, account_id) == 1020.0
    own = await _fine_row(db_pool, fine["id"])
    assert float(own["refunded_amount"]) == 0.0
