"""
Integration tests สำหรับ FinanceService.reconcile_balances (Reconciliation script).

ขอบเขต: เปรียบเทียบ finance_accounts.balance (ระบบเดิม) กับยอดสุทธิ asset-ledger
ในบัญชีคู่ของแต่ละบัญชี และเมื่อ apply แล้วให้ยอดบัญชีคู่กลับมาเท่า Legacy พอดี
(สร้าง journal reference_type='adjustment' + ขาสะท้อน equity '3001')

Pattern ตาม docs/rules/testing.md: ไม่ hardcode id, ใช้ randomized server_id,
deep DB verification ผ่าน db_pool, ไม่แตะ Redis (service ล้วน ๆ → ไม่ต้อง mock)
"""
import random
import string
import uuid

import pytest

from core.exceptions import RoomNotFoundError
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# === Fixtures & Setup (ลอกจาก test_finance_v2_read.py เพื่อ isolation) ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", username=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (email, first_name, last_name, username) VALUES ($1, $2, $3, $4) RETURNING id",
            email, first_name, last_name, username,
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


async def _insert_raw_account(pool, room_id: int, account_name: str, balance: float) -> int:
    """finance_accounts อย่างเดียว (ไม่มี asset ledger) — จำลองบัญชีที่ dual-write ไม่เคย provision."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, account_name, balance,
        )


async def _insert_revenue_ledger(pool, room_id: int) -> int:
    """สร้าง ledger รายได้ (revenue) สำหรับป้อน journal ขา Cr."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description) "
            "VALUES ($1, '4001', 'เงินบริจาค', 'revenue', 'test') RETURNING id",
            room_id,
        )


async def _post_journal(pool, room_id: int, lines: list) -> str:
    """ป้อน journal_entries ตรง ๆ (seed สำหรับจำลอง "journal ลงแล้วแต่ legacy ไม่มี")."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            entry_id = await FinanceService._insert_journal_entry(
                conn, room_id,
                reference_type="manual_transaction",
                reference_id=str(random.randint(1, 1_000_000)),
                description="seed journal for reconcile test",
                recorded_by="Test",
                metadata={"note": "reconcile-test"},
                lines=lines,
            )
            return str(entry_id)


async def _account_asset_net(pool, room_id: int, account_id: int) -> float:
    """SUM(debit−credit) ของ asset ledger ของบัญชี (เงื่อนไขเดียวกับ summary v2)."""
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE AL.legacy_account_id = $1 AND AL.account_type = 'asset'
                 AND JE.room_id = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            account_id, room_id,
        ) or 0.0)


async def _count_adjustments(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1 AND reference_type = 'adjustment'",
            room_id,
        )


# === เทส: dry-run + apply (เลียนแบบรอยรั่ว #1 — legacy ได้เงินแต่ journal ไม่มี) ===


async def test_dry_run_detects_positive_drift_then_apply_fixes(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    # account มียอด 1000 ในระบบเดิม (balance) แต่ asset ledger ยัง net 0 (ไม่มี journal)
    await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 1000.0)

    # dry-run: แค่รายงาน ไม่เขียน
    rep = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=False)
    assert rep["room_id"] == room_id
    assert rep["checked_accounts"] == 1
    assert rep["adjustments_created"] == 0
    assert rep["mismatches"][0]["action"] == "dr_asset"
    assert rep["mismatches"][0]["amount"] == pytest.approx(1000.0)
    assert await _count_adjustments(db_pool, room_id) == 0  # ยังไม่เขียน

    # apply: สร้าง 1 adjustment ใบ
    rep2 = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert rep2["adjustments_created"] == 1
    assert rep2["total_adjustment_amount"] == pytest.approx(1000.0)

    # deep DB: มี entry reference_type='adjustment' + 2 lines (asset Dr / equity Cr)
    async with db_pool.acquire() as conn:
        entry = await conn.fetchrow(
            """SELECT * FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'adjustment'""", room_id
        )
        assert entry is not None
        assert entry["recorded_by"] == "SYSTEM"
        assert entry["status"] == "posted"
        lines = await conn.fetch(
            """SELECT L.debit, L.credit, AL.account_type, AL.account_code
               FROM journal_lines L
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE L.journal_entry_id = $1 ORDER BY L.id""", entry["id"]
        )
        assert len(lines) == 2
        asset_line = next(ln for ln in lines if ln["account_type"] == "asset")
        equity_line = next(ln for ln in lines if ln["account_type"] == "equity")
        assert float(asset_line["debit"]) == pytest.approx(1000.0)
        assert float(asset_line["credit"]) == 0.0
        assert float(equity_line["credit"]) == pytest.approx(1000.0)
        assert float(equity_line["debit"]) == 0.0
        assert equity_line["account_code"] == "3001"
    # หลัง apply: net บัญชีคู่ == ยอด legacy เป๊ะ ๆ (ดึง account_id จริง ไม่ hardcode)
    async with db_pool.acquire() as conn:
        account_id = await conn.fetchval(
            "SELECT id FROM finance_accounts WHERE room_id = $1", room_id
        )
    assert await _account_asset_net(db_pool, room_id, account_id) == pytest.approx(1000.0)


async def test_negative_drift_credits_asset(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    account_id = await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 0.0)
    # journal มี asset Dr 500 / revenue Cr 500 → asset net 500 แต่ legacy balance ยัง 0
    rev_ledger = await _insert_revenue_ledger(db_pool, room_id)
    async with db_pool.acquire() as conn:
        asset_ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_account_id = $1 AND account_type = 'asset'",
            account_id,
        )
    await _post_journal(
        db_pool, room_id,
        lines=[
            {"ledger_id": asset_ledger_id, "debit": 500.0, "credit": 0,
             "line_description": "รับรายได้แต่ legacy ยังไม่บันทึก (ทดสอบ)"},
            {"ledger_id": rev_ledger, "debit": 0, "credit": 500.0,
             "line_description": "รายได้"},
        ],
    )
    assert await _account_asset_net(db_pool, room_id, account_id) == pytest.approx(500.0)

    rep = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert rep["adjustments_created"] == 1
    assert rep["mismatches"][0]["action"] == "cr_asset"
    assert rep["mismatches"][0]["amount"] == pytest.approx(500.0)

    # deep DB: ขา asset เป็น credit, ขา equity เป็น debit
    async with db_pool.acquire() as conn:
        entry = await conn.fetchrow(
            "SELECT * FROM journal_entries WHERE room_id = $1 AND reference_type = 'adjustment'", room_id
        )
        lines = await conn.fetch(
            """SELECT L.debit, L.credit, AL.account_type
               FROM journal_lines L
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE L.journal_entry_id = $1 ORDER BY L.id""", entry["id"]
        )
        asset_line = next(ln for ln in lines if ln["account_type"] == "asset")
        equity_line = next(ln for ln in lines if ln["account_type"] == "equity")
        assert float(asset_line["credit"]) == pytest.approx(500.0)
        assert float(asset_line["debit"]) == 0.0
        assert float(equity_line["debit"]) == pytest.approx(500.0)
        assert float(equity_line["credit"]) == 0.0
    # หลัง apply: net กลับมาเท่า legacy (0)
    assert await _account_asset_net(db_pool, room_id, account_id) == pytest.approx(0.0)


async def test_idempotent_second_apply(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    await _insert_finance_account(db_pool, room_id, "กระเป๋าเงินสด", 1000.0)

    await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert await _count_adjustments(db_pool, room_id) == 1

    # รอบสอง: ไม่มีผลต่างเหลือ → ไม่สร้างเพิ่ม
    rep = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert rep["mismatches"] == []
    assert rep["adjustments_created"] == 0
    assert await _count_adjustments(db_pool, room_id) == 1


async def test_missing_asset_ledger_is_provisioned(db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    # บัญชี A มียอด แต่ไม่มี asset ledger เลย (dual-write ไม่เคย provision) → ต้องสร้างให้ + ปรับยอด
    acct_a = await _insert_raw_account(db_pool, room_id, "บัญชีไม่มี ledger", 123.45)
    # บัญชี B ยอด 0 ไม่มี ledger → ต้องโดนข้าม (ไม่สร้าง ledger ขยะ)
    await _insert_raw_account(db_pool, room_id, "บัญชีว่าง", 0.0)

    rep = await FinanceService.reconcile_balances(pool=db_pool, room_id=room_id, apply=True)
    assert rep["adjustments_created"] == 1
    assert rep["checked_accounts"] == 2
    # ตรวจเฉพาะตัวที่ต่าง (A) — B ข้ามไป
    assert [m["account_name"] for m in rep["mismatches"]] == ["บัญชีไม่มี ledger"]

    async with db_pool.acquire() as conn:
        # A: มี asset ledger ใหม่ code 1{id:04d}
        ledger_a = await conn.fetchrow(
            """SELECT * FROM accounting_ledgers
               WHERE room_id = $1 AND legacy_account_id = $2 AND account_type = 'asset'""",
            room_id, acct_a,
        )
        assert ledger_a is not None
        assert ledger_a["account_code"] == f"1{acct_a:04d}"
        # B: ยังไม่มี ledger
        b_ledger_count = await conn.fetchval(
            """SELECT COUNT(*) FROM accounting_ledgers
               WHERE room_id = $1 AND legacy_account_id = $2""",
            room_id,
            await conn.fetchval("SELECT id FROM finance_accounts WHERE room_id = $1 AND account_name = 'บัญชีว่าง'", room_id),
        )
        assert b_ledger_count == 0
    assert await _account_asset_net(db_pool, room_id, acct_a) == pytest.approx(123.45)


async def test_server_id_resolution_and_unknown_room(db_pool):
    owner = await _insert_user(db_pool)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    # resolve ผ่าน server_id ได้
    rep = await FinanceService.reconcile_balances(pool=db_pool, server_id=server_id, apply=False)
    assert rep["room_id"] == room_id
    assert rep["mismatches"] == []  # ยังไม่มีบัญชี → ตรงกัน

    # ไม่พบห้อง → RoomNotFoundError
    with pytest.raises(RoomNotFoundError):
        await FinanceService.reconcile_balances(
            pool=db_pool, server_id=random.randint(10_000_000, 99_999_999)
        )
    with pytest.raises(RoomNotFoundError):
        await FinanceService.reconcile_balances(
            pool=db_pool, room_id=random.randint(10_000_000, 99_999_999)
        )
