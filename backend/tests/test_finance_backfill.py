"""
Integration tests สำหรับ FinanceService.backfill_missing_journals (Backfill script).

ขอบเขต: แถว legacy ที่ตกหล่นจาก dual-write (ช่วงเปลี่ยนผ่าน 7 ชม. แรกของ 1 ก.ย. ไทย
และรอยรั่วของ student_payment สมัยก่อน FIX A) ต้องถูกสร้าง journal ย้อนหลังให้
**โดยไม่แตะแถวก่อนเส้นตัด** และ **ไม่สร้างซ้ำ** เมื่อรันหลายครั้ง

Pattern ตาม docs/rules/testing.md: ไม่ hardcode id, randomized server_id,
deep DB verification ผ่าน db_pool, ไม่แตะ Redis (service ล้วน ๆ → ไม่ต้อง mock)
"""
import json
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from core.exceptions import RoomNotFoundError
from services.finance.constants import DEFAULT_INCOME_CATEGORIES, THAI_TZ
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === ช่วงเวลาที่ใช้ทดสอบ (หัวใจของงานนี้) =====================================
# `finance_transactions.created_at` เป็น TIMESTAMP **naive ที่เก็บเวลา UTC**
# เส้นตัดคือ "วันที่ไทย" 2026-09-01 ⇒ เทียบด้วยปฏิทินไทยเท่านั้น

# 2026-08-31 23:00 เวลาไทย → **ก่อน** เส้นตัด (วันไทย 31 ส.ค.) ห้ามแตะเด็ดขาด
PRE_CUTOFF_UTC = datetime(2026, 8, 31, 16, 0, 0)
# 2026-09-01 01:00 เวลาไทย → **หลัง** เส้นตัด (วันไทย 1 ก.ย.) แต่ยังไม่มี journal = ช่องว่างช่วงเปลี่ยนผ่าน
STRADDLE_UTC = datetime(2026, 8, 31, 18, 0, 0)
# 2026-09-10 12:00 เวลาไทย → กลางเดือน ปกติ
POST_CUTOFF_UTC = datetime(2026, 9, 10, 5, 0, 0)


# === Fixtures & Setup (ลอกจาก test_finance_reconcile.py เพื่อ isolation) ===


async def _insert_user(pool, *, first_name="Test", last_name="User") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (email, first_name, last_name, username) VALUES ($1, $2, $3, $4) RETURNING id",
            None, first_name, last_name, f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None) -> int:
    """สร้างห้อง (owner เป็น admin). คืน room_id; server_id จะ random ถ้าไม่ระบุ."""
    if server_id is None:
        server_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id, server_id) VALUES ($1, $2, $3, $4) RETURNING id",
            room_name, code, owner_id, server_id,
        )
        await conn.execute(
            "INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions) "
            "VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)",
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_finance_account(pool, room_id: int, account_name="กระเป๋ากลาง", balance=0.0) -> int:
    """สร้าง finance_accounts + asset ledger ให้ครบ (เหมือนคู่ใน dual-write)."""
    async with pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, account_name, balance,
        )
        await conn.execute(
            "INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description) "
            "VALUES ($1, $2, $3, 'asset', $4, 'test')",
            room_id, f"1{account_id:04d}", account_name, account_id,
        )
        return account_id


async def _insert_category(pool, room_id: int, name: str, category_type: str) -> int:
    """สร้าง finance_categories + ledger (revenue 4xxxx / expense 5xxxx) เหมือน dual-write."""
    async with pool.acquire() as conn:
        cat_id = await conn.fetchval(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, category_type,
        )
        account_type = "revenue" if category_type == "income" else "expense"
        prefix = "4" if category_type == "income" else "5"
        await conn.execute(
            "INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_category_id, description) "
            "VALUES ($1, $2, $3, $4, $5, 'test')",
            room_id, f"{prefix}{cat_id:04d}", name, account_type, cat_id,
        )
        return cat_id


async def _insert_payment(pool, student_id: int, paid_amount: float = 100.0) -> int:
    """สร้าง student_payments 1 แถว (collection_id = NULL ได้) สำหรับ student_payment shape."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO student_payments (student_id, status, paid_amount) VALUES ($1, 'paid', $2) RETURNING id",
            student_id, paid_amount,
        )


async def _insert_legacy_tx(
    pool, room_id: int, *, amount: float, description: str = "รายการทดสอบ",
    transaction_type: str = "income", account_id=None, category_id=None,
    created_at: datetime = POST_CUTOFF_UTC, transfer_group_id=None,
    student_payment_id=None, recorded_by: str = "Tester", deleted: bool = False,
) -> int:
    """ป้อนแถว legacy ตรง ๆ พร้อม `created_at` ที่กำหนดเองได้.

    ⚠️ `created_at` เป็น naive ที่ต้องสื่อ **เวลา UTC** — ใช้ค่าคงที่ด้านบนเสมอ
    เพื่อให้เทสต์แยก "วันไทย" กับ "วัน UTC" ออกจากกันได้จริง (นี่คือหัวใจของบั๊กที่ไฟล์นี้ล็อก)
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_transactions
               (room_id, account_id, category_id, amount, description, transaction_type,
                transfer_group_id, student_payment_id, recorded_by, created_at, deleted_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                       CASE WHEN $11 THEN NOW() ELSE NULL END)
               RETURNING id""",
            room_id, account_id, category_id, amount, description, transaction_type,
            transfer_group_id, student_payment_id, recorded_by, created_at, deleted,
        )


async def _count_journals(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id
        )


async def _fetch_journal_by_legacy(pool, room_id: int, legacy_tx_id: int):
    """ดึง journal ที่ metadata ชี้ไปที่แถว legacy นี้ (ท่าเดียวกับที่ revert_transaction ใช้หา)."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT * FROM journal_entries
               WHERE room_id = $1 AND metadata->>'legacy_transaction_id' = $2""",
            room_id, str(legacy_tx_id),
        )


def _meta(row) -> dict:
    """ถอด JSONB ที่ asyncpg คืนมาเป็น **string** (harness นี้ไม่ได้ลง jsonb codec).

    ใช้เฉพาะในเทสต์ — โค้ด producción อ่าน JSONB ผ่าน SQL (`metadata->>'k'`) ทั้งหมด
    """
    raw = row["metadata"]
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


async def _fetch_lines(pool, entry_id) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT L.debit, L.credit, AL.account_type, AL.legacy_account_id, AL.legacy_category_id
               FROM journal_lines L JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE L.journal_entry_id = $1 ORDER BY L.id""",
            entry_id,
        )


# === 1. เส้นตัด: ห้ามแตะแถวก่อนเส้นตัดเด็ดขาด ================================


async def test_pre_cutoff_row_is_never_backfilled(db_pool):
    """แถวที่ "วันไทย" ยังเป็น 31 ส.ค. ต้องไม่ถูกแตะ แม้ UTC จะเป็นเดือน 8 เหมือนกัน.

    เหตุผล: งบการเงิน (trial balance / balance sheet) อ่าน journal_lines เป็นแหล่งเดียว
    การสร้าง journal ให้แถวก่อนเส้นตัด = **เพิ่มข้อมูลที่ไม่มีมาก่อน** ⇒ ยอดยกมาเพี้ยนถาวร
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_legacy_tx(
        db_pool, room_id, amount=500.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=PRE_CUTOFF_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=False)
    assert rep["candidates"] == 0
    assert rep["journals_planned"] == 0

    rep2 = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep2["journals_created"] == 0
    assert await _count_journals(db_pool, room_id) == 0


# === 2. ช่องว่างช่วงเปลี่ยนผ่าน: ตรวจเจอ + dry-run ไม่เขียน ==================


async def test_straddle_row_detected_but_dry_run_writes_nothing(db_pool):
    """แถวเช้ามืดวันที่ 1 ก.ย. ไทย (UTC ยังเป็น 31 ส.ค.) = เคสจริงที่ต้อง backfill.

    dry-run ต้องเห็นแผนครบ แต่ **ไม่เขียนอะไรลง DB เลย** (ไม่แม้แต่ ledger ที่ auto-provision)
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=750.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=False)
    assert rep["candidates"] == 1
    assert rep["journals_planned"] == 1
    assert rep["journals_created"] == 0
    assert rep["total_amount"] == pytest.approx(750.0)
    assert rep["plans"][0]["legacy_ids"] == [tx_id]

    # 🛡️ dry-run ต้อง rollback: ไม่มี journal, ไม่มี line, และ ledger ที่ auto-provision ก็ต้องไม่ค้าง
    assert await _count_journals(db_pool, room_id) == 0
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM journal_lines L JOIN journal_entries JE ON L.journal_entry_id = JE.id "
            "WHERE JE.room_id = $1", room_id
        ) == 0


# === 3. apply: เขียน journal ด้วยเวลาที่เงินเคลื่อนไหวจริง ==================


async def test_apply_writes_journal_with_true_instant_and_metadata(db_pool):
    """journal ที่ backfill ต้อง (ก) ลงเดือนไทยของ **เวลาที่เงินเคลื่อนไหวจริง**
    (ข) มี metadata คีย์ชุดเดียวกับ dual-write สด (ค) Dr = Cr."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด")
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=750.0, description="เงินบริจาคผู้ปกครอง",
        transaction_type="income", account_id=account_id, category_id=cat_id,
        created_at=STRADDLE_UTC, recorded_by="ครูสมชาย",
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["journals_created"] == 1
    assert len(rep["created_journal_ids"]) == 1

    entry = await _fetch_journal_by_legacy(db_pool, room_id, tx_id)
    assert entry is not None
    assert entry["reference_type"] == "manual_transaction"
    assert entry["reference_id"] == str(tx_id)
    assert entry["status"] == "posted"
    assert entry["recorded_by"] == "ครูสมชาย"
    assert entry["description"] == "เงินบริจาคผู้ปกครอง"

    # ⏰ หัวใจ: transaction_date = เวลาที่เงินเข้าจริง (UTC) ไม่ใช่ NOW()
    # `transaction_date` เป็น timestamptz ⇒ asyncpg คืน aware; normalize เป็น UTC ก่อนเทียบ
    assert entry["transaction_date"].astimezone(THAI_TZ).replace(tzinfo=None) == STRADDLE_UTC + timedelta(hours=7)
    # และต้อง **ไม่** ถูกตั้งเป็น NOW() (นั่นคือสิ่งที่ DEFAULT CURRENT_TIMESTAMP จะให้)
    assert entry["transaction_date"] != entry["created_at"]
    # ฝั่ง UTC ยังเป็น 31 ส.ค. แต่ฝั่งไทยเป็น 1 ก.ย. = วันเดียวกับเส้นตัด ⇒ ผู้อ่าน v2 เห็น
    assert entry["transaction_date"].astimezone(timezone.utc).date().isoformat() == "2026-08-31"
    assert entry["transaction_date"].astimezone(THAI_TZ).date().isoformat() == "2026-09-01"

    # 🏷️ metadata ต้องมีคีย์ชุดเดียวกับ dual-write สด + รอยประทับว่าใครสร้าง
    meta = _meta(entry)
    assert meta["legacy_transaction_id"] == tx_id
    assert meta["backfilled"] is True
    assert meta["backfill_source"] == "backfill_missing_journals"
    assert meta["backfill_legacy_ids"] == [tx_id]

    # ⚖️ Dr = Cr และขา Dr อยู่ฝั่งสินทรัพย์ (income)
    lines = await _fetch_lines(db_pool, entry["id"])
    assert len(lines) == 2
    assert sum(float(ln["debit"]) for ln in lines) == pytest.approx(750.0)
    assert sum(float(ln["credit"]) for ln in lines) == pytest.approx(750.0)
    asset_line = next(ln for ln in lines if ln["account_type"] == "asset")
    assert float(asset_line["debit"]) == pytest.approx(750.0)
    assert asset_line["legacy_account_id"] == account_id
    rev_line = next(ln for ln in lines if ln["account_type"] == "revenue")
    assert float(rev_line["credit"]) == pytest.approx(750.0)
    assert rev_line["legacy_category_id"] == cat_id


# === 4. idempotency =========================================================


async def test_backfill_is_idempotent_across_runs(db_pool):
    """รันซ้ำต้องไม่สร้างซ้ำ — เงื่อนไข NOT EXISTS ทำให้เป็น idempotent โดยโครงสร้าง."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_legacy_tx(
        db_pool, room_id, amount=120.0, transaction_type="expense",
        account_id=account_id, category_id=cat_id, created_at=POST_CUTOFF_UTC,
    )

    rep1 = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep1["journals_created"] == 1

    rep2 = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep2["candidates"] == 0
    assert rep2["journals_created"] == 0
    assert await _count_journals(db_pool, room_id) == 1

    # รันซ้ำอีกรอบแบบ dry-run ก็ยังต้องเห็น 0 (ไม่ใช่เห็น 1 แล้วเขียนซ้ำ)
    rep3 = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=False)
    assert rep3["candidates"] == 0
    assert rep3["journals_planned"] == 0


async def test_row_that_already_has_journal_is_not_a_candidate(db_pool):
    """แถวที่ผ่าน dual-write ปกติแล้วต้องไม่ถูกมองว่า "ตกหล่น" (กันนับซ้ำ)."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=300.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=POST_CUTOFF_UTC,
    )
    # จำลอง dual-write สด: journal ที่ metadata ชี้แถวนี้ (ยังไม่ void)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._insert_journal_entry(
                conn, room_id, reference_type="manual_transaction", reference_id=str(tx_id),
                description="dual-write", recorded_by="Tester",
                metadata={"legacy_transaction_id": tx_id},
                lines=[
                    {"ledger_id": await FinanceService._resolve_asset_ledger(conn, room_id, account_id),
                     "debit": 300.0, "credit": 0},
                    {"ledger_id": await FinanceService._resolve_category_ledger(conn, room_id, cat_id, "income"),
                     "debit": 0, "credit": 300.0},
                ],
            )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["candidates"] == 0
    assert rep["journals_created"] == 0
    assert await _count_journals(db_pool, room_id) == 1


# === 5. แถวที่ถูกลบไปแล้ว ====================================================


async def test_deleted_legacy_row_is_skipped(db_pool):
    """แถวที่ `deleted_at IS NOT NULL` = ถูก revert และคืนยอดแล้ว.

    ถ้า backfill สร้าง journal ให้ ⇒ ได้ journal สถานะ 'posted' ⇒ รายการผีโผล่กลับมาในประวัติ
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=900.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC, deleted=True,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["candidates"] == 0
    assert await _count_journals(db_pool, room_id) == 0
    assert await _fetch_journal_by_legacy(db_pool, room_id, tx_id) is None


# === 6. กลุ่มโอนเงิน: 2 แถว legacy → 1 journal ==============================


async def test_transfer_group_creates_one_journal_for_both_legs(db_pool):
    """เงินโอน 1 ครั้ง = แถว legacy 2 แถว แต่ journal มี **ใบเดียว**.

    ถ้าสร้างแยกขา ยอดโอนจะถูกนับซ้ำในงบการเงิน (asset เคลื่อนไหว 2 เท่า)
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 0.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "บัญชีธนาคารห้อง", 0.0)
    group_id = random.randint(1_000_000, 9_999_999)
    out_id = await _insert_legacy_tx(
        db_pool, room_id, amount=2000.0, description="โอนออก: ฝากเงินเข้าธนาคาร",
        transaction_type="expense", account_id=from_acc, created_at=STRADDLE_UTC,
        transfer_group_id=group_id,
    )
    in_id = await _insert_legacy_tx(
        db_pool, room_id, amount=2000.0, description="รับโอน: ฝากเงินเข้าธนาคาร",
        transaction_type="income", account_id=to_acc, created_at=STRADDLE_UTC,
        transfer_group_id=group_id,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["candidates"] == 2          # แถว legacy 2 แถว
    assert rep["journals_created"] == 1    # แต่ journal ใบเดียว
    assert rep["by_kind"] == {"transfer": 1}
    assert await _count_journals(db_pool, room_id) == 1

    entry = await _fetch_journal_by_legacy(db_pool, room_id, out_id)
    assert entry is not None
    assert entry["reference_type"] == "transfer"
    assert entry["reference_id"] == str(group_id)
    # metadata ต้องมีทั้งคู่ — revert_transaction หา journal ด้วย transfer_group_id
    meta = _meta(entry)
    assert meta["transfer_group_id"] == group_id
    assert meta["legacy_transaction_ids"] == [out_id, in_id]
    # 💡 description ถูกถอด prefix "โอนออก: " ออก → เหมือน dual-write สด
    assert entry["description"] == "ฝากเงินเข้าธนาคาร"

    lines = await _fetch_lines(db_pool, entry["id"])
    assert len(lines) == 2
    debited = next(ln for ln in lines if float(ln["debit"]) > 0)
    credited = next(ln for ln in lines if float(ln["credit"]) > 0)
    assert debited["legacy_account_id"] == to_acc      # Dr ปลายทาง
    assert credited["legacy_account_id"] == from_acc   # Cr ต้นทาง
    assert float(debited["debit"]) == pytest.approx(2000.0)
    assert float(credited["credit"]) == pytest.approx(2000.0)


async def test_malformed_transfer_group_is_reported_not_raised(db_pool):
    """กลุ่มโอนที่ขาไม่ครบ 2 ขา → รายงานเป็น "ข้าม" พร้อมเหตุผล ไม่ล้มทั้งสคริปต์.

    แถวอื่นในห้องเดียวกันต้องยัง backfill ได้ตามปกติ (ops tool ต้องไม่หยุดกลางคัน)
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 0.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    broken_group = random.randint(1_000_000, 9_999_999)
    await _insert_legacy_tx(
        db_pool, room_id, amount=500.0, description="โอนออก: ข้อมูลกำพร้า",
        transaction_type="expense", account_id=from_acc, created_at=POST_CUTOFF_UTC,
        transfer_group_id=broken_group,
    )
    good_tx = await _insert_legacy_tx(
        db_pool, room_id, amount=250.0, transaction_type="income",
        account_id=from_acc, category_id=cat_id, created_at=POST_CUTOFF_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["journals_created"] == 1          # แถวปกติยังได้
    assert len(rep["skipped"]) == 1
    assert rep["skipped"][0]["group_id"] == broken_group
    assert "ขาไม่ครบ" in rep["skipped"][0]["reason"]
    # ขาที่กำพร้าไม่ได้ถูกสร้าง journal
    assert await _count_journals(db_pool, room_id) == 1
    assert await _fetch_journal_by_legacy(db_pool, room_id, good_tx) is not None


async def test_transfer_legs_with_unequal_amounts_are_skipped(db_pool):
    """สองขาโอนจำนวนไม่เท่ากัน = ข้อมูลเสีย → ข้ามพร้อมเหตุผล (ไม่สร้าง journal ที่ไม่สมดุล)."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 0.0)
    to_acc = await _insert_finance_account(db_pool, room_id, "บัญชีธนาคารห้อง", 0.0)
    group_id = random.randint(1_000_000, 9_999_999)
    await _insert_legacy_tx(
        db_pool, room_id, amount=1000.0, description="โอนออก: เพี้ยน",
        transaction_type="expense", account_id=from_acc, created_at=POST_CUTOFF_UTC,
        transfer_group_id=group_id,
    )
    await _insert_legacy_tx(
        db_pool, room_id, amount=999.0, description="รับโอน: เพี้ยน",
        transaction_type="income", account_id=to_acc, created_at=POST_CUTOFF_UTC,
        transfer_group_id=group_id,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["journals_created"] == 0
    assert len(rep["skipped"]) == 1
    assert "ไม่เท่ากัน" in rep["skipped"][0]["reason"]
    assert await _count_journals(db_pool, room_id) == 0


# === 7. student_payment shape + FIX A =======================================


async def test_student_payment_row_uses_payment_metadata_and_autoprovisions_revenue(db_pool):
    """แถว legacy ของการรับชำระเงิน → journal ต้องอ้าง `student_payment_id` ให้ revert ตามได้.

    และกรณี **ห้องยังไม่มี ledger รายได้เลย** (รอยรั่วจริงสมัยก่อน FIX A) ต้อง auto-provision
    ไม่ใช่ปล่อยผ่าน — ไม่งั้นเงินที่รับมาก็ยังหายจากงบการเงินอยู่ดี
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด")
    async with db_pool.acquire() as conn:
        student_id = await conn.fetchval(
            "SELECT id FROM students WHERE room_id = $1 ORDER BY id LIMIT 1", room_id
        )
    payment_id = await _insert_payment(db_pool, student_id, paid_amount=300.0)
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=300.0, description="รับเงิน: ค่าห้อง จาก เด็กชายทดสอบ [ครบ]",
        transaction_type="income", account_id=account_id, created_at=STRADDLE_UTC,
        student_payment_id=payment_id,
    )
    # ⚠️ เจตนา: ไม่มี revenue ledger ในห้องนี้เลย → ต้อง auto-provision (FIX A)
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM accounting_ledgers WHERE room_id = $1 AND account_type = 'revenue'", room_id
        ) == 0

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["journals_created"] == 1
    assert rep["by_kind"] == {"student_payment": 1}

    entry = await _fetch_journal_by_legacy(db_pool, room_id, tx_id)
    assert entry is not None
    assert entry["reference_type"] == "student_payment"
    assert entry["reference_id"] == str(payment_id)
    assert _meta(entry)["student_payment_id"] == payment_id

    # ledger รายได้ถูกสร้างขึ้นจริง และลงขา Cr (ไม่ใช่ปล่อยผ่าน)
    async with db_pool.acquire() as conn:
        revenue_ledger = await conn.fetchrow(
            "SELECT id, account_name FROM accounting_ledgers "
            "WHERE room_id = $1 AND account_type = 'revenue' ORDER BY id LIMIT 1", room_id
        )
    assert revenue_ledger is not None
    assert revenue_ledger["account_name"] == DEFAULT_INCOME_CATEGORIES[0]
    lines = await _fetch_lines(db_pool, entry["id"])
    rev_line = next(ln for ln in lines if ln["account_type"] == "revenue")
    assert rev_line["legacy_category_id"] is not None
    assert float(rev_line["credit"]) == pytest.approx(300.0)


# === 8. revert ต้องใช้ได้กับ journal ที่ backfill มา ========================


async def test_revert_transaction_voids_backfilled_journal(db_pool):
    """หลัง backfill แล้ว ผู้ใช้ต้องยกเลิกรายการนั้นได้ตามปกติ.

    `revert_transaction` หา journal จาก `metadata->>'legacy_transaction_id'`
    ⇒ ถ้า backfill ใส่คีย์อื่น ยกเลิกไม่ได้ และรายการจะค้างในงบตลอดกาล
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", balance=5000.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id = await _insert_legacy_tx(
        db_pool, room_id, amount=400.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["journals_created"] == 1

    await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=tx_id, user_id=owner,
        client_source="script", actor_identifier="Tester", user_name="Tester",
        room_id=room_id,
    )

    entry = await _fetch_journal_by_legacy(db_pool, room_id, tx_id)
    assert entry["status"] == "voided"
    assert entry["deleted_at"] is not None
    # ฝั่ง legacy ถูก mark ด้วย (สองฝั่งสอดคล้องกัน = ไม่นับซ้ำ)
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT deleted_at FROM finance_transactions WHERE id = $1", tx_id
        ) is not None


async def test_revert_transfer_group_voids_backfilled_transfer_journal(db_pool):
    """เส้นทางโอนเงินใช้คีย์คนละตัว (`transfer_group_id`) — ต้องถูกต้องด้วย."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    from_acc = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 0.0)
    # ปลายทางต้องมียอดพอหักคืนตอน revert (revert ขา income = เอาเงินออกจากบัญชีปลายทาง)
    to_acc = await _insert_finance_account(db_pool, room_id, "บัญชีธนาคารห้อง", 1000.0)
    group_id = random.randint(1_000_000, 9_999_999)
    out_id = await _insert_legacy_tx(
        db_pool, room_id, amount=1000.0, description="โอนออก: ย้ายเงิน",
        transaction_type="expense", account_id=from_acc, created_at=STRADDLE_UTC,
        transfer_group_id=group_id,
    )
    await _insert_legacy_tx(
        db_pool, room_id, amount=1000.0, description="รับโอน: ย้ายเงิน",
        transaction_type="income", account_id=to_acc, created_at=STRADDLE_UTC,
        transfer_group_id=group_id,
    )

    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    entry = await _fetch_journal_by_legacy(db_pool, room_id, out_id)
    assert entry is not None

    await FinanceService.revert_transaction(
        pool=db_pool, transaction_id=out_id, user_id=owner,
        client_source="script", actor_identifier="Tester", user_name="Tester",
        room_id=room_id,
    )
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, deleted_at FROM journal_entries WHERE id = $1", entry["id"]
        )
    assert row["status"] == "voided"
    assert row["deleted_at"] is not None


# === 9. ต้นเหตุของงานทั้งหมด: รายการต้อง "โผล่" หลัง backfill ================


async def test_straddle_row_is_invisible_before_and_visible_after_backfill(db_pool):
    """🎯 เทสต์ที่พิสูจน์ว่าบั๊กถูกแก้จริง (ไม่ใช่แค่สร้าง journal แล้วผ่าน).

    ผู้อ่านสองฝั่งแบ่งงานกันตาม **วันที่ไทย**: ฝั่ง legacy รับเฉพาะวันไทยก่อนเส้นตัด
    และ merge cap ที่ 31 ส.ค. ส่วนฝั่ง v2 รับวันไทย >= 1 ก.ย. จาก journal
    ⇒ แถวเช้ามืดวันที่ 1 (ที่ยังไม่มี journal) **ไม่มีผู้อ่านฝั่งใดรับเลย** = หายจากหน้าประวัติ
    หลัง backfill แล้วต้องกลับมา และ **ต้องได้ 1 รายการ ไม่ใช่ 2** (ไม่นับซ้ำ)
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด")
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_legacy_tx(
        db_pool, room_id, amount=750.0, description="เงินบริจาคช่วงเปลี่ยนผ่าน",
        transaction_type="income", account_id=account_id, category_id=cat_id,
        created_at=STRADDLE_UTC,
    )

    # 📅 เดือนไทย ก.ย. 2026 (เส้นตัดอยู่ต้นเดือนนี้)
    sep_start, sep_end = date(2026, 9, 1), date(2026, 9, 30)

    # ก่อน backfill: ขอทั้งเดือน → ไม่มีอะไรเลย (นี่คืออาการที่ผู้ใช้เห็น)
    before = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner, start_date=sep_start, end_date=sep_end,
    )
    assert before["total_count"] == 0

    # ก่อน backfill: ขอแบบไม่กรองช่วง (เส้นทาง MERGE) ก็ยังไม่เห็น
    before_merged = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner,
    )
    assert before_merged["total_count"] == 0

    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)

    # หลัง backfill: เห็น 1 รายการ พร้อมยอดและ description ครบ
    after = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner, start_date=sep_start, end_date=sep_end,
    )
    assert after["total_count"] == 1
    assert float(after["items"][0]["amount"]) == pytest.approx(750.0)
    assert after["items"][0]["description"] == "เงินบริจาคช่วงเปลี่ยนผ่าน"

    # และเส้นทาง MERGE ก็ต้องเห็น **1 ไม่ใช่ 2** (แถว legacy ถูก cap ออกไปแล้ว)
    after_merged = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner,
    )
    assert after_merged["total_count"] == 1

    # 📊 และงบกำไรขาดทุนของเดือน ก.ย. ต้องเห็นเงินก้อนนี้ด้วย (F1 อ่าน journal เท่านั้น)
    pl = await FinanceService.get_income_statement(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner, start_date=sep_start, end_date=sep_end,
    )
    assert float(pl["total_revenue"]) == pytest.approx(750.0)


async def test_backfilled_journal_lands_in_the_right_thai_month(db_pool):
    """วางเดือนไทยให้ถูก: แถวไทย 1 ก.ย. ต้องไม่ไปโผล่ในเดือน ส.ค. (และกลับกัน).

    ถ้าสคริปต์เผลอใช้ `transaction_date = NOW()` รายการจะไปกองที่เดือนที่รันสคริปต์
    ⇒ เดือนที่ขาดก็ยังขาดอยู่ดี (บั๊กเดิมไม่หาย แค่ย้ายที่)
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_legacy_tx(
        db_pool, room_id, amount=100.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC,
    )
    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)

    aug = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
    )
    assert aug["total_count"] == 0
    sep = await FinanceService.get_transactions(
        pool=db_pool, client_source="script", actor_identifier="Tester",
        room_id=room_id, user_id=owner,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
    )
    assert sep["total_count"] == 1


# === 10. การ resolve ห้อง + ห้องที่ไม่มีอะไรต้องทำ ===========================


async def test_server_id_resolution_and_unknown_room(db_pool):
    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_legacy_tx(
        db_pool, room_id, amount=100.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=POST_CUTOFF_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, server_id=server_id, apply=True)
    assert rep["room_id"] == room_id
    assert rep["room_name"] == "Test Room"
    assert rep["journals_created"] == 1

    with pytest.raises(RoomNotFoundError):
        await FinanceService.backfill_missing_journals(pool=db_pool, room_id=9_999_999, apply=False)

    with pytest.raises(ValueError):
        await FinanceService.backfill_missing_journals(pool=db_pool, apply=False)


async def test_room_with_nothing_to_do_reports_zero(db_pool):
    """ห้องที่ไม่มีแถวตกหล่น → รายงาน 0 ทุกช่อง ไม่ error (สำคัญสำหรับ `--all`)."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    assert rep["candidates"] == 0
    assert rep["journals_planned"] == 0
    assert rep["journals_created"] == 0
    assert rep["total_amount"] == 0
    assert rep["by_kind"] == {}
    assert rep["skipped"] == []
    assert rep["prior_adjustments"] == 0
    assert rep["cutoff_date"] == "2026-09-01"


# === 11. อันตรายจาก reconcile ที่รันไปก่อนหน้า ==============================


async def test_prior_reconcile_adjustment_is_reported(db_pool):
    """🚨 ห้องที่เคยรัน `reconcile_finance.py --apply` มาก่อน → ต้อง **รายงาน** ไม่ใช่เงียบ.

    `reconcile_balances` แก้ "ผลต่างยอดคงเหลือ" ด้วย `Dr สินทรัพย์ / Cr ทุน 3001` ซึ่งมักเป็น
    ผลต่างตัวเดียวกับที่แถวตกหล่นทำให้เกิด ⇒ พอ backfill เพิ่มการเคลื่อนไหวจริงเข้าไปอีก
    **ยอดสินทรัพย์จะเบิ้ล** (ledger = 2 เท่าของ legacy)

    ตรวจไม่เจอด้วย `NOT EXISTS` เพราะ journal ปรับปรุงยอดไม่มี `legacy_transaction_id`
    ⇒ ทางออกคือรายงานให้ผู้ใช้รู้ + ให้รัน reconcile ซ้ำหลัง backfill (รอบสองจะปรับกลับเอง)

    เทสต์นี้ล็อก **เจตนา**: รายงานแต่ **ไม่บล็อก** (ยัง backfill ให้) เพราะการไม่ backfill
    ก็ทำให้รายการหายจากงบต่อ — ผู้ใช้ต้องเป็นคนตัดสินจากคำเตือน
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", balance=750.0)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    # จำลองว่า reconcile ถูกสั่งไปแล้ว: Dr สินทรัพย์ 750 / Cr ทุน 3001 750
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            equity_id = await conn.fetchval(
                "INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description) "
                "VALUES ($1, '3001', 'ปรับปรุงยอด (Reconciliation)', 'equity', 'test') RETURNING id", room_id)
            await FinanceService._insert_journal_entry(
                conn, room_id, reference_type="adjustment", description="ปรับปรุงยอดคงเหลือ",
                recorded_by="SYSTEM",
                metadata={"adjustment_type": "reconcile", "finance_account_id": account_id},
                lines=[
                    {"ledger_id": await FinanceService._resolve_asset_ledger(conn, room_id, account_id),
                     "debit": 750.0, "credit": 0},
                    {"ledger_id": equity_id, "debit": 0, "credit": 750.0},
                ],
            )

    await _insert_legacy_tx(
        db_pool, room_id, amount=750.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC,
    )

    rep = await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=False)
    assert rep["prior_adjustments"] == 1     # ← ตรวจเจอและรายงาน
    assert rep["journals_planned"] == 1      # ← แต่ไม่บล็อก (ยังวางแผนให้)

    # พิสูจน์ว่าอันตรายเป็นจริง: หลัง backfill ยอด ledger เกิน legacy 2 เท่า
    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    async with db_pool.acquire() as conn:
        ledger_net = float(await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.legacy_account_id = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, account_id) or 0)
    assert ledger_net == pytest.approx(1500.0)   # = 750 (reconcile) + 750 (backfill) ≠ 750 legacy

    # ✅ และ reconcile ที่รันซ้ำจะเก็บกวาดให้เอง (ฝั่งรายได้ไม่ถูกแตะ)
    rep2 = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert rep2["adjustments_created"] == 1
    async with db_pool.acquire() as conn:
        ledger_net_after = float(await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.legacy_account_id = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, account_id) or 0)
    assert ledger_net_after == pytest.approx(750.0)   # กลับมาตรงกับ legacy


# === 12. audit log ==========================================================


async def test_apply_writes_audit_log(db_pool):
    """ops tool ที่แตะเงินต้องมีร่องรอยใน `audit_logs` (กฎ backend: ทุก mutation ต้อง audit)."""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _insert_legacy_tx(
        db_pool, room_id, amount=250.0, transaction_type="income",
        account_id=account_id, category_id=cat_id, created_at=STRADDLE_UTC,
    )

    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=True)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT action, entity_type, actor_identifier, client_source, new_values "
            "FROM audit_logs WHERE room_id = $1 AND entity_type = 'FINANCE_BACKFILL' "
            "ORDER BY id DESC LIMIT 1", room_id,
        )
    assert row is not None
    assert row["action"] == "BACKFILL"
    assert row["actor_identifier"] == "SYSTEM"
    assert row["client_source"] == "script"
    # audit_logs.new_values เป็น JSONB ⇒ asyncpg คืน string ใน harness นี้
    new_values = json.loads(row["new_values"]) if isinstance(row["new_values"], str) else row["new_values"]
    assert new_values["journals_created"] == 1

    # dry-run ต้องไม่ทิ้ง audit (ไม่มีการเปลี่ยนแปลงให้บันทึก)
    async with db_pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE room_id = $1 AND entity_type = 'FINANCE_BACKFILL'", room_id
        )
    await FinanceService.backfill_missing_journals(pool=db_pool, room_id=room_id, apply=False)
    async with db_pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT COUNT(*) FROM audit_logs WHERE room_id = $1 AND entity_type = 'FINANCE_BACKFILL'", room_id
        )
    assert after == before
