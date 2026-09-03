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

Exit code: 0 = สำเร็จ (รวม dry-run ที่เจอผลต่าง / apply ที่เขียนจริง); 1 = error ทางปฏิบัติ

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


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("กระทบยอดเงินระหว่างระบบเดิม (finance_accounts.balance) "
                     "กับบัญชีคู่ (accounting_ledgers) ของห้องเดียว")
    )
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument("--room-id", type=int, help="รหัสห้อง (rooms.id)")
    id_group.add_argument("--server-id", type=int, help="Discord server id ของห้อง")
    parser.add_argument("--apply", action="store_true",
                        help="เขียนรายการปรับปรุงลง DB (default = dry-run แค่รายงาน)")
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="ผลต่างขั้นต่ำที่ถือว่าต้องปรับ (บาท) default 0.01")
    args = parser.parse_args(argv)

    if not hasattr(settings, 'DATABASE_URL') or not settings.DATABASE_URL:
        print("❌ ไม่พบ DATABASE_URL ใน Environment Variables!")
        return 1

    pool = None
    try:
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=5)
        rep = await FinanceService.reconcile_balances(
            pool,
            room_id=args.room_id,
            server_id=args.server_id,
            apply=args.apply,
            threshold=args.threshold,
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
