"""ตั้งบัญชีผู้ค้างชำระยกมา (Opening AR) ณ วัน go-live — รันครั้งเดียวหลัง deploy

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำอะไร
═══════════════════════════════════════════════════════════════════════════════
ทุกบิลที่ยัง "เปิด" อยู่ ณ วัน go-live ต้องมี AR ในบัญชีคู่ เพื่อให้ยอดค้างในระบบ
เดิมกับงบดุลตรงกัน — แต่ **ห้ามรับรู้เป็นรายได้ของงวดปัจจุบัน** (มันคือรายได้
ของงวดก่อนที่ระบบบัญชีคู่ยังไม่ทำงาน) ⇒ ลง Dr AR / Cr 31002 (equity ยอดยกมา)

    opening_ar = FC.amount - SP.paid_amount + AR_credited_to_bill

`AR_credited_to_bill` = ผลรวม credit สุทธิที่ลงบัญชี AR (11001/11002) จาก journal
`student_payment` / `student_credit_apply` ของบิลนี้ที่ยังไม่ void

ทำไมต้องบวกกลับ: ถ้ารันสคริปต์หลัง deploy แล้วมีคนจ่ายเงินไปก่อน
  • การจ่ายยุคใหม่ลง Cr AR ไปแล้ว แต่ยังไม่มี accrual ของบิล (บิลเก่า) ⇒ AR ติดลบ
  • ลง opening ด้วยยอดเต็ม (amount) ไม่ใช่ยอดคงเหลือ ⇒ net AR = amount - paid = ค้างจริง
  • ถ้าการจ่ายเป็นยุคเก่า (Cr รายได้ ไม่แตะ AR) หรือไม่มี journal ⇒ credited = 0
    ⇒ ลงเฉพาะยอดคงเหลือ (amount - paid)

═══════════════════════════════════════════════════════════════════════════════
🔒 ความปลอดภัย
═══════════════════════════════════════════════════════════════════════════════
• Idempotent ต่อบิล — บิลที่มี `student_payment_issue` หรือ `opening_receivable`
  อยู่แล้วจะถูกข้าม (unique index `uq_journal_bill_issue` เป็นด่านสุดท้าย)
• ล็อกห้องด้วย `_lock_room_money` ตลอดช่วงคำนวณ+ลง journal ⇒ ไม่มีรับเงิน/
  ใช้เครดิตแทรกกลางทาง
• `--dry-run` ไม่เขียนอะไรเลย (ไม่แม้แต่สร้าง ledger)
• ต่อห้องเป็น transaction เดียว ⇒ ห้องที่ล้มไม่ทิ้งสภาพครึ่ง ๆ

═══════════════════════════════════════════════════════════════════════════════
📋 วิธีใช้
═══════════════════════════════════════════════════════════════════════════════
    python -m scripts.backfill_opening_ar --as-of 2026-11-24 --dry-run
    python -m scripts.backfill_opening_ar --as-of 2026-11-24
    python -m scripts.backfill_opening_ar --as-of 2026-11-24 --room-id 12

ผลลัพธ์ JSON ไป stdout / log ไป stderr (ให้ redirect เก็บได้)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, time as dtime
from typing import Optional

import asyncpg

# 🛠️ รันเป็น standalone ได้ (เหมือน scripts/migrate_phase2_5_opening_balance.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings  # noqa: E402
from services.finance.accrual import (  # noqa: E402
    AR_SOURCE_NONE,
    OPEN_BILL_PREDICATE,
)
from services.finance.base import _lock_room_money  # noqa: E402
from services.finance.constants import (  # noqa: E402
    AR_FINE_CODE,
    AR_LEDGER_CODES,
    AR_PROJECT_CODE,
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    OPENING_AR_EQUITY_CODE,
    REFERENCE_TYPE_CREDIT_APPLY,
    REFERENCE_TYPE_OPENING_RECEIVABLE,
    THAI_TZ,
)
from services.finance.service import FinanceService  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s - OPENING_AR - %(levelname)s - %(message)s",
)
logger = logging.getLogger("OPENING_AR")

_MIN_AMOUNT = 0.005  # ต่ำกว่านี้ถือว่าศูนย์ (ปัด 2 ตำแหน่งแล้ว)


def _normalize_kind(value: Optional[str]) -> str:
    return COLLECTION_KIND_FINE if value == COLLECTION_KIND_FINE else COLLECTION_KIND_PROJECT


def _as_of_timestamp(as_of: date) -> datetime:
    """เที่ยงคืนตามเวลาไทยของวัน go-live (tz-aware เสมอ — กฎของ `_insert_journal_entry`)"""
    return datetime.combine(as_of, dtime.min.replace(tzinfo=THAI_TZ))


async def _fetch_open_bills(conn: asyncpg.Connection, room_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT SP.id              AS payment_id,
               SP.paid_amount     AS paid_amount,
               FC.id              AS collection_id,
               FC.amount          AS total_amount,
               FC.collection_kind AS collection_kind,
               FC.title           AS title,
               FC.due_date        AS due_date,
               S.student_no       AS student_no
        FROM student_payments SP
        JOIN fee_collections FC ON FC.id = SP.collection_id
        JOIN students S ON S.id = SP.student_id
        WHERE FC.room_id = $1
          AND {OPEN_BILL_PREDICATE}
        ORDER BY SP.id
        """,
        room_id,
    )


async def _ar_credited_to_bill(conn: asyncpg.Connection, room_id: int, payment_id: int) -> float:
    """Credit สุทธิที่ลงบัญชี AR ของบิลนี้ (payment / credit apply ที่ยังไม่ void)"""
    value = await conn.fetchval(
        """
        SELECT COALESCE(SUM(L.credit - L.debit), 0)
        FROM journal_entries JE
        JOIN journal_lines L ON L.journal_entry_id = JE.id
        JOIN accounting_ledgers AL ON AL.id = L.ledger_id
        WHERE JE.room_id = $1
          AND JE.reference_id = $2
          AND JE.reference_type IN ($3, $4)
          AND JE.deleted_at IS NULL
          AND JE.status <> 'voided'
          AND AL.room_id = $1
          AND AL.account_code = ANY($5::text[])
        """,
        room_id,
        str(payment_id),
        "student_payment",
        REFERENCE_TYPE_CREDIT_APPLY,
        list(AR_LEDGER_CODES),
    )
    return float(value or 0)


async def _process_room(
    conn: asyncpg.Connection,
    *,
    room: asyncpg.Record,
    as_of: date,
    dry_run: bool,
) -> dict:
    room_id = int(room["id"])
    report = {
        "room_id": room_id,
        "room_name": room["room_name"],
        "open_bills": 0,
        "posted": 0,
        "skipped_existing": 0,
        "skipped_zero": 0,
        "opening_total": 0.0,
        "by_kind": {COLLECTION_KIND_PROJECT: 0.0, COLLECTION_KIND_FINE: 0.0},
    }

    async def _run() -> None:
        bills = await _fetch_open_bills(conn, room_id)
        report["open_bills"] = len(bills)
        as_of_dt = _as_of_timestamp(as_of)
        ledgers: Optional[dict] = None

        for bill in bills:
            payment_id = int(bill["payment_id"])

            source = await FinanceService._bill_ar_source(conn, payment_id)
            if source != AR_SOURCE_NONE:
                report["skipped_existing"] += 1
                continue

            total = round(float(bill["total_amount"]), 2)
            paid = round(float(bill["paid_amount"] or 0), 2)
            credited = round(
                await _ar_credited_to_bill(conn, room_id, payment_id), 2
            )
            opening = round(total - paid + credited, 2)
            if opening <= _MIN_AMOUNT:
                report["skipped_zero"] += 1
                continue

            # สร้าง ledger ตอนเจอบิลแรกที่ต้องลงจริง (ห้องที่ไม่มีอะไรต้องลง = ไม่เขียนเลย)
            if ledgers is None:
                ledgers = await FinanceService.ensure_finance_ledgers(conn, room_id)

            kind = _normalize_kind(bill["collection_kind"])
            ar_ledger_id = (
                ledgers[AR_FINE_CODE] if kind == COLLECTION_KIND_FINE
                else ledgers[AR_PROJECT_CODE]
            )
            equity_ledger_id = ledgers[OPENING_AR_EQUITY_CODE]

            await FinanceService._insert_journal_entry(
                conn, room_id,
                reference_type=REFERENCE_TYPE_OPENING_RECEIVABLE,
                reference_id=str(payment_id),
                description=(
                    f"ยอดยกมาผู้ค้างชำระ: {bill['title']} "
                    f"(บิล #{payment_id}, ณ {as_of.isoformat()})"
                ),
                recorded_by="SYSTEM",
                metadata={
                    "student_payment_id": payment_id,
                    "collection_id": int(bill["collection_id"]),
                    "collection_kind": kind,
                    "as_of": as_of.isoformat(),
                    "bill_total": total,
                    "paid_amount": paid,
                    "ar_credited": credited,
                    "opening_ar": opening,
                },
                transaction_date=as_of_dt,
                lines=[
                    {"ledger_id": ar_ledger_id, "debit": opening, "credit": 0,
                     "line_description": f"ผู้ค้างชำระยกมาบิล #{payment_id}"},
                    {"ledger_id": equity_ledger_id, "debit": 0, "credit": opening,
                     "line_description": "ยอดยกมาบัญชีเปิด – ผู้ค้างชำระ"},
                ],
            )

            report["posted"] += 1
            report["opening_total"] = round(report["opening_total"] + opening, 2)
            report["by_kind"][kind] = round(report["by_kind"][kind] + opening, 2)

    if dry_run:
        # อ่านอย่างเดียว: ไม่สร้าง ledger, ไม่ล็อก, ไม่เขียน
        report["dry_run"] = True
        await _dry_scan(conn, room_id, report)
    else:
        async with conn.transaction():
            await _lock_room_money(conn, room_id)
            await _run()

    return report


async def _dry_scan(
    conn: asyncpg.Connection,
    room_id: int,
    report: dict,
) -> None:
    """โหมด dry-run: คำนวณเหมือนจริงแต่ไม่เขียน (ไม่เรียก ensure ledgers)"""
    bills = await _fetch_open_bills(conn, room_id)
    report["open_bills"] = len(bills)
    for bill in bills:
        payment_id = int(bill["payment_id"])
        source = await FinanceService._bill_ar_source(conn, payment_id)
        if source != AR_SOURCE_NONE:
            report["skipped_existing"] += 1
            continue
        total = round(float(bill["total_amount"]), 2)
        paid = round(float(bill["paid_amount"] or 0), 2)
        credited = round(await _ar_credited_to_bill(conn, room_id, payment_id), 2)
        opening = round(total - paid + credited, 2)
        if opening <= _MIN_AMOUNT:
            report["skipped_zero"] += 1
            continue
        kind = _normalize_kind(bill["collection_kind"])
        report["posted"] += 1
        report["opening_total"] = round(report["opening_total"] + opening, 2)
        report["by_kind"][kind] = round(report["by_kind"][kind] + opening, 2)


async def backfill_opening_ar(
    pool: asyncpg.Pool,
    *,
    as_of: date,
    room_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """ลง opening AR ทุกห้อง (หรือห้องเดียว) คืนสรุปผลเป็น dict"""
    async with pool.acquire() as conn:
        if room_id is not None:
            rooms = await conn.fetch(
                "SELECT id, room_name FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                room_id,
            )
            if not rooms:
                raise ValueError(f"ไม่พบห้อง id={room_id}")
        else:
            rooms = await conn.fetch(
                "SELECT id, room_name FROM rooms WHERE deleted_at IS NULL ORDER BY id"
            )

        room_reports = []
        for room in rooms:
            logger.info(
                "ประมวลผลห้อง %s (#%s)%s",
                room["room_name"], room["id"], " [dry-run]" if dry_run else "",
            )
            room_reports.append(
                await _process_room(conn, room=room, as_of=as_of, dry_run=dry_run)
            )

    totals = {
        "open_bills": sum(r["open_bills"] for r in room_reports),
        "posted": sum(r["posted"] for r in room_reports),
        "skipped_existing": sum(r["skipped_existing"] for r in room_reports),
        "skipped_zero": sum(r["skipped_zero"] for r in room_reports),
        "opening_total": round(sum(r["opening_total"] for r in room_reports), 2),
        "by_kind": {
            COLLECTION_KIND_PROJECT: round(
                sum(r["by_kind"][COLLECTION_KIND_PROJECT] for r in room_reports), 2
            ),
            COLLECTION_KIND_FINE: round(
                sum(r["by_kind"][COLLECTION_KIND_FINE] for r in room_reports), 2
            ),
        },
    }

    return {
        "as_of": as_of.isoformat(),
        "dry_run": dry_run,
        "rooms": room_reports,
        "totals": totals,
    }


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="ตั้งบัญชีผู้ค้างชำระยกมา (Opening AR) ณ วัน go-live",
    )
    parser.add_argument(
        "--as-of", dest="as_of", type=date.fromisoformat, default=None,
        help="วัน go-live (YYYY-MM-DD) — ค่าเริ่มต้นคือวันนี้ตามเวลาไทย",
    )
    parser.add_argument(
        "--room-id", dest="room_id", type=int, default=None,
        help="ทำเฉพาะห้องนี้ (ไม่ระบุ = ทุกห้อง)",
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="คำนวณและรายงานผลโดยไม่เขียนอะไรลง DB",
    )
    args = parser.parse_args(argv)

    as_of = args.as_of or datetime.now(THAI_TZ).date()
    if args.as_of is None:
        logger.warning(
            "ไม่ได้ระบุ --as-of ⇒ ใช้วันนี้ (%s) — production ต้องระบุวัน go-live ให้ชัด",
            as_of,
        )

    if not getattr(settings, "DATABASE_URL", None):
        logger.error("ไม่พบ DATABASE_URL")
        return 2

    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)
    try:
        result = await backfill_opening_ar(
            pool, as_of=as_of, room_id=args.room_id, dry_run=args.dry_run,
        )
    finally:
        await pool.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info(
        "เสร็จ: %s บิล, ยอดรวม %.2f บาท (dry-run=%s)",
        result["totals"]["posted"], result["totals"]["opening_total"], result["dry_run"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
