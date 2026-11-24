"""📒 เกณฑ์คงค้าง (accrual AR) — migration + ledger helpers + journal helpers

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ล็อกอะไร
═══════════════════════════════════════════════════════════════════════════════
1. migration 0010 สร้างตาราง/index/คอลัมน์ครบ และ `collection_kind` มีค่าเริ่มต้น `project`
2. บัญชีผู้ค้างชำระ/ค่าปรับถูกสร้างด้วยรหัส/ชื่อ/ประเภทที่ถูก และ **idempotent**
3. collision guard: รหัสชนกับบัญชีที่ชื่อไม่ตรง หรือผูก legacy mapping → raise
   (ห้ามใช้บัญชีผิดเงียบ ๆ — งบยัง Dr = Cr ครบแต่ยอดโผล่ผิดที่)
4. ออกบิล → Dr AR / Cr รายได้ คู่ที่ถูก (โปรเจกต์ vs ค่าปรับ) และลงซ้ำไม่ได้
5. `_bill_ar_source` แยก `issue` / `opening` / `none` ถูก
6. กลับรายการ/ปรับยอดใช้ **รายได้** เมื่อ AR มาจาก issue และใช้ **equity 31002**
   เมื่อมาจาก opening (ห้ามแตะรายได้งวดนี้)
7. `_create_bills_with_accrual` สร้างบิลคนละใบต่อคน + journal ต่อใบ
8. predicate "บิลเปิด" ไม่กรอง `FC.status` (ปิดโปรเจกต์ ≠ ล้างหนี้)

⚠️ ทุกข้อตรวจกับ DB จริงผ่าน `db_pool` (ไม่เชื่อแค่ค่าที่ฟังก์ชันคืน)
"""
import uuid
from datetime import date

import pytest

from services.finance.accrual import (
    AR_SOURCE_ISSUE,
    AR_SOURCE_NONE,
    AR_SOURCE_OPENING,
    OPEN_BILL_PREDICATE,
)
from services.finance.constants import (
    AR_FINE_CODE,
    AR_PROJECT_CODE,
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    DEFAULT_FINE_TYPES,
    DEFAULT_INCOME_CATEGORIES,
    FINE_DISCOUNT_CODE,
    FINE_REVENUE_CODE,
    OPENING_AR_EQUITY_CODE,
    REFERENCE_TYPE_OPENING_RECEIVABLE,
    SYSTEM_LEDGER_SPECS,
)
from services.finance.service import FinanceService

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _make_room(pool, name: str = "ห้องทดสอบ accrual") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            name, f"ACC{uuid.uuid4().hex[:6].upper()}",
        )


async def _make_student(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            "เด็กชายทดสอบ", "คงค้าง", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _make_bill(
    pool,
    room_id: int,
    student_id: int,
    *,
    title: str = "ค่าเทอม",
    amount: float = 1000.0,
    paid: float = 0.0,
    status: str = "pending",
    kind: str = COLLECTION_KIND_PROJECT,
    collection_status: str = "active",
) -> tuple[int, int]:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, collection_kind)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            room_id, title, amount, date(2026, 12, 31), collection_status, kind,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            collection_id, student_id, status, paid,
        )
    return collection_id, payment_id


async def _journal_lines(pool, *, reference_type: str, reference_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT AL.account_code, AL.account_name, AL.account_type,
                      L.debit, L.credit
               FROM journal_entries JE
               JOIN journal_lines L ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON AL.id = L.ledger_id
               WHERE JE.reference_type = $1 AND JE.reference_id = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
               ORDER BY L.id""",
            reference_type, str(reference_id),
        )


async def _ledger_net(pool, room_id: int, code: str) -> float:
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_entries JE
               JOIN journal_lines L ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON AL.id = L.ledger_id
               WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND AL.room_id = $1 AND AL.account_code = $2""",
            room_id, code,
        )
    return round(float(value or 0), 2)


async def _revenue_ledger_code(pool, room_id: int) -> str:
    """รหัสบัญชีรายได้เริ่มต้นของห้อง (รหัสถูกสร้างอัตโนมัติเป็น `4<category_id>`)"""
    async with pool.acquire() as conn:
        code = await conn.fetchval(
            """SELECT account_code FROM accounting_ledgers
               WHERE room_id = $1 AND account_name = $2 AND account_type = 'revenue'""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
    assert code is not None, "ไม่พบ ledger รายได้เริ่มต้น"
    return code


async def _journal_count(pool, room_id: int, reference_type: str) -> int:
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND reference_type = $2
                 AND deleted_at IS NULL AND status <> 'voided'""",
            room_id, reference_type,
        ))


async def _post_opening_journal(pool, room_id: int, payment_id: int, amount: float) -> None:
    """จำลอง journal ยอดยกมาที่ opening script จะเขียน (Dr AR / Cr equity 31002)"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            ledgers = await FinanceService.ensure_finance_ledgers(conn, room_id)
            await FinanceService._insert_journal_entry(
                conn, room_id,
                reference_type=REFERENCE_TYPE_OPENING_RECEIVABLE,
                reference_id=str(payment_id),
                description="ยอดยกมาทดสอบ",
                recorded_by="SYSTEM",
                lines=[
                    {"ledger_id": ledgers[AR_PROJECT_CODE], "debit": amount, "credit": 0},
                    {"ledger_id": ledgers[OPENING_AR_EQUITY_CODE], "debit": 0, "credit": amount},
                ],
            )


# ═══════════════════════════════════════════════════════════════ 1. migration
async def test_migration_0010_creates_schema(db_pool):
    tables = (
        "fine_types", "fine_batches", "fines", "fine_waivers", "fine_refunds",
        "reminder_dispatch_log",
    )
    indexes = (
        "idx_fine_types_room_active",
        "uq_fine_batches_idempotency",
        "uq_fines_student_payment",
        "uq_fine_waivers_pending",
        "uq_fine_refunds_pending",
        "uq_reminder_dispatch",
        "idx_finance_receipts_fine_invoice_active",
        "uq_journal_bill_issue",
    )

    async with db_pool.acquire() as conn:
        for table in tables:
            assert await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
            ), f"ไม่พบตาราง {table}"

        data_type, default = await conn.fetchrow(
            """SELECT data_type, column_default
               FROM information_schema.columns
               WHERE table_name = 'fee_collections' AND column_name = 'collection_kind'"""
        )
        assert data_type == "text"
        assert "'project'" in default

        found = {
            r["indexname"] for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])",
                list(tables) + ["finance_receipts", "journal_entries"],
            )
        }
        assert set(indexes) <= found


async def test_default_fine_types_are_five_and_editable():
    """seed 5 รายการตามที่อนุมัติ — ชื่อไม่ซ้ำ และรายการ "อื่น ๆ" ตั้งยอด 0 (ต้องกรอกเอง)"""
    assert len(DEFAULT_FINE_TYPES) == 5
    names = [t["name"] for t in DEFAULT_FINE_TYPES]
    assert len(set(names)) == 5
    assert DEFAULT_FINE_TYPES[-1]["default_amount"] == 0
    assert all(t["default_due_days"] == 7 for t in DEFAULT_FINE_TYPES)


# ═══════════════════════════════════════════════════════ 2–3. ledger helpers
async def test_ensure_finance_ledgers_creates_all_and_is_idempotent(db_pool):
    room_id = await _make_room(db_pool)

    async with db_pool.acquire() as conn:
        first = await FinanceService.ensure_finance_ledgers(conn, room_id)
        second = await FinanceService.ensure_finance_ledgers(conn, room_id)

        assert first == second
        assert set(first) == set(SYSTEM_LEDGER_SPECS)

        rows = await conn.fetch(
            """SELECT account_code, account_name, account_type,
                      legacy_account_id, legacy_category_id
               FROM accounting_ledgers WHERE room_id = $1""",
            room_id,
        )

    assert len(rows) == len(SYSTEM_LEDGER_SPECS)
    for row in rows:
        expected_name, expected_type = SYSTEM_LEDGER_SPECS[row["account_code"]]
        assert row["account_name"] == expected_name
        assert row["account_type"] == expected_type
        assert row["legacy_account_id"] is None
        assert row["legacy_category_id"] is None


async def test_ensure_rejects_same_code_with_different_name(db_pool):
    """รหัสชนกันแต่ชื่อไม่ตรง = ห้ามใช้ต่อ (อาจเป็นบัญชี auto ของคนอื่น)"""
    room_id = await _make_room(db_pool)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type)
               VALUES ($1, $2, 'บัญชีที่ชนกัน', 'asset')""",
            room_id, AR_PROJECT_CODE,
        )
        with pytest.raises(ValueError, match="ชน"):
            await FinanceService.ensure_finance_ledgers(conn, room_id)


async def test_ensure_rejects_ledger_with_legacy_mapping(db_pool):
    """ledger ที่ผูก legacy mapping ไม่ใช่บัญชีของระบบ — ต้องไม่ถูกใช้ต่อ"""
    room_id = await _make_room(db_pool)
    async with db_pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'กระเป๋า', 0) RETURNING id",
            room_id,
        )
        await conn.execute(
            """INSERT INTO accounting_ledgers
                   (room_id, account_code, account_name, account_type, legacy_account_id)
               VALUES ($1, $2, $3, 'asset', $4)""",
            room_id, AR_PROJECT_CODE, SYSTEM_LEDGER_SPECS[AR_PROJECT_CODE][0], account_id,
        )
        with pytest.raises(ValueError, match="legacy"):
            await FinanceService.ensure_finance_ledgers(conn, room_id)


# ══════════════════════════════════════════════════════════ 4. bill accrual
async def test_bill_accrual_project_uses_ar_project_and_default_income(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            entry_id = await FinanceService._post_bill_accrual(
                conn, room_id, payment_id, amount=1000,
                collection_kind=COLLECTION_KIND_PROJECT, recorded_by="tester",
            )
        assert entry_id is not None

    lines = await _journal_lines(db_pool, reference_type="student_payment_issue", reference_id=payment_id)
    assert len(lines) == 2
    dr = next(l for l in lines if float(l["debit"]) > 0)
    cr = next(l for l in lines if float(l["credit"]) > 0)
    assert dr["account_code"] == AR_PROJECT_CODE
    assert float(dr["debit"]) == 1000
    assert cr["account_name"] == DEFAULT_INCOME_CATEGORIES[0]
    assert float(cr["credit"]) == 1000

    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 1000
    assert await _ledger_net(db_pool, room_id, AR_FINE_CODE) == 0


async def test_bill_accrual_fine_uses_fine_accounts(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(
        db_pool, room_id, student_id, amount=50, kind=COLLECTION_KIND_FINE,
        title="ค่าปรับ · มาสาย",
    )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(
                conn, room_id, payment_id, amount=50,
                collection_kind=COLLECTION_KIND_FINE,
            )

    lines = await _journal_lines(db_pool, reference_type="student_payment_issue", reference_id=payment_id)
    codes = {l["account_code"]: (float(l["debit"]), float(l["credit"])) for l in lines}
    assert codes[AR_FINE_CODE] == (50.0, 0.0)
    assert codes[FINE_REVENUE_CODE] == (0.0, 50.0)

    assert await _ledger_net(db_pool, room_id, AR_FINE_CODE) == 50
    assert await _ledger_net(db_pool, room_id, FINE_REVENUE_CODE) == -50
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 0


async def test_bill_accrual_is_idempotent_per_bill(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=300)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            assert await FinanceService._post_bill_accrual(
                conn, room_id, payment_id, amount=300
            )
        async with conn.transaction():
            assert await FinanceService._post_bill_accrual(
                conn, room_id, payment_id, amount=300
            ) is None

    assert await _journal_count(db_pool, room_id, "student_payment_issue") == 1
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 300


# ═══════════════════════════════════════════════════ 5. source resolution
async def test_bill_ar_source_distinguishes_issue_opening_none(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, issued = await _make_bill(db_pool, room_id, student_id, amount=100)
    _, opening = await _make_bill(db_pool, room_id, student_id, amount=200)
    _, untouched = await _make_bill(db_pool, room_id, student_id, amount=300)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(conn, room_id, issued, amount=100)

    await _post_opening_journal(db_pool, room_id, opening, 200)

    async with db_pool.acquire() as conn:
        assert await FinanceService._bill_ar_source(conn, issued) == AR_SOURCE_ISSUE
        assert await FinanceService._bill_ar_source(conn, opening) == AR_SOURCE_OPENING
        assert await FinanceService._bill_ar_source(conn, untouched) == AR_SOURCE_NONE


# ═════════════════════════════════════════════════ 6. reversal / adjustment
async def test_reversal_of_issue_hits_revenue(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(conn, room_id, payment_id, amount=1000)
        async with conn.transaction():
            entry = await FinanceService._post_bill_reversal(
                conn, room_id, payment_id, amount=1000,
            )
        assert entry is not None

    revenue_code = await _revenue_ledger_code(db_pool, room_id)
    lines = await _journal_lines(
        db_pool, reference_type="student_payment_reversal", reference_id=payment_id
    )
    codes = {l["account_code"]: (float(l["debit"]), float(l["credit"])) for l in lines}
    assert codes[AR_PROJECT_CODE] == (0.0, 1000.0)
    assert codes[revenue_code] == (1000.0, 0.0)

    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 0
    assert await _ledger_net(db_pool, room_id, revenue_code) == 0


async def test_reversal_of_opening_hits_equity_not_revenue(db_pool):
    """บิลเก่าที่ AR มาจากยอดยกมา — กลับกับ 31002 ไม่แตะรายได้งวดนี้"""
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=800)
    await _post_opening_journal(db_pool, room_id, payment_id, 800)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            entry = await FinanceService._post_bill_reversal(
                conn, room_id, payment_id, amount=800,
            )
        assert entry is not None

    lines = await _journal_lines(
        db_pool, reference_type="student_payment_reversal", reference_id=payment_id
    )
    codes = {l["account_code"]: (float(l["debit"]), float(l["credit"])) for l in lines}
    assert codes[OPENING_AR_EQUITY_CODE] == (800.0, 0.0)
    assert codes[AR_PROJECT_CODE] == (0.0, 800.0)

    assert await _ledger_net(db_pool, room_id, OPENING_AR_EQUITY_CODE) == 0
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 0
    # ไม่มีรายได้/รายจ่ายถูกแตะเลย
    assert await _journal_count(db_pool, room_id, "student_payment_reversal") == 1
    # ไม่มีบรรทัดรายได้/รายจ่ายถูกแตะเลย (ห้องนี้ไม่เคยมี ledger รายได้ด้วยซ้ำ)
    async with db_pool.acquire() as conn:
        touched = await conn.fetchval(
            """SELECT COUNT(*)
               FROM journal_entries JE
               JOIN journal_lines L ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON AL.id = L.ledger_id
               WHERE JE.room_id = $1 AND AL.account_type IN ('revenue', 'expense')""",
            room_id,
        )
    assert int(touched) == 0


async def test_reversal_without_ar_source_writes_nothing(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=500)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            entry = await FinanceService._post_bill_reversal(
                conn, room_id, payment_id, amount=500,
            )
        assert entry is None
        assert await _journal_count(db_pool, room_id, "student_payment_reversal") == 0


async def test_adjustment_decrease_of_issue_and_increase_of_opening(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, issued = await _make_bill(db_pool, room_id, student_id, amount=1000)
    _, opening = await _make_bill(db_pool, room_id, student_id, amount=1000)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(conn, room_id, issued, amount=1000)
    await _post_opening_journal(db_pool, room_id, opening, 1000)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_adjustment(
                conn, room_id, issued, delta=-200,
            )
        async with conn.transaction():
            await FinanceService._post_bill_adjustment(
                conn, room_id, opening, delta=300,
            )

    revenue_code = await _revenue_ledger_code(db_pool, room_id)
    issued_lines = await _journal_lines(
        db_pool, reference_type="fee_collection_adjustment", reference_id=issued
    )
    issued_codes = {l["account_code"]: (float(l["debit"]), float(l["credit"])) for l in issued_lines}
    assert issued_codes[revenue_code] == (200.0, 0.0)
    assert issued_codes[AR_PROJECT_CODE] == (0.0, 200.0)

    opening_lines = await _journal_lines(
        db_pool, reference_type="fee_collection_adjustment", reference_id=opening
    )
    opening_codes = {l["account_code"]: (float(l["debit"]), float(l["credit"])) for l in opening_lines}
    assert opening_codes[AR_PROJECT_CODE] == (300.0, 0.0)
    assert opening_codes[OPENING_AR_EQUITY_CODE] == (0.0, 300.0)

    # issue 1000 + opening 1000 − ลด 200 + เพิ่ม 300 = 2100
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 2100
    # opening Cr 1000 + ปรับเพิ่ม Cr 300 ⇒ สุทธิ −1300
    assert await _ledger_net(db_pool, room_id, OPENING_AR_EQUITY_CODE) == -1300
    # revenue เป็นบัญชีเครดิต: Cr 1000 ตอนออกบิล, ปรับลด Dr 200 ⇒ net −800
    assert await _ledger_net(db_pool, room_id, revenue_code) == -800


# ═══════════════════════════════════════════ 7. create bills with accrual
async def test_create_bills_with_accrual_one_bill_per_student(db_pool):
    room_id = await _make_room(db_pool)
    s1 = await _make_student(db_pool, room_id, student_no=91)
    s2 = await _make_student(db_pool, room_id, student_no=92)
    s3 = await _make_student(db_pool, room_id, student_no=93)

    async with db_pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, 'ค่าห้อง', 500, $2, 'active') RETURNING id""",
            room_id, date(2026, 12, 31),
        )
        async with conn.transaction():
            payment_ids = await FinanceService._create_bills_with_accrual(
                conn,
                room_id=room_id,
                collection_id=collection_id,
                student_ids=[s1, s2, s3, s1],  # ซ้ำได้ — ต้องถูกตัด
                amount=500,
                collection_kind=COLLECTION_KIND_PROJECT,
                recorded_by="tester",
            )

    assert len(payment_ids) == 3
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 1500
    assert await _journal_count(db_pool, room_id, "student_payment_issue") == 3
    for payment_id in payment_ids:
        assert await _journal_count(
            db_pool, room_id, "student_payment_issue"
        ) >= 1
        lines = await _journal_lines(
            db_pool, reference_type="student_payment_issue", reference_id=payment_id
        )
        assert sum(float(l["debit"]) for l in lines) == sum(float(l["credit"]) for l in lines) == 500


# ═════════════════════════════════════════════════════ 8. open-bill predicate
async def test_open_bill_predicate_ignores_collection_status(db_pool):
    assert "FC.status" not in OPEN_BILL_PREDICATE
    assert FinanceService._open_bill_predicate() == OPEN_BILL_PREDICATE

    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)

    await _make_bill(db_pool, room_id, student_id, amount=100)  # นับ
    await _make_bill(db_pool, room_id, student_id, amount=100, status="paid")  # ไม่นับ
    await _make_bill(
        db_pool, room_id, student_id, amount=100, collection_status="closed",
    )  # นับ (ปิดโปรเจกต์ = หยุดรับใหม่ ไม่ใช่ล้างหนี้)
    _, deleted_bill = await _make_bill(db_pool, room_id, student_id, amount=100)
    _, deleted_collection_bill = await _make_bill(db_pool, room_id, student_id, amount=100)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET deleted_at = NOW() WHERE id = $1", deleted_bill
        )
        await conn.execute(
            """UPDATE fee_collections SET deleted_at = NOW()
               WHERE id = (SELECT collection_id FROM student_payments WHERE id = $1)""",
            deleted_collection_bill,
        )
        count = await conn.fetchval(
            f"""SELECT COUNT(*)
                FROM student_payments SP
                JOIN fee_collections FC ON FC.id = SP.collection_id
                WHERE FC.room_id = $1 AND {OPEN_BILL_PREDICATE}""",
            room_id,
        )

    assert int(count) == 2


# ══════════════════════════════════════════════════════════ balance sanity
async def test_all_journals_are_balanced(db_pool):
    """Dr = Cr ทุกใบ — ตรวจทั้งห้องหลังผ่านทุกเส้นทางในไฟล์นี้"""
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, p1 = await _make_bill(db_pool, room_id, student_id, amount=400)
    _, p2 = await _make_bill(
        db_pool, room_id, student_id, amount=60, kind=COLLECTION_KIND_FINE,
        title="ค่าปรับ",
    )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(conn, room_id, p1, amount=400)
            await FinanceService._post_bill_accrual(
                conn, room_id, p2, amount=60, collection_kind=COLLECTION_KIND_FINE,
            )
        async with conn.transaction():
            await FinanceService._post_bill_adjustment(conn, room_id, p1, delta=-100)

        unbalanced = await conn.fetchval(
            """SELECT COUNT(*) FROM (
                   SELECT L.journal_entry_id
                   FROM journal_lines L
                   JOIN journal_entries JE ON JE.id = L.journal_entry_id
                   WHERE JE.room_id = $1
                   GROUP BY L.journal_entry_id
                   HAVING ROUND(SUM(L.debit), 2) <> ROUND(SUM(L.credit), 2)
               ) bad""",
            room_id,
        )

    assert int(unbalanced) == 0
    assert await _ledger_net(db_pool, room_id, FINE_DISCOUNT_CODE) == 0
