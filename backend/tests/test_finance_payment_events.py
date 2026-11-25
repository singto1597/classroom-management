"""🧾 [FIN-V2 / P2.1] รายการรับเงิน (payment event) — 1 ครั้งรับเงิน = 1 event

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **atomic ทั้งก้อน** — event + REC/DEP + journal + paid_amount ต้องเกิดหรือไม่เกิดพร้อมกัน
2. **REC 1 ใบต่อ event** (หลาย line_items) ไม่ใช่ 1 ใบต่อบิลอีกต่อไป
3. **เงินสดผ่าน `_confirm_single_payment` เท่านั้น · เครดิตผ่าน `_apply_plan_locked` เท่านั้น**
   ⇒ ไม่มีทางเดินบัญชีคู่ขนานที่ไม่มีใครปิดไว้
4. **idempotency** — กดซ้ำ/แข่งกันด้วยคีย์เดิมต้องได้ event เดิม ไม่ charge ซ้ำ
5. **สมการเงินถูกบังคับที่ DB** (`chk_event_balanced`) ไม่ใช่แค่ใน service
6. **RBAC** — MANAGE_FINANCE เท่านั้นถึงจะบันทึกรับเงินได้

⚠️ เงินทุกก้อน assert เป็น **สตริง 2 ตำแหน่ง** และอ่านกลับจาก Postgres ตรง ๆ ผ่าน `db_pool`

📝 เบี่ยงจาก brief 1 จุดโดยเจตนา: เคส "ปี พ.ศ. มาจาก event_at" ใช้
   `2024-12-31T17:00:00Z` (ไทย = 2025-01-01 → พ.ศ. 2568) แทนค่าอนาคตใน brief
   เพราะ service ปฏิเสธ `event_at` ที่เกิน CURRENT_TIMESTAMP + 1 วัน (ด่านกันพิมพ์ล่วงหน้า)
   ทั้งนี้ ณ วันเขียนเทสต์ (25 พ.ย. 2026) ค่าอนาคตใน brief ถูกปฏิเสธก่อนถึงขั้นออกเลข
"""
import asyncio
import json
import random
import string
import uuid
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from models.finance_schemas import PaymentEventCreate
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"


# ═══════════════════════════════════════════════════════════════════ helpers
def _events_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    """Decimal/float → สตริง 2 ตำแหน่ง (สไตล์เดียวกับ response ของ API)"""
    return f"{float(value):.2f}"


def _payload(
    student_id: int,
    account_id: int,
    *,
    key: str | None = None,
    cash: str = "0.00",
    use_credit: bool = False,
    excess_action: str = "credit",
    bill_selection: str = "auto",
    bill_ids: list[int] | None = None,
    payer_name: str = "ผู้ปกครองทดสอบ",
    receiver_name: str = RECEIVER,
    event_at: str | None = None,
    channel_id: int | None = None,
) -> dict:
    body = {
        "idempotency_key": key or _new_key(),
        "student_id": student_id,
        "wallet_account_id": account_id,
        "payer_name": payer_name,
        "receiver_name": receiver_name,
        "amount_received": cash,
        "use_credit": use_credit,
        "excess_action": excess_action,
        "bill_selection": bill_selection,
    }
    if bill_ids is not None:
        body["bill_ids"] = bill_ids
    if event_at is not None:
        body["event_at"] = event_at
    if channel_id is not None:
        body["channel_id"] = channel_id
    return body


async def _insert_student(pool, room_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, name,
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id)
               VALUES ('Other Room', $1, $2) RETURNING id""",
            code, owner_id,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *,
    title: str = "ค่าเทอม", amount: float = 1000.0,
    due_date=None, paid: float = 0.0, written_off: float = 0.0,
) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, $4, 'active', 'room_fund', 'project') RETURNING id""",
            room_id, title, amount, due_date,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', $3, $4) RETURNING id""",
            collection_id, student_id, paid, written_off,
        )


async def _insert_credit(pool, room_id: int, student_id: int, amount: float) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'topup', $3, $3)""",
            room_id, student_id, amount,
        )


async def _event_row(pool, event_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM finance_payment_events WHERE id = $1", event_id
        )


async def _event_count(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_events WHERE room_id = $1", room_id
        )


async def _documents(pool, event_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM finance_receipts
               WHERE payment_event_id = $1 AND deleted_at IS NULL
               ORDER BY id""",
            event_id,
        )


async def _event_lines(pool, event_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM finance_payment_event_lines WHERE event_id = $1 ORDER BY id",
            event_id,
        )


# ══════════════════════════════════════════════════════════ 1. บิลเดียวเต็มจำนวน
async def test_event_commits_single_bill_and_issues_one_receipt(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=1000.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["amount_received"] == "1000.00"
    assert data["total_applied"] == "1000.00"
    assert data["credit_used"] == "0.00"
    assert data["credit_added"] == "0.00"
    assert data["receipt_no"] and data["receipt_no"].startswith("REC-")
    assert data["deposit_no"] is None
    assert data["reused"] is False

    event = await _event_row(db_pool, data["event_id"])
    assert _money(event["amount_received"]) == "1000.00"
    assert _money(event["total_applied"]) == "1000.00"
    assert event["excess_action"] == "none"
    assert event["status"] == "active"

    docs = await _documents(db_pool, data["event_id"])
    assert len(docs) == 1
    rec = docs[0]
    assert rec["doc_type"] == "receipt"
    assert rec["layout_version"] == 2
    assert rec["student_payment_id"] is None     # 🔑 ใบระดับ event ไม่ผูกบิลเดียว
    assert rec["payment_event_id"] == data["event_id"]
    assert _money(rec["amount"]) == "1000.00"
    assert rec["event_at"] is not None

    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill
        )
    assert sp["status"] == "paid"
    assert _money(sp["paid_amount"]) == "1000.00"


# ══════════════════════════════════════════════════════════ 2. หลายบิล 1 ใบเสร็จ
async def test_event_pays_multiple_bills_with_one_receipt(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill_a = await _insert_bill(db_pool, room, student, title="ค่าเทอม", amount=500.0)
    bill_b = await _insert_bill(db_pool, room, student, title="ค่ากิจกรรม", amount=700.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="1200.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_applied"] == "1200.00"
    assert len(data["allocations"]) == 2
    assert data["receipt_no"] and data["deposit_no"] is None

    docs = await _documents(db_pool, data["event_id"])
    assert len(docs) == 1
    line_items = docs[0]["line_items"]
    if isinstance(line_items, str):
        line_items = json.loads(line_items)
    assert len(line_items) == 2
    assert sum(float(li["amount_applied"]) for li in line_items) == 1200.0
    assert {li["student_payment_id"] for li in line_items} == {bill_a, bill_b}

    async with db_pool.acquire() as conn:
        tx_count = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND payment_event_id = $2""",
            room, data["event_id"],
        )
        journal = await conn.fetchrow(
            """SELECT COALESCE(SUM(L.debit),0) AS d, COALESCE(SUM(L.credit),0) AS c
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               WHERE JE.room_id = $1""",
            room,
        )
    assert tx_count == 2
    assert float(journal["d"]) == 1200.0
    assert float(journal["c"]) == 1200.0


# ═══════════════════════════════════════════════════════ 3. เงินสด + เครดิตบิลเดียว
async def test_event_uses_credit_and_cash_on_same_bill(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=500.0)
    await _insert_credit(db_pool, room, student, 300.0)

    resp = client.post(
        _events_url(room),
        json=_payload(
            student, account, cash="200.00", use_credit=True,
        ),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["amount_received"] == "200.00"
    assert data["credit_used"] == "300.00"
    assert data["total_applied"] == "500.00"
    assert data["credit_added"] == "0.00"
    assert len(data["allocations"]) == 2
    assert {a["source"] for a in data["allocations"]} == {"cash", "credit"}

    lines = await _event_lines(db_pool, data["event_id"])
    kinds = [ln["line_kind"] for ln in lines]
    # 🔑 index ของ P1.1 ต้องมี predicate line_kind='bill' ไม่งั้นบรรทัดที่ 2 ชน unique
    assert sorted(kinds) == ["bill", "credit_apply"]
    assert all(ln["student_payment_id"] == bill for ln in lines)

    docs = await _documents(db_pool, data["event_id"])
    assert len(docs) == 1
    assert _money(docs[0]["amount"]) == "500.00"


# ═══════════════════════════════════════════════════ 4. จ่ายเกิน → เครดิต + DEP
async def test_event_overpay_creates_credit_and_deposit(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=500.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="1000.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["credit_added"] == "500.00"
    assert data["total_applied"] == "500.00"
    assert data["receipt_no"].startswith("REC-")
    assert data["deposit_no"] and data["deposit_no"].startswith("DEP-")

    docs = {d["doc_type"]: d for d in (await _documents(db_pool, data["event_id"]))}
    assert set(docs) == {"receipt", "deposit"}

    async with db_pool.acquire() as conn:
        credit = await conn.fetchrow(
            """SELECT amount, balance_after, payment_event_id FROM student_credits
               WHERE room_id = $1 AND student_id = $2 AND entry_type = 'topup'
               ORDER BY id DESC LIMIT 1""",
            room, student,
        )
        link = await conn.fetchrow(
            """SELECT 1 FROM finance_document_links
               WHERE room_id = $1 AND link_type = 'receipt_for_deposit'""",
            room,
        )
    assert _money(credit["amount"]) == "500.00"
    assert _money(credit["balance_after"]) == "500.00"
    assert credit["payment_event_id"] == data["event_id"]
    assert link is not None

    event = await _event_row(db_pool, data["event_id"])
    assert event["excess_action"] == "credit"


# ═════════════════════════════════════════════════════════ 5. เครดิตล้วน (ไม่มี REC)
async def test_event_credit_only_has_no_cash_transaction(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=500.0)
    await _insert_credit(db_pool, room, student, 500.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="0.00", use_credit=True),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["amount_received"] == "0.00"
    assert data["credit_used"] == "500.00"
    assert data["total_applied"] == "500.00"
    # 🔴 เครดิตไม่ใช่ "ครั้งรับเงิน" ⇒ ไม่มีใบเสร็จ
    assert data["receipt_no"] is None
    assert data["deposit_no"] is None

    async with db_pool.acquire() as conn:
        tx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room
        )
        sp = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill
        )
    assert tx_count == 0
    assert sp["status"] == "paid"
    assert _money(sp["paid_amount"]) == "500.00"

    lines = await _event_lines(db_pool, data["event_id"])
    assert [ln["line_kind"] for ln in lines] == ["credit_apply"]
    assert lines[0]["finance_transaction_id"] is None
    assert lines[0]["credit_entry_id"] is not None


# ════════════════════════════════════════════════ 6. เติมเครดิตล้วน → DEP อย่างเดียว
async def test_event_pure_topup_has_deposit_but_no_receipt(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="300.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["amount_received"] == "300.00"
    assert data["total_applied"] == "0.00"
    assert data["credit_added"] == "300.00"
    assert data["allocations"] == []
    assert data["receipt_no"] is None
    assert data["deposit_no"] and data["deposit_no"].startswith("DEP-")

    docs = await _documents(db_pool, data["event_id"])
    assert [d["doc_type"] for d in docs] == ["deposit"]

    lines = await _event_lines(db_pool, data["event_id"])
    assert [ln["line_kind"] for ln in lines] == ["credit_topup"]

    async with db_pool.acquire() as conn:
        credit = await conn.fetchrow(
            """SELECT amount, balance_after, payment_event_id FROM student_credits
               WHERE room_id = $1 AND student_id = $2 ORDER BY id DESC LIMIT 1""",
            room, student,
        )
        # 🔴 เงินรับล่วงหน้าต้องไม่ถูกนับเป็นรายรับ
        category = await conn.fetchval(
            """SELECT category_id FROM finance_transactions
               WHERE room_id = $1 AND payment_event_id = $2""",
            room, data["event_id"],
        )
    assert _money(credit["balance_after"]) == "300.00"
    assert credit["payment_event_id"] == data["event_id"]
    assert category is None


# ══════════════════════════════════════════════ 7. DB บังคับสมการ (CHECK constraint)
async def test_equation_is_enforced_by_db(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=100.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="100.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["event_id"]

    with pytest.raises(asyncpg.CheckViolationError):
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE finance_payment_events
                   SET total_applied = total_applied + 1 WHERE id = $1""",
                event_id,
            )

    # แถวยังเป็นค่าเดิม — ไม่มีอะไรถูกเขียนครึ่ง ๆ กลาง ๆ
    event = await _event_row(db_pool, event_id)
    assert _money(event["total_applied"]) == "100.00"


# ═══════════════════════════════════════════════════════════ 8. ยิงซ้ำ → event เดิม
async def test_idempotent_replay_returns_same_documents(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=500.0)

    # ให้ห้องผูก Discord เพื่อพิสูจน์ว่า replay **ไม่** notify ซ้ำ
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE rooms SET server_id = $1 WHERE id = $2",
            random.randint(1_000_000, 9_999_999), room,
        )

    key = _new_key()
    payload = _payload(student, account, key=key, cash="1000.00")

    with patch(
        "services.finance.payment_events.ActionService.notify_payments_confirmed",
        new_callable=AsyncMock,
    ) as notify:
        first = client.post(_events_url(room), json=payload, headers=admin_headers)
        second = client.post(_events_url(room), json=payload, headers=admin_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["event_id"] == second.json()["event_id"]
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert second.json()["receipt_no"] == first.json()["receipt_no"]
    assert second.json()["deposit_no"] == first.json()["deposit_no"]

    assert await _event_count(db_pool, room) == 1
    docs = await _documents(db_pool, first.json()["event_id"])
    assert sorted(d["doc_type"] for d in docs) == ["deposit", "receipt"]
    assert notify.await_count == 1


# ═══════════════════════════════════════════ 9. คีย์เดิม payload ต่าง → คืนของเดิม
async def test_duplicate_idempotency_key_different_payload_returns_original(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=500.0)

    key = _new_key()
    first = client.post(
        _events_url(room),
        json=_payload(student, account, key=key, cash="500.00"),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    # ⚠️ เจตนายิงยอดต่างด้วยคีย์เดิม — ระบบต้องไม่สร้าง event ที่สอง
    second = client.post(
        _events_url(room),
        json=_payload(student, account, key=key, cash="1000.00"),
        headers=admin_headers,
    )
    assert second.status_code == 200, second.text

    assert second.json()["event_id"] == first.json()["event_id"]
    assert second.json()["amount_received"] == "500.00"
    assert second.json()["reused"] is True
    assert await _event_count(db_pool, room) == 1


# ═══════════════════════════════════════════════════ 10. เลือกบิลเอง (ไม่แตะบิลอื่น)
async def test_manual_bill_selection_does_not_touch_other_bills(
    client, db_pool, admin_headers,
):
    from datetime import date

    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill_a = await _insert_bill(
        db_pool, room, student, title="ค่าเทอม", amount=500.0,
        due_date=date(2026, 1, 10),
    )
    bill_b = await _insert_bill(
        db_pool, room, student, title="ค่ากิจกรรม", amount=700.0,
        due_date=date(2026, 2, 10),
    )

    resp = client.post(
        _events_url(room),
        json=_payload(
            student, account, cash="500.00",
            bill_selection="manual", bill_ids=[bill_a],
        ),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["allocations"]) == 1
    assert data["allocations"][0]["student_payment_id"] == bill_a

    async with db_pool.acquire() as conn:
        a = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill_a
        )
        b = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill_b
        )
    assert a["status"] == "paid"
    assert _money(a["paid_amount"]) == "500.00"
    assert b["status"] == "pending"
    assert _money(b["paid_amount"]) == "0.00"


# ═════════════════════════════════════ 11. บิลคนอื่น (409) / กระเป๋าห้องอื่น (404)
async def test_event_rejects_bill_from_other_student(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    other_student = await _insert_student(db_pool, room, student_no=2)
    foreign_bill = await _insert_bill(db_pool, room, other_student, amount=500.0)

    resp = client.post(
        _events_url(room),
        json=_payload(
            student, account, cash="500.00",
            bill_selection="manual", bill_ids=[foreign_bill],
        ),
        headers=admin_headers,
    )
    assert resp.status_code in (400, 409), resp.text
    assert await _event_count(db_pool, room) == 0


async def test_event_rejects_account_from_other_room(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    await _insert_bill(db_pool, room, student, amount=500.0)
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    foreign_account = await _insert_account(db_pool, other_room)

    resp = client.post(
        _events_url(room),
        json=_payload(student, foreign_account, cash="500.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 404, resp.text
    assert await _event_count(db_pool, room) == 0


# ═══════════════════════════════════════════════════════════ 12. RBAC — MANAGE_FINANCE
async def test_event_requires_manage_finance(
    client, db_pool, member_headers,
):
    room, student = member_headers.room_id, member_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=500.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="500.00"),
        headers=member_headers,
    )
    assert resp.status_code == 403, resp.text
    assert await _event_count(db_pool, room) == 0


# ═══════════════════════════════════════════════ 13. ปี พ.ศ. ของเลข Comes From event_at
async def test_receipt_number_year_from_event_at(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=100.0)

    # 2024-12-31 17:00Z = 2025-01-01 00:00 เวลาไทย ⇒ พ.ศ. 2568
    # (เลี่ยงค่าอนาคตใน brief เพราะ service กัน event_at เกิน CURRENT_TIMESTAMP + 1 วัน)
    resp = client.post(
        _events_url(room),
        json=_payload(
            student, account, cash="100.00",
            event_at="2024-12-31T17:00:00Z",
        ),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["receipt_no"].startswith("REC-2568-"), data["receipt_no"]
    docs = await _documents(db_pool, data["event_id"])
    assert docs[0]["year_be"] == 2568


# ═════════════════════════════════════════════════ 14. แจ้งเตือนครั้งเดียวทุกบิล
async def test_notify_called_once_with_all_bills(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, title="ค่าเทอม", amount=500.0)
    await _insert_bill(db_pool, room, student, title="ค่ากิจกรรม", amount=700.0)

    async with db_pool.acquire() as conn:
        server_id = random.randint(1_000_000, 9_999_999)
        await conn.execute(
            "UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, room
        )

    with patch(
        "services.finance.payment_events.ActionService.notify_payments_confirmed",
        new_callable=AsyncMock,
    ) as notify:
        resp = client.post(
            _events_url(room),
            json=_payload(student, account, cash="1200.00"),
            headers=admin_headers,
        )

    assert resp.status_code == 200, resp.text
    assert notify.await_count == 1
    kwargs = notify.await_args.kwargs
    assert kwargs["server_id"] == server_id
    assert kwargs["total_amount"] == 1200.0
    assert sorted(item["amount"] for item in kwargs["items"]) == [500.0, 700.0]
    assert kwargs["receipt_nos"] == [resp.json()["receipt_no"]]


# ═══════════════════════════════════════════════ 15. ยิงพร้อมกัน → ไม่ charge ซ้ำ
async def test_concurrent_duplicate_does_not_double_charge(db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=500.0)

    req = PaymentEventCreate(
        **_payload(student, account, key=_new_key(), cash="500.00")
    )

    async def fire():
        return await FinanceService.create_payment_event(
            pool=db_pool, room_id=room, req=req,
            user_id=admin_headers.user_id,
            client_source="web", actor_identifier="test",
        )

    results = await asyncio.gather(fire(), fire())

    assert await _event_count(db_pool, room) == 1
    assert sorted(r["reused"] for r in results) == [False, True]
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill
        )
    assert sp["status"] == "paid"
    assert _money(sp["paid_amount"]) == "500.00"   # บวกครั้งเดียว ไม่ใช่ 1000

    docs = await _documents(db_pool, results[0]["event_id"])
    assert [d["doc_type"] for d in docs] == ["receipt"]
    assert len(docs) == 1


# ═══════════════════════════════════════════════════════ 16. journal สมดุลทั้ง event
async def test_journal_is_balanced_for_event(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=500.0)
    await _insert_bill(db_pool, room, student, amount=700.0)

    resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="1200.00"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    async with db_pool.acquire() as conn:
        totals = await conn.fetchrow(
            """SELECT COALESCE(SUM(L.debit), 0) AS debit,
                      COALESCE(SUM(L.credit), 0) AS credit
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               WHERE JE.room_id = $1 AND JE.status = 'posted'""",
            room,
        )
        entries = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room
        )
    # 1 journal ต่อ 1 บิลที่รับเงินสด (helper นี้ไม่ออก accrual ตอนสร้างบิล)
    assert entries == 2
    assert float(totals["debit"]) == 1200.0
    assert float(totals["credit"]) == 1200.0


# ═════════════════════════════════════════════════════ 17. อ่านกลับ: detail + list
async def test_get_and_list_payment_events(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill = await _insert_bill(db_pool, room, student, amount=500.0)

    created = client.post(
        _events_url(room),
        json=_payload(student, account, cash="500.00"),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    event_id = created.json()["event_id"]

    detail = client.get(
        f"{_events_url(room)}/{event_id}", headers=admin_headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["event_id"] == event_id
    assert body["student_id"] == student
    assert body["payer_name"] == "ผู้ปกครองทดสอบ"
    assert body["receiver_name"] == RECEIVER
    assert body["lines"][0]["line_kind"] == "bill"
    assert body["lines"][0]["student_payment_id"] == bill

    listing = client.get(
        _events_url(room), params={"student_id": student}, headers=admin_headers
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["event_id"] == event_id
    assert items[0]["amount_received"] == "500.00"

    # กรองด้วยชื่อผู้จ่าย (ILIKE) — เจอเฉพาะที่ตรง
    miss = client.get(
        _events_url(room), params={"q": "ไม่มีใครชื่อนี้"}, headers=admin_headers
    )
    assert miss.status_code == 200
    assert miss.json()["items"] == []

    # event ที่ไม่มีอยู่ → 404
    missing = client.get(f"{_events_url(room)}/999999", headers=admin_headers)
    assert missing.status_code == 404
