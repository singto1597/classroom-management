"""[F4] เงินรับล่วงหน้า / เครดิตคงเหลือรายนักเรียน — student_credits + ใบ DEP

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **เงินรับล่วงหน้าไม่ใช่รายได้** — เงินที่รับมาก่อนจะมีบิล ต้องพักเป็น **หนี้สิน**
   (ledger `2099`) ไม่ใช่ revenue ถ้าขา "เงินพัก" กลายเป็นรายได้ ยอดจะดูปกติทุกหน้าจอ
   (บัญชีคู่ยัง Dr = Cr ครบ) แต่ **กำไรจะพองทันทีที่รับเงิน** แล้วพองซ้ำอีกครั้งตอนหักบิล

2. **รายได้เกิดตอนหักบิล ครั้งเดียว** — เติม 1000 → หัก 500 ⇒ revenue = 500 (ไม่ใช่ 1000
   และไม่ใช่ 0) และหนี้สินลดลงเท่ากัน ⇒ พิสูจน์ว่าไม่ double count และไม่หาย

3. **การหักไม่เขียน `finance_transactions`** — เงินไม่ได้เคลื่อนไหวตอนหัก (เข้ามาตั้งแต่
   ตอนเติม) ⇒ ตาราง "เงินเคลื่อนไหว" ต้องไม่มีแถวปลอม **และ** ยอดใน `GET /finance/summary`
   ต้องไม่เพิ่มเป็นสองเท่า (เทสต์คู่: นับแถว + เทียบยอด)

4. **`budgets.py` เห็นรายได้จากการหัก** — งบหลัง CUTOFF อ่าน journal **ตาม
   `reference_type`** ⇒ ถ้าลืมเติม `'student_credit_apply'` เข้า filter ยอดจะหายเงียบ
   (ต่ำกว่าจริงโดยไม่มีอะไรฟ้อง) ← เทสต์นี้ **ล้มถ้าลืมแก้ budgets.py**

5. **กันกดซ้ำ** — การเติมเครดิตสร้าง transaction ใหม่ทุกครั้ง ⇒
   `idx_finance_receipts_deposit_active` กันให้ไม่ได้ (คนละ transaction) ต้องพึ่ง
   `idempotency_key` จาก client ⇒ เทสต์กดซ้ำด้วยคีย์เดิมต้องได้ผลเดิม ไม่ใช่เงินเข้า 2 รอบ

6. **เอกสาร DEP** — ตัวนับเลขแยกจากใบเสร็จ/ใบแจ้งหนี้, ทะเบียนกรอง `doc_type=deposit`
   ได้ (ไม่ 422), ชื่อไฟล์ PDF ไม่โกหก, และ revert แล้วใบต้องเป็น voided **คู่กับ**
   `deleted_at` (บังคับด้วย `chk_receipt_voided_is_deleted`)

7. **ด่าน RBAC เขียนจริง** — สมาชิกอ่านได้ (โปร่งใสเหมือนหน้าลูกหนี้) แต่เขียนไม่ได้ และ
   **ต้องไม่มีแถวถูกเขียน** (ไม่ใช่แค่ได้ status 403)

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (กฎ docs/rules/testing.md)
⚠️ ห้าม hardcode id — ทุกอย่างมาจาก fixture/seed ของเทสต์ตัวเอง
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from services.finance.constants import (
    ADVANCE_LIABILITY_CODE, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_REVERSE, CREDIT_ENTRY_TOPUP,
    DEFAULT_INCOME_CATEGORIES, DOC_TYPE_DEPOSIT, REFERENCE_TYPE_CREDIT_APPLY,
    REFERENCE_TYPE_CREDIT_TOPUP,
)
from services.finance.pdf import pdf_filename
from services.finance.receipts import DOC_TYPE_RECEIPT, ReceiptsMixin

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
CREDITS_PATH = API_PREFIX + "/{room}/finance/credits"
PLAN_PATH = API_PREFIX + "/{room}/finance/credits/plan"
STUDENT_CREDIT_PATH = API_PREFIX + "/{room}/finance/credits/{student_id}"
APPLY_PATH = API_PREFIX + "/{room}/finance/credits/apply"
UNDO_PATH = API_PREFIX + "/{room}/finance/credits/undo"
DEBTORS_PATH = API_PREFIX + "/{room}/finance/debtors"
SUMMARY_PATH = API_PREFIX + "/{room}/finance/summary"
BALANCE_SHEET_PATH = API_PREFIX + "/{room}/finance/balance-sheet"
BUDGETS_PATH = API_PREFIX + "/{room}/finance/budgets"
BUDGET_OVERVIEW_PATH = API_PREFIX + "/{room}/finance/budgets/overview"
RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipts"
TRANSACTIONS_PATH = API_PREFIX + "/{room}/finance/transactions"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"


def _url(template: str, room_id: int, **kwargs) -> str:
    """สร้าง URL ของ finance API — web ต้องส่ง `target_type=room` เสมอ (default คือ server)"""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


def _key() -> str:
    """คีย์กันบันทึกซ้ำ — ฝั่ง client สร้างใหม่ต่อการกดหนึ่งครั้ง (UUID)"""
    return uuid.uuid4().hex


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, balance,
        )


async def _make_debtor(pool, room_id: int, *, student_no: int = 90,
                       first_name: str = "เด็กชายทดสอบ") -> int:
    """สร้าง user + students row สำหรับเป็น "เจ้าของเครดิต" (คนละคนกับผู้ออกเอกสาร)

    ⚠️ `student_no` ต้องไม่ชนกับคนอื่นในห้อง — conftest จองเลข 1 ไว้แล้ว
    """
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "ทดลอง", f"u{uuid.uuid4().hex[:12]}",
        )
        student_id = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )
    return student_id


async def _make_bill(pool, room_id: int, student_id: int, *,
                     title: str = "ค่าเทอม", amount: float = 1000.0,
                     paid_amount: float = 0.0, due_date: date = date(2026, 12, 31)) -> tuple:
    """สร้าง fee_collections + student_payments (บิลตั้งต้น) → (collection_id, payment_id)"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, due_date,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            collection_id, student_id, "paid" if paid_amount > 0 else "pending", paid_amount,
        )
    return collection_id, payment_id


async def _seed_income_category(pool, room_id: int) -> int:
    """สร้างหมวดรายได้ '📥 เก็บเงินห้องปกติ' ก่อน — เพื่อให้ revenue ledger ผูกกับ "หมวด"

    🔴 จำเป็นสำหรับเทสต์งบประมาณ: `budgets.py` clause (ข) join ด้วย
       `AL.legacy_category_id = B.category_id` ⇒ ถ้า ledger ไม่ผูกหมวด งบจะไม่มีทางเห็น
       รายได้ก้อนนั้นเลย **ทั้งที่โค้ดถูก** (และเทสต์จะฟ้องผิดคน)
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, 'income') RETURNING id""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _top_up(client, headers, student_id: int, account_id: int, amount: float, *,
            key: str = None, note: str = None, room_id: int = None):
    body = {
        "student_id": student_id,
        "amount": amount,
        "paid_to_account_id": account_id,
        "idempotency_key": key or _key(),
        "user_name": "Tester",
    }
    if note is not None:
        body["note"] = note
    return client.post(
        _url(CREDITS_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _plan(client, headers, student_ids, room_id: int = None):
    qs = "&".join(f"student_ids={int(s)}" for s in student_ids)
    return client.get(
        _url(PLAN_PATH, room_id if room_id is not None else headers.room_id) + "&" + qs,
        headers=headers,
    )


def _apply(client, headers, student_ids, room_id: int = None):
    return client.post(
        _url(APPLY_PATH, room_id if room_id is not None else headers.room_id),
        json={"student_ids": [int(s) for s in student_ids], "user_name": "Tester"},
        headers=headers,
    )


def _undo(client, headers, credit_entry_id: int, *, reason: str = None, room_id: int = None):
    body = {"credit_entry_id": credit_entry_id, "user_name": "Tester"}
    if reason is not None:
        body["reason"] = reason
    return client.post(
        _url(UNDO_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _list_credits(client, headers):
    return client.get(_url(CREDITS_PATH, headers.room_id), headers=headers)


def _student_credit(client, headers, student_id: int):
    return client.get(_url(STUDENT_CREDIT_PATH, headers.room_id, student_id=student_id), headers=headers)


def _revert(client, headers, transaction_id: int):
    """⚠️ ต้องใช้ `client.request("DELETE", ...)` — `TestClient.delete()` ของ httpx
    **ไม่รับ** คีย์เวิร์ด `json=` (จะได้ `TypeError` ทันที ไม่ใช่ 4xx) ⇒ ใช้ `.delete()`
    พร้อม body ไม่ได้เลย ต้องผ่าน `request()` เท่านั้น"""
    return client.request(
        "DELETE",
        _url(TRANSACTION_PATH, headers.room_id, tx_id=transaction_id),
        json={"user_name": "Tester"}, headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _ledger_net(pool, room_id: int, account_type: str) -> float:
    """ยอดสุทธิ (credit − debit) ของ ledger ทุกตัวประเภทนั้น — เฉพาะ journal ที่ยังไม่ถูก void

    ⚠️ เงื่อนไข `deleted_at IS NULL AND status <> 'voided'` ต้องตรงกับที่รายงานใช้
       (ไม่งั้นเทสต์จะเห็นยอดที่ผู้ใช้ไม่เห็น แล้วกลายเป็นเทสต์ที่ "ผ่าน" ทั้งที่ระบบผิด)
    """
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.credit - L.debit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, account_type,
        )
    return round(float(val), 2)


async def _revenue_net(pool, room_id: int) -> float:
    return await _ledger_net(pool, room_id, "revenue")


async def _liability_net(pool, room_id: int) -> float:
    return await _ledger_net(pool, room_id, "liability")


async def _asset_net(pool, room_id: int) -> float:
    """ยอดสุทธิของสินทรัพย์ — **debit-normal** ⇒ ต้องเป็น `SUM(debit − credit)`

    ⚠️ กลับทางกับ `_liability_net`/`_revenue_net` (credit-normal) โดยเจตนา — ถ้าใช้
       `credit − debit` กับสินทรัพย์จะได้ **ค่าติดลบ** แล้วเทสต์จะล้มด้วยข้อความที่
       ชี้ผิดที่ (`-1000.0 != 1000.0` อ่านเหมือนบัญชีผิด ทั้งที่ helper กลับขา)
    """
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = 'asset'
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id,
        )
    return round(float(val), 2)


async def _advance_ledger(pool, room_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, account_code, account_name, account_type, legacy_account_id
               FROM accounting_ledgers
               WHERE room_id = $1 AND account_code = $2""",
            room_id, ADVANCE_LIABILITY_CODE,
        )


async def _credit_entries(pool, room_id: int, student_id: int) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, entry_type, amount, balance_after, finance_transaction_id,
                      student_payment_id, collection_id, journal_entry_id,
                      idempotency_key, deleted_at
               FROM student_credits
               WHERE room_id = $1 AND student_id = $2 AND deleted_at IS NULL
               ORDER BY id""",
            room_id, student_id,
        )
        return [dict(r) for r in rows]


async def _count(pool, table: str, where: str = "TRUE", *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE {where}", *args)


async def _receipts(pool, room_id: int, doc_type: str = DOC_TYPE_DEPOSIT) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, receipt_no, doc_type, year_be, seq, legacy_transaction_id,
                      student_payment_id, collection_id, amount, paid_total_after,
                      event_at, status, voided_at, deleted_at
               FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 ORDER BY id""",
            room_id, doc_type,
        )
        return [dict(r) for r in rows]


async def _bill_row(pool, payment_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT SP.id, SP.paid_amount, SP.status, SP.paid_at, SP.recorded_by,
                      SP.paid_to_account_id, SP.transaction_id,
                      FC.amount AS total_amount, FC.title
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               WHERE SP.id = $1""",
            payment_id,
        )
        return dict(row) if row else {}


# ══════════════════════════════════════════════════════════════════════════════
# 1. หัวใจทางบัญชี: เงินพัก = หนี้สิน, รายได้เกิดตอนหัก
# ══════════════════════════════════════════════════════════════════════════════
async def test_top_up_is_a_liability_and_never_revenue(client, db_pool, admin_headers):
    """เติมเครดิต 1000 ⇒ สินทรัพย์ +1000, **หนี้สิน +1000**, รายได้ **+0**

    🎯 ถ้าขา "เงินพัก" เผลอไปผูก revenue ledger (เช่นใช้ `_resolve_category_ledger` ผิดขา)
       เทสต์นี้ล้มทันที — และเป็นบั๊กที่หน้าจอทุกหน้าดูปกติ (Dr = Cr ยังครบ)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)

    assert await _revenue_net(db_pool, room_id) == 0.0
    assert await _liability_net(db_pool, room_id) == 0.0

    res = _top_up(client, admin_headers, student_id, account_id, 1000.0)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["amount"] == 1000.0
    assert body["balance_after"] == 1000.0
    assert body["reused"] is False
    assert body["receipt"]["receipt_no"].startswith("DEP-")

    # 💰 บัญชีถูกต้อง
    assert await _asset_net(db_pool, room_id) == 1000.0
    assert await _liability_net(db_pool, room_id) == 1000.0
    assert await _revenue_net(db_pool, room_id) == 0.0, "เงินรับล่วงหน้าต้องไม่ใช่รายได้"

    # 🏦 ledger หนี้สินต้องเป็น 2099 จริง และ **ไม่** ผูก legacy_account_id
    #    (ถ้าผูก จะโผล่ใน `_scan_account_diffs` แล้วสร้าง diff ปลอมให้ reconcile)
    adv = await _advance_ledger(db_pool, room_id)
    assert adv is not None
    assert adv["account_type"] == "liability"
    assert adv["legacy_account_id"] is None

    # 📝 แถว legacy mirror ต้องมี แต่ **category_id ต้องเป็น NULL**
    #    ถ้าใส่หมวดรายได้ลงไป `budgets.py` clause (ก) จะนับเงินรับล่วงหน้าเป็น
    #    "รายรับของงบ" ทันทีที่รับเงิน = รายได้เกิดสองรอบ
    async with db_pool.acquire() as conn:
        tx = await conn.fetchrow(
            "SELECT id, category_id, transaction_type, amount FROM finance_transactions WHERE room_id = $1",
            room_id,
        )
    assert tx is not None and tx["transaction_type"] == "income"
    assert tx["category_id"] is None, "เงินรับล่วงหน้าต้องไม่ผูกหมวดรายได้ (§4.1 ของแผน)"

    # 📊 งบดุลยังสมดุล และ Net Worth เพิ่มเท่ายอดที่รับ (ไม่มากกว่า)
    bs = client.get(_url(BALANCE_SHEET_PATH, room_id), headers=admin_headers).json()
    assert bs["liability_total"] == 1000.0
    assert bs["assets_total"] == 1000.0
    assert bs["is_balanced"] is True

    summary = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()
    assert summary["total_income"] == 0.0, "รับเงินล่วงหน้ายังไม่ใช่รายได้ของงวด"
    assert summary["net_worth"] == 1000.0


async def test_revenue_arises_once_when_credit_is_applied(client, db_pool, admin_headers):
    """เติม 1000 → หักปิดบิล → revenue = ยอดที่หัก **ครั้งเดียว**, หนี้สินลดลงเท่ากัน"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=700.0)

    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200

    res = _apply(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total_applied"] == 700.0
    assert body["bills_paid"] == 1
    assert body["total_balance_after"] == 300.0
    assert len(body["items"]) == 1
    assert body["items"][0]["allocations"][0]["payment_id"] == payment_id

    # 💵 บัญชี: หนี้สิน 1000 − 700 = 300, รายได้ +700 (และไม่ใช่ 1400)
    assert await _liability_net(db_pool, room_id) == 300.0
    assert await _revenue_net(db_pool, room_id) == 700.0
    assert await _asset_net(db_pool, room_id) == 1000.0, "การหักเครดิตไม่ทำให้เงินในกระเป๋าเปลี่ยน"

    # 🧾 บิลถูกปิดจริง
    bill = await _bill_row(db_pool, payment_id)
    assert round(float(bill["paid_amount"]), 2) == 700.0
    assert bill["status"] == "paid"
    # 🚫 `paid_to_account_id`/`transaction_id` = NULL โดยเจตนา (เงินไม่ได้เข้าจากกระเป๋าตอนหัก)
    assert bill["paid_to_account_id"] is None
    assert bill["transaction_id"] is None

    # 📒 ledger แถว 'apply' มี journal ผูก และ **ไม่มี** finance_transaction
    entries = await _credit_entries(db_pool, room_id, student_id)
    assert [e["entry_type"] for e in entries] == [CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_APPLY]
    assert entries[1]["student_payment_id"] == payment_id
    assert entries[1]["journal_entry_id"] is not None
    assert entries[1]["finance_transaction_id"] is None

    # 📊 งบดุล: สินทรัพย์ 1000 = หนี้สิน 300 + ส่วนของเจ้าของ 700
    bs = client.get(_url(BALANCE_SHEET_PATH, room_id), headers=admin_headers).json()
    assert bs["assets_total"] == 1000.0
    assert bs["liability_total"] == 300.0
    assert bs["is_balanced"] is True

    # 📈 summary: รายได้เกิดครั้งเดียว (ไม่ใช่ 1700 = เติม + หัก)
    summary = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()
    assert summary["total_income"] == 700.0
    assert summary["net_worth"] == 1000.0


async def test_apply_writes_no_transaction_and_does_not_double_count(
    client, db_pool, admin_headers
):
    """การหักต้อง **ไม่** เพิ่มแถวใน `finance_transactions` และไม่ทำให้ยอด summary พอง

    🎯 ตรวจสองด้านคู่กันเพื่อไม่ให้ "ผ่านเพราะยอดหาย":
       (ก) จำนวนแถวเท่าเดิม ⇒ ไม่มีแถวปลอม
       (ข) ยอดรายได้ **เพิ่มขึ้นจริงเท่ายอดที่หัก** ⇒ ไม่ได้หายไปเหมือนกัน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=400.0)

    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200
    tx_before = await _count(db_pool, "finance_transactions", "room_id = $1", room_id)
    inc_before = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()["total_income"]

    assert _apply(client, admin_headers, [student_id]).status_code == 200

    tx_after = await _count(db_pool, "finance_transactions", "room_id = $1", room_id)
    assert tx_after == tx_before, "การหักเครดิตต้องไม่เขียน finance_transactions"
    inc_after = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()["total_income"]
    assert inc_before == 0.0
    assert inc_after == 400.0, "รายได้ต้องโผล่พอดีหนึ่งครั้งจาก journal ฝั่งเดียว"

    # 📄 ทะเบียน "เงินเคลื่อนไหว" ต้องมีแถวเดียว (ของตอนเติม) ไม่ใช่สอง
    listing = client.get(_url(TRANSACTIONS_PATH, room_id), headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1


async def test_budget_overview_counts_revenue_from_credit_application(
    client, db_pool, admin_headers
):
    """งบประมาณต้องเห็นรายได้ที่เกิดจากการหักเครดิต — และ **ไม่** เห็นตอนเติมเครดิต

    🔴 นี่คือเทสต์ที่จะ **ล้มถ้าลืมเติม `'student_credit_apply'`** เข้า
       `JE.reference_type IN (...)` ที่ `budgets.py` (ยอดจะหายเงียบ ไม่มี error)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    category_id = await _seed_income_category(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=600.0)

    budget = client.post(
        _url(BUDGETS_PATH, room_id),
        json={
            "category_id": category_id, "amount": 5000.0,
            "start_date": "2026-09-01", "end_date": "2026-09-30",
            "user_name": "Tester",
        },
        headers=admin_headers,
    )
    assert budget.status_code == 200, budget.text
    overview_url = _url(BUDGET_OVERVIEW_PATH, room_id) + "&start_date=2026-09-01&end_date=2026-09-30"

    def used() -> float:
        rows = client.get(overview_url, headers=admin_headers).json()["items"]
        row = next(r for r in rows if r["category_id"] == category_id)
        return round(row["used"], 2)

    assert used() == 0.0

    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200
    assert used() == 0.0, "เงินรับล่วงหน้ายังไม่ใช่รายได้ ⇒ ต้องไม่เข้างบตอนเติม"

    assert _apply(client, admin_headers, [student_id]).status_code == 200
    assert used() == 600.0, (
        "รายได้จากการหักเครดิตต้องถูกนับเข้างบ — ถ้าได้ 0 แปลว่าลืมแก้ "
        "`reference_type IN (...)` ที่ services/finance/budgets.py"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. การจัดสรรเครดิต — ยอดต้องตรงกับหน้าลูกหนี้ และ snapshot ต้องต่อกัน
# ══════════════════════════════════════════════════════════════════════════════
async def test_net_pending_matches_what_apply_actually_deducts(client, db_pool, admin_headers):
    """`GET /finance/debtors` ต้องบอกยอดที่ "ต้องเก็บจริง" ตรงกับที่ระบบหักจริงเป๊ะ

    🎯 3 บิลคนละกำหนด (บิลครบกำหนดก่อนถูกหักก่อน) + เครดิต 1000 ⇒
       เหลือค้าง = 2500 − 1000 = 1500 ทั้งบนจอและใน DB
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, title="บิล ก", amount=800.0,
                     due_date=date(2026, 10, 1))
    await _make_bill(db_pool, room_id, student_id, title="บิล ข", amount=900.0,
                     due_date=date(2026, 11, 1))
    await _make_bill(db_pool, room_id, student_id, title="บิล ค", amount=800.0,
                     due_date=date(2026, 12, 1))
    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200

    def debtor_row() -> dict:
        rows = client.get(_url(DEBTORS_PATH, room_id), headers=admin_headers).json()
        return next(r for r in rows if r["student_id"] == student_id)

    row = debtor_row()
    assert row["total_pending_amount"] == 2500.0, "ยอดดิบต้องคงความหมายเดิม (บอท/จอเดิมใช้อยู่)"
    assert row["credit_balance"] == 1000.0
    assert row["net_pending_amount"] == 1500.0

    applied = _apply(client, admin_headers, [student_id]).json()
    assert applied["total_applied"] == 1000.0

    row_after = debtor_row()
    assert row_after["credit_balance"] == 0.0
    assert row_after["net_pending_amount"] == 1500.0, "ยอดบนจอต้องตรงกับที่เหลือจริงใน DB"

    # 🔍 ตรวจกับ DB ตรง ๆ อีกรอบ (ไม่เชื่อ SQL ของ service ตัวเดียวกับที่หน้าจอใช้)
    async with db_pool.acquire() as conn:
        remaining = await conn.fetchval(
            """SELECT COALESCE(SUM(FC.amount - SP.paid_amount), 0)
               FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id
               WHERE SP.student_id = $1 AND SP.status = 'pending'""",
            student_id,
        )
    assert round(float(remaining), 2) == 1500.0

    # 💡 greedy "ครบกำหนดก่อน": บิล 800 ถูกปิดเต็ม, บิล 900 ได้ 200, บิล 800 ไม่ถูกแตะ
    entries = await _credit_entries(db_pool, room_id, student_id)
    assert [e["amount"] for e in entries if e["entry_type"] == CREDIT_ENTRY_APPLY] == [800.0, 200.0]
    assert entries[-1]["balance_after"] == 0.0

    # 🎯 `GET /finance/credits` ต้องให้ตัวเลขชุดเดียวกับหน้าลูกหนี้ (predicate เดียวกัน)
    balances = client.get(_url(CREDITS_PATH, room_id), headers=admin_headers).json()
    mine = next(b for b in balances if b["student_id"] == student_id)
    assert mine["credit_balance"] == 0.0
    assert mine["total_pending_amount"] == 1500.0
    assert mine["net_pending_amount"] == 1500.0


async def test_balance_after_is_a_snapshot_chain_not_a_sum(client, db_pool, admin_headers):
    """`balance_after` ต้องเป็น snapshot ต่อกัน (1000 → 700 → 100) ไม่ใช่ค่าที่คำนวณย้อนหลัง

    🎯 ยอดคงเหลือปัจจุบัน = `balance_after` ของ **แถวล่าสุด** ⇒ ถ้ามีใครเปลี่ยนไปใช้
       `SUM(amount)` ยอดจะเพี้ยนทันทีที่มีการ reverse (ซึ่งเป็นเหตุผลที่ตารางนี้เก็บ snapshot)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, title="บิล 1", amount=300.0,
                     due_date=date(2026, 10, 1))
    await _make_bill(db_pool, room_id, student_id, title="บิล 2", amount=600.0,
                     due_date=date(2026, 11, 1))
    await _make_bill(db_pool, room_id, student_id, title="บิล 3", amount=500.0,
                     due_date=date(2026, 12, 1))

    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200

    detail = _student_credit(client, admin_headers, student_id)
    assert detail.status_code == 200, detail.text
    assert detail.json()["plan"]["allocations"][0]["apply_amount"] == 300.0

    # 1000 กระจายเป็น 300 (บิล 1) + 600 (บิล 2) + 100 (บิล 3) — ครบกำหนดก่อนได้ก่อน
    assert _apply(client, admin_headers, [student_id]).json()["total_applied"] == 1000.0

    entries = await _credit_entries(db_pool, room_id, student_id)
    assert [e["entry_type"] for e in entries] == [
        CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_APPLY,
    ]
    assert [round(float(e["balance_after"]), 2) for e in entries] == [1000.0, 700.0, 100.0, 0.0]
    assert sum(float(e["amount"]) for e in entries) == 2000.0, (
        "ผลรวม amount (2000) ต้องไม่เท่ากับยอดคงเหลือ (0) — "
        "นี่คือเหตุผลที่ต้องอ่านแถวล่าสุด ไม่ใช่ SUM"
    )

    detail = _student_credit(client, admin_headers, student_id).json()
    assert detail["credit_balance"] == 0.0
    assert [e["entry_type"] for e in detail["entries"]] == [
        CREDIT_ENTRY_APPLY, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_TOPUP,
    ], "ประวัติต้องเรียงใหม่→เก่า (แถวล่าสุดก่อน)"
    assert detail["entries"][0]["balance_after"] == 0.0
    assert detail["entries"][-1]["balance_after"] == 1000.0
    # บิล 3 ยังเหลือ 400 (เครดิตหมดก่อน)
    assert len(detail["open_bills"]) == 1
    assert detail["open_bills"][0]["remaining_amount"] == 400.0


async def test_plan_is_read_only_and_matches_what_apply_executes(client, db_pool, admin_headers):
    """`GET .../credits/plan` ต้องไม่เขียนอะไรเลย และให้ตัวเลขชุดเดียวกับที่ apply ทำจริง

    🔴 "สิ่งที่ครูเห็น = สิ่งที่ระบบทำ" ต้องพิสูจน์ได้ ไม่ใช่แค่คอมเมนต์ในโค้ด
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=700.0)
    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200

    res = _plan(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    plan = res.json()
    assert plan["total_applied"] == 700.0
    assert plan["bills_paid"] is None, "เส้นทางดูตัวอย่างต้องไม่รายงานผลการลงมือ"

    # 🚫 อ่านล้วนจริง — ไม่มีแถวใหม่เกิดขึ้นแม้แต่แถวเดียว
    assert await _count(db_pool, "student_credits", "entry_type = $1", CREDIT_ENTRY_APPLY) == 0
    assert len(await _receipts(db_pool, room_id)) == 1, "มีแต่ใบ DEP ของตอนเติม"

    applied = _apply(client, admin_headers, [student_id]).json()
    assert applied["total_applied"] == plan["total_applied"]
    assert applied["items"][0]["allocations"] == plan["items"][0]["allocations"], (
        "รูปร่าง/ตัวเลขของข้อเสนอกับผลที่ลงมือต้องเท่ากันเป๊ะ"
    )


async def test_plan_route_is_not_swallowed_by_student_id_route(client, admin_headers, db_pool):
    """`/credits/plan` ต้องไม่ถูกตีความเป็น `student_id` (กับดักลำดับ route)

    ⚠️ อาการของบั๊กนี้คือ 422 ที่ข้อความบอกแค่ "ค่าไม่ใช่จำนวนเต็ม" ซึ่งหาสาเหตุยากมาก
       ⇒ ต้องมีเทสต์ pin ไว้ ไม่งั้นวันหนึ่งมีคนสลับลำดับประกาศแล้วเงียบ
    """
    res = _plan(client, admin_headers, [admin_headers.student_id])
    assert res.status_code == 200, f"route ลำดับเพี้ยน (น่าจะตกไปที่ /{{student_id}}): {res.text}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Idempotency + เลขเอกสาร
# ══════════════════════════════════════════════════════════════════════════════
async def test_top_up_with_same_idempotency_key_is_not_a_second_payment(
    client, db_pool, admin_headers
):
    """กดซ้ำด้วยคีย์เดิม = ผลลัพธ์เดิม (`reused: true`) ไม่ใช่เงินเข้า 2 รอบ

    🔴 จำเป็นเพราะการเติมสร้าง `finance_transactions` แถวใหม่ทุกครั้ง ⇒
       `idx_finance_receipts_deposit_active` กันให้ไม่ได้ (คนละ legacy_transaction_id)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, balance=0.0)
    student_id = await _make_debtor(db_pool, room_id)
    key = _key()

    first = _top_up(client, admin_headers, student_id, account_id, 500.0, key=key)
    assert first.status_code == 200
    second = _top_up(client, admin_headers, student_id, account_id, 500.0, key=key)
    assert second.status_code == 200, second.text

    a, b = first.json(), second.json()
    assert b["reused"] is True
    assert b["credit_entry_id"] == a["credit_entry_id"]
    assert b["balance_after"] == 500.0, "กดซ้ำต้องไม่เพิ่มเครดิตเป็น 1000"
    assert b["receipt"]["receipt_no"] == a["receipt"]["receipt_no"]
    assert b["receipt_reused"] is True

    # 🔍 DB: มีแถวเดียวทุกตาราง และกระเป๋าเพิ่มแค่ 500
    assert await _count(db_pool, "student_credits", "room_id = $1", room_id) == 1
    assert await _count(db_pool, "finance_transactions", "room_id = $1", room_id) == 1
    assert len(await _receipts(db_pool, room_id)) == 1
    assert await _asset_net(db_pool, room_id) == 500.0
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert round(float(balance), 2) == 500.0


async def test_deposit_sequence_is_separate_from_receipt_sequence(client, db_pool, admin_headers):
    """ตัวนับเลขของ `deposit` ต้องแยกจาก `receipt`/`invoice` โดยอัตโนมัติ (PK มี doc_type)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    first_student = await _make_debtor(db_pool, room_id, student_no=91)
    second_student = await _make_debtor(db_pool, room_id, student_no=92, first_name="เด็กหญิงทดสอบ")

    assert _top_up(client, admin_headers, first_student, account_id, 100.0).status_code == 200
    assert _top_up(client, admin_headers, second_student, account_id, 200.0).status_code == 200

    receipts = await _receipts(db_pool, room_id)
    assert [r["receipt_no"] for r in receipts] == ["DEP-2569-0001", "DEP-2569-0002"]
    assert [r["seq"] for r in receipts] == [1, 2]
    assert all(r["student_payment_id"] is None for r in receipts), (
        "ใบรับเงินล่วงหน้าไม่มีบิล ⇒ student_payment_id ต้องเป็น NULL"
    )
    assert all(r["collection_id"] is None for r in receipts)

    # ไม่มีตัวนับของ 'receipt' ถูกกินไปเลย
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT doc_type, last_seq FROM receipt_sequences WHERE room_id = $1 ORDER BY doc_type",
            room_id,
        )
    assert {r["doc_type"]: r["last_seq"] for r in rows} == {DOC_TYPE_DEPOSIT: 2}


async def test_receipts_registry_accepts_deposit_filter(client, db_pool, admin_headers):
    """ทะเบียนเอกสารต้องกรอง `doc_type=deposit` ได้ (200) ไม่ใช่ 422 จาก Query pattern

    🔴 ถ้าลืมขยาย `pattern="^(receipt|invoice|deposit)$"` ที่ `routers/finance/receipts.py`
       chip "ใบรับเงินล่วงหน้า" บนหน้าจอจะได้ 422 ทันทีที่กด — เทสต์นี้คือด่านกัน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    assert _top_up(client, admin_headers, student_id, account_id, 100.0).status_code == 200

    res = client.get(_url(RECEIPTS_PATH, room_id) + "&doc_type=deposit", headers=admin_headers)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["doc_type"] == DOC_TYPE_DEPOSIT
    assert rows[0]["receipt_no"] == "DEP-2569-0001"
    # 🏷️ ป้ายชนิดเอกสารต้องบอกว่าเป็นใบรับเงินล่วงหน้า ไม่ใช่ใบเสร็จ/ใบแจ้งหนี้
    assert rows[0]["doc_type_label"] == "ใบรับเงินล่วงหน้า"


async def test_pdf_filename_does_not_lie_for_deposit():
    """ชื่อไฟล์ดาวน์โหลดต้องบอกชนิดเอกสารจริง ไม่ใช่ `invoice-` (ชื่อไฟล์โกหก)

    🧪 pure function — ไม่แตะ DB เลย แต่ยังเป็น `async def` เพราะทั้งโมดูลติด
       `pytestmark = pytest.mark.asyncio` (เทสต์ sync ที่ติด marker จะได้ warning)
    """
    assert pdf_filename("DEP-2569-0001", DOC_TYPE_DEPOSIT) == "deposit-DEP-2569-0001.pdf"
    assert pdf_filename("REC-2569-0001", "receipt") == "receipt-REC-2569-0001.pdf"
    assert pdf_filename("INV-2569-0001", "invoice") == "invoice-INV-2569-0001.pdf"
    # ชนิดที่ไม่รู้จักต้องไม่แอบอ้างว่าเป็นใบเสร็จ/ใบแจ้งหนี้
    assert pdf_filename("XXX-2569-0001", "mystery") == "document-XXX-2569-0001.pdf"


# ══════════════════════════════════════════════════════════════════════════════
# 4. ความถูกต้องของเส้นทาง (validation / all-or-nothing / RBAC)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("amount, expected", [
    (0, 422),        # ติด `gt=0` ที่ schema — ด่านแรก
    (-5, 422),       # ติด `gt=0` ที่ schema
    (0.004, 400),    # ผ่าน schema แต่ **ปัดเป็นสตางค์แล้วเหลือ 0** ⇒ ด่าน service
])
async def test_invalid_top_up_amount_writes_nothing(client, db_pool, admin_headers, amount, expected):
    """ยอดที่ไม่ถูกต้องต้องถูกปฏิเสธ **ก่อน** จองเลข DEP และก่อนเขียนแถวใด ๆ

    🎯 ถ้าด่านยอดเงินอยู่ *หลัง* การจองเลข เลข DEP จะถูกกินทิ้งทุกครั้งที่ผู้ใช้พิมพ์ผิด
       (และผู้ใช้จะเห็นเลขกระโดดโดยหาสาเหตุไม่ได้)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)

    res = _top_up(client, admin_headers, student_id, account_id, amount)
    assert res.status_code == expected, res.text

    assert await _count(db_pool, "student_credits", "room_id = $1", room_id) == 0
    assert await _count(db_pool, "finance_transactions", "room_id = $1", room_id) == 0
    assert await _receipts(db_pool, room_id) == []
    async with db_pool.acquire() as conn:
        seq = await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = $2",
            room_id, DOC_TYPE_DEPOSIT,
        )
    assert seq is None, "คำขอที่ยอดไม่ถูกต้องต้องไม่กินเลขเอกสาร"


async def test_top_up_without_idempotency_key_is_rejected(client, db_pool, admin_headers):
    """ไม่มีคีย์ = ไม่มีด่านกันซ้ำเลย ⇒ ต้องถูกปฏิเสธที่ schema ไม่ใช่ยอมให้เป็น NULL เงียบ ๆ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)

    res = client.post(
        _url(CREDITS_PATH, room_id),
        json={"student_id": student_id, "amount": 100.0, "paid_to_account_id": account_id},
        headers=admin_headers,
    )
    assert res.status_code == 422, res.text
    assert await _count(db_pool, "student_credits", "room_id = $1", room_id) == 0


async def test_apply_is_all_or_nothing_when_one_student_is_missing(client, db_pool, admin_headers):
    """มี student_id ที่ไม่มีอยู่ปนมา ⇒ ยกเลิกทั้งชุด ไม่หักใครเลยแม้แต่คนเดียว"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    good = await _make_debtor(db_pool, room_id, student_no=93)
    _, payment_id = await _make_bill(db_pool, room_id, good, amount=500.0)
    assert _top_up(client, admin_headers, good, account_id, 500.0).status_code == 200

    res = _apply(client, admin_headers, [good, 999_999_999])
    assert res.status_code == 404, res.text

    assert await _count(db_pool, "student_credits", "entry_type = $1", CREDIT_ENTRY_APPLY) == 0
    assert (await _bill_row(db_pool, payment_id))["status"] == "pending"
    assert await _revenue_net(db_pool, room_id) == 0.0
    assert await _liability_net(db_pool, room_id) == 500.0, "เครดิตต้องไม่ถูกแตะ"


async def test_member_can_read_credits_but_every_write_is_forbidden(
    client, db_pool, member_headers
):
    """สมาชิกอ่านได้ (โปร่งใส) แต่เขียนไม่ได้ **และไม่มีแถวถูกเขียน**"""
    room_id = member_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=300.0)

    # ✅ อ่าน — สมาชิกดูได้เหมือนหน้าลูกหนี้
    lists = _list_credits(client, member_headers)
    assert lists.status_code == 200, lists.text
    assert any(r["student_id"] == student_id for r in lists.json())
    assert _plan(client, member_headers, [student_id]).status_code == 200
    assert _student_credit(client, member_headers, student_id).status_code == 200

    # 🚫 เขียน — 403 ทั้งสามเส้นทาง
    blocked = [
        _top_up(client, member_headers, student_id, account_id, 500.0),
        _apply(client, member_headers, [student_id]),
        _undo(client, member_headers, 1),
    ]
    for res in blocked:
        assert res.status_code == 403, f"ต้อง 403 แต่ได้ {res.status_code}: {res.text}"

    # 🔍 ไม่มีอะไรถูกเขียนเลย (ไม่ใช่แค่ได้ status ที่ถูก)
    assert await _count(db_pool, "student_credits", "room_id = $1", room_id) == 0
    assert await _count(db_pool, "finance_transactions", "room_id = $1", room_id) == 0
    assert await _receipts(db_pool, room_id) == []
    async with db_pool.acquire() as conn:
        seq = await conn.fetchval("SELECT last_seq FROM receipt_sequences WHERE room_id = $1", room_id)
    assert seq is None


async def test_finance_manager_is_not_admin_but_can_still_write(client, db_pool, finance_manager_headers):
    """เหรัญญิก (ไม่ใช่ admin) ต้องเติม/หักได้ — ไม่งั้นหน้าจอใหม่จะใช้ได้แค่แอดมิน"""
    room_id = finance_manager_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=250.0)

    assert _top_up(client, finance_manager_headers, student_id, account_id, 400.0).status_code == 200
    assert _apply(client, finance_manager_headers, [student_id]).status_code == 200
    assert await _revenue_net(db_pool, room_id) == 250.0
    assert await _liability_net(db_pool, room_id) == 150.0


async def test_top_up_rejects_student_or_account_outside_the_room(client, db_pool, admin_headers):
    """นักเรียน/กระเป๋าของห้องอื่นต้องใช้ไม่ได้ (กันข้ามห้อง)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)

    async with db_pool.acquire() as conn:
        other_room = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องอื่น", f"OTH{uuid.uuid4().hex[:6].upper()}",
        )
    other_student = await _make_debtor(db_pool, other_room, student_no=70, first_name="เด็กห้องอื่น")
    other_account = await _insert_account(db_pool, other_room, name="กระเป๋าห้องอื่น")

    assert _top_up(client, admin_headers, other_student, account_id, 100.0).status_code == 404
    assert _top_up(client, admin_headers, other_student, other_account, 100.0).status_code == 404
    assert await _count(db_pool, "student_credits", "room_id = $1", room_id) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. ถอยกลับได้ — ยกเลิกการหัก และยกเลิกรายการเติมเงิน
# ══════════════════════════════════════════════════════════════════════════════
async def test_undo_application_returns_credit_and_reopens_the_bill(client, db_pool, admin_headers):
    """ยกเลิกการหัก ⇒ เครดิตคืน, บิลกลับเป็นค้าง, journal ถูก void, **กระเป๋าไม่ขยับ**"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=800.0)
    assert _top_up(client, admin_headers, student_id, account_id, 800.0).status_code == 200
    assert _apply(client, admin_headers, [student_id]).json()["total_applied"] == 800.0

    apply_entry = (await _credit_entries(db_pool, room_id, student_id))[-1]
    assets_before = await _asset_net(db_pool, room_id)

    res = _undo(client, admin_headers, apply_entry["id"], reason="หักผิดบิล")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reverted_amount"] == 800.0
    assert body["credit_balance_after"] == 800.0
    assert body["bill_paid_amount"] == 0.0
    assert body["bill_status"] == "pending"
    assert body["reverse_entry_id"] != apply_entry["id"]

    # 💵 เครดิตคืน + บิลกลับเป็นค้าง (ล้างร่องรอยการชำระทั้งหมด)
    entries = await _credit_entries(db_pool, room_id, student_id)
    assert [e["entry_type"] for e in entries] == [CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_REVERSE]
    assert entries[-1]["balance_after"] == 800.0
    bill = await _bill_row(db_pool, payment_id)
    assert round(float(bill["paid_amount"]), 2) == 0.0
    assert bill["status"] == "pending"
    assert bill["paid_at"] is None and bill["recorded_by"] is None

    # 📉 รายได้ถูก void ⇒ หายจากทั้งงบดุลและ summary
    assert await _revenue_net(db_pool, room_id) == 0.0
    assert await _liability_net(db_pool, room_id) == 800.0
    assert await _asset_net(db_pool, room_id) == assets_before, (
        "การยกเลิกการหักต้องไม่แตะยอดกระเป๋า — เงินไม่ได้เข้าตอนหัก จึงไม่มีอะไรต้องคืน"
    )
    summary = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()
    assert summary["total_income"] == 0.0

    # 🚫 ยกเลิกซ้ำไม่ได้ (แถวเดิมถูก soft delete ⇒ หาไม่เจอ)
    again = _undo(client, admin_headers, apply_entry["id"])
    assert again.status_code == 400, again.text


async def test_undo_refuses_a_top_up_entry(client, db_pool, admin_headers):
    """ยกเลิก 'การเติม' ผ่านเส้นทาง undo ไม่ได้ — ต้องยกเลิกรายการธุรกรรม (ซึ่ง void ใบ DEP ด้วย)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    assert _top_up(client, admin_headers, student_id, account_id, 300.0).status_code == 200

    topup_entry = (await _credit_entries(db_pool, room_id, student_id))[0]
    res = _undo(client, admin_headers, topup_entry["id"])
    assert res.status_code == 400, res.text
    assert await _liability_net(db_pool, room_id) == 300.0, "เครดิตต้องไม่ถูกแตะ"


async def test_revert_top_up_voids_the_deposit_and_the_credit_row(client, db_pool, admin_headers):
    """ยกเลิกรายการเติมที่ **ยังไม่ถูกใช้** ⇒ ใบ DEP ต้อง voided **คู่กับ** deleted_at

    ⚠️ บังคับด้วย constraint `chk_receipt_voided_is_deleted` — void อย่างเดียวจะ INSERT ไม่ผ่าน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, balance=0.0)
    student_id = await _make_debtor(db_pool, room_id)
    topup = _top_up(client, admin_headers, student_id, account_id, 600.0).json()

    res = _revert(client, admin_headers, topup["finance_transaction_id"])
    assert res.status_code == 200, res.text
    assert topup["receipt"]["receipt_no"] in res.json()["voided_receipts"], (
        "ผู้ใช้ต้องรู้ว่าใบ DEP ถูกยกเลิกไปด้วย ไม่ใช่หายเงียบ"
    )

    deposit = (await _receipts(db_pool, room_id))[0]
    assert deposit["status"] == "voided"
    assert deposit["deleted_at"] is not None
    assert deposit["voided_at"] is not None

    # ↩️ เครดิตถูกถอนคืนด้วยแถว reverse (append-only — ประวัติยังตรวจสอบได้)
    entries = await _credit_entries(db_pool, room_id, student_id)
    assert [e["entry_type"] for e in entries] == [CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_REVERSE]
    assert entries[-1]["balance_after"] == 0.0
    assert await _liability_net(db_pool, room_id) == 0.0
    assert await _asset_net(db_pool, room_id) == 0.0
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert round(float(balance), 2) == 0.0

    # 🚫 ยกเลิกซ้ำไม่ได้ — **404 ไม่ใช่ 400** เพราะการยกเลิกครั้งแรก soft delete แถว
    #    `finance_transactions` ทิ้ง ⇒ การค้นหาไม่เจอตั้งแต่ต้น (ประตูบานเดียวกันกับ
    #    ทุกประเภทธุรกรรม — ดู `test_finance.py::test_revert_transaction_already_deleted_raises`)
    #    ⚠️ สิ่งที่ต้องพิสูจน์จริง ๆ คือ **ไม่มีแถว reverse แถวที่สอง** (การคืนเงินสองรอบ)
    #       ไม่ใช่รหัส status เฉย ๆ ⇒ ยืนยันด้วยจำนวนแถวอีกครั้งหลังยิงซ้ำ
    again = _revert(client, admin_headers, topup["finance_transaction_id"])
    assert again.status_code == 404, again.text
    assert [e["entry_type"] for e in await _credit_entries(db_pool, room_id, student_id)] == [
        CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_REVERSE,
    ], "ยิงยกเลิกซ้ำแล้วต้องไม่เกิดแถว reverse ใบที่สอง"
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert round(float(balance), 2) == 0.0, "คืนเงินซ้ำไม่ได้ — กระเป๋าต้องไม่ติดลบ"


async def test_revert_is_refused_when_the_credit_was_already_used(client, db_pool, admin_headers):
    """ยกเลิกรายการเติมที่ถูกหักใช้ไปแล้ว = เครดิตติดลบโดยไม่รู้ตัว ⇒ ต้อง 400

    🎯 และต้องบอกทางออกกับผู้ใช้ด้วย (ยกเลิกการหักก่อน) ไม่ใช่แค่ปฏิเสธเฉย ๆ
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=300.0)
    topup = _top_up(client, admin_headers, student_id, account_id, 1000.0).json()
    assert _apply(client, admin_headers, [student_id]).status_code == 200

    res = _revert(client, admin_headers, topup["finance_transaction_id"])
    assert res.status_code == 400, res.text
    assert "ยกเลิก" in res.json()["detail"], "ข้อความต้องบอกทางออก ไม่ใช่ปฏิเสธลอย ๆ"

    # 🔍 ไม่มีอะไรเปลี่ยน — ทั้งใบ DEP และเครดิตยังอยู่ครบ
    assert (await _receipts(db_pool, room_id))[0]["status"] == "active"
    assert await _liability_net(db_pool, room_id) == 700.0
    assert await _revenue_net(db_pool, room_id) == 300.0


async def test_revert_is_refused_after_a_later_top_up_of_the_same_student(
    client, db_pool, admin_headers
):
    """เติมซ้ำแล้วอยากยกเลิกรายการแรก ⇒ ปฏิเสธ (การถอนจะทำให้ยอดคงเหลือเพี้ยน)

    🎯 guard นี้กัน invariant ที่พิสูจน์ได้: "ไม่มีแถวเครดิตของคนนี้ที่ id ใหม่กว่า"
       ⇒ การ append แถว reverse ต่อท้ายยังทำให้ `balance_after` ของแถวล่าสุดถูกต้องเสมอ
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    first = _top_up(client, admin_headers, student_id, account_id, 100.0).json()
    assert _top_up(client, admin_headers, student_id, account_id, 200.0).status_code == 200

    res = _revert(client, admin_headers, first["finance_transaction_id"])
    assert res.status_code == 400, res.text
    assert await _liability_net(db_pool, room_id) == 300.0


async def test_revert_of_top_up_keeps_audit_rows_and_removes_nothing_from_the_journal(
    client, db_pool, admin_headers
):
    """การยกเลิกต้อง **void** journal + **เก็บ** audit ไม่ใช่ลบ — ร่องรอยต้องอยู่ครบ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    topup = _top_up(client, admin_headers, student_id, account_id, 450.0).json()

    # 📏 วัด "ก่อน" แล้วเทียบกับ "หลัง" — ไม่ฮาร์ดโค้ดตัวเลขที่ต้องเดา
    #    (ถ้าฮาร์ดโค้ด `>= 2` เทสต์จะพังทันทีที่บรรทัด audit ของการเติมเปลี่ยนจำนวน
    #     ทั้งที่ตัวสมบัติที่ต้องการพิสูจน์ — "การยกเลิกลบร่องรอยทิ้ง" — ยังเป็นเท็จอยู่)
    async def _credit_audit_rows():
        async with db_pool.acquire() as conn:
            return await conn.fetchval(
                """SELECT COUNT(*) FROM audit_logs
                   WHERE room_id = $1 AND entity_type = 'STUDENT_CREDIT'""",
                room_id,
            )

    before = await _credit_audit_rows()
    assert before >= 1, "การเติมเครดิตต้องถูกบันทึก audit ตั้งแต่แรก"

    assert _revert(client, admin_headers, topup["finance_transaction_id"]).status_code == 200
    assert await _credit_audit_rows() == before, "การยกเลิกต้องไม่ลบร่องรอย audit ของการเติม"

    # 🧾 และการยกเลิกเองก็ต้องถูกบันทึก — คนละ `entity_type` กับของเครดิตโดยเจตนา
    #    (มันคือการยกเลิกรายการธุรกรรม ⇒ `revert_transaction` เป็นเจ้าของร่องรอยนั้น)
    #    ⚠️ ถ้าไม่ assert ตรงนี้ เทสต์จะเขียวแม้การยกเลิกจะไม่ถูกบันทึกเลย
    async with db_pool.acquire() as conn:
        revert_logs = await conn.fetchval(
            """SELECT COUNT(*) FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_TRANSACTION'
                 AND entity_id = $2 AND action = 'UPDATE'""",
            room_id, str(topup["finance_transaction_id"]),
        )
    assert revert_logs == 1, "การยกเลิกรายการเติมเงินต้องถูกบันทึก audit"

    async with db_pool.acquire() as conn:
        entry = await conn.fetchrow(
            "SELECT id, status, deleted_at FROM journal_entries WHERE id = $1",
            uuid.UUID(topup["journal_entry_id"]),
        )
        lines = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_lines WHERE journal_entry_id = $1", entry["id"],
        )
    assert entry is not None, "journal entry ต้องไม่ถูกลบ"
    assert entry["status"] == "voided" and entry["deleted_at"] is not None
    assert lines == 2, "บรรทัด Dr/Cr ต้องอยู่ครบ (void ทั้งใบ ไม่ใช่ลบบรรทัด)"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Mutation guards — พิสูจน์ว่าเทสต์ข้างบน "มีฟัน" จริง
# ══════════════════════════════════════════════════════════════════════════════
async def test_income_ledger_resolver_is_shared_with_cash_payment(client, db_pool, admin_headers):
    """รายได้จากการหักเครดิตต้องลง **ledger ตัวเดียวกับ** ที่เงินสดใช้

    🎯 ถ้ามีสองชุดโค้ดที่ "ทำคล้ายกัน" วันหนึ่งจะแก้ข้างเดียว ⇒ รายได้จากสองทาง
       ไปคนละ ledger แล้วงบประมาณ (ที่ join ด้วย legacy_category_id) จะเห็นข้างเดียว
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cash_student = await _make_debtor(db_pool, room_id, student_no=94)
    credit_student = await _make_debtor(db_pool, room_id, student_no=95, first_name="เด็กเครดิต")
    _, cash_payment = await _make_bill(db_pool, room_id, cash_student, amount=100.0)
    await _make_bill(db_pool, room_id, credit_student, amount=100.0)

    # ทางที่ 1: เงินสด (confirm_payment → _resolve_default_income_ledger)
    paid = client.put(
        _url(API_PREFIX + "/{room}/finance/payments/{payment_id}/pay", room_id, payment_id=cash_payment),
        json={"paid_to_account_id": account_id, "paid_amount": 100.0, "user_name": "Tester"},
        headers=admin_headers,
    )
    assert paid.status_code == 200, paid.text

    # ทางที่ 2: หักเครดิต
    assert _top_up(client, admin_headers, credit_student, account_id, 100.0).status_code == 200
    assert _apply(client, admin_headers, [credit_student]).status_code == 200

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT JE.reference_type, AL.id AS ledger_id
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = 'revenue' AND L.credit > 0
               ORDER BY JE.reference_type""",
            room_id,
        )
    by_ref = {r["reference_type"]: r["ledger_id"] for r in rows}
    assert set(by_ref) == {"student_payment", REFERENCE_TYPE_CREDIT_APPLY}, by_ref
    assert by_ref["student_payment"] == by_ref[REFERENCE_TYPE_CREDIT_APPLY], (
        "รายได้จากเงินสดกับจากการหักเครดิตต้องลง ledger ตัวเดียวกัน"
    )
    assert await _revenue_net(db_pool, room_id) == 200.0

    # 🧾 และไม่มี journal ไหนที่ติด reference_type ของการ "เติม" แล้วมีขา revenue
    async with db_pool.acquire() as conn:
        leak = await conn.fetchval(
            """SELECT COUNT(*)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND JE.reference_type = $2 AND AL.account_type = 'revenue'""",
            room_id, REFERENCE_TYPE_CREDIT_TOPUP,
        )
    assert leak == 0, "การเติมเครดิตต้องไม่มีขา revenue เล็ดลอดออกมาได้เลย"


async def test_credit_queries_never_leak_across_rooms(client, db_pool, admin_headers):
    """นักเรียน/แถวเครดิตของห้องอื่นต้องไม่โผล่และแก้ไม่ได้จากห้องนี้ (กันข้ามห้อง)

    🎯 ด่านนี้สำคัญเพราะ `room_id` มาจาก URL ไม่ใช่จาก session — ถ้าลืมกรองที่ใดที่หนึ่ง
       เหรัญญิกห้อง ก. จะเห็นและหักเครดิตของเด็กห้อง ข. ได้
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)

    async with db_pool.acquire() as conn:
        other_room = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องอื่น", f"OTR{uuid.uuid4().hex[:6].upper()}",
        )
    other_account = await _insert_account(db_pool, other_room, name="กระเป๋าห้องอื่น")
    other_student = await _make_debtor(db_pool, other_room, student_no=71, first_name="เด็กห้องอื่น")
    await _make_bill(db_pool, other_room, other_student, amount=999.0)

    # 🚫 ยิงไปที่ URL ของห้องอื่นด้วยสิทธิ์ของห้องนี้ → 403 (ไม่ใช่สมาชิกห้องนั้น)
    assert _top_up(
        client, admin_headers, other_student, other_account, 100.0, room_id=other_room
    ).status_code == 403
    assert await _count(db_pool, "student_credits", "room_id = $1", other_room) == 0

    # 📋 รายการเครดิตของห้องนี้ต้องไม่มีเด็กห้องอื่น
    rows = _list_credits(client, admin_headers).json()
    assert all(r["student_id"] != other_student for r in rows)

    # 🔍 รายละเอียดรายคนของเด็กห้องอื่น → 404 (ไม่ใช่ 200 ที่เผยข้อมูลข้ามห้อง)
    assert _student_credit(client, admin_headers, other_student).status_code == 404

    # 🚫 หักเครดิตข้ามห้อง → 404 และไม่มีอะไรถูกเขียนในห้องอื่น
    assert _apply(client, admin_headers, [other_student]).status_code == 404
    assert await _count(
        db_pool, "student_credits", "room_id = $1 AND entry_type = $2",
        other_room, CREDIT_ENTRY_APPLY,
    ) == 0


async def test_reconcile_does_not_see_the_advance_liability_as_a_diff(client, db_pool, admin_headers):
    """ledger หนี้สิน 2099 ต้อง **มองไม่เห็น** จาก reconcile (ไม่มี legacy_account_id)

    🎯 ถ้ามันโผล่ใน `_scan_account_diffs` ระบบจะสร้างรายการปรับปรุงปลอมขึ้นมาทุกครั้ง
       ที่มีคนเติมเครดิต — และยอดกระเป๋าจะถูก "แก้" ให้ตรงกับอะไรที่ไม่มีอยู่จริง
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    assert _top_up(client, admin_headers, student_id, account_id, 1000.0).status_code == 200

    from services.finance_service import FinanceService

    async with db_pool.acquire() as conn:
        diffs = await FinanceService._scan_account_diffs(conn, room_id=room_id)
    assert [d for d in diffs if abs(d["diff"]) >= 0.01] == [], (
        f"reconcile รายงาน diff ทั้งที่บัญชีถูกต้อง: {diffs}"
    )
    # ยอด legacy กับ asset ledger ตรงกัน (เพราะการเติมเขียนทั้งสองฝั่งพร้อมกัน)
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1", account_id)
    assert round(float(balance), 2) == round(await _asset_net(db_pool, room_id), 2) == 1000.0


async def test_credit_entry_constants_are_pinned():
    """ค่าคงที่ของ entry_type/reference_type ต้องไม่ถูกเปลี่ยนเงียบ ๆ (มี CHECK constraint ผูกอยู่)"""
    assert (CREDIT_ENTRY_TOPUP, CREDIT_ENTRY_APPLY, CREDIT_ENTRY_REVERSE) == ("topup", "apply", "reverse")
    assert REFERENCE_TYPE_CREDIT_TOPUP == "student_credit_topup"
    assert REFERENCE_TYPE_CREDIT_APPLY == "student_credit_apply"
    assert ADVANCE_LIABILITY_CODE == "2099"


async def test_credit_timestamps_are_aware_utc_not_thai_naive(client, db_pool, admin_headers):
    """`student_credits.created_at` ต้องเป็น timestamptz และอ่านออกมาได้เป็น UTC จริง

    ⚠️ ข้อห้ามของผู้ใช้: **ห้ามแก้ Timezone ของ Postgres ให้เป็นไทย** — คอลัมน์ใหม่ต้อง
       เก็บเป็น UTC แล้วให้โค้ดแปลงเป็นเวลาไทยเอง (`_as_utc` → `astimezone(THAI_TZ)`)
       ⇒ เทสต์นี้กันการ "แก้ปัญหาที่ปลายเหตุ" ด้วยการเปลี่ยน timezone ของ DB

    🎯 และพิสูจน์ว่าเส้นทางอ่านของ API ไม่ได้ตีความค่า naive ผิด: `created_at` ที่คืนมา
       ต้องอยู่ห่างจากเวลาปัจจุบันไม่เกินไม่กี่นาที (ถ้าตีความเป็นไทยทั้งที่เก็บ UTC
       จะเพี้ยนไป 7 ชั่วโมงทันที)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    assert _top_up(client, admin_headers, student_id, account_id, 100.0).status_code == 200

    async with db_pool.acquire() as conn:
        dtype = await conn.fetchval(
            """SELECT data_type FROM information_schema.columns
               WHERE table_name = 'student_credits' AND column_name = 'created_at'"""
        )
        # 🕐 ค่าที่ DB คืนมาต้องมี tzinfo (timestamptz) ⇒ เอาไป astimezone(THAI_TZ) ได้ตรง ๆ
        raw = await conn.fetchval(
            "SELECT created_at FROM student_credits WHERE room_id = $1 LIMIT 1", room_id,
        )
        pg_timezone = await conn.fetchval("SHOW TimeZone")
    assert dtype == "timestamp with time zone", f"created_at ต้องเป็น timestamptz แต่ได้ {dtype}"
    assert raw.tzinfo is not None, "ค่าที่อ่านได้ต้อง tz-aware"
    assert pg_timezone == "UTC", (
        f"Timezone ของ Postgres ต้องเป็น UTC เสมอ (ข้อห้ามของผู้ใช้) แต่ได้ {pg_timezone}"
    )

    entry = _student_credit(client, admin_headers, student_id).json()["entries"][0]
    created = datetime.fromisoformat(entry["created_at"])
    assert created.tzinfo is not None, "API ต้องคืน created_at แบบ tz-aware"
    delta = abs((datetime.now(timezone.utc) - created).total_seconds())
    assert delta < 300, f"created_at เพี้ยนจากเวลาจริง {delta / 3600:.1f} ชั่วโมง (น่าจะตีความ TZ ผิด)"


# ══════════════════════════════════════════════════════════════════════════════
# 🖨️ เทมเพลตเอกสาร — กับดักที่ **เทสต์ทั้ง 64 ตัวก่อนหน้านี้มองไม่เห็น**
# ══════════════════════════════════════════════════════════════════════════════
# 🔴 บั๊กจริงที่พบตอน "เรนเดอร์ PDF ดูด้วยตา" (แผนงานข้อ Verification 4):
#    `_document_context` ตั้งคีย์ `remaining` **เฉพาะเมื่อมี `collection_amount`**
#    แต่ `receipt.html:253` กันด้วย `{% if d.remaining is not none %}` ซึ่งบน Jinja
#    `Undefined` ตอบ **True** ⇒ เข้าสาขาแล้วระเบิดที่ `"{:,.2f}".format(Undefined)`
#    ⇒ **ดาวน์โหลดใบรับเงินล่วงหน้าได้ HTTP 500 ทุกครั้ง**
#
#    🕳️ ทำไมเทสต์เดิมไม่จับ: ใบเสร็จ/ใบแจ้งหนี้ **ทุกใบผูกกับบิล** ⇒ มี
#       `collection_amount` เสมอ · ส่วน `test_receipt_template_declares_one_font_face_per_weight`
#       ส่ง `remaining` เข้าไปเองครบทั้ง 4 ฟิลด์ numeric ⇒ ไม่เคยเดินผ่านเส้นทางที่คีย์หาย
#       ⇒ ใบรับเงินล่วงหน้าเป็น **เอกสารชนิดแรกที่ไม่มีบิล** จึงเป็นใบแรกที่ตกหลุมนี้
#
# ⚠️ เทสต์กลุ่มนี้ **ไม่ต้องมี DB** — เป็นฟังก์ชันบริสุทธิ์ล้วน (เร็ว และไม่กินคิว container)
#    ⇒ ครอบ "เอกสารชนิดใหม่" ได้ทุกชนิดในอนาคตโดยไม่ต้องต่อ DB


def _deposit_doc(**overrides) -> dict:
    """รูปร่างของ dict ที่ `_shape_receipt_detail` ผลิตให้ใบรับเงินล่วงหน้า

    ค่าที่สำคัญคือ **ต้องไม่มีบิล**: `student_payment_id`/`collection_id`/`line_items`
    เป็น None และ `collection_amount` เป็น None ⇒ คีย์ `remaining` จะไม่ถูกตั้ง
    """
    doc = {
        "doc_type": DOC_TYPE_DEPOSIT,
        "doc_type_label": "ใบรับเงินล่วงหน้า",
        "receipt_no": "DEP-2569-0001",
        "status": "active",
        "void_reason": None,
        "amount": 1500.0,
        "paid_total_after": 1500.0,
        "student_payment_id": None,
        "collection_id": None,
        "collection_title": None,
        "collection_amount": None,
        "collection_due_date": None,
        "line_items": None,
        "issued_to_name": "เด็กชายสมชาย ใจดี",
        "student_no": 7,
        "issued_by_name": "ครูสมศรี",
        "issued_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
        "event_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
        "note": None,
        "room_name": "ห้อง ม.4/1",
        "room_code": "M4-1",
    }
    doc.update(overrides)
    return doc


async def test_deposit_context_pins_bill_only_keys_to_none():
    """คีย์ที่เป็นของ "บิล" ต้องถูก **ตั้งเป็น None** ไม่ใช่หายไปจาก context

    🔴 นี่คือรากของบั๊ก 500: เทมเพลตเขียนสัญญาไว้เองว่า *"บิลเดอร์ตั้งคีย์นี้เป็น None
       เสมอ เมื่อไม่มีแนวคิดนี้ และ `is defined` บนคีย์ที่เป็น None จะเป็น True"*
       (receipt.html เหนือบรรทัด `{% if d.remaining is not none %}`)
       ⚠️ ถ้าคีย์ **หาย** Jinja จะให้ `Undefined` ซึ่ง `is not none` ตอบ True
          ⇒ เข้าสาขาแล้ว TypeError ตอน `.format()` ⇒ ล้มทั้งการเรนเดอร์
    """
    ctx = ReceiptsMixin._document_context(_deposit_doc())

    assert "remaining" in ctx, "ต้องมีคีย์ `remaining` (ค่า None) ไม่ใช่ไม่มีคีย์เลย"
    assert ctx["remaining"] is None
    assert "collection_amount" in ctx, "ต้องมีคีย์ `collection_amount` (ค่า None)"
    assert ctx["collection_amount"] is None
    assert "remaining_text" in ctx
    # 🧾 เอกสารนี้รับเงินมาแล้ว ⇒ ต้องเป็น "ใบเสร็จ" ไม่ใช่ "ใบแจ้งหนี้"
    assert ctx["is_receipt"] is True, (
        "ใบรับเงินล่วงหน้าต้อง is_receipt=True — ไม่งั้นเทมเพลตจะพิมพ์ด้วยถ้อยคำ "
        "ใบแจ้งหนี้ ('เรียกเก็บจาก'/'ยอดค้างชำระ') ผิดทั้งใบโดยไม่มีอะไรฟ้อง"
    )


async def test_deposit_document_renders_and_speaks_as_a_receipt():
    """เรนเดอร์ใบรับเงินล่วงหน้าจริง — ต้องไม่ระเบิด และต้องไม่มีคำของใบแจ้งหนี้

    ← เทสต์นี้ **ล้ม (TypeError) ถ้าเอา `"remaining": None` ออก** จาก `_document_context`
      ซึ่งเป็นบั๊กที่ทำให้ผู้ใช้ดาวน์โหลด PDF ไม่ได้เลย (HTTP 500 จาก Gotenberg path)
    """
    from services.finance.pdf import render_receipt_html

    html = render_receipt_html(ReceiptsMixin._document_context(_deposit_doc()))

    assert ">None<" not in html, "มี None หลุดขึ้นกระดาษ"
    for invoice_word in ("เรียกเก็บจาก", "ยอดค้างชำระ", "ผู้รับแจ้ง"):
        assert invoice_word not in html, (
            f"พบคำของ **ใบแจ้งหนี้** ('{invoice_word}') บนใบรับเงินล่วงหน้า — "
            "แปลว่าเทมเพลตไม่ได้ branch ด้วย `is_receipt`"
        )
    # 🧾 ถ้อยคำที่ต้องมี: หลักฐานว่ารับเงินมาแล้ว + บอกชัดว่ายังไม่ผูกกับบิล
    assert "ใบรับเงินล่วงหน้า" in html
    assert "ได้รับเงินจาก" in html
    assert "รับเงินล่วงหน้า" in html and "ยังไม่หักปิดบิลใด" in html, (
        "แถวรายการต้องบอกว่าเงินก้อนนี้ยังไม่ผูกกับบิล — ห้ามตกไปที่คำกลาง ๆ "
        "'รายการชำระเงิน' ซึ่งสื่อว่ามีบิลให้ชำระ"
    )
    assert "รายการชำระเงิน" not in html, "ต้องไม่เหลือคำ fallback ของเอกสารที่มีบิล"
    # 🗓️ ปี พ.ศ. บนเลขเอกสารต้องมาจาก "เหตุการณ์" ไม่ใช่วันที่กดพิมพ์
    assert "DEP-2569-0001" in html


async def test_deposit_document_omits_the_remaining_row_entirely():
    """ไม่มีบิล ⇒ ต้อง **ไม่มีแถว "คงเหลือ"** เลย (ไม่ใช่พิมพ์ 0.00)

    💡 เทมเพลตใช้ `{% if d.remaining is not none %}` โดยเจตนา — แถวที่พิมพ์ "คงเหลือ 0.00"
       บนเอกสารที่แนวคิดนี้ไม่มีความหมาย ทำให้ผู้อ่านเข้าใจผิดว่ามีบิลที่ปิดครบแล้ว
    """
    from services.finance.pdf import render_receipt_html

    html = render_receipt_html(ReceiptsMixin._document_context(_deposit_doc()))
    # 🔴 ต้องเล็งที่ **แถว** ไม่ใช่แค่คำว่า "คงเหลือ" — เพราะคำนี้โผล่ชอบธรรมใน
    #    "ประเภท: เงินรับล่วงหน้า (เครดิตคงเหลือของนักเรียน)" ซึ่งเป็นคำอธิบายที่ต้องการ
    #    ⚠️ เทสต์ที่ grep คำลอย ๆ จะล้มทั้งที่เทมเพลตถูก (จับผิดที่) — เล็ง markup ของแถวแทน
    assert '<td class="k">คงเหลือ</td>' not in html, (
        "ใบรับเงินล่วงหน้าไม่มีบิล ⇒ ต้องไม่มี **แถว** 'คงเหลือ' (คนละเรื่องกับคำว่า "
        "'เครดิตคงเหลือของนักเรียน' ในบรรทัดประเภท ซึ่งต้องมี)"
    )
    assert '<td class="k">ยอดค้างชำระ</td>' not in html, "ห้ามมีแถวของใบแจ้งหนี้บนใบรับเงิน"


async def test_receipt_context_still_computes_remaining_from_the_bill():
    """ใบเสร็จของ **บิล** ยังต้องคำนวณ `remaining` ตามเดิม — การแก้ต้องไม่กระทบของเดิม

    ⚠️ เทสต์คู่นี้จำเป็นเพราะวิธีแก้บั๊กคือ "ตั้ง None ให้เสมอ" ซึ่งถ้าลวกมือ
       (เช่นตั้ง None **หลัง** if) จะทำให้ใบเสร็จของบิลทุกใบหายแถว "คงเหลือ" เงียบ ๆ
    """
    ctx = ReceiptsMixin._document_context(_deposit_doc(
        doc_type=DOC_TYPE_RECEIPT,
        doc_type_label="ใบเสร็จรับเงิน",
        receipt_no="REC-2569-0009",
        collection_id=5,
        collection_title="ค่าไปทัศนศึกษา",
        collection_amount=1000.0,
        collection_due_date=date(2026, 9, 10),
        amount=700.0,          # ยอดที่เครดิตจ่ายงวดนี้
        paid_total_after=1000.0,  # ยอดสะสมหลังปิดบิล
    ))

    assert ctx["collection_amount"] == 1000.0
    assert ctx["remaining"] == 0.0, "คงเหลือ = ยอดเต็ม − ยอดสะสม"
    assert ctx["is_receipt"] is True
