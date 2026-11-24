"""ผู้ค้างชำระยกมา (Opening AR) ณ วัน go-live — สคริปต์ `scripts/backfill_opening_ar.py`

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ล็อกอะไร
═══════════════════════════════════════════════════════════════════════════════
1. บิลที่ยังเปิดอยู่ทุกรายการ (โปรเจกต์ + ค่าปรับ) ได้ AR ยกมา = ยอดคงเหลือ
   และ **ไม่แตะรายได้/ค่าใช้จ่าย** (Dr AR / Cr 31002 เท่านั้น)
2. บิลที่จ่ายครบ / ถูกลบ / มี accrual ยุคใหม่อยู่แล้ว **ถูกข้าม**
3. รันซ้ำได้ (idempotent) — ไม่ลง journal ซ้ำ
4. `AR_credited_to_bill` บวกกลับถูก: ถ้ามีการจ่ายยุคใหม่ (Cr AR) ไปแล้วก่อนรันสคริปต์
   ต้องลง opening ด้วยยอดเต็มของบิล เพื่อให้ AR สุทธิ = ค้างจริง
5. `--dry-run` ไม่อ่านเขียนอะไรเลย แม้แต่ ledger
6. `--room-id` จำกัดห้องได้
7. `transaction_date` = เที่ยงคืนเวลาไทยของวัน go-live
8. ค่าคงเหลือติดลบ/ศูนย์ถูกข้าม (ไม่สร้าง AR ติดลบ)

⚠️ ตรวจกับ DB จริงทุกข้อ — ไม่เชื่อแค่ตัวเลขใน report ที่สคริปต์คืนมา
"""
import json
import uuid
from datetime import date, datetime

import pytest

from scripts.backfill_opening_ar import backfill_opening_ar
from services.finance.accrual import AR_SOURCE_OPENING
from services.finance.constants import (
    AR_FINE_CODE,
    AR_PROJECT_CODE,
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    DEFAULT_INCOME_CATEGORIES,
    FINE_REVENUE_CODE,
    OPENING_AR_EQUITY_CODE,
    REFERENCE_TYPE_OPENING_RECEIVABLE,
    THAI_TZ,
)
from services.finance.service import FinanceService

pytestmark = pytest.mark.asyncio

GO_LIVE = date(2026, 11, 24)


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _make_room(pool, name: str = "ห้องทดสอบ opening") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            name, f"OPN{uuid.uuid4().hex[:6].upper()}",
        )


async def _make_student(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            "เด็กชายทดสอบ", "ยกมา", f"u{uuid.uuid4().hex[:12]}",
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
) -> tuple[int, int]:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, collection_kind)
               VALUES ($1, $2, $3, $4, 'active', $5) RETURNING id""",
            room_id, title, amount, date(2026, 12, 31), kind,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            collection_id, student_id, status, paid,
        )
    return collection_id, payment_id


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


async def _opening_entries(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, reference_id, recorded_by, transaction_date, metadata
               FROM journal_entries
               WHERE room_id = $1 AND reference_type = $2
                 AND deleted_at IS NULL AND status <> 'voided'
               ORDER BY reference_id::bigint""",
            room_id, REFERENCE_TYPE_OPENING_RECEIVABLE,
        )


async def _room_report(result: dict, room_id: int) -> dict:
    return next(r for r in result["rooms"] if r["room_id"] == room_id)


async def _post_new_era_payment(pool, room_id: int, payment_id: int, amount: float) -> None:
    """จำลองการจ่ายยุค accrual ที่ลง Cr AR ไปแล้ว (Dr เงินสด / Cr 11001)"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            ledgers = await FinanceService.ensure_finance_ledgers(conn, room_id)
            cash_id = await conn.fetchval(
                """INSERT INTO accounting_ledgers
                       (room_id, account_code, account_name, account_type)
                   VALUES ($1, '10000', 'เงินสด', 'asset') RETURNING id""",
                room_id,
            )
            await FinanceService._insert_journal_entry(
                conn, room_id,
                reference_type="student_payment",
                reference_id=str(payment_id),
                description="รับชำระ (ยุค accrual)",
                lines=[
                    {"ledger_id": cash_id, "debit": amount, "credit": 0},
                    {"ledger_id": ledgers[AR_PROJECT_CODE], "debit": 0, "credit": amount},
                ],
            )


# ══════════════════════════════════════════════════════ 1. ยอดคงเหลือ + kinds
async def test_posts_remaining_balance_and_routes_kinds_to_their_ar(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, project_bill = await _make_bill(db_pool, room_id, student_id, amount=1000)
    _, fine_bill = await _make_bill(
        db_pool, room_id, student_id, amount=50, paid=20,
        kind=COLLECTION_KIND_FINE, title="ค่าปรับ · มาสาย",
    )

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["open_bills"] == 2
    assert report["posted"] == 2
    assert report["opening_total"] == 1030.0
    assert report["by_kind"] == {
        COLLECTION_KIND_PROJECT: 1000.0,
        COLLECTION_KIND_FINE: 30.0,
    }

    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 1000
    assert await _ledger_net(db_pool, room_id, AR_FINE_CODE) == 30
    assert await _ledger_net(db_pool, room_id, OPENING_AR_EQUITY_CODE) == -1030
    # opening ห้ามแตะรายได้ของงวดนี้
    assert await _ledger_net(db_pool, room_id, DEFAULT_INCOME_CATEGORIES[0]) == 0
    assert await _ledger_net(db_pool, room_id, FINE_REVENUE_CODE) == 0

    entries = await _opening_entries(db_pool, room_id)
    assert {e["reference_id"] for e in entries} == {str(project_bill), str(fine_bill)}
    assert all(e["recorded_by"] == "SYSTEM" for e in entries)


async def test_unknown_collection_kind_falls_back_to_project(db_pool):
    """ค่า kind ที่ไม่รู้จัก (ข้อมูลก่อน migration) ต้องไม่กลายเป็นบัญชีอื่น"""
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=100)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE fee_collections SET collection_kind = 'legacy_kind'
               WHERE id = (SELECT collection_id FROM student_payments WHERE id = $1)""",
            payment_id,
        )

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["by_kind"][COLLECTION_KIND_PROJECT] == 100
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 100
    assert await _ledger_net(db_pool, room_id, AR_FINE_CODE) == 0


# ══════════════════════════════════════════════════════ 2. บิลที่ไม่ควรถูกนับ
async def test_skips_paid_and_soft_deleted_bills(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, pending = await _make_bill(db_pool, room_id, student_id, amount=100)
    await _make_bill(db_pool, room_id, student_id, amount=500, paid=500, status="paid")
    _, deleted = await _make_bill(db_pool, room_id, student_id, amount=900)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET deleted_at = NOW() WHERE id = $1", deleted
        )

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["open_bills"] == 1
    assert report["posted"] == 1
    assert report["opening_total"] == 100
    entries = await _opening_entries(db_pool, room_id)
    assert [e["reference_id"] for e in entries] == [str(pending)]


async def test_skips_bill_that_already_has_new_era_accrual(db_pool):
    """บิลที่ออกหลัง deploy (มี student_payment_issue) ห้ามลง opening ซ้ำ"""
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=400)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await FinanceService._post_bill_accrual(conn, room_id, payment_id, amount=400)

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["open_bills"] == 1
    assert report["posted"] == 0
    assert report["skipped_existing"] == 1
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 400
    assert await _opening_entries(db_pool, room_id) == []


async def test_skips_zero_or_negative_remainder(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100, paid=150)

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["posted"] == 0
    assert report["skipped_zero"] == 1
    assert await _opening_entries(db_pool, room_id) == []
    # ไม่มีอะไรต้องลง ⇒ ไม่สร้าง ledger เลย
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM accounting_ledgers WHERE room_id = $1", room_id
        ) == 0


# ══════════════════════════════════════════════════════ 3. idempotency
async def test_rerun_posts_nothing_new(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=700)

    first = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    second = await backfill_opening_ar(db_pool, as_of=GO_LIVE)

    assert (await _room_report(first, room_id))["posted"] == 1
    report2 = await _room_report(second, room_id)
    assert report2["posted"] == 0
    assert report2["skipped_existing"] == 1

    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 700
    assert len(await _opening_entries(db_pool, room_id)) == 1


# ══════════════════════════════════ 4. การจ่ายยุคใหม่ก่อนรันสคริปต์ (credited)
async def test_payment_already_credited_to_ar_is_added_back(db_pool):
    """บิล 1000 จ่ายไปแล้ว 400 (Cr AR ยุคใหม่) ⇒ opening ต้องลง 1000 ให้ AR สุทธิ = 600"""
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000, paid=400)
    await _post_new_era_payment(db_pool, room_id, payment_id, 400)

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE)
    report = await _room_report(result, room_id)

    assert report["opening_total"] == 1000
    entries = await _opening_entries(db_pool, room_id)
    assert len(entries) == 1
    # asyncpg ไม่ได้ลง codec JSONB ⇒ metadata กลับมาเป็น str ต้อง parse เอง
    metadata = json.loads(entries[0]["metadata"])
    assert float(metadata["ar_credited"]) == 400
    assert float(metadata["opening_ar"]) == 1000

    # สุทธิ = ยอดค้างจริง 1000 - 400
    assert await _ledger_net(db_pool, room_id, AR_PROJECT_CODE) == 600


async def test_bill_ar_source_reports_opening_after_backfill(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250)

    await backfill_opening_ar(db_pool, as_of=GO_LIVE)

    async with db_pool.acquire() as conn:
        assert await FinanceService._bill_ar_source(conn, payment_id) == AR_SOURCE_OPENING


# ══════════════════════════════════════════════════════ 5. dry-run
async def test_dry_run_writes_nothing(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=500)

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE, dry_run=True)
    report = await _room_report(result, room_id)

    assert result["dry_run"] is True
    assert report["posted"] == 1
    assert report["opening_total"] == 500
    assert await _opening_entries(db_pool, room_id) == []
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id
        ) == 0
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM accounting_ledgers WHERE room_id = $1", room_id
        ) == 0


# ══════════════════════════════════════════════════════ 6. room filter
async def test_room_id_filter_only_touches_that_room(db_pool):
    room_a = await _make_room(db_pool, "ห้อง A")
    room_b = await _make_room(db_pool, "ห้อง B")
    student_a = await _make_student(db_pool, room_a, student_no=1)
    student_b = await _make_student(db_pool, room_b, student_no=2)
    await _make_bill(db_pool, room_a, student_a, amount=100)
    await _make_bill(db_pool, room_b, student_b, amount=200)

    result = await backfill_opening_ar(db_pool, as_of=GO_LIVE, room_id=room_a)

    assert [r["room_id"] for r in result["rooms"]] == [room_a]
    assert len(await _opening_entries(db_pool, room_a)) == 1
    assert await _opening_entries(db_pool, room_b) == []
    assert await _ledger_net(db_pool, room_b, AR_PROJECT_CODE) == 0


async def test_missing_room_raises(db_pool):
    with pytest.raises(ValueError, match="ไม่พบห้อง"):
        await backfill_opening_ar(db_pool, as_of=GO_LIVE, room_id=999999)


# ═══════════════════════════════ 7. transaction_date + ไม่มี revenue/expense
async def test_transaction_date_is_go_live_midnight_bangkok(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100)

    await backfill_opening_ar(db_pool, as_of=GO_LIVE)

    entries = await _opening_entries(db_pool, room_id)
    assert len(entries) == 1
    assert entries[0]["transaction_date"].astimezone(THAI_TZ) == datetime(
        GO_LIVE.year, GO_LIVE.month, GO_LIVE.day, 0, 0, tzinfo=THAI_TZ,
    )
    assert json.loads(entries[0]["metadata"])["as_of"] == GO_LIVE.isoformat()


async def test_opening_uses_only_asset_and_equity_ledgers(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100)
    await _make_bill(
        db_pool, room_id, student_id, amount=40,
        kind=COLLECTION_KIND_FINE, title="ค่าปรับ",
    )

    await backfill_opening_ar(db_pool, as_of=GO_LIVE)

    async with db_pool.acquire() as conn:
        types = {
            r["account_type"] for r in await conn.fetch(
                """SELECT DISTINCT AL.account_type
                   FROM journal_entries JE
                   JOIN journal_lines L ON L.journal_entry_id = JE.id
                   JOIN accounting_ledgers AL ON AL.id = L.ledger_id
                   WHERE JE.room_id = $1 AND JE.reference_type = $2""",
                room_id, REFERENCE_TYPE_OPENING_RECEIVABLE,
            )
        }
    assert types == {"asset", "equity"}


# ═══════════════════════════════════════════════════ invariant: AR = ค้างจริง
async def test_ar_net_equals_open_bill_remainders(db_pool):
    room_id = await _make_room(db_pool)
    student_id = await _make_student(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=300, paid=100)
    await _make_bill(db_pool, room_id, student_id, amount=120, paid=0,
                     kind=COLLECTION_KIND_FINE, title="ค่าปรับ ก")
    await _make_bill(db_pool, room_id, student_id, amount=80, paid=30,
                     kind=COLLECTION_KIND_FINE, title="ค่าปรับ ข")

    await backfill_opening_ar(db_pool, as_of=GO_LIVE)

    async with db_pool.acquire() as conn:
        expected = await conn.fetchval(
            """SELECT COALESCE(SUM(FC.amount - COALESCE(SP.paid_amount, 0)), 0)
               FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE FC.room_id = $1 AND SP.deleted_at IS NULL
                 AND SP.status = 'pending' AND FC.deleted_at IS NULL""",
            room_id,
        )

    actual = (
        await _ledger_net(db_pool, room_id, AR_PROJECT_CODE)
        + await _ledger_net(db_pool, room_id, AR_FINE_CODE)
    )
    assert round(float(expected), 2) == round(actual, 2) == 370
    assert await _ledger_net(db_pool, room_id, OPENING_AR_EQUITY_CODE) == -370
