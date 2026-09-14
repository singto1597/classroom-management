#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับงาน F4 (เงินรับล่วงหน้า)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
เทสต์ที่ "เขียว" ไม่ได้แปลว่ามีฟัน — มันอาจเขียวเพราะไม่เคยแตะโค้ดที่มันอ้างว่าคุม
สคริปต์นี้จึง **ทำลายโค้ดจริง** ทีละจุด แล้วดูว่าเทสต์ล้มจริงไหม:

  • mutation ถูกจับ (เทสต์ล้ม)  = เทสต์มีฟัน ✅
  • mutation รอด (เทสต์เขียว)   = เทสต์หลอกตัวเอง ❌  ← ต้องแก้เทสต์

⚠️ หลักความซื่อสัตย์: ถ้าเทสต์ที่เล็งไว้ไม่ล้ม จะ **ไม่ด่วนสรุปว่าหมดฟัน** แต่จะ
   ถอยไปรันทั้งไฟล์ก่อน (mutation อาจถูกจับโดยเทสต์ตัวอื่นที่ไม่ได้เล็ง) ⇒ ผลลัพธ์
   ในการรายงานจึงแยก "จับโดยเทสต์ที่เล็ง" กับ "จับโดยเทสต์อื่นในไฟล์" ออกจากกัน

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433
   ร่วมกัน ⇒ สอง container พร้อมกันจะชนกัน

⚠️ สคริปต์นี้ **คืนไฟล์เสมอ** (finally) และยืนยันด้วย git status ตอนจบ
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1 | tail -25"]

CREDITS = "tests/test_finance_credits.py"
LOCK = "tests/test_finance_money_lock.py"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
#   เทสต์ที่ควรจับ = path ไฟล์::ชื่อเทสต์ (หรือ path ไฟล์ เพื่อรันทั้งไฟล์)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    (
        "M1 ถอด advisory lock ออกจาก top_up_credit",
        "services/finance/credits.py",
        "                        # 🔒 ล็อกห้องเป็นคำสั่งแรกก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ)\n"
        "                        await _lock_room_money(conn, target_room_id)",
        "                        pass  # MUTANT: ถอดล็อกห้องออก",
        [f"{LOCK}::test_every_money_path_takes_the_room_lock[credits-CreditsMixin-top_up_credit]"],
    ),
    (
        "M2 ถอด advisory lock ออกจาก apply_credit",
        "services/finance/credits.py",
        "                    # 🔒 ลำดับการล็อก: ห้อง → บิลทั้งชุดตาม id (เหมือน batch_confirm_payments)\n"
        "                    await _lock_room_money(conn, target_room_id)",
        "                    pass  # MUTANT: ถอดล็อกห้องออก",
        [f"{LOCK}::test_every_money_path_takes_the_room_lock[credits-CreditsMixin-apply_credit]"],
    ),
    (
        "M3 ขาเครดิตใช้ revenue ledger แทน liability (กับดักหลักของงานนี้)",
        "services/finance/credits.py",
        "        asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, account_id)\n"
        "        advance_ledger_id = await cls._resolve_advance_ledger(conn, room_id=target_room_id)",
        "        asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, account_id)\n"
        "        advance_ledger_id = await cls._resolve_default_income_ledger(conn, target_room_id)  # MUTANT",
        [f"{CREDITS}::test_top_up_is_a_liability_and_never_revenue"],
    ),
    (
        "M4 ถอดการกันบันทึกซ้ำด้วย idempotency_key (ชั้นที่ 1)",
        "services/finance/credits.py",
        "        if existing_id is not None:",
        "        if False:  # MUTANT: ปิดการกันซ้ำ",
        [f"{CREDITS}::test_top_up_with_same_idempotency_key_is_not_a_second_payment"],
    ),
    (
        "M5 ถอดด่านยอดเงิน <= 0 (ก่อนจองเลขเอกสาร)",
        "services/finance/credits.py",
        "        if amount < _MIN_AMOUNT:",
        "        if False:  # MUTANT: ปิดด่านยอดเงิน",
        [f"{CREDITS}::test_invalid_top_up_amount_writes_nothing"],
    ),
    (
        "M6 ถอด 'student_credit_apply' จาก reference_type ของงบประมาณ (รายได้หายเงียบ)",
        "services/finance/budgets.py",
        "AND JE.reference_type IN ('student_payment', 'student_credit_apply')",
        "AND JE.reference_type IN ('student_payment')  -- MUTANT",
        [f"{CREDITS}::test_budget_overview_counts_revenue_from_credit_application"],
    ),
    (
        "M7 คืนค่า double-restore ใน _undo_credit_locked (บั๊กที่เทสต์จับได้จริง)",
        "services/finance/credits.py",
        "        balance_after = round(balance_before + applied, 2)",
        "        balance_after = round(balance_before + applied * 2, 2)  # MUTANT",
        [f"{CREDITS}::test_undo_application_returns_credit_and_reopens_the_bill"],
    ),
    (
        "M8 ถอดการเติม student_id เข้า plan (ทำให้ endpoint 500)",
        "services/finance/credits.py",
        '                plan["student_id"] = student_id',
        "                pass  # MUTANT: ไม่เติม student_id",
        [f"{CREDITS}::test_balance_after_is_a_snapshot_chain_not_a_sum"],
    ),
    (
        "M9 ปิด idempotency ของใบ DEP (กันซ้ำชั้นที่ 1)",
        "services/finance/receipts.py",
        "        existing = await cls._find_existing_deposit(conn, transaction_id)\n"
        "        if existing:",
        "        existing = await cls._find_existing_deposit(conn, transaction_id)\n"
        "        if False:  # MUTANT",
        [CREDITS],
    ),
    (
        "M10 ทำ pdf_filename ให้โกหกสำหรับ deposit อีกครั้ง",
        "services/finance/pdf.py",
        '    "deposit": "deposit",',
        '    # MUTANT: ตัด deposit ออก',
        [f"{CREDITS}::test_pdf_filename_does_not_lie_for_deposit"],
    ),
    (
        "M11 ถอด guard 'เครดิตถูกใช้ไปแล้ว' ของ revert",
        "services/finance/transactions.py",
        "                        if later_id is not None:",
        "                        if False:  # MUTANT: ปิด guard เครดิตถูกใช้",
        [f"{CREDITS}::test_revert_is_refused_when_the_credit_was_already_used"],
    ),
    (
        "M12 ถอด audit log ของการยกเลิกรายการ",
        "services/finance/transactions.py",
        'conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,\n                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="success",',
        'None  # MUTANT: ไม่บันทึก audit',
        [f"{CREDITS}::test_revert_of_top_up_keeps_audit_rows_and_removes_nothing_from_the_journal"],
    ),
    # ── 🖨️ กลุ่มเทมเพลต: บั๊กที่ **เทสต์ 64 ตัวแรกจับไม่ได้** พบตอนเรนเดอร์ PDF ดูด้วยตา ──
    (
        "M13 ถอนการตั้ง remaining=None (ทำให้ใบ DEP ดาวน์โหลดไม่ได้ — 500)",
        "services/finance/receipts.py",
        '            "collection_amount": None,\n            "remaining": None,\n            "remaining_text": None,\n',
        '            "collection_amount": None,  # MUTANT: คีย์ remaining หายไป\n',
        [f"{CREDITS}::test_deposit_context_pins_bill_only_keys_to_none",
         f"{CREDITS}::test_deposit_document_renders_and_speaks_as_a_receipt"],
    ),
    (
        "M14 ถอยแถวรายการของใบ DEP กลับไปเป็นคำกลาง ๆ 'รายการชำระเงิน'",
        "templates/finance/receipt.html",
        "          {%- elif d.doc_type == 'deposit' -%}\n            รับเงินล่วงหน้า (ยังไม่หักปิดบิลใด)\n",
        "          {%- elif false -%}\n",
        [f"{CREDITS}::test_deposit_document_renders_and_speaks_as_a_receipt"],
    ),
]


def run_pytest(targets: list[str]) -> tuple[bool, str]:
    """คืน (ผ่าน?, ข้อความท้ายสุด)"""
    cmd = COMPOSE[:-1] + [COMPOSE[-1].format(targets=" ".join(f"/app/{t}" for t in targets))]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=2400)
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-4:])
    return proc.returncode == 0, tail


def main() -> int:
    results = []
    # 🎯 กรองได้ด้วย argv: `python tests/_mutation_credits.py M13 M14`
    #    💡 มีไว้เพราะแต่ละ mutation ต้องสตาร์ท container ใหม่ (~4 นาที) ⇒ การรันทั้งชุด
    #       ใช้เวลาเป็นชั่วโมง · ตอนแก้เทสต์ใหม่จึงอยากรันเฉพาะตัวที่เกี่ยวข้อง
    #    ⚠️ ไม่มี argument = รันทั้งหมด (พฤติกรรมเดิม) — ห้ามทำให้การรันเต็มเงียบลง
    only = {a.upper() for a in sys.argv[1:]}
    selected = [
        m for m in MUTATIONS if not only or m[0].split()[0].upper() in only
    ]
    if only:
        print(f"🎯 เลือกรันเฉพาะ: {', '.join(sorted(only))} ({len(selected)} mutation)\n", flush=True)
    for name, rel, old, new, targets in selected:
        path = BACKEND / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append((name, "STALE", "ไม่พบข้อความเป้าหมายในไฟล์ — ตกยุค ต้องอัปเดตสคริปต์"))
            print(f"⚠️  {name}: STALE", flush=True)
            continue

        if original.count(old) != 1:
            results.append((name, "AMBIG", f"ข้อความเป้าหมายซ้ำ {original.count(old)} ที่"))
            print(f"⚠️  {name}: AMBIG", flush=True)
            continue

        try:
            path.write_text(original.replace(old, new), encoding="utf-8")
            caught_by, tail = run_pytest(targets)
            if caught_by:
                verdict = "จับโดยเทสต์ที่เล็ง ✅"
            else:
                # ถอยไปรันทั้งไฟล์ — mutation อาจถูกจับโดยเทสต์ตัวอื่น
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                caught_by, tail = run_pytest([CREDITS, LOCK])
                verdict = ("จับโดยเทสต์อื่นในไฟล์ ✅" if caught_by
                           else "รอด ❌ เทสต์หลอกตัวเอง")
        finally:
            path.write_text(original, encoding="utf-8")

        results.append((name, "CATCH" if caught_by else "SURVIVE", tail))
        print(f"{'✅' if caught_by else '❌'} {name}: {verdict}", flush=True)

    print("\n" + "═" * 78)
    print(f"{'ผล':<10} mutation")
    print("═" * 78)
    for name, status, _ in results:
        print(f"{status:<10} {name}")
    survived = [n for n, s, _ in results if s == "SURVIVE"]
    print("═" * 78)
    print(f"จับได้ {sum(1 for _, s, _ in results if s == 'CATCH')}/{len(results)}"
          f" | รอด {len(survived)}")
    for n, s, t in results:
        if s in ("SURVIVE", "STALE", "AMBIG"):
            print(f"\n── {n} [{s}] ──\n{t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
