"""
🛠️ Backfill Script — สร้าง journal ย้อนหลังให้แถว legacy ที่ตกหล่นจาก dual-write

## ทำไมต้องมี

ระบบเขียนทั้ง `finance_transactions` (single-entry) และ `journal_entries` (double-entry)
คู่กันใน transaction เดียวตั้งแต่ `CUTOFF_DATE = 2026-09-01` แต่มีแถวกลุ่มหนึ่งที่ **ไม่มี journal**:

1. **ช่วงเปลี่ยนผ่าน** — แถวที่ถูกบันทึกในช่วง ~7 ชม. แรกของวันที่ 1 ก.ย. (เวลาไทย)
   ก่อนโค้ด dual-write จะขึ้นจริง
2. **รอยรั่วที่ปิดไปแล้ว** — การรับชำระเงินของห้องที่ยังไม่มี ledger รายได้สมัยที่
   `_confirm_single_payment` ยัง `pass` ข้าม dual-write (ปิดด้วย FIX A แล้ว)

แถวกลุ่มนี้ **ไม่มีผู้อ่านฝั่งใดรับเลย** เพราะผู้อ่านฝั่ง legacy รับเฉพาะวันที่ไทยก่อนเส้นตัด
และฝั่ง journal รับตั้งแต่วันที่ไทยของเส้นตัดเป็นต้นไป ⇒ หายจากหน้าประวัติและไม่โผล่ในงบการเงิน
ทั้งที่ข้อมูลยังอยู่ใน DB ครบ

## วิธีรัน (Dry-run = default แค่รายงาน, เติม --apply เพื่อเขียนจริง)

    python backend/scripts/backfill_journals.py --room-id 12
    python backend/scripts/backfill_journals.py --server-id 456789012
    python backend/scripts/backfill_journals.py --room-id 12 --apply
    python backend/scripts/backfill_journals.py --all                # dry-run ทุกห้อง
    python backend/scripts/backfill_journals.py --all --apply        # เขียนจริงทุกห้อง

Exit code: 0 = สำเร็จ · 1 = error ทางปฏิบัติ หรือมีห้องใดห้องหนึ่ง error ระหว่างรัน --all

## ⚠️ ข้อควรรู้ก่อนรัน --apply

- **รันซ้ำได้ปลอดภัย (idempotent)** — สคริปต์หาเฉพาะแถวที่ยังไม่มี journal คู่ ⇒ รันซ้ำไม่สร้างซ้ำ
- **แตะเฉพาะแถวที่ "วันที่ไทย" >= 2026-09-01** — แถวก่อนเส้นตัดไม่มี journal โดยเจตนา
  (dual-write ยังไม่เริ่ม) การสร้างให้จะ **เพิ่มข้อมูลเข้างบการเงินที่ไม่มีมาก่อน**
- **ข้ามแถวที่ถูกลบไปแล้ว** (`deleted_at IS NOT NULL`) — แถวนั้นถูก revert และยอดถูกคืนแล้ว
- เป็น **Ops tool** — แนะนำให้รันช่วงที่ไม่มีรายการสด (เหมือน `reconcile_finance.py`)
- หลังรันแล้วแนะนำรัน `reconcile_finance.py` เพื่อยืนยันว่ายอดคงเหลือยังตรงกัน
"""
import argparse
import asyncio
import logging
import os
import sys

import asyncpg

# 🛠️ ตั้งค่า Path ให้รันเป็น Standalone ได้ (เหมือน reconcile_finance.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.config import settings
except ImportError:
    sys.path.append(os.path.join(os.getcwd(), 'classroom-backend'))
    try:
        from core.config import settings
    except ImportError:
        print("❌ ไม่สามารถโหลด core.config ได้ กรุณาตรวจสอบ Path")
        sys.exit(1)

from core.exceptions import RoomNotFoundError
from services.finance.backfill import KIND_LABELS, _fmt_thai
from services.finance_service import FinanceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - BACKFILL - %(levelname)s - %(message)s"
)
logger = logging.getLogger("BACKFILL")

# จำนวนบรรทัดแผนสูงสุดที่จะพิมพ์ในโหมด dry-run (กัน terminal ท่วมเมื่อห้องมีรายการเยอะ)
_MAX_PLAN_LINES = 50


def _kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def _print_report(rep: dict) -> None:
    """พิมพ์รายงานภาษาไทยจาก dict ที่ backfill_missing_journals คืนมา."""
    print("\n📊 Backfill journal ย้อนหลัง")
    print(f"ห้อง: {rep['room_name']} (id={rep['room_id']})")
    print(f"เส้นตัด: {rep['cutoff_date']} (วันที่ไทย) — แตะเฉพาะแถวตั้งแต่วันนี้เป็นต้นไป")
    mode = "dry-run (ยังไม่เขียน)" if not rep["apply"] else "apply (เขียนจริง)"
    print(f"โหมด: {mode}")
    print(f"พบแถว legacy ที่ยังไม่มี journal: {rep['candidates']} แถว "
          f"→ ต้องสร้าง {rep['journals_planned']} ใบ รวม {rep['total_amount']:,.2f} บาท")

    if rep["by_kind"]:
        print("-" * 88)
        for kind, n in sorted(rep["by_kind"].items(), key=lambda kv: -kv[1]):
            print(f"   • {_kind_label(kind):<26} {n:>4} ใบ")
        print("-" * 88)

    plans = rep["plans"]
    if plans:
        print(f"{'#':>3}  {'วันที่-เวลาไทย':<19} {'ชนิด':<22} {'จำนวนเงิน':>13}  รายละเอียด")
        for i, p in enumerate(plans[:_MAX_PLAN_LINES], 1):
            print(
                f"{i:>3}  {_fmt_thai(p['occurred_at']):<19} "
                f"{_kind_label(p['kind'])[:22]:<22} {p['amount']:>13,.2f}  "
                f"{(p['description'] or '')[:40]}"
            )
        if len(plans) > _MAX_PLAN_LINES:
            print(f"   … อีก {len(plans) - _MAX_PLAN_LINES} ใบ (ตัดการแสดงผลเพื่อความอ่านง่าย)")
        print("-" * 88)

    if rep["skipped"]:
        print(f"\n⚠️ ข้าม {len(rep['skipped'])} รายการ (ต้องตรวจด้วยตา):")
        for s in rep["skipped"][:_MAX_PLAN_LINES]:
            ref = s.get("legacy_id") or f"group {s.get('group_id')}"
            print(f"   • {ref}: {s['reason']}")

    # 🚨 คำเตือนสำคัญ: ห้องที่เคยถูกรัน reconcile มาก่อน
    # reconcile แก้ "ผลต่างยอดคงเหลือ" ซึ่งมักเกิดจากแถวตกหล่นกลุ่มเดียวกับที่ backfill กำลังจะแก้
    # ⇒ พอเพิ่มการเคลื่อนไหวจริงเข้าไปอีก สินทรัพย์จะเบิ้ล (ledger = 2 เท่าของ legacy)
    if rep["prior_adjustments"]:
        print(f"\n🚨 คำเตือน: ห้องนี้มี journal 'ปรับปรุงยอด' (reconcile) อยู่ {rep['prior_adjustments']} ใบ")
        print("   รายการเหล่านั้นอาจปรับยอดสินทรัพย์ไปแล้วในทิศทางเดียวกับที่ backfill กำลังจะเพิ่ม")
        print("   ⇒ ต้องรัน reconcile_finance.py ซ้ำ **หลัง** backfill เสมอ ไม่งั้นยอดสินทรัพย์จะเบิ้ล")
        print("   (รอบสองจะออกรายการปรับปรุง 'ทางกลับ' ให้เอง — ฝั่งรายได้ไม่ถูกแตะ)")

    if rep["apply"]:
        print(f"\n✅ สร้าง journal แล้ว {rep['journals_created']} ใบ")
        if rep["created_journal_ids"]:
            print("   journal id: " + ", ".join(rep["created_journal_ids"][:10])
                  + (" …" if len(rep["created_journal_ids"]) > 10 else ""))
        print("💡 แนะนำรัน reconcile_finance.py ต่อเพื่อยืนยันว่ายอดคงเหลือยังตรงกัน")
    else:
        print(f"\n✅ ตรวจแล้วไม่มีการเขียนลงฐานข้อมูล — จะสร้าง {rep['journals_planned']} ใบ")
        if rep["journals_planned"]:
            print("💡 ถ้าต้องการเขียนจริงให้เพิ่ม --apply")


async def _run_single(pool, *, room_id=None, server_id=None, apply: bool) -> dict:
    """Backfill 1 ห้อง → คืน report (backfill_missing_journals)"""
    return await FinanceService.backfill_missing_journals(
        pool, room_id=room_id, server_id=server_id, apply=apply,
    )


async def _run_all(pool, *, apply: bool) -> int:
    """[ALL] รัน backfill เรียงทุกห้อง (rooms ที่ไม่ถูกลบ) — dry-run/apply ตามค่า apply."""
    async with pool.acquire() as conn:
        rooms = await conn.fetch(
            "SELECT id, room_name FROM rooms WHERE deleted_at IS NULL ORDER BY id"
        )
    if not rooms:
        print("ℹ️ ไม่มีห้องในระบบ")
        return 0

    print(f"\n{'=' * 78}")
    print(f"📊 Backfill ทุกห้อง ({len(rooms)} ห้อง) — "
          f"{'DRY-RUN (ยังไม่เขียน)' if not apply else 'APPLY (เขียนจริง)'}")
    print(f"{'=' * 78}")

    error_count = 0
    total_candidates = 0
    total_planned = 0
    total_created = 0
    total_amount = 0.0
    for room in rooms:
        try:
            rep = await _run_single(pool, room_id=room["id"], apply=apply)
        except Exception as e:  # noqa: BLE001 — Ops tool: เจอ error ให้ข้ามห้องไป ไม่หยุดทั้งชุด
            error_count += 1
            print(f"❌ ห้อง {room['id']} ({room['room_name']}): error — {e}")
            continue
        total_candidates += rep["candidates"]
        total_planned += rep["journals_planned"]
        total_created += rep["journals_created"]
        total_amount += rep["total_amount"]
        marker = "✅" if rep["journals_planned"] == 0 else "🩹"
        print(
            f"{marker} ห้อง {rep['room_id']:>4} ({rep['room_name']}): "
            f"แถวตกหล่น {rep['candidates']} · ต้องสร้าง {rep['journals_planned']} ใบ · "
            f"สร้างแล้ว {rep['journals_created']} ใบ · รวม {rep['total_amount']:,.2f} บาท"
            + (f" · ข้าม {len(rep['skipped'])}" if rep["skipped"] else "")
        )

    print(f"{'=' * 78}")
    print(
        f"สรุป: {len(rooms) - error_count}/{len(rooms)} ห้องรันสำเร็จ · "
        f"แถวตกหล่นรวม {total_candidates} · ต้องสร้าง {total_planned} ใบ · "
        f"สร้างแล้ว {total_created} ใบ รวม {total_amount:,.2f} บาท"
    )
    if error_count:
        print(f"⚠️ มี {error_count} ห้อง error — ตรวจ log ด้านบน")
    return 1 if error_count else 0


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("สร้าง journal ย้อนหลัง (backfill) ให้แถว legacy ที่ตกหล่นจาก dual-write "
                     "— เลือกห้องเดียว หรือ --all ทุกห้อง")
    )
    id_group = parser.add_mutually_exclusive_group(required=False)
    id_group.add_argument("--room-id", type=int, help="รหัสห้อง (rooms.id)")
    id_group.add_argument("--server-id", type=int, help="Discord server id ของห้อง")
    id_group.add_argument("--all", action="store_true",
                          help="รันเรียงทุกห้องที่ยังไม่ถูกลบ (ต้องไม่ใช้ --room-id/--server-id)")
    parser.add_argument("--apply", action="store_true",
                        help="เขียน journal ลง DB (default = dry-run แค่รายงาน)")
    args = parser.parse_args(argv)

    # 🐛 นับเฉพาะค่าที่เป็น True (sum(1 for ... if x)) — ดูบทเรียนใน reconcile_finance.py
    chosen = sum(1 for x in (args.room_id is not None, args.server_id is not None, args.all) if x)
    if chosen != 1:
        parser.error("ต้องระบุอย่างใดอย่างหนึ่ง: --room-id, --server-id หรือ --all")

    if not hasattr(settings, 'DATABASE_URL') or not settings.DATABASE_URL:
        print("❌ ไม่พบ DATABASE_URL ใน Environment Variables!")
        return 1

    pool = None
    try:
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=5)
        if args.all:
            return await _run_all(pool, apply=args.apply)
        rep = await _run_single(pool, room_id=args.room_id, server_id=args.server_id, apply=args.apply)
        _print_report(rep)
        return 0
    except (RoomNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 1
    except Exception as e:
        logger.exception("เกิดข้อผิดพลาดระหว่าง backfill")
        print(f"❌ เกิดข้อผิดพลาด: {e}")
        return 1
    finally:
        if pool:
            await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
