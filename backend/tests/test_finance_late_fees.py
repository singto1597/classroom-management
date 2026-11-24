"""⏰ ค่าปรับจ่ายล่าช้าอัตโนมัติ (Phase 6.5)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **เลือกบิลถูกชุด** — เฉพาะบิลโปรเจกต์ที่เลยกำหนด **พ้นวันผ่อนผันแล้ว** · ยอดคงเหลือ > 0
   · ยังไม่มีค่าปรับล่าช้า · แคมเปญตั้ง `late_fee_mode <> 'none'`
   (บิลจ่ายครบ / ถูกลบ / โปรเจกต์ถูกลบ / แคมเปญ `none` / โปรเจกต์ซ่อน kind='fine' ต้องหลุด)
2. **คิดยอดถูก** — `fixed` = จำนวนคงที่ · `percent` = % ของ **ยอดคงเหลือ** · ไม่เกินยอดค้าง
3. **ออกผ่านเครื่องจักรเดิมครบ** — แคมเปญซ่อน `kind='fine'` + บิล + accrual
   Dr 11002 / Cr 49001 + INV- 1 ใบ + `fines.auto_late_fee=TRUE` + ลิงก์ `source_payment_id`
4. **1 บิลต้นทาง = 1 ค่าปรับตลอดชีพ** — เรียกซ้ำไม่สร้างใหม่ (unique index เป็นด่านจริง)
5. **worker เรียกก่อนเตือนรายวัน** — `run_once` ถึงเวลา ⇒ apply_late_fees ถูกเรียก
"""
import random
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from services.action_service import ActionService
from services.finance.constants import (
    AR_FINE_CODE, COLLECTION_KIND_FINE, FINE_REVENUE_CODE, LATE_FEE_FINE_TYPE_NAME,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

AS_OF = date(2026, 11, 24)


# ---------------------------------------------------------------- seeding

async def _insert_student(pool, room_id: int, *, student_no: int | None = None, with_user: bool = True) -> int:
    student_no = student_no if student_no is not None else random.randint(100, 9999)
    async with pool.acquire() as conn:
        user_id = None
        if with_user:
            user_id = await conn.fetchval(
                "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
                "Kid", "Test", f"u{uuid.uuid4().hex[:12]}",
            )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *, due: date, amount: float = 100.0,
    paid: float = 0.0, mode: str = "fixed", fee: float = 20.0, grace: int = 0,
    kind: str = "project", bill_status: str = "pending", bill_deleted: bool = False,
    coll_deleted: bool = False,
) -> tuple[int, int]:
    """คืน (collection_id, payment_id)"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, collection_kind,
                    late_fee_mode, late_fee_amount, late_fee_grace_days, deleted_at)
               VALUES ($1, $2, $3, $4, 'active', $5, $6, $7, $8,
                       CASE WHEN $9 THEN NOW() ELSE NULL END)
               RETURNING id""",
            room_id, f"ค่าห้อง {uuid.uuid4().hex[:4]}", amount, due, kind,
            mode, fee, grace, coll_deleted,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, deleted_at)
               VALUES ($1, $2, $3, $4, CASE WHEN $5 THEN NOW() ELSE NULL END) RETURNING id""",
            collection_id, student_id, bill_status, paid, bill_deleted,
        )
        return collection_id, payment_id


async def _set_server_id(pool, room_id: int, server_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, room_id)


async def _ledger_net(pool, room_id: int, code: str, side: str) -> float:
    expr = "debit - credit" if side == "debit" else "credit - debit"
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            f"""SELECT COALESCE(SUM(L.{expr}), 0)
                FROM journal_lines L
                JOIN journal_entries JE ON L.journal_entry_id = JE.id
                JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                WHERE JE.room_id = $1 AND AL.account_code = $2
                  AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, code,
        )
    return round(float(val), 2)


# ---------------------------------------------------------------- candidacy + คำนวณ

async def test_collects_only_overdue_beyond_grace_with_policy(db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _insert_student(db_pool, room_id, student_no=random.randint(100, 9999))

    keep = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=3), mode="fixed", fee=10)
    keep_grace = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=3),
                                    mode="percent", fee=5, grace=5)  # ยังอยู่ในผ่อนผัน
    keep_paid_some = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=9),
                                        amount=100.0, paid=40.0, mode="percent", fee=10)

    # ↓ ต้องหลุด
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), mode="none")
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), mode="fixed", fee=10,
                       paid=100.0)                       # จ่ายครบ
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), mode="fixed",
                       bill_deleted=True)                # บิลถูกลบ
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), mode="fixed",
                       coll_deleted=True)                # โปรเจกต์ถูกลบ
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), mode="fixed",
                       kind=COLLECTION_KIND_FINE)        # โปรเจกต์ซ่อน (ค่าปรับ) — ห้ามปรับซ้อน

    async with db_pool.acquire() as conn:
        rows = await FinanceService._collect_late_fee_candidates(
            conn, as_of=AS_OF, room_id=room_id
        )

    assert sorted(r["payment_id"] for r in rows) == sorted([
        keep[1], keep_paid_some[1]
    ])  # keep_grace ยังไม่พ้นผ่อนผัน


async def test_compute_fixed_percent_and_cap(db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _insert_student(db_pool, room_id, student_no=random.randint(100, 9999))
    _, fixed_pid = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=2),
                                      amount=100.0, paid=30.0, mode="fixed", fee=20.0)
    _, pct_pid = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=2),
                                    amount=100.0, paid=20.0, mode="percent", fee=10.0)
    _, cap_pid = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=2),
                                    amount=10.0, paid=9.5, mode="fixed", fee=20.0)

    async with db_pool.acquire() as conn:
        rows = await FinanceService._collect_late_fee_candidates(
            conn, as_of=AS_OF, room_id=room_id
        )
    by_pid = {r["payment_id"]: r for r in rows}

    assert FinanceService._compute_late_fee_amount(by_pid[fixed_pid]) == 20.0
    assert FinanceService._compute_late_fee_amount(by_pid[pct_pid]) == 8.0   # 10% ของ 80
    assert FinanceService._compute_late_fee_amount(by_pid[cap_pid]) == 0.5   # ไม่เกินยอดค้าง


# ---------------------------------------------------------------- ออกจริง

async def test_apply_creates_fine_bill_invoice_and_journal(db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _set_server_id(db_pool, room_id, 424242)
    sid = await _insert_student(db_pool, room_id, student_no=random.randint(100, 9999))
    _, source_pid = await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=4),
                                       amount=100.0, paid=0.0, mode="percent", fee=10.0)

    with patch.object(ActionService, "notify_fines_issued", new_callable=AsyncMock) as mock_pub:
        stats = await FinanceService.apply_late_fees(db_pool, as_of=AS_OF, room_id=room_id)

    assert stats["issued"] == 1
    assert stats["total_amount"] == 10.0

    async with db_pool.acquire() as conn:
        fine = await conn.fetchrow(
            """SELECT F.*, FC.collection_kind, FC.title AS coll_title
               FROM fines F JOIN fee_collections FC ON FC.id = F.hidden_collection_id
               WHERE F.room_id = $1""",
            room_id,
        )
        inv = await conn.fetchrow(
            "SELECT receipt_no FROM finance_receipts WHERE student_payment_id = $1 "
            "AND doc_type = 'invoice' AND deleted_at IS NULL",
            fine["student_payment_id"],
        )
        payment = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1",
            fine["student_payment_id"],
        )

    assert fine["fine_type_name"] == LATE_FEE_FINE_TYPE_NAME
    assert fine["source_payment_id"] == source_pid
    assert fine["auto_late_fee"] is True
    assert fine["created_by"] is None
    assert fine["collection_kind"] == COLLECTION_KIND_FINE
    assert float(fine["amount"]) == 10.0
    assert inv is not None and inv["receipt_no"].startswith("INV-")
    assert payment["status"] == "pending"
    assert float(payment["paid_amount"]) == 0.0

    assert await _ledger_net(db_pool, room_id, AR_FINE_CODE, "debit") == 10.0
    assert await _ledger_net(db_pool, room_id, FINE_REVENUE_CODE, "credit") == 10.0

    mock_pub.assert_awaited_once()
    assert mock_pub.await_args.args[0] == 424242  # server_id ส่งเป็น positional
    kwargs = mock_pub.await_args.kwargs
    assert kwargs["student_count"] == 1
    assert kwargs["total_amount"] == 10.0
    assert kwargs["fine_type_name"] == LATE_FEE_FINE_TYPE_NAME


async def test_apply_is_permanently_idempotent_per_source_bill(db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _insert_student(db_pool, room_id, student_no=random.randint(100, 9999))
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=2),
                       amount=50.0, mode="fixed", fee=5.0)

    with patch.object(ActionService, "notify_fines_issued", new_callable=AsyncMock):
        first = await FinanceService.apply_late_fees(db_pool, as_of=AS_OF, room_id=room_id)
        second = await FinanceService.apply_late_fees(db_pool, as_of=AS_OF, room_id=room_id)

    assert first["issued"] == 1
    assert second["issued"] == 0

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM fines WHERE room_id = $1 AND deleted_at IS NULL", room_id
        )
    assert count == 1


async def test_apply_notifies_bill_owner_in_app(db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _insert_student(db_pool, room_id, student_no=random.randint(100, 9999))
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM students WHERE id = $1", sid)
    await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=2), amount=30.0, mode="fixed", fee=5.0)

    with patch.object(ActionService, "notify_fines_issued", new_callable=AsyncMock):
        await FinanceService.apply_late_fees(db_pool, as_of=AS_OF, room_id=room_id)

    async with db_pool.acquire() as conn:
        note = await conn.fetchrow(
            "SELECT type, url, user_id FROM notifications WHERE room_id = $1", room_id
        )
    assert note["type"] == "fine_issued"
    assert note["url"].startswith("/finance/fines/")
    assert note["user_id"] == user_id


async def test_worker_runs_late_fees_before_reminders(db_pool):
    from workers.finance_reminder_worker import run_once

    with patch.object(FinanceService, "apply_late_fees", new_callable=AsyncMock) as mock_late, \
         patch.object(FinanceService, "dispatch_daily_reminders",
                      new_callable=AsyncMock, return_value={"rooms_with_debt": 0}) as mock_dispatch:
        result = await run_once(db_pool, now=__import__("datetime").datetime(2026, 11, 24, 9, 5))

    assert result["status"] == "sent"
    assert "late_fees" in result
    mock_late.assert_awaited_once()
    assert mock_late.await_args.kwargs["as_of"] == AS_OF
    mock_dispatch.assert_awaited_once()
