"""🛡️ [FIN-V2 / P6.1] guard ของ void engine — กันก่อนแตะเงินเสมอ

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **เครดิตที่ถูกใช้ต่อแล้ว** ⇒ ยกเลิก event ที่เติมเครดิตนั้นไม่ได้ (409)
   ไม่งั้นจะถอนเครดิตที่นักเรียนใช้ไปแล้ว = ยอดคงเหลือติดลบ/เพี้ยน
2. **เงินในกระเป๋าไม่พอคืน** (INC) ⇒ 409 ไม่ปล่อยให้ `balance` ติดลบ
   (ตาราง `finance_accounts` ไม่มี CHECK กันติดลบ ⇒ ต้องดักที่ service)
3. **legacy ไม่ผ่าน engine นี้** ⇒ 409 ชี้ไปทาง revert รายการเงินเดิม
4. **ล็อกห้องเป็น statement แรกหลัง permission** — ตรวจลำดับจากซอร์สจริง
   (พฤติกรรมของ advisory lock ถูกพิสูจน์ใน `test_finance_money_lock.py`)
5. **ไม่มี DELETE ในไฟล์ engine** — void = soft delete เท่านั้น

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import inspect
import random
import string
import uuid
from pathlib import Path

import pytest

import services.finance as finance_pkg
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"


# ═══════════════════════════════════════════════════════════════════ helpers
def _events_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events"


def _event_void_url(room_id: int, event_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events/{event_id}/void"


def _batches_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/income-batches?target_type=room"


def _batch_void_url(room_id: int, batch_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/income-batches/{batch_id}/void"
        "?target_type=room"
    )


def _vouchers_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers?target_type=room"


def _voucher_void_url(room_id: int, voucher_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/expense-vouchers/{voucher_id}/void"
        "?target_type=room"
    )


def _doc_void_url(room_id: int, doc_type: str, doc_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/documents/{doc_type}/{doc_id}/void"


def _money(value) -> str:
    return f"{float(value):.2f}"


def _key() -> str:
    return uuid.uuid4().hex


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


async def _insert_bill(pool, room_id: int, student_id: int, amount: float = 1000.0) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, 'ค่าเทอม', $2, NULL, 'active', 'room_fund', 'project')
               RETURNING id""",
            room_id, amount,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', 0, 0) RETURNING id""",
            collection_id, student_id,
        )


async def _event_payload(student_id: int, account_id: int, *, cash: str) -> dict:
    return {
        "idempotency_key": _key(),
        "student_id": student_id,
        "wallet_account_id": account_id,
        "payer_name": "ผู้ปกครองทดสอบ",
        "receiver_name": RECEIVER,
        "amount_received": cash,
        "use_credit": False,
        "excess_action": "credit",
        "bill_selection": "auto",
    }


async def _insert_apply(
    pool, room_id: int, student_id: int, *, amount: float, balance_after: float,
    payment_id: int | None = None,
) -> int:
    """แถว `apply` ที่มี id มากกว่า topup ของ event — จำลอง "เครดิตถูกใช้ภายหลัง\""""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after,
                    student_payment_id, note)
               VALUES ($1, $2, 'apply', $3, $4, $5, 'ใช้เครดิตปิดบิลอื่น')
               RETURNING id""",
            room_id, student_id, amount, balance_after, payment_id,
        )


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


def _income_payload(*, wallet_account_id: int, category_id: int, amount: float) -> dict:
    return {
        "idempotency_key": _key(),
        "payer_name": "ผู้ปกครองนักเรียน ม.2",
        "wallet_account_id": wallet_account_id,
        "receiver_name": "ครูสมหญิง",
        "note": "รายรับอื่นทดสอบ",
        "lines": [{
            "description": "เงินสนับสนุนกิจกรรม",
            "amount": _money(amount),
            "category_id": category_id,
        }],
    }


def _voucher_payload(*, default_wallet_account_id: int, category_id: int, lines: list) -> dict:
    return {
        "idempotency_key": _key(),
        "default_wallet_account_id": default_wallet_account_id,
        "payee_name": "ร้านวัสดุทดสอบ",
        "note": "ใบสำคัญจ่ายทดสอบ",
        "approved_by_name": "ครูอนุมัติ",
        "lines": [
            {
                "description": desc,
                "amount": _money(amt),
                "category_id": category_id,
                "wallet_account_id": wallet_id,
                "receipt_status": "attached",
                "paper_bill_count": 0,
                "funding_source": "room_fund",
            }
            for amt, wallet_id, desc in lines
        ],
    }


# ═════════════ 16. เครดิตส่วนเกินจาก event ถูกใช้ปิดบิลอื่น ⇒ void event ต้อง 409
async def test_event_credit_used_later_blocks_void_409(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=1000.0)

    created = client.post(
        _events_url(room),
        json=await _event_payload(student, account, cash="1500.00"),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    assert data["credit_added"] == "500.00"

    # 📤 ใช้เครดิต 200 ไปปิดบิลอื่น (id มากกว่า topup ของ event ⇒ ถูกใช้ภายหลังแน่นอน)
    await _insert_apply(db_pool, room, student, amount=200.0, balance_after=300.0)

    res = client.post(
        _event_void_url(room, data["event_id"]),
        json={"reason": "ยกเลิกทั้งที่ใช้เครดิตไปแล้ว"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert "ถูกใช้ไปแล้ว" in detail
    assert "200.00" in detail

    # ไม่มีอะไรถูกแตะ
    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM finance_payment_events WHERE id = $1", data["event_id"]
        )
        doc_status = await conn.fetchval(
            "SELECT status FROM finance_receipts WHERE payment_event_id = $1 AND doc_type = 'receipt'",
            data["event_id"],
        )
    assert status == "active"
    assert doc_status == "active"
    assert _money(await _balance(db_pool, account)) == "1500.00"


# ═══════════════ 17. DEP (event เติมเครดิต ไม่มีบิล) ที่เครดิตถูกใช้ ⇒ void event 409
async def test_dep_credit_used_later_blocks_event_void_409(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)

    created = client.post(
        _events_url(room),
        json=await _event_payload(student, account, cash="500.00"),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    data = created.json()
    assert data["receipt_no"] is None          # เติมเครดิตล้วน = ไม่มี REC
    assert data["deposit_no"].startswith("DEP-")

    await _insert_apply(db_pool, room, student, amount=500.0, balance_after=0.0)

    res = client.post(
        _event_void_url(room, data["event_id"]),
        json={"reason": "พยายามยกเลิก DEP ที่ถูกใช้แล้ว"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "500.00" in res.json()["detail"]

    assert _money(await _balance(db_pool, account)) == "500.00"


# ═══════════════════ 18. INC ที่เงินในกระเป๋าถูกใช้ไปแล้ว ⇒ 409 (กันยอดติดลบ)
async def test_void_inc_blocked_when_wallet_insufficient_409(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม", "income")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    created = client.post(
        _batches_url(room),
        json=_income_payload(wallet_account_id=wallet, category_id=cat, amount=2000.0),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    batch_id = created.json()["id"]
    assert _money(await _balance(db_pool, wallet)) == "2000.00"

    # 💸 ใช้เงินไป 1500 (จำลองด้วยการปรับ balance ตรง ๆ — ทางใช้เงินจริงมี guard ของมันเอง)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_accounts SET balance = 500 WHERE id = $1", wallet,
        )

    res = client.post(
        _batch_void_url(room, batch_id),
        json={"reason": "ยกเลิกหลังใช้เงินไปแล้ว"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert "ไม่พอคืน" in detail
    assert "500.00" in detail
    assert "2,000.00" in detail

    # 🚫 ไม่มีอะไรถูกแตะ — ยอดกระเป๋าไม่ติดลบ, INC/batch ยัง active
    assert _money(await _balance(db_pool, wallet)) == "500.00"
    async with db_pool.acquire() as conn:
        batch = await conn.fetchrow(
            "SELECT status, voided_at FROM finance_income_batches WHERE id = $1",
            batch_id,
        )
        inc = await conn.fetchrow(
            "SELECT status, deleted_at FROM finance_receipts WHERE id = $1",
            created.json()["inc_receipt_id"],
        )
        txns = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND income_batch_id = $2 AND deleted_at IS NULL""",
            room, batch_id,
        )
    assert batch["status"] == "active" and batch["voided_at"] is None
    assert inc["status"] == "active" and inc["deleted_at"] is None
    assert txns == 1


# ═══════════ 19. legacy receipt (layout 1 / ไม่มี event) ไม่ผ่าน engine นี้ ⇒ 409 ชี้ทางเดิม
async def test_void_legacy_receipt_points_to_transaction_revert_409(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    async with db_pool.acquire() as conn:
        receipt_id = await conn.fetchval(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, amount,
                    paid_total_after, layout_version, payment_event_id)
               VALUES ($1, 'REC-2569-9001', 'receipt', 2569, 9001, 100, 100, 1, NULL)
               RETURNING id""",
            room,
        )

    res = client.post(
        _doc_void_url(room, "receipt", receipt_id),
        json={"reason": "ยกเลิกใบเสร็จเก่า"}, headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "รายการเงินที่ออกเอกสาร" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, deleted_at FROM finance_receipts WHERE id = $1",
            receipt_id,
        )
    assert row["status"] == "active" and row["deleted_at"] is None


# ═══════════════════ 20. ล็อกห้องถูกยึดเป็น statement แรกหลัง permission (ตรวจจากซอร์ส)
async def test_void_uses_money_lock_first():
    """🧪 เชิงโครงสร้างโดยเจตนา: "ล็อกก่อนอ่าน/เขียนเงิน" สังเกตจาก HTTP ไม่ได้

    🎯 ตรวจว่าในทุก public void method:
       1. `require_permission` มาก่อน `_lock_room_money` (สิทธิ์ก่อนเสมอ)
       2. `_lock_room_money` มาก่อน `FOR UPDATE` แถวเงินทุกแถว
       3. `_lock_room_money` มาก่อนการเรียก `_void_*_locked` ที่ลงมือกลับขาเงิน

    ⚠️ ขอบเขตของหลักฐาน: เทสต์นี้พิสูจน์ "ลำดับในซอร์ส" ไม่ได้ยิง concurrent จริง —
       พฤติกรรมของ advisory lock ถูกพิสูจน์แล้วใน `test_finance_money_lock.py`
    """
    targets = {
        "void_payment_event": "_void_event_locked",
        "void_expense_voucher": "_void_voucher_locked",
        "void_income_batch": "_void_income_locked",
        "void_document": "_void_receipt_doc_locked",
    }
    for method_name, helper_name in targets.items():
        src = inspect.getsource(getattr(FinanceService, method_name))
        perm_at = src.find("await require_permission(")
        lock_at = src.find("await _lock_room_money(")
        helper_at = src.find(f"await cls.{helper_name}(")
        assert perm_at != -1, f"{method_name}: ไม่พบ require_permission"
        assert lock_at != -1, (
            f"{method_name}: แตะเงินแต่ไม่ยึด advisory lock ของห้องเลย"
        )
        assert perm_at < lock_at, (
            f"{method_name}: ยึดล็อกก่อนตรวจสิทธิ์ (ต้อง RBAC → reason → lock)"
        )
        assert helper_at != -1, f"{method_name}: ไม่พบการเรียก `{helper_name}`"
        assert lock_at < helper_at, (
            f"{method_name}: เรียก `{helper_name}` (กลับขาเงิน) ก่อนยึดล็อกห้อง"
        )
        row_lock_at = src.find("FOR UPDATE")
        assert row_lock_at == -1 or lock_at < row_lock_at, (
            f"{method_name}: อ่านแถวเงินด้วย FOR UPDATE ก่อนยึดล็อกห้อง"
        )


# ═══════════════ 21. void PV ไม่แตะกระเป๋า custody ที่ PV ไม่ได้ใช้จ่าย
async def test_void_pv_does_not_touch_custody_accounts(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน", "expense")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 500.0)
    custody = await _insert_account(
        db_pool, room, "กระเป๋าครู A (ถือเงิน)", 100.0, is_custody=True
    )

    created = client.post(
        _vouchers_url(room),
        json=_voucher_payload(
            default_wallet_account_id=wallet, category_id=cat,
            lines=[(150.0, wallet, "กระดาษ A4")],
        ),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    voucher_id = created.json()["id"]
    assert _money(await _balance(db_pool, wallet)) == "350.00"
    assert _money(await _balance(db_pool, custody)) == "100.00"

    res = client.post(
        _voucher_void_url(room, voucher_id),
        json={"reason": "ทำใบผิด"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    # กระเป๋าที่ PV ใช้ถูกคืน · กระเป๋า custody ไม่ถูกส่งเข้า `accounts` และไม่ขยับ
    assert _money(await _balance(db_pool, wallet)) == "500.00"
    assert _money(await _balance(db_pool, custody)) == "100.00"
    assert res.json()["reversed"]["accounts"] == [
        {"account_id": wallet, "delta": 150.0},
    ]


# ══════════════════════ 22. engine ใช้ soft delete เท่านั้น — ไม่มี DELETE/DROP ในไฟล์
async def test_void_engine_has_no_hard_delete():
    src = Path(finance_pkg.__file__).parent.joinpath("voids.py").read_text(encoding="utf-8")
    code_lines = [
        ln for ln in src.splitlines()
        if not ln.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "DELETE FROM" not in code, "void ต้องไม่ลบแถว — ใช้ status + deleted_at"
    assert "DROP " not in code
