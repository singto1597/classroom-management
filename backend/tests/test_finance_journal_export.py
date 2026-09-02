"""
Integration tests for FinanceService.export_journal_excel (สมุดรายวันทั่วไป)

ครอบคลุม:
  - โครงสร้าง Excel: แผ่นเดียว 'สมุดรายวัน' + คอลัมน์ครบ
    (วันที่/เวลา/Reference/คำอธิบาย/รหัสบัญชี/ชื่อบัญชี/เดบิต/เครดิต/ผู้บันทึก)
  - ความสมดุลของบัญชีคู่: ยอดเดบิตรวม = ยอดเครดิตเสมอ (มีแถวรวมท้าย)
  - การจัดกลุ่มหัวบิล: วันที่/Reference/คำอธิบาย/ผู้บันทึก แสดงเฉพาะบรรทัดแรกของบิล
  - การกรองช่วงเวลา (month+year / start_date+end_date)
  - RBAC: สมาชิกต่างห้อง/คนนอกโดน ForbiddenError
  - การโอนเงินระหว่างบัญชีแสดงเป็น 2 บรรทัด (Dr/Cr) ที่สมดุล

Pattern ตาม docs/rules/testing.md: service-level เรียกตรง, deep DB verification,
dual-write ของ add_transaction/transfer_money สร้าง journal ให้เอง
"""
import io
import random
import string
import uuid
from datetime import date, datetime

import openpyxl
import pytest

from core.exceptions import ForbiddenError
from models.finance_schemas import TransactionCreate, TransferCreate
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Fixtures & Setup (ลอก pattern จาก test_finance_export.py) ===


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


async def _insert_finance_account(pool, room_id: int, account_name="กระเป๋ากลาง", balance=0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_accounts (room_id, account_name, balance)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, account_name, balance,
        )


async def _insert_category(pool, room_id: int, category_name="ค่าอาหาร", category_type="expense") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO finance_categories (room_id, category_name, category_type)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_id, category_name, category_type,
        )


async def _add_txn(pool, room_id, owner, account_id, category_id, amount, ttype, desc):
    """add_transaction + dual-write → สร้าง journal_entries/journal_lines ให้เอง"""
    await FinanceService.add_transaction(
        pool=pool,
        req=TransactionCreate(
            account_id=account_id, category_id=category_id, amount=amount,
            description=desc, transaction_type=ttype, user_name="Owner",
        ),
        user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
    )


def _read_journal(excel_file) -> tuple:
    """อ่าน Sheet 'สมุดรายวัน' → (header, data_rows, totals)

    โครงสร้างไฟล์: แถว 1 title, แถว 2 subtitle, แถว 3 ว่าง, แถว 4 = header,
    แถว 5 ขึ้นไป = data, แถวสุดท้าย 'รวมทั้งสิ้น'
    """
    wb = openpyxl.load_workbook(excel_file)
    assert wb.sheetnames == ["สมุดรายวัน"]
    ws = wb["สมุดรายวัน"]
    all_rows = list(ws.values)
    header = list(all_rows[3])
    data = []
    totals = None
    for row in all_rows[4:]:
        if row[0] == "รวมทั้งสิ้น":
            totals = row
            break
        data.append(list(row))
    return header, data, totals


# === Tests ===


async def test_journal_export_empty_room_returns_valid_workbook(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner, room_name="ห้องเทส")

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
    )
    assert isinstance(excel_file, io.BytesIO)

    header, data, totals = _read_journal(excel_file)
    # คอลัมน์ครบตามสเปค (9 คอลัมน์)
    assert header == [
        "วันที่", "เวลา", "Reference", "คำอธิบาย", "รหัสบัญชี",
        "ชื่อบัญชี", "เดบิต (บาท)", "เครดิต (บาท)", "ผู้บันทึก",
    ]
    # ไม่มีรายการ → มี placeholder + แถวรวม 0
    assert len(data) == 1 and data[0][3] == "(ไม่มีรายการในช่วงนี้)"
    assert totals[6] == 0.0 and totals[7] == 0.0


async def test_journal_export_groups_income_expense_and_balances(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    acc = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    exp_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    # income 500 → 2 บรรทัด (Asset Dr / Revenue Cr), expense 200 → 2 บรรทัด (Expense Dr / Asset Cr)
    await _add_txn(db_pool, room_id, owner, acc, inc_cat, 500.0, "income", "บริจาค")
    await _add_txn(db_pool, room_id, owner, acc, exp_cat, 200.0, "expense", "ซื้อของ")
    async with db_pool.acquire() as conn:
        # เรียงเวลาให้ชัด (ย้ายไปงวด ต.ค. 2026) — เพื่อให้ลำดับบิล deterministic
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-10 09:00:00' WHERE room_id = $1 AND description = 'บริจาค'",
            room_id,
        )
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-12 10:30:00' WHERE room_id = $1 AND description = 'ซื้อของ'",
            room_id,
        )

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=10, year=2026,
    )
    header, data, totals = _read_journal(excel_file)

    assert len(data) == 4  # 2 บิล × 2 บรรทัด
    debit_sum = sum((r[6] or 0.0) for r in data)
    credit_sum = sum((r[7] or 0.0) for r in data)
    assert debit_sum == pytest.approx(700.0)
    assert credit_sum == pytest.approx(700.0)
    # แถวรวมท้าย = เท่ากันทั้งสองฝั่ง
    assert totals[6] == pytest.approx(700.0)
    assert totals[7] == pytest.approx(700.0)

    # บรรทัดแรกของบิล income (Asset Dr 500) — ใส่หัวบิลครบ
    income_head = next(r for r in data if r[3] == "บริจาค")
    assert income_head[6] == pytest.approx(500.0) and income_head[7] in (None, 0.0)
    assert income_head[4].startswith("1")          # รหัสบัญชีสินทรัพย์ 1xxxx
    assert income_head[5] == "กองกลาง"
    assert income_head[0] == "10/10/2026"
    assert income_head[2] is not None and "รายการ #" in str(income_head[2])
    assert income_head[8] == "Owner"

    # บรรทัดที่สองของบิล income (Revenue Cr 500) — ไม่ซ้ำหัวบิล (ว่าง)
    revenue_cr = next(r for r in data if r[5] == "เงินบริจาค" and (r[7] or 0.0) == 500.0)
    assert revenue_cr[3] is None and revenue_cr[2] is None

    # บรรทัดแรกของบิล expense (Expense Dr 200)
    expense_head = next(r for r in data if r[3] == "ซื้อของ")
    assert expense_head[6] == pytest.approx(200.0)
    assert expense_head[5] == "ค่าอาหาร"
    assert expense_head[4].startswith("5")         # รหัสบัญชีค่าใช้จ่าย 5xxxx

    # บรรทัดที่สองของบิล expense (Asset Cr 200)
    asset_cr = next(r for r in data if r[5] == "กองกลาง" and (r[7] or 0.0) == 200.0)
    assert asset_cr[3] is None


async def test_journal_export_month_filter(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    acc = await _insert_finance_account(db_pool, room_id, "กองกลาง", 0.0)
    inc_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    await _add_txn(db_pool, room_id, owner, acc, inc_cat, 100.0, "income", "ต.ค.")
    await _add_txn(db_pool, room_id, owner, acc, inc_cat, 200.0, "income", "พ.ย.")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-10' WHERE room_id = $1 AND description = 'ต.ค.'",
            room_id,
        )
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-11-10' WHERE room_id = $1 AND description = 'พ.ย.'",
            room_id,
        )

    # เอาเฉพาะ ต.ค. 2026
    excel_oct = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=10, year=2026,
    )
    _, data_oct, totals_oct = _read_journal(excel_oct)
    assert len(data_oct) == 2
    assert totals_oct[6] == pytest.approx(100.0)
    assert any(r[3] == "ต.ค." for r in data_oct)
    assert not any(r[3] == "พ.ย." for r in data_oct)

    # เอาเฉพาะช่วง 1-15 พ.ย. 2026 (start_date + end_date)
    excel_nov = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner,
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 15),
    )
    _, data_nov, totals_nov = _read_journal(excel_nov)
    assert len(data_nov) == 2
    assert totals_nov[6] == pytest.approx(200.0)
    assert any(r[3] == "พ.ย." for r in data_nov)


async def test_journal_export_transfer_shows_balanced_two_legs(db_pool):
    """การโอนเงินในสมุดรายวันต้องโชว์ 2 บรรทัด (Dr ปลายทาง / Cr ต้นทาง) ที่สมดุล
    (สมุดรายวันต่างจากสรุปรายการ — นักบัญชีต้องเห็นทุกขาทางบัญชี)"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "บัญชีหลัก", 1000.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "บัญชีย่อย", 0.0)

    await FinanceService.transfer_money(
        pool=db_pool,
        req=TransferCreate(from_account_id=from_acc, to_account_id=to_acc, amount=400.0,
                           description="ฝากสำรอง", user_name="Owner"),
        user_id=owner, client_source="test", actor_identifier="test", room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET transaction_date = '2026-10-10' WHERE room_id = $1", room_id
        )

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=10, year=2026,
    )
    _, data, totals = _read_journal(excel_file)
    assert len(data) == 2
    assert totals[6] == pytest.approx(400.0)
    assert totals[7] == pytest.approx(400.0)

    dr = next(r for r in data if (r[6] or 0.0) == 400.0)
    cr = next(r for r in data if (r[7] or 0.0) == 400.0)
    assert dr[5] == "บัญชีย่อย"   # Dr ปลายทาง
    assert cr[5] == "บัญชีหลัก"   # Cr ต้นทาง
    # Reference ใช้ 'โอนเงิน #<group_id>'
    head = next(r for r in data if r[2] is not None)
    assert str(head[2]).startswith("โอนเงิน #")


async def test_journal_export_non_member_forbidden(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="Outsider", last_name="User")

    with pytest.raises(ForbiddenError):
        await FinanceService.export_journal_excel(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_id, user_id=outsider,
        )


async def test_journal_export_cross_room_member_forbidden(db_pool):
    owner_a = await _insert_user(db_pool, first_name="Admin", last_name="A")
    room_a = await _insert_room(db_pool, owner_a, room_name="ห้อง A")
    owner_b = await _insert_user(db_pool, first_name="Admin", last_name="B")
    room_b = await _insert_room(db_pool, owner_b, room_name="ห้อง B")

    member_a = await _insert_user(db_pool, first_name="Member", last_name="A")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 1, 'student', 'active', FALSE, '[]'::jsonb)
            """,
            room_a, member_a,
        )

    # สมาชิกห้อง A export ห้อง B → ForbiddenError
    with pytest.raises(ForbiddenError):
        await FinanceService.export_journal_excel(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_b, user_id=member_a,
        )


async def test_journal_export_invalid_period_raises(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    # month โดยไม่มี year → ValueError
    with pytest.raises(ValueError):
        await FinanceService.export_journal_excel(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_id, user_id=owner, month=10,
        )
    # start_date หลัง end_date → ValueError
    with pytest.raises(ValueError):
        await FinanceService.export_journal_excel(
            pool=db_pool, client_source="test", actor_identifier="test",
            room_id=room_id, user_id=owner,
            start_date=date(2026, 2, 1), end_date=date(2026, 1, 1),
        )
