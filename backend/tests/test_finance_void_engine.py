"""🚫 [FIN-V2 / P6.1] void engine — ยกเลิก event/PV/INC/เอกสารแบบ atomic จุดเดียว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **กลับทุกขา** — `finance_accounts.balance`, `student_payments.paid_amount`,
   `student_credits` (append-only `reverse`), journal, transaction และเอกสาร
   ต้องกลับครบในคำสั่งเดียว ไม่มีทางเดินครึ่ง ๆ
2. **ไม่ DELETE** — void = `status='voided'` + `deleted_at` คู่กันเสมอ
   (`finance_receipts` มี CHECK `chk_receipt_voided_is_deleted`; journal ใช้ convention)
3. **CERT ตายพร้อม PV** — ห้ามเหลือ CERT `active` ที่อ้างใบสำคัญจ่ายที่ถูกยกเลิกแล้ว
4. **เหตุผลบังคับ** — ว่าง/ช่องว่างล้วน = **400** (service เป็นผู้ตัดสิน ไม่ใช่ 422)
5. **atomic** — ล้มกลางทางหลังหักกระเป๋าไปแล้ว ⇒ rollback ทั้งใบ ไม่มีร่องรอย
6. **dispatch ข้ามเจ้าของ** — REC/DEP ของ event, CERT เดี่ยว, INV ที่ถูกอ้าง,
   doc_type ที่ไม่รู้จัก ถูกปฏิเสธพร้อมรหัสที่ถูก (409/400) ไม่ใช่เงียบ ๆ

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"


# ═══════════════════════════════════════════════════════════════════ helpers
def _events_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events"


def _event_void_url(room_id: int, event_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events/{event_id}/void"


def _vouchers_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers?target_type=room"


def _voucher_void_url(room_id: int, voucher_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/expense-vouchers/{voucher_id}/void"
        "?target_type=room"
    )


def _batches_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/income-batches?target_type=room"


def _batch_void_url(room_id: int, batch_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/income-batches/{batch_id}/void"
        "?target_type=room"
    )


def _doc_void_url(room_id: int, doc_type: str, doc_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/documents/{doc_type}/{doc_id}/void"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    return f"{float(value):.2f}"


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


async def _insert_category(pool, room_id: int, name: str, cat_type: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, cat_type,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *,
    title: str = "ค่าเทอม", amount: float = 1000.0,
) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, NULL, 'active', 'room_fund', 'project') RETURNING id""",
            room_id, title, amount,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', 0, 0) RETURNING id""",
            collection_id, student_id,
        )


async def _insert_credit(pool, room_id: int, student_id: int, amount: float) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'topup', $3, $3) RETURNING id""",
            room_id, student_id, amount,
        )


def _event_payload(
    student_id: int, account_id: int, *,
    key: str | None = None, cash: str = "0.00", use_credit: bool = False,
    excess_action: str = "credit",
) -> dict:
    return {
        "idempotency_key": key or _new_key(),
        "student_id": student_id,
        "wallet_account_id": account_id,
        "payer_name": "ผู้ปกครองทดสอบ",
        "receiver_name": RECEIVER,
        "amount_received": cash,
        "use_credit": use_credit,
        "excess_action": excess_action,
        "bill_selection": "auto",
    }


def _voucher_payload(*, default_wallet_account_id: int, lines: list) -> dict:
    return {
        "idempotency_key": _new_key(),
        "default_wallet_account_id": default_wallet_account_id,
        "payee_name": "ร้านวัสดุทดสอบ",
        "note": "ใบสำคัญจ่ายทดสอบ",
        "approved_by_name": "ครูอนุมัติ",
        "lines": lines,
    }


def _voucher_line(
    amount: float, *, category_id: int, wallet_account_id: int,
    description: str = "รายการทดสอบ", receipt_status: str = "none",
) -> dict:
    return {
        "description": description,
        "amount": _money(amount),
        "category_id": category_id,
        "wallet_account_id": wallet_account_id,
        "receipt_status": receipt_status,
        "paper_bill_count": 0,
        "funding_source": "room_fund",
    }


def _income_payload(*, wallet_account_id: int, lines: list) -> dict:
    return {
        "idempotency_key": _new_key(),
        "payer_name": "ผู้ปกครองนักเรียน ม.2",
        "wallet_account_id": wallet_account_id,
        "receiver_name": "ครูสมหญิง",
        "note": "รายรับอื่นทดสอบ",
        "lines": lines,
    }


def _income_line(amount: float, *, category_id: int, description: str) -> dict:
    return {"description": description, "amount": _money(amount), "category_id": category_id}


async def _insert_receipt_doc(
    pool, room_id: int, *, doc_type: str, seq: int, amount: float = 100.0,
    payment_event_id: int | None = None,
) -> int:
    """เอกสารเปล่า (legacy/INV) สำหรับทดสอบ dispatch — ไม่มี journal/เงินผูก"""
    prefix = {"invoice": "INV", "receipt": "REC", "certificate": "CERT"}[doc_type]
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, amount,
                    paid_total_after, layout_version, payment_event_id)
               VALUES ($1, $2, $3, 2569, $4, $5, $5, 1, $6) RETURNING id""",
            room_id, f"{prefix}-2569-{seq:04d}", doc_type, seq, amount,
            payment_event_id,
        )


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


async def _payment(pool, payment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM student_payments WHERE id = $1", payment_id
        )


async def _receipt_row(pool, receipt_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM finance_receipts WHERE id = $1", receipt_id
        )


async def _event_receipt_id(pool, event_id: int, doc_type: str = "receipt") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT id FROM finance_receipts
               WHERE payment_event_id = $1 AND doc_type = $2 AND deleted_at IS NULL""",
            event_id, doc_type,
        )


# ═════════════════════════ 1. กลับกระเป๋า/บิล/เครดิต ครบในคำสั่งเดียว
async def test_void_event_reverses_wallet_bill_and_credit(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=1000.0)
    await _insert_credit(db_pool, room, student, 300.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="700.00", use_credit=True),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    event_id = created.json()["event_id"]
    assert _money(await _balance(db_pool, account)) == "700.00"

    res = client.post(
        _event_void_url(room, event_id),
        json={"reason": "บันทึกผิดรายการ"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["doc_type"] == "payment_event"
    assert body["doc_id"] == event_id
    assert _money(body["reversed"]["amount"]) == "700.00"
    assert _money(body["reversed"]["paid_amount_delta"]) == "-1000.00"
    assert _money(body["reversed"]["credit_restored"]) == "300.00"
    assert body["reversed"]["accounts"] == [
        {"account_id": account, "delta": -700.0},
    ]

    # 💰 กระเป๋ากลับเป็น 0
    assert _money(await _balance(db_pool, account)) == "0.00"

    # 📄 บิลกลับเป็นค้างชำระ เต็มจำนวน
    sp = await _payment(db_pool, bill)
    assert _money(sp["paid_amount"]) == "0.00"
    assert sp["status"] == "pending"
    assert sp["paid_at"] is None and sp["transaction_id"] is None

    async with db_pool.acquire() as conn:
        credits = await conn.fetch(
            """SELECT entry_type, amount, balance_after, deleted_at
               FROM student_credits
               WHERE room_id = $1 AND student_id = $2 ORDER BY id""",
            room, student,
        )
    topup, apply, reverse = credits
    assert topup["entry_type"] == "topup" and topup["deleted_at"] is None
    assert apply["entry_type"] == "apply" and apply["deleted_at"] is not None
    assert reverse["entry_type"] == "reverse" and reverse["deleted_at"] is None
    assert _money(reverse["amount"]) == "300.00"
    # 📸 `balance_after` ต้องกลับเท่าเดิมก่อนถูกหัก (ไม่ใช่ 0 แล้วบวกซ้ำ)
    assert _money(reverse["balance_after"]) == "300.00"

    async with db_pool.acquire() as conn:
        txn = await conn.fetchrow(
            "SELECT deleted_at FROM finance_transactions WHERE payment_event_id = $1",
            event_id,
        )
    assert txn["deleted_at"] is not None


# ═══════════════════════════════ 2. REC + DEP ถูก void พร้อมกัน (status กับ deleted_at คู่กัน)
async def test_void_event_voids_rec_and_dep(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1500.00"),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    assert data["receipt_no"].startswith("REC-")
    assert data["deposit_no"].startswith("DEP-")

    res = client.post(
        _event_void_url(room, data["event_id"]),
        json={"reason": "ลูกค้าขอยกเลิก"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["receipt_no"] == data["receipt_no"]

    async with db_pool.acquire() as conn:
        docs = await conn.fetch(
            """SELECT doc_type, status, voided_at, deleted_at, void_reason
               FROM finance_receipts WHERE payment_event_id = $1 ORDER BY id""",
            data["event_id"],
        )
        event = await conn.fetchrow(
            "SELECT status, voided_at, voided_by, void_reason "
            "FROM finance_payment_events WHERE id = $1",
            data["event_id"],
        )
    assert {d["doc_type"] for d in docs} == {"receipt", "deposit"}
    for d in docs:
        assert d["status"] == "voided"
        assert d["voided_at"] is not None
        assert d["deleted_at"] is not None
        assert d["void_reason"] == "ลูกค้าขอยกเลิก"
    assert event["status"] == "voided"
    assert event["void_reason"] == "ลูกค้าขอยกเลิก"

    # เครดิตส่วนเกินถูกถอนคืน (append-only reverse) ⇒ ยอดคงเหลือกลับ 0
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval(
            """SELECT balance_after FROM student_credits
               WHERE room_id = $1 AND student_id = $2 AND deleted_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            room, student,
        )
    assert _money(balance) == "0.00"


# ═══════════════════════ 3. journal ถูก mark voided — แถวและบรรทัด Dr/Cr ยังอยู่ครบ
async def test_void_event_marks_journal_voided_not_deleted(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    event_id = created.json()["event_id"]

    async with db_pool.acquire() as conn:
        journals = await conn.fetch(
            """SELECT id FROM journal_entries
               WHERE room_id = $1 AND deleted_at IS NULL ORDER BY id""",
            room,
        )
    assert len(journals) >= 1
    journal_ids = [j["id"] for j in journals]

    async with db_pool.acquire() as conn:
        lines_before = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_lines WHERE journal_entry_id = ANY($1::uuid[])",
            journal_ids,
        )

    res = client.post(
        _event_void_url(room, event_id),
        json={"reason": "ทดสอบ journal"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, deleted_at FROM journal_entries "
            "WHERE id = ANY($1::uuid[])",
            journal_ids,
        )
        lines_after = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_lines WHERE journal_entry_id = ANY($1::uuid[])",
            journal_ids,
        )
    assert len(rows) == len(journal_ids)          # ไม่มีแถวหายไป
    for row in rows:
        assert row["status"] == "voided"
        assert row["deleted_at"] is not None
    assert lines_after == lines_before             # Dr/Cr ไม่ถูกลบ


# ═══════════════════════════════════ 4. บรรทัดของ event ยังอยู่ครบ (หลักฐานว่าอะไรเคยลง)
async def test_void_event_does_not_delete_event_lines(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)
    await _insert_credit(db_pool, room, student, 300.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="700.00", use_credit=True),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    event_id = created.json()["event_id"]

    async with db_pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_event_lines WHERE event_id = $1",
            event_id,
        )
    assert before == 2

    res = client.post(
        _event_void_url(room, event_id),
        json={"reason": "ทดสอบเก็บหลักฐาน"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_event_lines WHERE event_id = $1",
            event_id,
        )
    assert after == before


# ═══════════════════════════════════════════════════ 5. void ซ้ำ = 409 ไม่ใช่ 200 เงียบ
async def test_void_event_twice_conflicts_409(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    event_id = created.json()["event_id"]

    first = client.post(
        _event_void_url(room, event_id),
        json={"reason": "ยกเลิกครั้งแรก"}, headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        _event_void_url(room, event_id),
        json={"reason": "กดซ้ำ"}, headers=admin_headers,
    )
    assert second.status_code == 409, second.text
    assert "ถูกยกเลิกแล้ว" in second.json()["detail"]

    # ยอดต้องไม่ถูกหักสองรอบ
    assert _money(await _balance(db_pool, account)) == "0.00"


# ═══════════════════════════════════════ 6. เหตุผลว่าง/ช่องว่างล้วน = 400 และไม่มีอะไรเปลี่ยน
async def test_void_event_requires_reason(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    event_id = created.json()["event_id"]

    for reason in ("", "   ", "\n\t "):
        res = client.post(
            _event_void_url(room, event_id),
            json={"reason": reason}, headers=admin_headers,
        )
        assert res.status_code == 400, res.text
        assert "เหตุผล" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM finance_payment_events WHERE id = $1", event_id
        )
    assert status == "active"
    assert _money(await _balance(db_pool, account)) == "1000.00"


# ═══════════════════════════════════ 7. audit log เขียนใน transaction เดียวกัน (1 แถว success)
async def test_void_event_audit_log_in_transaction(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    event_id = created.json()["event_id"]

    res = client.post(
        _event_void_url(room, event_id),
        json={"reason": "ตรวจ audit"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT action, status, old_values, new_values, endpoint_or_command
               FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_PAYMENT_EVENT'
                 AND entity_id = $2 AND status = 'success'""",
            room, str(event_id),
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "UPDATE"
    assert row["endpoint_or_command"] == "POST /finance/payment-events/{event_id}/void"
    new_values = row["new_values"]
    if isinstance(new_values, str):
        import json
        new_values = json.loads(new_values)
    assert new_values["void_reason"] == "ตรวจ audit"
    assert new_values["status"] == "voided"
    assert float(new_values["amount_reversed"]) == 1000.0


# ═══════════════════ 8. PV 3 บรรทัด 2 กระเป๋า + CERT → คืนทุกกระเป๋า + void CERT/PV
async def test_void_pv_reverses_all_wallets_and_cert(client, db_pool, admin_headers):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน", "expense")
    wallet_a = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)
    wallet_b = await _insert_account(db_pool, room, "ธนาคารห้อง", 500.0)

    created = client.post(
        _vouchers_url(room),
        json=_voucher_payload(
            default_wallet_account_id=wallet_a,
            lines=[
                _voucher_line(250.0, category_id=cat, wallet_account_id=wallet_a,
                              receipt_status="none"),
                _voucher_line(100.0, category_id=cat, wallet_account_id=wallet_b,
                              receipt_status="attached"),
                _voucher_line(50.0, category_id=cat, wallet_account_id=wallet_a,
                              receipt_status="paper"),
            ],
        ),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    voucher_id = data["id"]
    assert data["cert_receipt_id"] is not None
    # CERT รับรองเฉพาะบรรทัดที่ไม่มีหลักฐาน (`none`) — บรรทัด `paper` ไม่เข้า CERT
    assert data["cert_line_nos"] == [1]

    assert _money(await _balance(db_pool, wallet_a)) == "200.00"
    assert _money(await _balance(db_pool, wallet_b)) == "400.00"

    res = client.post(
        _voucher_void_url(room, voucher_id),
        json={"reason": "ทำใบซ้ำ"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["doc_type"] == "expense_voucher"
    assert body["receipt_no"] == data["pv_receipt_no"]
    assert _money(body["reversed"]["amount"]) == "400.00"
    assert body["reversed"]["accounts"] == [
        {"account_id": wallet_a, "delta": 300.0},
        {"account_id": wallet_b, "delta": 100.0},
    ]

    assert _money(await _balance(db_pool, wallet_a)) == "500.00"
    assert _money(await _balance(db_pool, wallet_b)) == "500.00"

    async with db_pool.acquire() as conn:
        pv = await conn.fetchrow(
            "SELECT status, voided_at, deleted_at FROM finance_receipts WHERE id = $1",
            data["pv_receipt_id"],
        )
        cert = await conn.fetchrow(
            "SELECT status, voided_at, deleted_at, void_reason "
            "FROM finance_receipts WHERE id = $1",
            data["cert_receipt_id"],
        )
        voucher = await conn.fetchrow(
            "SELECT status, voided_at, voided_by, void_reason "
            "FROM finance_expense_vouchers WHERE id = $1",
            voucher_id,
        )
        journals = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND deleted_at IS NULL
                 AND metadata->>'expense_voucher_id' = $2""",
            room, str(voucher_id),
        )
        txns = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND expense_voucher_id = $2 AND deleted_at IS NULL""",
            room, voucher_id,
        )
    assert pv["status"] == "voided" and pv["deleted_at"] is not None
    assert cert["status"] == "voided" and cert["deleted_at"] is not None
    assert "ยกเลิกพร้อมใบสำคัญจ่าย" in cert["void_reason"]
    assert voucher["status"] == "voided"
    assert voucher["voided_by"] == admin_headers.user_id
    assert journals == 0
    assert txns == 0


# ═══════════════════════════════ 9. 2 บรรทัดกระเป๋าเดียวกัน → คืนยอดรวมครั้งเดียวถูกต้อง
async def test_void_pv_reverses_two_lines_same_wallet(client, db_pool, admin_headers):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "ค่าขนส่ง", "expense")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)

    created = client.post(
        _vouchers_url(room),
        json=_voucher_payload(
            default_wallet_account_id=wallet,
            lines=[
                _voucher_line(100.0, category_id=cat, wallet_account_id=wallet,
                              receipt_status="attached"),
                _voucher_line(150.0, category_id=cat, wallet_account_id=wallet,
                              receipt_status="attached"),
            ],
        ),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    voucher_id = created.json()["id"]
    assert _money(await _balance(db_pool, wallet)) == "250.00"

    res = client.post(
        _voucher_void_url(room, voucher_id),
        json={"reason": "ยกเลิกทั้งใบ"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["reversed"]["accounts"] == [
        {"account_id": wallet, "delta": 250.0},
    ]
    assert _money(await _balance(db_pool, wallet)) == "500.00"


# ═══════════════════════════════════ 10. INC → คืนกระเป๋า + void INC/transaction/journal
async def test_void_inc_reverses_wallet_and_batch(client, db_pool, admin_headers):
    room = admin_headers.room_id
    cat_a = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม", "income")
    cat_b = await _insert_category(db_pool, room, "ขายของที่ระลึก", "income")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    created = client.post(
        _batches_url(room),
        json=_income_payload(
            wallet_account_id=wallet,
            lines=[
                _income_line(2000.0, category_id=cat_a, description="เงินสนับสนุน"),
                _income_line(500.0, category_id=cat_b, description="ขายของที่ระลึก"),
            ],
        ),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    batch_id = data["id"]
    assert _money(await _balance(db_pool, wallet)) == "2500.00"

    res = client.post(
        _batch_void_url(room, batch_id),
        json={"reason": "บันทึกซ้ำ"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["receipt_no"] == data["inc_receipt_no"]
    assert _money(body["reversed"]["amount"]) == "2500.00"
    assert body["reversed"]["accounts"] == [
        {"account_id": wallet, "delta": -2500.0},
    ]

    assert _money(await _balance(db_pool, wallet)) == "0.00"

    async with db_pool.acquire() as conn:
        batch = await conn.fetchrow(
            "SELECT status, voided_at, void_reason FROM finance_income_batches "
            "WHERE id = $1", batch_id,
        )
        inc = await conn.fetchrow(
            "SELECT status, deleted_at, void_reason FROM finance_receipts WHERE id = $1",
            data["inc_receipt_id"],
        )
        txns = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND income_batch_id = $2 AND deleted_at IS NULL""",
            room, batch_id,
        )
        journals = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND deleted_at IS NULL
                 AND metadata->>'income_batch_id' = $2""",
            room, str(batch_id),
        )
    assert batch["status"] == "voided"
    assert batch["void_reason"] == "บันทึกซ้ำ"
    assert inc["status"] == "voided" and inc["deleted_at"] is not None
    assert txns == 0
    assert journals == 0


# ═══════════════════ 11. INV ที่ถูกอ้างโดยเอกสารอื่น (link/ACK) → 409 ไม่แตะเงิน
async def test_void_invoice_refused_when_linked_to_ack_409(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    invoice_id = await _insert_receipt_doc(
        db_pool, room, doc_type="invoice", seq=1, amount=500.0
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_document_links
                   (room_id, from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type)
               VALUES ($1, 'acknowledgement', 99, 'invoice', $2, 'invoice_for_ack')""",
            room, invoice_id,
        )

    res = client.post(
        _doc_void_url(room, "invoice", invoice_id),
        json={"reason": "ยกเลิกใบแจ้งหนี้"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "ถูกอ้างโดยเอกสารอื่น" in res.json()["detail"]

    row = await _receipt_row(db_pool, invoice_id)
    assert row["status"] == "active" and row["deleted_at"] is None


# ══════════════════════════════════════ 12. CERT ยกเลิกเดี่ยวไม่ได้ → 409 (ต้องไปกับ PV)
async def test_void_cert_alone_refused_409(client, db_pool, admin_headers):
    room = admin_headers.room_id
    res = client.post(
        _doc_void_url(room, "certificate", 1),
        json={"reason": "ลองยกเลิกเดี่ยว"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "ใบสำคัญจ่าย" in res.json()["detail"]


# ═══════════════ 13. REC/DEP ของ event ต้องยกเลิกผ่าน endpoint ของ event (ไม่ใช่เอกสาร)
async def test_void_receipt_with_event_points_to_event_endpoint_409(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=_event_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    event_id = created.json()["event_id"]
    receipt_id = await _event_receipt_id(db_pool, event_id)

    res = client.post(
        _doc_void_url(room, "receipt", receipt_id),
        json={"reason": "ลองยกเลิกใบเสร็จเดี่ยว"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert f"/finance/payment-events/{event_id}/void" in res.json()["detail"]

    row = await _receipt_row(db_pool, receipt_id)
    assert row["status"] == "active" and row["deleted_at"] is None


# ══════════════════════════════════════════════ 14. doc_type ที่ไม่รู้จัก → 400
async def test_void_unknown_doc_type_400(client, db_pool, admin_headers):
    room = admin_headers.room_id
    res = client.post(
        _doc_void_url(room, "banana", 1),
        json={"reason": "ทดสอบชนิดเอกสาร"}, headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert "ไม่รองรับ" in res.json()["detail"]


# ═══════════ 15. atomic — ล้มหลังหักกระเป๋าไปแล้ว ⇒ กระเป๋า/CERT/PV กลับสภาพเดิมทั้งหมด
async def test_void_is_atomic_on_failure(client, db_pool, admin_headers):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน", "expense")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)

    created = client.post(
        _vouchers_url(room),
        json=_voucher_payload(
            default_wallet_account_id=wallet,
            lines=[
                _voucher_line(200.0, category_id=cat, wallet_account_id=wallet,
                              receipt_status="none"),
            ],
        ),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    assert _money(await _balance(db_pool, wallet)) == "300.00"

    # 💥 ล้มหลังคืนกระเป๋า/soft-delete txn/journal แล้ว แต่ก่อน void เอกสาร
    with patch.object(
        FinanceService, "_void_receipt_ids_locked",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError):
            client.post(
                _voucher_void_url(room, data["id"]),
                json={"reason": "ทดสอบ atomic"}, headers=admin_headers,
            )

    # 🔄 ทั้งหมดต้องกลับสภาพก่อน void
    assert _money(await _balance(db_pool, wallet)) == "300.00"
    async with db_pool.acquire() as conn:
        voucher = await conn.fetchrow(
            "SELECT status, voided_at FROM finance_expense_vouchers WHERE id = $1",
            data["id"],
        )
        pv = await conn.fetchrow(
            "SELECT status, deleted_at FROM finance_receipts WHERE id = $1",
            data["pv_receipt_id"],
        )
        cert = await conn.fetchrow(
            "SELECT status, deleted_at FROM finance_receipts WHERE id = $1",
            data["cert_receipt_id"],
        )
        txns = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND expense_voucher_id = $2 AND deleted_at IS NULL""",
            room, data["id"],
        )
        journals = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND deleted_at IS NULL
                 AND metadata->>'expense_voucher_id' = $2""",
            room, str(data["id"]),
        )
    assert voucher["status"] == "active" and voucher["voided_at"] is None
    assert pv["status"] == "active" and pv["deleted_at"] is None
    assert cert["status"] == "active" and cert["deleted_at"] is None
    assert txns == 1
    assert journals >= 1

    # failure audit ถูกเขียนด้วย connection แยก (transaction หลัก rollback แล้ว)
    async with db_pool.acquire() as conn:
        failed = await conn.fetchval(
            """SELECT COUNT(*) FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_EXPENSE_VOUCHER'
                 AND entity_id = $2 AND status = 'failed'""",
            room, str(data["id"]),
        )
    assert failed == 1


# ═══════════════ 16. engine ทำงานกับ mixin จริง (กันผู้เรียกไปหาฟังก์ชันที่ไม่มี)
async def test_void_engine_methods_are_wired_into_finance_service():
    for name in (
        "void_payment_event", "void_expense_voucher",
        "void_income_batch", "void_document",
    ):
        method = getattr(FinanceService, name, None)
        assert callable(method), f"FinanceService ไม่มี `{name}` (mixin ไม่ถูก wire?)"

    # 🔎 ตรวจ source ระดับไฟล์ว่าผู้เรียกใช้ MRO ถูก — ไม่มี `_void_*_locked` ที่แย่งกัน
    src = inspect.getsource(FinanceService.void_expense_voucher)
    assert "cls._void_voucher_locked(" in src
