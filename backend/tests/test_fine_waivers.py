"""⚖️ คำขอยกเว้น/ลดค่าปรับ — ขอ → อนุมัติ (ห้ามอนุมัติตัวเอง) → journal + บิล + INV

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ส่วนลด ≠ หนี้สูญ** — discount → Dr 49002 (contra-revenue) / uncollectible → Dr 59001
   ทั้งคู่ Cr 11002 ผู้ค้างชำระค่าปรับ
2. **ยอดถูกปรับจริงทั้งสามที่** — `fines.amount`, `fee_collections.amount` และ INV-
   ต้องตรงกันเสมอ (ใบเดิม void + ออกใหม่ตามยอดคงเหลือ)
3. **ห้ามอนุมัติคำขอของตัวเอง/ค่าปรับที่ตัวเองออก** → 403
4. **คำขอ pending บล็อกการชำระ** — กันยอดในคำขอเทียบกับบิลไม่ตรงตอนอนุมัติ
5. **ยกเว้นเต็มจำนวน** → fine/payment `waived`, ไม่มี INV active, AR กลับเป็น 0
"""
import uuid

import pytest

from services.finance.constants import (
    AR_FINE_CODE,
    FINE_BAD_DEBT_CODE,
    FINE_DISCOUNT_CODE,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
WAIVERS_PATH = API_PREFIX + "/{room}/finance/fine-waivers"
WAIVER_APPROVE = WAIVERS_PATH + "/{waiver_id}/approve"
WAIVER_REJECT = WAIVERS_PATH + "/{waiver_id}/reject"
WAIVER_CANCEL = WAIVERS_PATH + "/{waiver_id}/cancel"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"


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
            "ทดสอบ", "ยกเว้น", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _make_finance_user(pool, room_id: int, *, is_admin: bool = False) -> _H:
    """ผู้ใช้เพิ่มเติมในห้องเดียวกัน — ใช้ทดสอบ no-self approval"""
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
               VALUES ($1, $2, $3, 'student', 'active', $4, '["MANAGE_FINANCE"]'::jsonb)""",
            room_id, user_id, random.randint(10_000, 19_999), is_admin,
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
            "reason": "ทดสอบยกเว้น",
            "idempotency_key": uuid.uuid4().hex,
            "user_name": "Tester",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["fines"][0]


def _request(client, headers, fine_id: int, *, amount: float, category: str = "discount"):
    return client.post(
        _url(FINES_PATH + "/{fine_id}/waivers", headers.room_id, fine_id=fine_id),
        json={
            "amount": amount, "reason_category": category,
            "reason": "ทดสอบยกเว้น", "user_name": "Requester",
        },
        headers=headers,
    )


def _decide(client, headers, template: str, waiver_id: int, note: str = ""):
    return client.post(
        _url(template, headers.room_id, waiver_id=waiver_id),
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


async def _ar_fine(pool, room_id: int) -> float:
    return await _debit_net(pool, room_id, AR_FINE_CODE)


async def _fine_row(pool, fine_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT F.*, SP.status AS payment_status, SP.paid_amount
               FROM fines F JOIN student_payments SP ON SP.id = F.student_payment_id
               WHERE F.id = $1""",
            fine_id,
        )


async def _active_invoices(pool, payment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, amount, status FROM finance_receipts
               WHERE student_payment_id = $1 AND doc_type = 'invoice'
                 AND status = 'active' AND deleted_at IS NULL""",
            payment_id,
        )


async def _waiver_id_from_response(res) -> int:
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_partial_discount_waiver_adjusts_bill_invoice_and_journal(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)

    created = _request(client, requester, fine["id"], amount=8.0, category="discount")
    waiver_id = await _waiver_id_from_response(created)

    # 🚧 pending บล็อกการชำระ
    account_id = await _insert_account(db_pool, room_id, balance=1000)
    blocked = client.put(
        _url(PAY_PATH, room_id, payment_id=fine["student_payment_id"]),
        json={"paid_to_account_id": account_id, "paid_amount": 5.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert blocked.status_code == 400, blocked.text

    decided = _decide(client, approver, WAIVER_APPROVE, waiver_id)
    assert decided.status_code == 200, decided.text
    assert decided.json()["waiver"]["status"] == "approved"

    row = await _fine_row(db_pool, fine["id"])
    assert float(row["amount"]) == 12.0
    assert float(row["waived_amount"]) == 8.0
    assert row["status"] == "issued"
    assert row["payment_status"] == "pending"

    assert await _ar_fine(db_pool, room_id) == 12.0
    assert await _debit_net(db_pool, room_id, FINE_DISCOUNT_CODE) == 8.0
    assert await _debit_net(db_pool, room_id, FINE_BAD_DEBT_CODE) == 0.0

    async with db_pool.acquire() as conn:
        fc_amount = await conn.fetchval(
            "SELECT amount FROM fee_collections WHERE id = $1", fine["hidden_collection_id"]
        )
    assert float(fc_amount) == 12.0

    invoices = await _active_invoices(db_pool, fine["student_payment_id"])
    assert len(invoices) == 1
    assert float(invoices[0]["amount"]) == 12.0


async def test_full_uncollectible_waiver_closes_fine(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)

    waiver_id = await _waiver_id_from_response(
        _request(client, requester, fine["id"], amount=20.0, category="uncollectible")
    )
    decided = _decide(client, approver, WAIVER_APPROVE, waiver_id)
    assert decided.status_code == 200, decided.text

    row = await _fine_row(db_pool, fine["id"])
    assert float(row["amount"]) == 0.0
    assert row["status"] == "waived"
    assert row["payment_status"] == "waived"
    assert await _ar_fine(db_pool, room_id) == 0.0
    assert await _debit_net(db_pool, room_id, FINE_BAD_DEBT_CODE) == 20.0
    assert await _active_invoices(db_pool, fine["student_payment_id"]) == []


async def test_cannot_approve_own_request_or_own_fine(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    requester = await _make_finance_user(db_pool, room_id)

    waiver_id = await _waiver_id_from_response(
        _request(client, requester, fine["id"], amount=5.0)
    )
    # ผู้ขออนุมัติเอง
    own = _decide(client, requester, WAIVER_APPROVE, waiver_id)
    assert own.status_code == 403, own.text

    # ผู้ออกค่าปรับ (admin) อนุมัติก็ไม่ได้
    issuer = _decide(client, admin_headers, WAIVER_APPROVE, waiver_id)
    assert issuer.status_code == 403, issuer.text

    # คำขอยัง pending และยอดไม่ขยับ
    async with db_pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM fine_waivers WHERE id = $1", waiver_id)
    assert status == "pending"
    assert await _ar_fine(db_pool, room_id) == 20.0


async def test_reject_and_cancel_leave_fine_untouched(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    requester = await _make_finance_user(db_pool, room_id)
    approver = await _make_finance_user(db_pool, room_id)

    w1 = await _waiver_id_from_response(_request(client, requester, fine["id"], amount=5.0))
    rejected = _decide(client, approver, WAIVER_REJECT, w1, note="หลักฐานไม่พอ")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["waiver"]["status"] == "rejected"

    w2 = await _waiver_id_from_response(_request(client, requester, fine["id"], amount=5.0))
    cancelled = _decide(client, requester, WAIVER_CANCEL, w2)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["waiver"]["status"] == "cancelled"

    row = await _fine_row(db_pool, fine["id"])
    assert float(row["amount"]) == 20.0
    assert await _ar_fine(db_pool, room_id) == 20.0


async def test_waiver_amount_cannot_exceed_outstanding(client, db_pool, admin_headers):
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    requester = await _make_finance_user(db_pool, admin_headers.room_id)

    res = _request(client, requester, fine["id"], amount=25.0)
    assert res.status_code == 400, res.text


async def test_member_cannot_request_waiver(client, db_pool, admin_headers, member_headers):
    """สมาชิกธรรมดา (ไม่มี MANAGE_FINANCE) ขอยกเว้นไม่ได้"""
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)
    # member อยู่คนละห้องตาม fixture — ยิงเข้าห้องของ admin
    res = client.post(
        _url(FINES_PATH + "/{fine_id}/waivers", admin_headers.room_id, fine_id=fine["id"]),
        json={"amount": 5.0, "reason_category": "discount", "reason": "x", "user_name": "M"},
        headers=member_headers,
    )
    assert res.status_code == 403, res.text
