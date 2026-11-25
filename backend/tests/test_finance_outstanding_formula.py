"""📐 [FIN-V2 / P6.2] สูตรยอดค้าง = `FC.amount - paid_amount - written_off_amount` ทุกจุด

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมีเทสต์ชุดนี้แยกจากเทสต์อื่น
═══════════════════════════════════════════════════════════════════════════════
`student_payments.written_off_amount` เป็นคอลัมน์ใหม่ — จุดอ่านยอดค้างที่มีอยู่เดิม
**ทุกจุด** ใช้สูตร 2 พจน์ (`amount - paid`) ⇒ ถ้าลืมจุดใด จุดนั้นจะรายงานยอดค้าง
เกินจริงทันทีที่ผู้ใช้ตัดจำหน่ายบิล (ความเสี่ยง #8 ของแผน)

เทสต์ชุดนี้จึง "ปลูกบิลเดียวกัน ตัดจำหน่าย 400 จาก 1,000" แล้วเดินไปถามทุกจุดอ่าน
ที่ผู้ใช้เห็นจริง — ทุกจุดต้องตอบ **600.00** (หรือตัดบิลนั้นออกจากรายการ ถ้าตัดครบ)

📍 จุดที่ตรวจ (ตรงกับตารางใน brief P6.2)
  · /finance/debtors            → collections.py (hot ของ P2.1 — ดู xfail ล่างสุด)
  · /finance/receivables/aging  → receivables.py
  · /finance/summary            → reporting.py (legacy + v2 ใช้ query เดียวกัน)
  · ใบแจ้งหนี้รวม               → receipts.py (`_load_student_outstanding`)
  · export ทะเบียนลูกหนี้        → export.py
  · ฐานค่าปรับล่าช้า             → late_fees.py
  · เตือนผู้ค้างชำระ             → reminders.py
  · /me/stats                   → me_activity_service.py
  · /home/summary               → home_summary_service.py
  · /finance/credits            → credits.py (`get_credit_balances`)
  · revert_transaction          → transactions.py (คำนวณสถานะใหม่จาก 3 พจน์)
"""
from datetime import date, timedelta

import pytest

from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
BILL_AMOUNT = 1000.0
WRITE_OFF = 400.0
EXPECTED_OUTSTANDING = 600.0


# ═══════════════════════════════════════════════════════════════════ helpers
async def _insert_account(pool, room_id: int, balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance, is_custody)
               VALUES ($1, 'กระเป๋ากลาง', $2, FALSE) RETURNING id""",
            room_id, balance,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *, amount: float = BILL_AMOUNT,
    due_in_days: int = -10, late_fee_mode: str = "none",
    late_fee_amount: float = 0.0,
) -> tuple[int, int]:
    """บิลดิบ (ไม่มี accrual journal) — พอสำหรับจุดอ่านยอดค้าง"""
    due = date.today() + timedelta(days=due_in_days)
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind,
                    late_fee_mode, late_fee_amount, late_fee_grace_days)
               VALUES ($1, 'ค่าเทอม 1/2569', $2, $3, 'active', 'room_fund', 'project',
                       $4, $5, 0)
               RETURNING id""",
            room_id, amount, due, late_fee_mode, late_fee_amount,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', 0, 0) RETURNING id""",
            collection_id, student_id,
        )
    return collection_id, payment_id


def _write_off(client, headers, room_id: int, payment_id: int, amount: float):
    return client.post(
        f"{API_PREFIX}/{room_id}/finance/payments/{payment_id}/write-off",
        json={
            "amount": amount,
            "reason": "ตัดหนี้สูญทดสอบสูตรยอดค้าง",
            "idempotency_key": f"p62-formula-{payment_id}-{amount}",
        },
        headers=headers,
    )


async def _setup_written_off_bill(pool, client, headers, **bill_kwargs):
    _, payment_id = await _insert_bill(
        pool, headers.room_id, headers.student_id, **bill_kwargs,
    )
    res = _write_off(client, headers, headers.room_id, payment_id, WRITE_OFF)
    assert res.status_code == 200, res.text
    return payment_id


# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ 1. /finance/debtors — อยู่ใน collections.py ซึ่ง P6.2 **ห้ามแก้เอง**
#    (Gotcha 1 ของ brief: hot file ของ P2.1) ⇒ ยังเป็นสูตร 2 พจน์
#    ⇒ xfail(strict=True): ถ้าวันหนึ่งมีคนแก้ collections.py ให้ถูก เทสต์นี้จะ
#    "unexpectedly pass" แล้วเตือนให้เปลี่ยนเป็นเทสต์ปกติทันที
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.xfail(
    strict=True,
    reason=(
        "P6.2 ห้ามแก้ collections.py (hot ของ P2.1) — get_all_debtors ยอดค้างยังเป็น 2 พจน์ "
        "ต้องประสานเจ้าของ P2.1 แก้ collections.py:1030 แล้วถอด xfail"
    ),
)
async def test_outstanding_reflects_written_off_in_debtors(
    client, db_pool, admin_headers,
):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/finance/debtors", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["student_id"] == admin_headers.student_id)
    assert float(row["total_pending_amount"]) == EXPECTED_OUTSTANDING


# ═══════════════════════════════════════════════════════ 2. receivables aging
async def test_outstanding_reflects_written_off_in_aging(
    client, db_pool, admin_headers,
):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/finance/receivables/aging",
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert float(data["grand_total"]) == EXPECTED_OUTSTANDING
    rows = [r for r in data["rows"] if r["student_id"] == admin_headers.student_id]
    assert len(rows) == 1
    assert float(rows[0]["outstanding"]) == EXPECTED_OUTSTANDING


# ═════════════════════════════════════════════════ 3. /finance/summary pending
async def test_outstanding_reflects_written_off_in_summary_pending(
    client, db_pool, admin_headers,
):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/finance/summary", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert float(res.json()["pending_collection_amount"]) == EXPECTED_OUTSTANDING


# ══════════════════════════════ 4. ใบแจ้งหนี้รวม (`_load_student_outstanding`)
async def test_outstanding_reflects_written_off_in_receipts_breakdown(
    client, db_pool, admin_headers,
):
    """🔍 เรียก helper ตรง ๆ — เป็น "breakdown" ภายในที่ใบ INV รวมใช้ (ไม่มี route ของตัวเอง)

    ต้องอยู่ใน transaction ตามสัญญาของ caller (อ่านยอดค้างหลายแถวขณะถือล็อกห้อง)
    """
    room, student = admin_headers.room_id, admin_headers.student_id
    await _setup_written_off_bill(db_pool, client, admin_headers)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            rows = await FinanceService._load_student_outstanding(conn, student, room)

    assert len(rows) == 1
    assert float(rows[0]["outstanding"]) == EXPECTED_OUTSTANDING
    # ยอดค้างบนใบ INV ต้องเป็น "ยอดที่ยังต้องเก็บจริง" — 1,000 - 0 จ่าย - 400 ตัด
    assert float(rows[0]["bill_amount"]) == BILL_AMOUNT


# ═════════════════════════════════════════ 5. export ทะเบียนลูกหนี้ (AR sheet)
async def test_outstanding_reflects_written_off_in_export(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    await _setup_written_off_bill(db_pool, client, admin_headers)

    async with db_pool.acquire() as conn:
        ar = await FinanceService._fetch_accounts_receivable(conn, room)

    assert float(ar["total_outstanding"]) == EXPECTED_OUTSTANDING
    assert ar["rows"][0]["outstanding"] == EXPECTED_OUTSTANDING


# ═══════════════════════════════════════════════ 6. ฐานคำนวณค่าปรับล่าช้า
async def test_outstanding_reflects_written_off_in_late_fee_base(
    client, db_pool, admin_headers,
):
    """ค่าปรับคิดจากยอดที่ **ยังค้างจริง** — บิลที่ตัดครบต้องไม่ถูกปรับอีก"""
    room, student = admin_headers.room_id, admin_headers.student_id
    _, partial_id = await _insert_bill(
        db_pool, room, student, due_in_days=-10,
        late_fee_mode="fixed", late_fee_amount=50.0,
    )
    assert _write_off(client, admin_headers, room, partial_id, WRITE_OFF).status_code == 200

    _, full_id = await _insert_bill(
        db_pool, room, student, due_in_days=-10,
        late_fee_mode="fixed", late_fee_amount=50.0,
    )
    assert _write_off(client, admin_headers, room, full_id, BILL_AMOUNT).status_code == 200

    async with db_pool.acquire() as conn:
        candidates = await FinanceService._collect_late_fee_candidates(
            conn, as_of=date.today(), room_id=room,
        )

    ids = {r["payment_id"] for r in candidates}
    assert partial_id in ids
    assert full_id not in ids                          # ตัดครบ = ไม่ค้าง = ไม่ปรับ
    partial = next(r for r in candidates if r["payment_id"] == partial_id)
    assert float(partial["outstanding"]) == EXPECTED_OUTSTANDING


# ═════════════════════════════════════════════════ 7. เตือนผู้ค้างชำระรายวัน
async def test_outstanding_reflects_written_off_in_reminders(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    await _setup_written_off_bill(db_pool, client, admin_headers, due_in_days=1)

    async with db_pool.acquire() as conn:
        bills = await FinanceService._collect_reminder_bills(
            conn, as_of=date.today(), room_id=room,
        )

    assert len(bills) == 1
    assert float(bills[0]["outstanding"]) == EXPECTED_OUTSTANDING


# ═══════════════════════════════════════════════════════ 8. /me/stats outstanding
async def test_me_outstanding_reflects_written_off(client, db_pool, admin_headers):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/me/stats", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert float(res.json()["outstanding"]) == EXPECTED_OUTSTANDING


# ════════════════════════════════════════════════════ 9. /home/summary outstanding
async def test_home_summary_outstanding_reflects_written_off(
    client, db_pool, admin_headers,
):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/home/summary", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    finance = res.json()["finance"]
    assert finance["has_profile"] is True
    assert float(finance["outstanding"]) == EXPECTED_OUTSTANDING


# ══════════════════════════════════════════ 10. /finance/credits ยอดค้างดิบต่อคน
async def test_credit_apply_candidates_exclude_written_off(
    client, db_pool, admin_headers,
):
    await _setup_written_off_bill(db_pool, client, admin_headers)
    res = client.get(
        f"{API_PREFIX}/{admin_headers.room_id}/finance/credits", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["student_id"] == admin_headers.student_id)
    assert float(row["total_pending_amount"]) == EXPECTED_OUTSTANDING


# ═══════════════════════ 11. revert_transaction — สถานะใหม่ต้องคำนึงถึง written_off
async def test_revert_transaction_keeps_status_consistent_with_written_off(
    client, db_pool, admin_headers,
):
    """จ่าย 600 → ตัด 400 (ตัดครบ ⇒ waived) → ยกเลิกการจ่าย

    🎯 หลังยกเลิก: paid=0, written_off=400, ค้าง 600 ⇒ ต้องกลับเป็น `pending`
       (ถ้าโค้ดเดิมคิดแค่ `paid vs total` มันจะตั้ง `pending` ถูกโดยบังเอิญในเคสนี้ —
       แต่เคส "จ่ายครบ + ตัดครบ" ด้านล่างคือเคสที่สูตร 2 พจน์ตั้งผิด)
    """
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student, due_in_days=0)
    account = await _insert_account(db_pool, room)

    pay = client.put(
        f"{API_PREFIX}/{room}/finance/payments/{payment_id}/pay",
        json={
            "paid_to_account_id": account,
            "paid_amount": 600.0,
            "user_name": "ครูสมศรี",
        },
        headers=admin_headers,
    )
    assert pay.status_code == 200, pay.text

    assert _write_off(client, admin_headers, room, payment_id, WRITE_OFF).status_code == 200
    row = await _db_row(db_pool, payment_id)
    assert row["status"] == "waived"                   # 600 + 400 = 1000 ตัดครบ

    async with db_pool.acquire() as conn:
        txn_id = await conn.fetchval(
            """SELECT id FROM finance_transactions
               WHERE student_payment_id = $1 AND deleted_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            payment_id,
        )
    assert txn_id is not None

    revert = client.delete(
        f"{API_PREFIX}/{room}/finance/transactions/{txn_id}", headers=admin_headers,
    )
    assert revert.status_code == 200, revert.text

    row = await _db_row(db_pool, payment_id)
    assert float(row["paid_amount"]) == 0.0
    assert float(row["written_off_amount"]) == WRITE_OFF   # written_off ไม่ถูกย้อน
    assert row["status"] == "pending"                      # ยังค้าง 600 ⇒ เปิดบิลอีกครั้ง


async def _db_row(pool, payment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT paid_amount, written_off_amount, status FROM student_payments WHERE id = $1",
            payment_id,
        )
