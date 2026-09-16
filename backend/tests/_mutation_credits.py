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
import re
import signal
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** (`1 failed in 5.05s` / `130 passed, 1 skipped`)
#    ใช้เป็นหลักฐานว่า "เทสต์รันจริง" — ไม่มีบรรทัดนี้ = infra พัง ไม่ว่า exit code จะเป็นอะไร
#    ⚠️ จงใจ **ไม่** รับ `N error` — collection error ไม่ใช่ "เทสต์ล้ม" และต้องไม่นับเป็น "จับได้"
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

# 🔴 **ห้ามต่อ `| tail` ในคำสั่งนี้เด็ดขาด** — `sh` เป็น dash ⇒ exit code ของ pipeline
#    คือของ **ตัวสุดท้าย** ไม่ใช่ของ pytest ⇒ `proc.returncode` เป็น 0 **เสมอ**
#    ⇒ `run_pytest` คืน "ผ่าน" ทุกครั้ง ⇒ harness รายงาน CATCH ให้ mutant **ทุกตัว**
#    โดยไม่มีเทสต์จับอะไรเลย — ผลบวกลวงที่อันตรายกว่า false negative เพราะอ่านเหมือน
#    "เทสต์มีฟันครบ" ⇒ ไม่มีใครกลับไปตรวจ
#    พิสูจน์สองบรรทัด: `sh -c "false | tail -1"` → 0 · `sh -c "false"` → 1
#    และ dash ไม่มี `PIPESTATUS` ให้กู้ ⇒ ตัด pipe ทิ้ง แล้วให้ Python ตัด tail เอง
#    (ดูบทเรียนเต็มใน `docs/skills.md`)
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

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
        [
            f"{CREDITS}::test_top_up_with_same_idempotency_key_is_not_a_second_payment",
            # 🔑 เทสต์ตัวนี้คือตัวที่จับ M4 ได้จริง — เทสต์ข้างบนผ่านทั้งสองชั้นเพราะ
            #    response ของทั้งสองทางเหมือนกันเป๊ะ (ดู docstring ของเทสต์นี้)
            f"{CREDITS}::test_repeated_top_up_leaves_an_audit_row_flagged_reused",
        ],
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
        # 🟡 **mutant นี้ "รอด" โดยชอบธรรม (equivalent ที่ระดับ API) — พิสูจน์แล้ว 2026-09-15**
        #    ปิด `if existing:` ⇒ ไป `INSERT INTO receipt_sequences ... last_seq + 1` (กินเลข)
        #    แล้วชน `idx_finance_receipts_deposit_active` ⇒ ชั้นที่ 2 (`raced`) คืนใบเดิม
        #    ⇒ **ใบที่ได้ + แถวใน DB เหมือนเดิมเป๊ะ** ต่างแค่เลขที่ถูกกินไป 1
        #    🔑 แต่ผลต่างนั้น **ไปไม่ถึง**: `_issue_deposit` มีผู้เรียกเดียว (`credits.py:408`)
        #       และ `top_up_credit` **return เร็วที่ idempotency_key ก่อนสร้าง transaction**
        #       (`credits.py:308-313`) ⇒ ทุกครั้งที่เรียกได้ `trans_id` ใหม่เสมอ ⇒ `existing`
        #       ไม่มีทางไม่เป็น None ผ่านเส้นทางที่มี route อยู่จริง
        #    ⚠️ **ห้ามลบสาขานี้ทิ้ง** — มันเป็นสัญญาของ `_issue_deposit` ในฐานะฟังก์ชันกลาง
        #       (เหมือนสาขา `reused` ใน `collections.py` ที่ตายในเส้นทางนั้นแต่ยังต้องอยู่)
        "M9 ปิด idempotency ของใบ DEP (กันซ้ำชั้นที่ 1)",
        "services/finance/receipts.py",
        "        existing = await cls._find_existing_deposit(conn, transaction_id)\n"
        "        if existing:",
        "        existing = await cls._find_existing_deposit(conn, transaction_id)\n"
        "        if False:  # MUTANT",
        [CREDITS],
        # 🟡 รอดโดยชอบธรรม — ดูเหตุผลเต็มในคอมเมนต์เหนือ mutant นี้
        #    ⇒ ต้องเป็น EQUIV ไม่ใช่ SURVIVE (ไม่งั้นอ่านเป็น "มีช่องว่างของเทสต์" ทั้งที่ไม่มี)
        "equiv",
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
        # 🔴 เดิม mutant นี้แทน "แค่ kwargs สองบรรทัด" ด้วย `None  # MUTANT` ⇒ โค้ดที่ได้คือ
        #    `log(None` แล้วตามด้วย `old_values=…` โดยไม่มีจุลภาค = **SyntaxError**
        #    ⇒ pytest collection พังทั้งไฟล์ ⇒ ไม่มีบรรทัดสรุปของ pytest ⇒ อ่านเป็น `infra`
        #    ไม่ใช่ `CATCH` · แย่กว่านั้นคือมัน **ไม่เคยพิสูจน์อะไรเลย** มาตลอด
        #    ⇒ ต้องแทน **ทั้งคำสั่ง** ด้วย `pass` เพื่อให้ mutant เป็น Python ที่ถูกต้อง
        #      (มิฉะนั้น harness จะรายงาน INFRA ที่อ่านคล้าย "หาข้อมูลไม่ได้" ทั้งที่ความจริง
        #       คือ "ไม่มีอะไรถูกทดสอบ" — ผลบวกลวงแบบกลับด้าน)
        "M12 ถอด audit log ของการยกเลิกรายการ",
        "services/finance/transactions.py",
        '                    await service_logger.log(\n'
        '                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,\n'
        '                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="success",\n'
        '                        old_values=old_values,\n'
        '                        new_values={"action": action_detail, "voided_receipts": voided_nos},\n'
        '                        endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time\n'
        '                    )',
        '                    pass  # MUTANT: ไม่บันทึก audit',
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
        # 🔴 PR-5 แตก `receipt.html` เป็น shell + partial (`{% include d.body_template %}`)
        #    ⇒ เนื้อในทั้งดุ้น **ย้ายไฟล์** ไป `_receipt_body.html` (indent เดิมทุกไบต์)
        #    ปล่อย path เก่าไว้ = anchor ไม่เจอ ⇒ harness ขึ้น STALE แล้ว **ข้ามไปเงียบ ๆ**
        #    ซึ่งอ่านเผิน ๆ เหมือน "ผ่าน" ทั้งที่ mutation ตัวนั้นไม่ถูกทดสอบเลย
        "templates/finance/_receipt_body.html",
        "          {%- elif d.doc_type == 'deposit' -%}\n            รับเงินล่วงหน้า (ยังไม่หักปิดบิลใด)\n",
        "          {%- elif false -%}\n",
        [f"{CREDITS}::test_deposit_document_renders_and_speaks_as_a_receipt"],
    ),
]

# 🔑 เติมช่องที่ 6 "ความคาดหวัง" ให้ครบทุก mutant ⇒ `(name, rel, old, new, targets, expect)`
#    ไม่ใส่ = `"catch"` (พฤติกรรมเดิมของทุกตัวไม่เปลี่ยนแม้แต่ไบต์เดียว)
#
#    🟡 `expect="equiv"` = mutant ที่ **รอดโดยชอบธรรม** เพราะพิสูจน์แล้วว่าเทียบเท่ากับ
#       โค้ดเดิมในระดับที่ผู้ใช้สังเกตได้ (ดูเหตุผลรายตัวในคอมเมนต์ของ mutant นั้น)
#       ⇒ harness ต้องรายงาน 🟡 EQUIV ไม่ใช่ ❌ SURVIVE และ **ห้ามนับเป็นความล้มเหลว**
#       🔴 เดิมไม่มีกลไกนี้ ⇒ M9 มีคอมเมนต์พิสูจน์ครบในไฟล์แล้ว แต่ harness ยังพิมพ์ ❌
#          ⇒ คนอ่านเห็น "รอด 1" แล้วเข้าใจว่ามีช่องว่างของเทสต์ทั้งที่ไม่มี
#          (คอมเมนต์ที่ไม่มีโค้ดรองรับ = คำอ้างที่ระบบไม่เคยบังคับใช้ — บทเรียนเดิมใน `docs/skills.md`)
MUTATIONS = [m if len(m) == 6 else (*m, "catch") for m in MUTATIONS]


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    🔴 **แยก "เทสต์ล้ม" ออกจาก "container/collection พัง" ให้ออก** — ถ้ารวมเป็น boolean
       เดียว การที่ docker ดึง image ไม่ได้ / pytest ไม่เก็บเทสต์เลย (exit 5) จะถูกอ่านเป็น
       "mutant ถูกจับ" ซึ่งเป็นผลบวกลวงที่อันตรายที่สุดของ harness แบบนี้
       📌 pytest exit code: 0 = ผ่านหมด · 1 = มีเทสต์ล้ม · 2 = ถูกขัดจังหวะ · 3 = internal
          error · 4 = flag ผิด · 5 = ไม่เก็บเทสต์เลย ⇒ รับเฉพาะ 1 เป็น "ล้มจริง"
    """
    cmd = COMPOSE[:-1] + [COMPOSE[-1].format(targets=" ".join(f"/app/{t}" for t in targets))]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=2400)
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-30:])
    if not PYTEST_SUMMARY_RE.search(out):
        # ไม่มีบรรทัดสรุปของ pytest ⇒ **ไม่รู้ว่าเกิดอะไรขึ้น** ⇒ ห้ามเดา ห้ามนับเป็น "จับได้"
        return "infra", f"exit={proc.returncode} · ไม่พบบรรทัดสรุปของ pytest\n{tail}"
    if proc.returncode == 0:
        return "pass", tail
    if proc.returncode == 1:
        return "fail", tail
    return "infra", f"exit={proc.returncode}\n{tail}"


MARKER = "MUTANT"

# 🔴 `finally` **ไม่รัน** เมื่อถูก SIGTERM (TaskStop / kill) ⇒ mutant ค้างในไฟล์จริง
#    และรอบถัดไปจะอ่านไฟล์ที่ค้างเป็น "original" เงียบ ๆ ⇒ ต้องจับสัญญาณแล้ว raise
#    SystemExit เพื่อให้ finally ได้คืนไฟล์ + มีด่าน pre-flight กัน baseline เสียอีกชั้น
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def main() -> int:
    results = []
    # 🛡️ ด่าน pre-flight: ห้ามเริ่มถ้ามี mutant ค้างจากรอบที่ถูกฆ่า
    dirty = sorted({
        rel for _, rel, _, _, _, _ in MUTATIONS
        if MARKER in (BACKEND / rel).read_text(encoding="utf-8")
    })
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

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
    for name, rel, old, new, targets, expect in selected:
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

        caught_by, infra = False, False
        try:
            path.write_text(original.replace(old, new), encoding="utf-8")
            state, tail = run_pytest(targets)
            if state == "infra":
                verdict = "infra พัง — ผลใช้ไม่ได้"
            elif state == "fail":
                verdict = "จับโดยเทสต์ที่เล็ง ✅"
            else:
                # ถอยไปรันทั้งไฟล์ — mutation อาจถูกจับโดยเทสต์ตัวอื่น
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                state, tail = run_pytest([CREDITS, LOCK])
                verdict = ("จับโดยเทสต์อื่นในไฟล์ ✅" if state == "fail"
                           else "รอด")
            caught_by, infra = state == "fail", state == "infra"
        finally:
            path.write_text(original, encoding="utf-8")

        if infra:
            status, icon = "INFRA", "🛑"
        elif expect == "equiv":
            # 🟡 mutant ที่ประกาศว่าเทียบเท่า — "รอด" คือผลที่ถูกต้อง ไม่ใช่ความล้มเหลว
            #    🔴 แต่ถ้ามัน **ถูกจับ** ⇒ คำอ้าง "เทียบเท่า" ถูกหักล้าง ต้องได้เห็น
            #       (ไม่ใช่รายงานเป็น CATCH เฉย ๆ แล้วผ่านไป — นั่นทำให้คำอ้างผิดมีชีวิตต่อ)
            #    ⚠️ ข้อความ verdict ต้องไม่ใช้ถ้อยคำของเส้นทาง "catch" — ไม่งั้นบรรทัดนี้
            #       จะพิมพ์ 🟡 แล้วต่อท้ายด้วย "เทสต์หลอกตัวเอง ❌" ซึ่งขัดกันเอง
            #       (บั๊กชนิดเดียวกับที่งานนี้ตั้งใจกำจัด — ข้อความที่โกหกผลของตัวเอง)
            status = "SURPRISE" if caught_by else "EQUIV"
            icon = "⚠️" if caught_by else "🟡"
            if caught_by:
                verdict = "ถูกจับ — คำอ้าง 'เทียบเท่า' ถูกหักล้าง ต้องทบทวน ⚠️"
            elif verdict == "รอด":
                verdict = "รอดโดยชอบธรรม (พิสูจน์แล้วว่าเทียบเท่า) 🟡"
        else:
            status, icon = ("CATCH", "✅") if caught_by else ("SURVIVE", "❌")
            if not caught_by and verdict == "รอด":
                verdict = "รอด ❌ เทสต์หลอกตัวเอง"
        results.append((name, status, tail))
        print(f"{icon} {name}: {verdict}", flush=True)

    print("\n" + "═" * 78)
    print(f"{'ผล':<10} mutation")
    print("═" * 78)
    for name, status, _ in results:
        print(f"{status:<10} {name}")
    n_surv = sum(1 for _, s, _ in results if s == "SURVIVE")
    n_infra = sum(1 for _, s, _ in results if s == "INFRA")
    n_surprise = sum(1 for _, s, _ in results if s == "SURPRISE")
    print("═" * 78)
    print(f"จับได้ {sum(1 for _, s, _ in results if s == 'CATCH')}/{len(results)}"
          f" | รอด {n_surv} | เทียบเท่า {sum(1 for _, s, _ in results if s == 'EQUIV')}"
          f" | คำอ้าง equiv ถูกหักล้าง {n_surprise} | infra พัง {n_infra}")
    for n, s, t in results:
        if s in ("SURVIVE", "INFRA", "STALE", "AMBIG", "SURPRISE"):
            print(f"\n── {n} [{s}] ──\n{t}")
    # 🛑 infra = "ไม่รู้ผล" ไม่ใช่ "ผ่าน" ⇒ ต้อง exit ไม่เป็นศูนย์ให้คนเห็น
    # ⚠️ SURPRISE ก็นับเป็นความล้มเหลว: มันแปลว่าคำอ้าง "mutant นี้เทียบเท่า" **ผิด**
    #    ⇒ ต้องกลับไปดูว่ามีเทสต์ที่จับมันได้จริง และควรเปลี่ยน expect กลับเป็น "catch"
    return 1 if (n_infra or n_surprise) else 0


if __name__ == "__main__":
    sys.exit(main())
