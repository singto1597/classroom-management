"""
🛠️ Reconciliation Script — กระทบยอดเงินห้องเดียวระหว่างระบบเดิมกับบัญชีคู่

เปรียบเทียบ finance_accounts.balance (ระบบ Single-Entry = แหล่งความจริงฝั่งเดิม)
กับยอดสุทธิ asset-ledger ในบัญชีคู่ (SUM(debit - credit) เฉพาะ journal ที่ไม่ void/ไม่ลบ)
ของทุกบัญชีในห้อง ถ้าต่างกัน → สร้าง journal_entries reference_type='adjustment'
1 ใบต่อบัญชี (asset ± / equity '3001' เป็นขาสะท้อน) ให้ยอดบัญชีคู่กลับมาเท่า Legacy พอดี.

วิธีรัน (Dry-run = default แค่รายงาน, เติม --apply เพื่อเขียนจริง):
    python backend/scripts/reconcile_finance.py --room-id 12
    python backend/scripts/reconcile_finance.py --server-id 456789012
    python backend/scripts/reconcile_finance.py --room-id 12 --apply --threshold 0.01
    # รันเรียงทุกห้องตามลำดับ (ต้องเลือกอย่างใดอย่างหนึ่ง: --room-id / --server-id / --all)
    python backend/scripts/reconcile_finance.py --all                 # dry-run ทุกห้อง
    python backend/scripts/reconcile_finance.py --all --apply         # เขียนจริงทุกห้อง

Exit code: 0 = สำเร็จ (รวม dry-run ที่เจอผลต่าง / apply ที่เขียนจริง; --all ไม่มีห้อง error);
          1 = error ทางปฏิบัติ หรือมีห้องใดห้องหนึ่ง error ระหว่างรัน --all

⚠️ เป็น Ops tool — ตัว apply ไม่ล็อกแถวระหว่างเขียน ควรวิ่งช่วงที่ไม่มีรายการสด
"""
import argparse
import asyncio
import logging
import os
import sys

import asyncpg

# 🛠️ ตั้งค่า Path ให้รันเป็น Standalone ได้ (เหมือน migrate_phase2_5_opening_balance.py)
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
from services.finance_service import FinanceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - RECONCILE - %(levelname)s - %(message)s"
)
logger = logging.getLogger("RECONCILE")


def _action_label(action: str, amount: float) -> str:
    """แปลง action ('dr_asset'|'cr_asset') เป็นข้อความรายการปรับปรุงภาษาไทย."""
    if action == "dr_asset":
        return f"Dr สินทรัพย์ {amount:,.2f}"
    if action == "cr_asset":
        return f"Cr สินทรัพย์ {amount:,.2f}"
    return "-"


def _print_report(rep: dict) -> None:
    """พิมพ์รายงานภาษาไทยจาก dict ที่ reconcile_balances คืนมา."""
    print("\n📊 กระทบยอดคงเหลือ (Reconciliation)")
    print(f"ห้อง: {rep['room_name']} (id={rep['room_id']})")
    mode = "dry-run (ยังไม่เขียน)" if not rep["apply"] else "apply (เขียนจริง)"
    print(f"โหมด: {mode}    threshold: {rep['threshold']} บาท")
    print(f"ตรวจสอบ {rep['checked_accounts']} บัญชี พบผลต่าง {len(rep['mismatches'])} รายการ")

    if rep["mismatches"]:
        print("-" * 80)
        header = (f"{'#':>3}  {'บัญชี':<24} {'ยอดคงเหลือ(เดิม)':>16} "
                  f"{'ยอดบัญชีคู่':>13} {'ผลต่าง':>12}    รายการปรับปรุง")
        print(header)
        for i, m in enumerate(rep["mismatches"], 1):
            print(
                f"{i:>3}  {m['account_name'][:24]:<24} "
                f"{m['legacy_balance']:>16,.2f} {m['ledger_net']:>13,.2f} "
                f"{m['diff']:>+12,.2f}    {_action_label(m['action'], m['amount'])}"
            )
        print("-" * 80)
    else:
        print("✅ ยอดทุกบัญชีตรงกันแล้ว ไม่ต้องปรับปรุง")

    print(f"สร้างรายการปรับปรุงแล้ว: {rep['adjustments_created']} บิล "
          f"รวม {rep['total_adjustment_amount']:,.2f} บาท")
    if not rep["apply"] and rep["mismatches"]:
        print("💡 ยังไม่มีการเขียนลงฐานข้อมูล — ถ้าต้องการเขียนจริงให้เพิ่ม --apply")


async def _run_single(pool, *, room_id=None, server_id=None, apply: bool, threshold: float) -> dict:
    """กระทบยอด 1 ห้อง → คืน report (reconcile_balances)"""
    return await FinanceService.reconcile_balances(
        pool,
        room_id=room_id,
        server_id=server_id,
        apply=apply,
        threshold=threshold,
    )


async def _run_all(pool, *, apply: bool, threshold: float) -> int:
    """[ALL] รันกระทบยอดเรียงทุกห้อง (rooms ที่ไม่ถูกลบ) — dry-run/apply ตามค่า apply."""
    async with pool.acquire() as conn:
        rooms = await conn.fetch(
            "SELECT id, room_name FROM rooms WHERE deleted_at IS NULL ORDER BY id"
        )
    if not rooms:
        print("ℹ️ ไม่มีห้องในระบบ")
        return 0

    print(f"\n{'=' * 70}")
    print(f"📊 กระทบยอดทุกห้อง ({len(rooms)} ห้อง) — "
          f"{'DRY-RUN (ยังไม่เขียน)' if not apply else 'APPLY (เขียนจริง)'} · threshold {threshold:g} บาท")
    print(f"{'=' * 70}")

    error_count = 0
    total_diffs = 0
    total_created = 0
    total_amount = 0.0
    for room in rooms:
        try:
            rep = await _run_single(pool, room_id=room["id"], apply=apply, threshold=threshold)
        except Exception as e:  # noqa: BLE001 — Ops tool: เจอ error ให้ข้ามห้องไป ไม่หยุดทั้งชุด
            error_count += 1
            print(f"❌ ห้อง {room['id']} ({room['room_name']}): error — {e}")
            continue
        n_diffs = len(rep["mismatches"])
        created = rep["adjustments_created"]
        amt = rep["total_adjustment_amount"]
        total_diffs += n_diffs
        total_created += created
        total_amount += amt
        marker = "✅" if n_diffs == 0 else "⚠️"
        print(
            f"{marker} ห้อง {rep['room_id']:>4} ({rep['room_name']}): "
            f"ตรวจ {rep['checked_accounts']} บัญชี · ผลต่าง {n_diffs} · "
            f"สร้าง {created} บิล · รวม {amt:,.2f} บาท"
        )

    print(f"{'=' * 70}")
    print(
        f"สรุป: {len(rooms) - error_count}/{len(rooms)} ห้องรันสำเร็จ · "
        f"พบผลต่างรวม {total_diffs} · สร้าง {total_created} บิล รวม {total_amount:,.2f} บาท"
    )
    if error_count:
        print(f"⚠️ มี {error_count} ห้อง error — ตรวจ log ด้านบน")
    return 1 if error_count else 0


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("กระทบยอดเงินระหว่างระบบเดิม (finance_accounts.balance) "
                     "กับบัญชีคู่ (accounting_ledgers) — เลือกห้องเดียว หรือ --all ทุกห้อง")
    )
    id_group = parser.add_mutually_exclusive_group(required=False)
    id_group.add_argument("--room-id", type=int, help="รหัสห้อง (rooms.id)")
    id_group.add_argument("--server-id", type=int, help="Discord server id ของห้อง")
    id_group.add_argument("--all", action="store_true",
                          help="รันเรียงทุกห้องที่ยังไม่ถูกลบ (ต้องไม่ใช้ --room-id/--server-id)")
    parser.add_argument("--apply", action="store_true",
                        help="เขียนรายการปรับปรุงลง DB (default = dry-run แค่รายงาน)")
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="ผลต่างขั้นต่ำที่ถือว่าต้องปรับ (บาท) default 0.01")
    args = parser.parse_args(argv)

    # 🐛 นับเฉพาะค่าที่เป็น True (sum(1 for ... if x)) — เดิม sum(1 for x in ...) นับสมาชิกเสมอ = 3 → reject ทุกคำสั่ง
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
            return await _run_all(pool, apply=args.apply, threshold=args.threshold)
        rep = await _run_single(
            pool, room_id=args.room_id, server_id=args.server_id,
            apply=args.apply, threshold=args.threshold,
        )
        _print_report(rep)
        return 0
    except (RoomNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 1
    except Exception as e:
        logger.exception("เกิดข้อผิดพลาดระหว่างกระทบยอด")
        print(f"❌ เกิดข้อผิดพลาด: {e}")
        return 1
    finally:
        if pool:
            await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
