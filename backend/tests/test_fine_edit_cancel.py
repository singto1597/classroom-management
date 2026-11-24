"""⚖️ แก้ไข / ยกเลิกค่าปรับ (ก่อนมีคนจ่าย) — journal ปรับส่วนต่าง + void/ออก INV ใหม่

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **แก้ยอดต้องกระทบทั้งบิลและค่าปรับ** — `fee_collections.amount` (บิลที่คนจ่ายเห็น)
   กับ `fines.amount` (โดเมนค่าปรับ) ต้องเท่ากันเสมอ ไม่งั้นยอดค้าง/สถานะจะขัดกัน
2. **journal ปรับส่วนต่าง (`fine_adjustment`)** — ไม่ void ใบออกเดิมแล้วออกใหม่ (รายได้
   ตอนออกยังถูกต้อง) แต่ลงเฉพาะ delta: AR 11002 ↔ รายได้ 49001
3. **ใบแจ้งหนี้เป็น snapshot** — ข้อมูลบนใบเปลี่ยน ⇒ ใบเก่าต้อง void **คู่กับ** deleted_at
   และต้องมีใบใหม่ active 1 ใบ (unique index อนุญาตให้มี active ใบเดียว)
4. **ยกเลิก = กลับรายได้ + เก็บหลักฐาน** — Dr 49001 / Cr 11002, บิล/โปรเจกต์ซ่อนถูก
   soft delete, `fines` ยังอยู่ (สถานะ cancelled — ห้าม soft delete เพราะประวัติต้องเห็น)
5. **จ่ายแล้วห้ามทั้งแก้และยกเลิก** — ต้องใช้ยกเว้น/คืนเงินแทน
"""
import uuid

import pytest

from services.finance.constants import (
    AR_FINE_CODE, COLLECTION_KIND_FINE, DOC_TYPE_INVOICE, FINE_REVENUE_CODE,
    FINE_STATUS_CANCELLED, REFERENCE_TYPE_FINE_ADJUSTMENT, REFERENCE_TYPE_FINE_CANCEL,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
FINE_PATH = API_PREFIX + "/{room}/finance/fines/{fine_id}"
CANCEL_PATH = API_PREFIX + "/{room}/finance/fines/{fine_id}/cancel"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"


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


async def _issued_fine(client, admin_headers, db_pool, *, amount: float = 20.0) -> dict:
    room_id = admin_headers.room_id
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
            "reason": "ทดสอบแก้ไข",
            "idempotency_key": uuid.uuid4().hex,
            "user_name": "Tester",
        },
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["fines"][0]


async def _balance(pool, room_id: int, code: str, direction: str = "debit") -> float:
    expr = "L.debit - L.credit" if direction == "debit" else "L.credit - L.debit"
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            f"""SELECT COALESCE(SUM({expr}), 0)
                FROM journal_lines L
                JOIN journal_entries JE ON L.journal_entry_id = JE.id
                JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                WHERE JE.room_id = $1 AND AL.account_code = $2
                  AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, code,
        )
    return round(float(val), 2)


async def _journal_refs(pool, room_id: int, reference_type: str):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, metadata FROM journal_entries
               WHERE room_id = $1 AND reference_type = $2
                 AND deleted_at IS NULL AND status <> 'voided'""",
            room_id, reference_type,
        )


async def test_update_amount_posts_delta_and_reissues_invoice(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)

    res = client.patch(
        _url(FINE_PATH, room_id, fine_id=fine["id"]),
        json={"amount": 35.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        fine_row = await conn.fetchrow(
            "SELECT * FROM fines WHERE id = $1", fine["id"]
        )
        bill = await conn.fetchrow(
            """SELECT SP.id, FC.amount FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE SP.id = $1""",
            fine["student_payment_id"],
        )
        invoices = await conn.fetch(
            """SELECT id, amount, status, deleted_at FROM finance_receipts
               WHERE room_id = $1 AND student_payment_id = $2 AND doc_type = $3
               ORDER BY id""",
            room_id, fine["student_payment_id"], DOC_TYPE_INVOICE,
        )
    assert float(fine_row["amount"]) == 35.0
    assert float(bill["amount"]) == 35.0
    assert len(invoices) == 2, "ใบเดิมต้องถูก void และมีใบใหม่อีกใบ"
    assert invoices[0]["status"] == "voided" and invoices[0]["deleted_at"] is not None
    assert invoices[1]["status"] == "active" and invoices[1]["deleted_at"] is None
    assert float(invoices[1]["amount"]) == 35.0
    assert fine_row["invoice_receipt_id"] == invoices[1]["id"]

    entries = await _journal_refs(db_pool, room_id, REFERENCE_TYPE_FINE_ADJUSTMENT)
    assert len(entries) == 1
    import json
    meta = entries[0]["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else meta
    assert meta["delta"] == 15.0

    assert await _balance(db_pool, room_id, AR_FINE_CODE, "debit") == 35.0
    assert await _balance(db_pool, room_id, FINE_REVENUE_CODE, "credit") == 35.0


async def test_update_reason_only_reissues_invoice(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool)

    res = client.patch(
        _url(FINE_PATH, room_id, fine_id=fine["id"]),
        json={"reason": "ปรับเหตุผลใหม่"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        active = await conn.fetch(
            """SELECT id FROM finance_receipts
               WHERE student_payment_id = $1 AND doc_type = $2
                 AND status = 'active' AND deleted_at IS NULL""",
            fine["student_payment_id"], DOC_TYPE_INVOICE,
        )
        reason = await conn.fetchval("SELECT reason FROM fines WHERE id = $1", fine["id"])
    assert len(active) == 1
    assert reason == "ปรับเหตุผลใหม่"
    # ไม่มีรายการเงินแตะ ⇒ ไม่มี journal adjustment
    assert await _journal_refs(db_pool, room_id, REFERENCE_TYPE_FINE_ADJUSTMENT) == []


async def test_update_after_payment_is_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool)
    account_id = await _insert_account(db_pool, room_id, balance=1000)

    pay = client.put(
        _url(PAY_PATH, room_id, payment_id=fine["student_payment_id"]),
        json={"paid_to_account_id": account_id, "paid_amount": 10.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert pay.status_code == 200, pay.text

    res = client.patch(
        _url(FINE_PATH, room_id, fine_id=fine["id"]),
        json={"amount": 50.0},
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    async with db_pool.acquire() as conn:
        assert float(await conn.fetchval("SELECT amount FROM fines WHERE id = $1", fine["id"])) == 20.0


async def test_cancel_before_payment_reverses_revenue_and_soft_deletes_bill(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool, amount=20.0)

    res = client.post(
        _url(CANCEL_PATH, room_id, fine_id=fine["id"]),
        json={"reason": "ออกผิด", "user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        fine_row = await conn.fetchrow("SELECT status, deleted_at FROM fines WHERE id = $1", fine["id"])
        bill = await conn.fetchrow(
            "SELECT status, deleted_at FROM student_payments WHERE id = $1",
            fine["student_payment_id"],
        )
        collection = await conn.fetchrow(
            "SELECT deleted_at FROM fee_collections WHERE id = $1", fine["hidden_collection_id"]
        )
        invoice = await conn.fetchrow(
            """SELECT status, deleted_at FROM finance_receipts
               WHERE student_payment_id = $1 AND doc_type = $2""",
            fine["student_payment_id"], DOC_TYPE_INVOICE,
        )
    assert fine_row["status"] == FINE_STATUS_CANCELLED
    assert fine_row["deleted_at"] is None, "ค่าปรับต้องยังมองเห็นในประวัติ (ไม่ soft delete)"
    assert bill["status"] == "cancelled" and bill["deleted_at"] is not None
    assert collection["deleted_at"] is not None
    assert invoice["status"] == "voided" and invoice["deleted_at"] is not None

    entries = await _journal_refs(db_pool, room_id, REFERENCE_TYPE_FINE_CANCEL)
    assert len(entries) == 1
    # ยอด AR/รายได้ต้องกลับเป็นศูนย์สุทธิ
    assert await _balance(db_pool, room_id, AR_FINE_CODE, "debit") == 0.0
    assert await _balance(db_pool, room_id, FINE_REVENUE_CODE, "credit") == 0.0

    # ยกเลิกซ้ำ — idempotent (ไม่ลง journal เพิ่ม)
    again = client.post(
        _url(CANCEL_PATH, room_id, fine_id=fine["id"]),
        json={"user_name": "Tester"},
        headers=admin_headers,
    )
    assert again.status_code == 200, again.text
    assert await _balance(db_pool, room_id, AR_FINE_CODE, "debit") == 0.0


async def test_cancel_after_payment_is_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool)
    account_id = await _insert_account(db_pool, room_id, balance=1000)

    pay = client.put(
        _url(PAY_PATH, room_id, payment_id=fine["student_payment_id"]),
        json={"paid_to_account_id": account_id, "paid_amount": 5.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert pay.status_code == 200, pay.text

    res = client.post(
        _url(CANCEL_PATH, room_id, fine_id=fine["id"]),
        json={"user_name": "Tester"},
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM fines WHERE id = $1", fine["id"]) != FINE_STATUS_CANCELLED


async def test_update_due_date_before_incident_is_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    fine = await _issued_fine(client, admin_headers, db_pool)

    res = client.patch(
        _url(FINE_PATH, room_id, fine_id=fine["id"]),
        json={"due_date": "2026-11-01"},
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
