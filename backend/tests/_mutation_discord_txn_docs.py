#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับงาน F6/PR-6 (แนบเอกสารของรายการเงินเข้า Discord)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
สัญญาระหว่าง backend กับบอทในงานนี้เป็น **"คีย์เดียวใน payload"** ล้วน ๆ — ไม่มีสกีมา
ไม่มี exception ไม่มี log ⇒ ถ้ามันหลุด จะ **ไม่มีอะไร error เลย** ผู้ใช้เห็นแค่
"ข้อความมาแต่ไม่มีไฟล์" ซึ่งแยกไม่ออกจากการที่ Gotenberg ล่ม (ซึ่งเป็นเรื่องปกติที่ยอมรับได้)

  • mutation ถูกจับ (เทสต์ล้ม)  = เทสต์มีฟัน ✅
  • mutation รอด (เทสต์เขียว)   = เทสต์หลอกตัวเอง ❌  ← ต้องแก้เทสต์

⚠️ mutation ที่ "รอด" อาจเป็น **equivalent mutant** (เปลี่ยนโค้ดแต่พฤติกรรมเท่ากัน)
   ⇒ ก่อนแก้เทสต์ให้ถอยไปตรวจ invariant ก่อนเสมอ (ดู `docs/skills.md`)

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433 ร่วมกัน

🔧 **วิธีรัน: จาก host** (สคริปต์ shell ออกไปสั่ง `docker compose … test_runner` เอง):
       python3 backend/tests/_mutation_discord_txn_docs.py           # ทั้งหมด
       python3 backend/tests/_mutation_discord_txn_docs.py N2 N3     # เฉพาะบางตัว

⚠️ สคริปต์นี้ **คืนไฟล์เสมอ** (finally) และยืนยันด้วย md5 ตอนจบ
"""
import hashlib
import re
import signal
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** — ไม่มีบรรทัดนี้ = infra พัง ไม่ว่า exit code
#    จะเป็นอะไร (บทเรียนซ้ำแล้วซ้ำเล่า: อ่าน infra พังเป็น "mutant ถูกจับ" คือผลบวกลวง)
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

# 🔴 **ห้ามต่อ `| tail`** — `sh` เป็น dash ⇒ exit code ของ pipeline คือของตัวสุดท้าย
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

ACTION = "services/action_service.py"
TXN = "services/finance/transactions.py"
NOTIF = "tests/test_discord_notifications.py"

T_NO_KEY = f"{NOTIF}::test_notify_new_finance_without_document_has_no_key"
T_INCOME = f"{NOTIF}::test_add_income_transaction_publishes"
T_EXPENSE = f"{NOTIF}::test_add_expense_transaction_publishes"
T_CARRIES = f"{NOTIF}::test_notify_new_finance_carries_receipt_nos_of_its_document"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
# ─────────────────────────────────────────────────────────────────────────────
# 🔴 anchor ของ N1/N2 ต้องลากบรรทัด `await cls._publish("FINANCE_TRANSACTION"…)` มาด้วย
#    ⇒ `if receipt_nos:` + บรรทัดถัดไป **เหมือนกันเป๊ะ** กับที่ `notify_payments_confirmed`
#      (F5/PR-3) ⇒ anchor สั้นกว่านี้จะซ้ำ 2 ที่ = AMBIG (harness จะไม่ทดสอบอะไรเลย)
_PUBLISH_TXN = '        await cls._publish("FINANCE_TRANSACTION", server_id, payload,\n'
_INSERT_KEY = '        if receipt_nos:\n            payload["receipt_nos"] = receipt_nos\n'

MUTATIONS = [
    (
        "N1 🔴 ใส่คีย์เสมอ (`if True:`) ⇒ payload เดิมได้ `receipt_nos: None` ติดไปด้วย",
        ACTION,
        _INSERT_KEY + _PUBLISH_TXN,
        '        if True:  # MUTANT: ใส่คีย์เสมอ\n'
        '            payload["receipt_nos"] = receipt_nos\n' + _PUBLISH_TXN,
        [T_NO_KEY],
    ),
    (
        "N2 🔴 'รัดเข็มขัด' เป็น `is not None` ⇒ ลิสต์ว่างกลายเป็นคีย์ที่บอทขอ PDF เปล่า",
        ACTION,
        _INSERT_KEY + _PUBLISH_TXN,
        "        if receipt_nos is not None:  # MUTANT\n"
        '            payload["receipt_nos"] = receipt_nos\n' + _PUBLISH_TXN,
        [T_NO_KEY],
    ),
    (
        "N3 🔴 ถอด `receipt_nos` ออกจากจุดเรียก ⇒ ฟีเจอร์แนบไฟล์หายทั้งฟีเจอร์แบบเงียบ",
        TXN,
        '                    receipt_nos=[doc_row["receipt_no"]] if doc_row else None,\n',
        "                    receipt_nos=None,  # MUTANT: ลืมส่งเลขเอกสาร\n",
        [T_INCOME, T_EXPENSE],
    ),
    (
        "N4 🔴 ส่งฟิลด์ผิด (`doc_type` แทน `receipt_no`) ⇒ บอทขอ PDF ด้วยคำที่ไม่ใช่เลขเอกสาร",
        TXN,
        '                    receipt_nos=[doc_row["receipt_no"]] if doc_row else None,\n',
        '                    receipt_nos=[doc_row["doc_type"]] if doc_row else None,  # MUTANT\n',
        [T_INCOME, T_EXPENSE],
    ),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    📌 pytest exit code: 0 = ผ่านหมด · 1 = มีเทสต์ล้ม · 4 = flag ผิด · 5 = ไม่เก็บเทสต์
       ⇒ รับเฉพาะ 1 เป็น "ล้มจริง"
    """
    cmd = COMPOSE[:-1] + [COMPOSE[-1].format(targets=" ".join(f"/app/{t}" for t in targets))]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=2400)
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-30:])
    if not PYTEST_SUMMARY_RE.search(out):
        return "infra", f"exit={proc.returncode} · ไม่พบบรรทัดสรุปของ pytest\n{tail}"
    if proc.returncode == 0:
        return "pass", tail
    if proc.returncode == 1:
        return "fail", tail
    return "infra", f"exit={proc.returncode}\n{tail}"


MARKER = "MUTANT"

# 🔴 `finally` **ไม่รัน** เมื่อถูก SIGTERM ⇒ mutant ค้างในไฟล์จริง และรอบถัดไปจะอ่าน
#    ไฟล์ที่ค้างเป็น "original" ⇒ ไม่มีอะไรฟ้องว่า baseline เสีย
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def main() -> int:
    touched = sorted({rel for _, rel, _, _, _ in MUTATIONS})

    # 🛡️ ด่าน pre-flight: ห้ามเริ่มถ้ามี mutant ค้างจากรอบที่ถูกฆ่า
    dirty = [rel for rel in touched if MARKER in (BACKEND / rel).read_text(encoding="utf-8")]
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

    before = {rel: md5(BACKEND / rel) for rel in touched}

    only = {a.upper() for a in sys.argv[1:]}
    selected = [m for m in MUTATIONS if not only or m[0].split()[0].upper() in only]
    if only:
        print(f"🎯 เลือกรันเฉพาะ: {', '.join(sorted(only))} ({len(selected)} mutation)\n", flush=True)

    results = []
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

        caught_by, infra = False, False
        try:
            path.write_text(original.replace(old, new), encoding="utf-8")
            state, tail = run_pytest(targets)
            if state == "infra":
                verdict = "infra พัง — ผลใช้ไม่ได้"
            elif state == "fail":
                verdict = "จับโดยเทสต์ที่เล็ง ✅"
            else:
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                state, tail = run_pytest([NOTIF])
                verdict = ("จับโดยเทสต์อื่นในไฟล์ ✅" if state == "fail"
                           else "รอด ❌ เทสต์หลอกตัวเอง")
            caught_by, infra = state == "fail", state == "infra"
        finally:
            path.write_text(original, encoding="utf-8")

        status = "INFRA" if infra else ("CATCH" if caught_by else "SURVIVE")
        results.append((name, status, tail))
        icon = "🛑" if infra else ("✅" if caught_by else "❌")
        print(f"{icon} {name}: {verdict}", flush=True)

    print("\n" + "═" * 78)
    print(f"{'ผล':<10} mutation")
    print("═" * 78)
    for name, status, _ in results:
        print(f"{status:<10} {name}")
    survived = [n for n, s, _ in results if s == "SURVIVE"]
    n_infra = sum(1 for _, s, _ in results if s == "INFRA")
    print("═" * 78)
    print(f"จับได้ {sum(1 for _, s, _ in results if s == 'CATCH')}/{len(results)}"
          f" | รอด {len(survived)} | infra พัง {n_infra}")
    for n, s, t in results:
        if s in ("SURVIVE", "INFRA", "STALE", "AMBIG"):
            print(f"\n── {n} [{s}] ──\n{t}")

    # 🔒 ยืนยันด้วย md5 ว่าไฟล์กลับสภาพเดิมจริง (ไม่ใช่แค่ "เชื่อว่า finally ทำงาน")
    print("\n── ตรวจความสมบูรณ์ของไฟล์ ──")
    broken = [rel for rel in touched if md5(BACKEND / rel) != before[rel]]
    if broken:
        print("🔴 ไฟล์ไม่กลับสภาพเดิม:")
        for rel in broken:
            print(f"   • {rel}")
        return 3
    print("✅ ไฟล์ทั้งหมดกลับสภาพเดิม (md5 ตรง)")
    return 1 if n_infra else 0


if __name__ == "__main__":
    sys.exit(main())
