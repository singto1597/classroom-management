"""
Integration tests สำหรับ Excel Export ระดับ Enterprise (ERP) ใน finance_service.py

ครอบคลุมโครงสร้างใหม่ (Refactor 2026-09):
  Management export (export_transactions_excel) → 5 แผ่น
    - Sheet 4 'สรุปโปรเจคเก็บเงิน (Fee Collections)' ตัวเลขตรงกับ DB (deep verification)
    - Sheet 5 'ทะเบียนลูกหนี้ (Accounts Receivable)' รวมหนี้/ลูกหนี้ตรงกับ DB
    - Sheet 'สรุปยอด' มีอัตราการเก็บเงิน + ยอดหนี้ AR (Real-time)
  Accounting export (export_journal_excel) → 6 แผ่น Full Audit Report
    - GL: ยอดยกมา/เดบิต/เครดิต/ยอดยกไป ตรงกับผลรวม journal_lines
    - Trial Balance: Dr = Cr และสมดุล
    - Income Statement: รายได้ − ค่าใช้จ่าย = Net Income
    - Balance Sheet: สินทรัพย์ = ส่วนของเจ้าของ + กำไรสะสม (สมดุล)
    - General Journal: Audit Trail (โมดูล/Legacy TX/Transfer/Student Payment) จาก metadata
    - Regression: บิล voided ต้องไม่ถูกนับใน GL/TB/Dashboard (เหมือน fix ก่อนหน้า)

Pattern ตาม docs/rules/testing.md: service-level เรียกตรง, deep DB verification,
randomized id ผ่าน fixtures ของ conftest, ไม่แตะ Redis
"""
import io
import random
import string
import uuid
from datetime import date

import openpyxl
import pytest

from models.finance_schemas import (
    FinanceExportRequest,
    TransactionCreate,
    TransferCreate,
    PaymentConfirm,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Fixtures & Helpers (ลอก pattern จาก test_finance.py) ===

MANAGEMENT_SHEETS = [
    "สรุปยอด", "ประวัติรายการ", "สรุปรายหมวดหมู่",
    "สรุปโปรเจคเก็บเงิน (Fee)", "ทะเบียนลูกหนี้ (AR)",
]
ACCOUNTING_SHEETS = [
    "Financial Dashboard", "สมุดรายวัน (General Journal)",
    "สมุดบัญชีแยกประเภท (GL)", "งบทดลอง (Trial Balance)",
    "งบกำไรขาดทุน (Income Statement)", "งบแสดงฐานะการเงิน (BS)",
]


async def _insert_user(pool, *, first_name="Test", last_name="User") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (first_name, last_name, username)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            first_name, last_name, f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room") -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_name, code, owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, status="active") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', $4, FALSE, '[]'::jsonb)
            RETURNING id
            """,
            room_id, user_id, student_no, status,
        )


async def _insert_finance_account(pool, room_id: int, account_name="กองกลาง", balance=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_accounts (room_id, account_name, balance)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, account_name, balance,
        )


async def _insert_category(pool, room_id: int, category_name, category_type) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_categories (room_id, category_name, category_type)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, category_name, category_type,
        )


async def _insert_collection(pool, room_id: int, title="ค่าเทอม", amount=1000.0, due_date=None) -> int:
    if due_date is None:
        due_date = date(2026, 12, 31)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO fee_collections (room_id, title, amount, due_date, status)
            VALUES ($1, $2, $3, $4, 'active')
            RETURNING id
            """,
            room_id, title, amount, due_date,
        )


async def _insert_student_payment(pool, collection_id, student_id, status="pending", paid_amount=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            collection_id, student_id, status, paid_amount,
        )


def _values(wb, sheet: str) -> list:
    return list(wb[sheet].values)


def _find_row(rows: list, col: int, needle) -> tuple:
    """หาแถวแรกที่ rows[row][col] == needle."""
    for r in rows:
        if r and r[col] == needle:
            return r
    raise AssertionError(f"ไม่พบแถวที่ col {col} == {needle!r} ใน {rows}")


# =====================================================================
# Requirement 1: Management export → 5 แผ่น (Fee Collections + AR)
# =====================================================================


async def test_management_export_fee_and_ar_sheets_match_db(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องเทส")
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="One"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Two"), 2)

    c1 = await _insert_collection(db_pool, room_id, "ค่าเทอม", 100.0, due_date=date(2026, 11, 30))
    await _insert_student_payment(db_pool, c1, s1, status="pending", paid_amount=30.0)  # ทยอยจ่าย 30/100
    await _insert_student_payment(db_pool, c1, s2, status="pending", paid_amount=0.0)   # ยังไม่จ่าย

    # Deep DB: ค่าที่คาดหวัง
    async with db_pool.acquire() as conn:
        paid_db = await conn.fetchval(
            "SELECT COALESCE(SUM(paid_amount),0) FROM student_payments WHERE collection_id = $1 AND deleted_at IS NULL",
            c1,
        )
        member_db = await conn.fetchval(
            "SELECT COUNT(*) FROM student_payments WHERE collection_id = $1 AND deleted_at IS NULL", c1
        )
        ar_db = await conn.fetchval(
            "SELECT COALESCE(SUM(FC.amount - SP.paid_amount),0) "
            "FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id "
            "WHERE SP.deleted_at IS NULL AND SP.status='pending' AND FC.room_id = $1",
            room_id,
        )
    assert member_db == 2 and paid_db == 30.0 and ar_db == 170.0

    excel_file = await FinanceService.export_transactions_excel(
        pool=db_pool, req=FinanceExportRequest(), client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert isinstance(excel_file, io.BytesIO)
    wb = openpyxl.load_workbook(excel_file)
    assert wb.sheetnames == MANAGEMENT_SHEETS

    # ---- Sheet 4: สรุปโปรเจคเก็บเงิน — block ต่อโปรเจค ไล่รายชื่อผู้ค้าง ----
    fee_all = _values(wb, "สรุปโปรเจคเก็บเงิน (Fee)")
    assert "เลขที่" in fee_all[2] and "คงค้าง (บาท)" in fee_all[2]  # หัวตารางแถว 3
    fee_data = fee_all[3:]  # ข้าม title/subtitle/header

    banners = [r for r in fee_data if r[0] and str(r[0]).startswith('โปรเจค "')]
    assert len(banners) == 1
    banner = str(banners[0][0])
    assert "ค่าเทอม" in banner
    assert "สมาชิก 2 คน" in banner
    assert "170.00" in banner                       # คงค้าง (บาท)
    assert "15.00%" in banner                       # % สำเร็จ = 30/200

    # แถวรายชื่อผู้ค้าง: col A = เลขที่ (int) → มีแค่ 2 คนที่ยังจ่ายไม่ครบ
    student_rows = [r for r in fee_data if isinstance(r[0], int)]
    assert [r[0] for r in student_rows] == [1, 2]
    assert sorted(float(r[5]) for r in student_rows) == [70.0, 100.0]  # คงค้าง col6
    # s1 ทยอยจ่าย 30/100 → "ทยอยจ่ายแล้ว", s2 ยังไม่จ่าย
    assert sorted(str(r[2]) for r in student_rows) == ["ทยอยจ่ายแล้ว", "ยังไม่จ่าย"]

    # แถวรวมยอดค้างของโปรเจคนี้ + แถวรวมทั้งสิ้น
    proj_sub = [r for r in fee_data if r[0] and str(r[0]).startswith("รวมยอดคงค้างของคนที่ยังจ่ายไม่ครบ")]
    assert len(proj_sub) == 1 and float(proj_sub[0][5]) == 170.0
    total = [r for r in fee_data if r[0] and str(r[0]).startswith("รวมทั้งสิ้น")]
    assert len(total) == 1 and "170.00" in str(total[0][0])

    # ---- Sheet 5: ทะเบียนลูกหนี้ — รายละเอียดรายคน + รหัสนักเรียน + รวมหนี้ ----
    ar_all = _values(wb, "ทะเบียนลูกหนี้ (AR)")
    assert "รหัสนักเรียน" in ar_all[2] and "ยอดคงค้าง (บาท)" in ar_all[2]
    ar_rows = ar_all[3:]
    subtotal_rows = [r for r in ar_rows if r[0] and str(r[0]).startswith("รวมหนี้ของ")]
    assert sorted(float(r[7]) for r in subtotal_rows) == [70.0, 100.0]  # ยอดคงค้าง col8
    s2_rows = [r for r in ar_rows if isinstance(r[0], int) and r[0] == 2]
    assert len(s2_rows) == 1 and float(s2_rows[0][7]) == 100.0
    grand = [r for r in ar_rows if r[0] and str(r[0]).startswith("รวมลูกหนี้ทั้งสิ้น")]
    assert float(grand[0][7]) == 170.0

    # ---- Sheet 1: สรุปยอด มีตัวเลขการเก็บเงิน/ลูกหนี้ ----
    summary = _values(wb, "สรุปยอด")
    by_label = {r[0]: r[1] for r in summary if r[0]}
    assert float(by_label["อัตราการเก็บเงินสำเร็จ (%)"]) == pytest.approx(15.0)
    assert float(by_label["หนี้ค้างชำระรวม — AR (บาท)"]) == pytest.approx(170.0)
    assert by_label["จำนวนลูกหนี้ที่ยังค้าง (คน)"] == 2


async def test_management_export_fee_sheet_lists_only_unpaid(db_pool):
    """Regression: Sheet 4 ไล่รายชื่อเฉพาะคนที่ยังค้าง (คนที่จ่ายครบแล้วต้องไม่หลุดเข้ามา)
    แต่ยังนับรวมในสรุปยอดของโปรเจค (สมาชิก/เก็บได้/%) — เหมือนหน้า 'ดูรายละเอียด' ในเว็บ."""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องเทส")
    await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="จ่าย", last_name="ครบ"), 1)
    s2 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="ยัง", last_name="ไม่จ่าย"), 2)

    c1 = await _insert_collection(db_pool, room_id, "ค่าชีท", 100.0)
    await _insert_student_payment(db_pool, c1, s1, status="paid", paid_amount=100.0)  # ✅ จ่ายครบ → ไม่ต้องขึ้นรายชื่อ
    await _insert_student_payment(db_pool, c1, s2, status="pending", paid_amount=0.0)   # ❌ ยังค้าง

    excel_file = await FinanceService.export_transactions_excel(
        pool=db_pool, req=FinanceExportRequest(), client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    wb = openpyxl.load_workbook(excel_file)

    fee_data = _values(wb, "สรุปโปรเจคเก็บเงิน (Fee)")[3:]
    banner = str(next(r[0] for r in fee_data if r[0] and str(r[0]).startswith('โปรเจค "')))
    # สรุปโปรเจคยังนับสมาชิกครบ 2 คน + เก็บได้ 100/200 (50%)
    assert "สมาชิก 2 คน" in banner
    assert "50.00%" in banner
    assert "100.00" in banner and "200.00" in banner
    # แต่รายชื่อผู้ค้างมีแค่คนที่ยังไม่จ่าย (เลขที่ 2) — ไม่มีคนจ่ายครบ (เลขที่ 1)
    student_rows = [r for r in fee_data if isinstance(r[0], int)]
    assert [r[0] for r in student_rows] == [2]

    # ทะเบียนลูกหนี้ (AR) ยังเหลือหนี้ของคนที่ยังไม่จ่ายคนเดียว = 100
    ar_rows = _values(wb, "ทะเบียนลูกหนี้ (AR)")[3:]
    subtotal_rows = [r for r in ar_rows if r[0] and str(r[0]).startswith("รวมหนี้ของ")]
    assert [float(r[7]) for r in subtotal_rows] == [100.0]
    grand = next(r for r in ar_rows if r[0] and str(r[0]).startswith("รวมลูกหนี้ทั้งสิ้น"))
    assert float(grand[7]) == 100.0


# =====================================================================
# Requirement 2: Accounting export → 6 แผ่น (Audit Report)
# =====================================================================


async def test_accounting_export_six_sheets_and_matches_db(db_pool):
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องบัญชี")
    acc_main = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    acc_sub = await _insert_finance_account(db_pool, room_id, "บัญชีย่อย", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    # บิล manual: รายรับ 1000 / รายจ่าย 200 / โอน 400
    async def _add(acc, cat, amount, ttype, desc):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(account_id=acc, category_id=cat, amount=amount,
                                  description=desc, transaction_type=ttype, user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
        )

    await _add(acc_main, inc_cat, 1000.0, "income", "บริจาคใหญ่")
    await _add(acc_main, exp_cat, 200.0, "expense", "ซื้อของ")
    await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=acc_main, to_account_id=acc_sub, amount=400.0,
                           description="ฝากสำรอง", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
    )

    # บิล student_payment: confirm 300 → journal reference_type='student_payment'
    s1 = await _insert_student(db_pool, room_id, await _insert_user(db_pool, first_name="Kid", last_name="Three"), 3)
    c2 = await _insert_collection(db_pool, room_id, "ทัศนศึกษา", 300.0)
    p1 = await _insert_student_payment(db_pool, c2, s1, status="pending", paid_amount=0.0)
    await FinanceService.confirm_payment(
        pool=db_pool, payment_id=p1,
        req=PaymentConfirm(paid_to_account_id=acc_main, paid_amount=300.0, user_name="Owner"),
        client_source="test", actor_identifier="test", room_id=room_id,
    )

    # ย้ายทุกบิลไปงวด ต.ค. 2026 (หลัง CUTOFF_DATE) เพื่อให้ GL/PL/BS มีเลขชัดเจน
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-15 09:00:00' WHERE room_id = $1", room_id
        )
        # Deep DB: รวม Dr/Cr ต่อ ledger ในงวด ต.ค. (ไม่นับ void)
        gl_check = await conn.fetch(
            """SELECT AL.account_name,
                      COALESCE(SUM(L.debit),0)  AS dr,
                      COALESCE(SUM(L.credit),0) AS cr
               FROM accounting_ledgers AL
               LEFT JOIN journal_lines L ON L.ledger_id = AL.id
               LEFT JOIN journal_entries JE ON L.journal_entry_id = JE.id
               WHERE AL.room_id = $1
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND JE.transaction_date >= '2026-10-01' AND JE.transaction_date <= '2026-10-31'
               GROUP BY AL.account_name""",
            room_id,
        )
    by_name = {r["account_name"]: (float(r["dr"]), float(r["cr"])) for r in gl_check}
    assert by_name["กองกลาง"] == (1300.0, 600.0)
    assert by_name["บัญชีย่อย"] == (400.0, 0.0)

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=10, year=2026,
    )
    assert isinstance(excel_file, io.BytesIO)
    wb = openpyxl.load_workbook(excel_file)
    assert wb.sheetnames == ACCOUNTING_SHEETS

    # ---- Sheet GL: ยอดยกมา=0, เดบิต/เครดิต/ยอดยกไป ตรง DB ----
    gl_rows = _values(wb, "สมุดบัญชีแยกประเภท (GL)")[3:]
    main_row = _find_row(gl_rows, 1, "กองกลาง")
    assert main_row[3] == 0.0       # ยอดยกมา (ก่อน ต.ค.)
    assert main_row[4] == 1300.0    # เดบิต
    assert main_row[5] == 600.0     # เครดิต
    assert main_row[6] == 700.0     # ยอดยกไป
    sub_row = _find_row(gl_rows, 1, "บัญชีย่อย")
    assert sub_row[6] == 400.0

    # ---- Sheet Trial Balance: รวม Dr = Cr + สมดุล ----
    tb_rows = _values(wb, "งบทดลอง (Trial Balance)")[3:]
    tb_total = _find_row(tb_rows, 0, "รวมทั้งสิ้น")
    assert tb_total[3] == tb_total[4]
    assert tb_total[3] == pytest.approx(1900.0)
    assert tb_total[5] is not None and "สมดุล" in str(tb_total[5])

    # ---- Sheet Income Statement: 1300 − 200 = 1100 ----
    pl_rows = _values(wb, "งบกำไรขาดทุน (Income Statement)")[3:]
    rev = _find_row(pl_rows, 1, "รวมรายได้")
    exp = _find_row(pl_rows, 1, "รวมค่าใช้จ่าย")
    ni = _find_row(pl_rows, 1, "กำไร/ขาดทุนสุทธิ (Net Income)")
    assert rev[2] == pytest.approx(1300.0)
    assert exp[2] == pytest.approx(200.0)
    assert ni[2] == pytest.approx(1100.0)

    # ---- Sheet Balance Sheet: สินทรัพย์ = ส่วนของเจ้าของ + กำไรสะสม ----
    bs_rows = _values(wb, "งบแสดงฐานะการเงิน (BS)")[3:]
    assets = _find_row(bs_rows, 1, "รวมสินทรัพย์")
    equity_side = _find_row(bs_rows, 1, "รวมส่วนของเจ้าของ")
    assert assets[2] == pytest.approx(1100.0)
    assert equity_side[2] == pytest.approx(1100.0)
    balanced = _find_row(bs_rows, 1, "ตรวจสอบสมดุล (Assets = Liab + Equity + Retained)")
    assert "สมดุล" in str(balanced[2])

    # ---- General Journal: Audit Trail จาก metadata ----
    j_rows = _values(wb, "สมุดรายวัน (General Journal)")[3:]
    manual = _find_row(j_rows, 9, "manual_transaction")
    assert manual[11] is not None          # Legacy TX ID
    transfer = _find_row(j_rows, 9, "transfer")
    assert transfer[12] is not None        # Transfer Group
    sp = _find_row(j_rows, 9, "student_payment")
    assert sp[13] is not None              # Student Payment ID
    assert sp[14]                          # Journal Entry ID (UUID)
    assert sp[15]                          # Journal Line ID


async def test_accounting_export_voided_journal_excluded_from_financials(db_pool):
    """Regression: บิลที่ void แล้วต้องไม่ถูกนับใน GL/TB/Dashboard (ตัดยอดเกินจริง)."""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องเทส")
    acc = await _insert_finance_account(db_pool, room_id, "เงินสด", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    async def _add(amount, desc):
        await FinanceService.add_transaction(
            pool=db_pool,
            req=TransactionCreate(account_id=acc, category_id=inc_cat, amount=amount,
                                  description=desc, transaction_type="income", user_name="Owner"),
            user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
        )

    await _add(300.0, "บริจาคจริง")          # ยังใช้งาน → ต้องนับ
    await _add(500.0, "บริจาคแล้วยกเลิก")    # โดน void → ต้องไม่นับ
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-10' WHERE room_id = $1", room_id
        )
        await conn.execute(
            "UPDATE journal_entries SET status = 'voided' WHERE room_id = $1 AND description = 'บริจาคแล้วยกเลิก'",
            room_id,
        )

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=10, year=2026,
    )
    wb = openpyxl.load_workbook(excel_file)

    # GL: เงินสด ยอดยกไป = 300 (ไม่ใช่ 800)
    gl_rows = _values(wb, "สมุดบัญชีแยกประเภท (GL)")[3:]
    cash = _find_row(gl_rows, 1, "เงินสด")
    assert cash[6] == 300.0

    # Trial Balance รวม Dr = 300 (เฉพาะ asset ฝั่ง Dr 300) → Dr=Cr=300
    tb_rows = _values(wb, "งบทดลอง (Trial Balance)")[3:]
    tb_total = _find_row(tb_rows, 0, "รวมทั้งสิ้น")
    assert tb_total[3] == pytest.approx(300.0)
    assert tb_total[4] == pytest.approx(300.0)

    # Dashboard: สินทรัพย์รวม (B5) = 300
    dash = _values(wb, "Financial Dashboard")
    assert dash[4][1] == pytest.approx(300.0)
