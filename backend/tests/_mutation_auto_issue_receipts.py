#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับ F5/PR-2 (ออกใบเสร็จอัตโนมัติเมื่อเคลียร์หนี้)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
เทสต์ที่ "เขียว" ไม่ได้แปลว่ามีฟัน — มันอาจเขียวเพราะไม่เคยแตะโค้ดที่มันอ้างว่าคุม
สคริปต์นี้จึง **ทำลายโค้ดจริง** ทีละจุด แล้วดูว่าเทสต์ล้มจริงไหม:

  • mutation ถูกจับ (เทสต์ล้ม)  = เทสต์มีฟัน ✅
  • mutation รอด (เทสต์เขียว)   = เทสต์หลอกตัวเอง ❌  ← ต้องแก้เทสต์

⚠️ **mutant ที่ตั้งใจให้ "รอด"** (`expect="equiv"`) มีอยู่จริงในตารางนี้ — คือ mutant ที่
   เปลี่ยนโค้ดแต่ **พฤติกรรมเท่ากันทุกเส้นทางที่เทสต์เอื้อมถึง** (equivalent mutant)
   ⇒ สคริปต์แยกผลลัพธ์เป็น CATCH / EQUIV(รอดตามคาด) / SURVIVE(รอดผิดคาด) เพื่อไม่ให้
   "การรอด" ถูกอ่านเป็น "เทสต์หลอกตัวเอง" ทั้งที่พิสูจน์แล้วว่าเทียบเท่า

⚠️ mutation ที่ "รอด" โดยไม่ตั้งใจ = ต้องถอยไปตรวจ **invariant ของโค้ดจริง** ก่อนเสมอ
   (ดู `docs/skills.md`) ห้ามด่วนแก้เทสต์ให้ล้ม

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433
   ร่วมกัน ⇒ สอง container พร้อมกันจะชนกัน · **ต้องรันจาก host** (สคริปต์เรียก
   `docker compose` เอง ไม่ได้รันใน container)

⚠️ สคริปต์นี้ **คืนไฟล์เสมอ** (finally) และตรวจ md5 เทียบสำเนาตั้งต้นตอนจบ
"""
import hashlib
import re
import signal
import subprocess
import sys
from pathlib import Path

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** (`1 failed in 5.05s` / `130 passed, 1 skipped in 40s`)
#    ใช้เป็น "หลักฐานว่าเทสต์รันจริง" — ถ้าไม่มีบรรทัดนี้ สถานะจะเป็น infra ทันทีไม่ว่า exit code
#    จะเป็นอะไร ⇒ กันทั้ง "container พังแล้ว exit 1" และ "ไม่มีเทสต์ถูกรัน"
#    ⚠️ จงใจ **ไม่** รับ `N error` — collection error ไม่ใช่ "เทสต์ล้ม" และต้องไม่ถูกนับเป็น "จับได้"
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# 🔴 **ห้ามต่อ `| tail` ในคำสั่งนี้เด็ดขาด** — `sh` เป็น dash ⇒ exit code ของ pipeline
#    คือของ `tail` (ตัวสุดท้าย) **ไม่ใช่ของ pytest** ⇒ `proc.returncode` เป็น 0 เสมอ
#    ⇒ ทุก mutant ถูกอ่านเป็น "เทสต์ผ่าน" ทั้งที่เทสต์ล้ม (พิสูจน์แล้ว: `sh -c "false | tail -1"`
#    คืน 0 · `sh -c "false"` คืน 1) และ dash ไม่มี `PIPESTATUS` ให้กู้ ⇒ ตัด pipe ทิ้ง
#    แล้วให้ Python ตัด tail เอง (`text=True` + `capture_output` เก็บ stdout ครบอยู่แล้ว)
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

HTTP = "tests/test_finance_http.py"
COL = "services/finance/collections.py"

# 🎯 node id แบบเจาะจง (เร็วกว่ารันทั้งไฟล์มาก) — ใช้ param `[1]` เพื่อไม่ต้องรันเคส 100 บิล
T_OPT_OUT = f"{HTTP}::test_batch_confirm_payments_opt_out_issue_receipts"
T_OVERFLOW = f"{HTTP}::test_batch_confirm_payments_seq_overflow_does_not_take_money"
T_PRECHECK = f"{HTTP}::test_batch_confirm_payments_seq_budget_precheck_names_the_shortfall"
T_ONE_BILL = f"{HTTP}::test_batch_confirm_payments_issues_one_receipt_per_bill[1]"
# 🔑 เทสต์ fault injection — เทสต์เดียวที่แยก "ออกใบเสร็จในธุรกรรม" ออกจาก "ออกหลัง commit"
#    ได้จริง (เทสต์ overflow ถูกด่านล่วงหน้าบัง ⇒ จับ M2 ไม่ได้ — ดู docstring ของเทสต์)
T_FAULT = f"{HTTP}::test_batch_confirm_payments_receipt_failure_takes_no_money"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (id+ชื่อ, expect, [(ไฟล์, ข้อความเดิม, ข้อความใหม่), ...], เทสต์ที่ควรจับ)
#   • `edits` เป็น **ลิสต์** เพราะ mutant บางตัวต้องแก้สองจุดพร้อมกัน (เช่น "ย้ายบล็อก")
#   • `expect`: "catch" = ต้องล้ม / "equiv" = รอดโดยชอบธรรม (ต้องมีเหตุผลกำกับ)
#   • เทสต์ที่ควรจับ = path ไฟล์::ชื่อเทสต์ (หรือ path ไฟล์ เพื่อรันทั้งไฟล์)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    (
        "M1 ถอดด่าน opt-out (`if req.issue_receipts:` → `if True:`)",
        "catch",
        [(COL,
          "                    issued, reused, batch_id = [], 0, None\n"
          "                    if req.issue_receipts:\n",
          "                    issued, reused, batch_id = [], 0, None\n"
          "                    if True:  # MUTANT: ติ๊กปิดก็ยังออกใบเสร็จ\n")],
        [T_OPT_OUT],
    ),
    (
        "M2 🔑 ย้ายการออกใบเสร็จไป **หลัง commit** (คนละ connection = คนละ transaction)",
        "catch",
        [
            # A: ปิดการออกใบเสร็จใน transaction
            (COL,
             "                    issued, reused, batch_id = [], 0, None\n"
             "                    if req.issue_receipts:\n"
             "                        new_ids = []\n",
             "                    issued, reused, batch_id = [], 0, None\n"
             "                    if False:  # MUTANT-A: ย้ายไปหลัง commit\n"
             "                        new_ids = []\n"),
            # B: ไปออกหลัง `conn.transaction()` ปิดไปแล้ว
            (COL,
             "                    room_server_id = await cls._get_room_server_id(conn, target_room_id)\n"
             "            if room_server_id and results:\n",
             "                    room_server_id = await cls._get_room_server_id(conn, target_room_id)\n"
             "            # MUTANT-B: ออกใบเสร็จหลัง commit (เงินถูก commit ไปแล้ว)\n"
             "            if req.issue_receipts and results:\n"
             "                async with pool.acquire() as mconn:\n"
             "                    new_ids = []\n"
             "                    for r in results:\n"
             "                        out = await ReceiptsMixin._issue_one(\n"
             "                            mconn, target_room_id, r[\"payment_id\"], DOC_TYPE_RECEIPT,\n"
             "                            r[\"trans_id\"], user_id, req.user_name or \"—\", None,\n"
             "                        )\n"
             "                        issued.append(out[\"receipt\"])\n"
             "                        if out[\"reused\"]:\n"
             "                            reused += 1\n"
             "                        else:\n"
             "                            new_ids.append(out[\"receipt\"][\"id\"])\n"
             "                    batch_id = await cls._attach_issuance_batch(\n"
             "                        mconn, room_id=target_room_id, issued=issued, new_ids=new_ids,\n"
             "                        source=BATCH_SOURCE_AUTO, user_id=user_id,\n"
             "                        user_name=req.user_name or \"—\",\n"
             "                    )\n"
             "            if room_server_id and results:\n"),
        ],
        [T_OVERFLOW, T_FAULT],
    ),
    (
        "M3 ถอดด่านล่วงหน้าของเลขเอกสาร (`_assert_receipt_seq_budget`)",
        "catch",
        [(COL,
          "                    if req.issue_receipts:\n"
          "                        await cls._assert_receipt_seq_budget(\n"
          "                            conn, target_room_id, DOC_TYPE_RECEIPT, len(items),\n"
          "                        )\n",
          "                    pass  # MUTANT: ถอดด่านล่วงหน้า\n")],
        [T_PRECHECK],
    ),
    (
        "M4 ตัดข้อความ `· ออกใบเสร็จ N ใบ` ออกจาก message",
        "catch",
        [(COL,
          "            issued_count = len(issued) - reused\n"
          "            receipt_note = (\n"
          '                f" · ออกใบเสร็จ {issued_count} ใบ"\n'
          '                + (f" (มีอยู่แล้ว {reused} ใบ)" if reused else "")\n'
          '                if issued else ""\n'
          "            )\n",
          "            issued_count = len(issued) - reused\n"
          '            receipt_note = ""  # MUTANT: ตัดข้อความจำนวนใบเสร็จทิ้ง\n')],
        [T_ONE_BILL],
    ),
    (
        "M5 ปล่อย `trans_id` เป็น None (แผนเตือนไว้ว่าห้าม)",
        "equiv",
        [(COL,
          '                                r["trans_id"], user_id, req.user_name or "—", None,\n',
          '                                None, user_id, req.user_name or "—", None,  # MUTANT\n')],
        [T_ONE_BILL],
    ),
]


MARKER = "MUTANT"

# 🔴 `finally` **ไม่รัน** เมื่อถูก SIGTERM (TaskStop / kill) ⇒ mutant ค้างในไฟล์จริง
#    และที่ร้ายกว่านั้น: รอบถัดไปจะอ่านไฟล์ที่ค้างเป็น "pristine" ⇒ md5 self-check
#    **ผ่านทั้งที่ baseline เสีย** (เจอของจริงมาแล้วกับ M5) ⇒ จับสัญญาณแล้ว raise
#    SystemExit เพื่อให้ finally ได้คืนไฟล์ — และมีด่าน pre-flight กัน baseline เสียอีกชั้น
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    🔴 **แยก "เทสต์ล้ม" ออกจาก "container/collection พัง" ให้ออก** — ถ้ารวมเป็น boolean
       เดียว การที่ docker ดึง image ไม่ได้ / pytest ไม่เก็บเทสต์เลย (exit 5) จะถูกอ่านเป็น
       "mutant ถูกจับ" ซึ่งเป็น **ผลบวกลวงที่อันตรายที่สุดของ harness แบบนี้**
       (พิสูจน์แล้วว่าจับได้จริง: M5 ในรอบแรกรายงาน CATCH ทั้งที่รันเทสต์เดี่ยว ๆ ผ่าน)

    📌 pytest exit code: 0 = ผ่านหมด · 1 = มีเทสต์ล้ม · 2 = ถูกขัดจังหวะ · 3 = internal
       error · 4 = ใช้ flag ผิด · 5 = ไม่เก็บเทสต์เลย ⇒ รับเฉพาะ 1 เป็น "ล้มจริง"
       ส่วน docker เองล้มก็ได้ 125/126/127 → ตกไปเป็น infra ทั้งหมด

    🔴 **ด่านที่สอง (สำคัญพอกัน): exit code ต้องมาจาก pytest เอง ไม่ใช่จาก `tail`** — ดูหมายเหตุ
       ที่ `COMPOSE` ⇒ ถ้าคำสั่งลงท้ายด้วย pipe เมื่อไร `returncode` จะเป็น 0 ตลอดกาล และ
       harness จะรายงาน "รอด (ไม่มีเทสต์จับ)" **ทุกตัว** ซึ่งอ่านเหมือน "เทสต์อ่อน" ทั้งที่
       ความจริงคือ "harness ตาบอด" — คนละเรื่องกันโดยสิ้นเชิง
    """
    cmd = COMPOSE[:-1] + [COMPOSE[-1].format(targets=" ".join(f"/app/{t}" for t in targets))]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=2400)
    out = (proc.stdout or "") + (proc.stderr or "")
    # เก็บ 30 บรรทัดท้าย — พอเห็นทั้ง `FAILED ...` และ assertion ที่ล้ม ไม่ใช่แค่สรุปบรรทัดเดียว
    tail = "\n".join(out.strip().splitlines()[-30:])
    if not PYTEST_SUMMARY_RE.search(out):
        # ไม่มีบรรทัดสรุปของ pytest ⇒ **ไม่รู้ว่าเกิดอะไรขึ้น** ⇒ ห้ามเดา ห้ามนับเป็น "จับได้"
        return "infra", f"exit={proc.returncode} · ไม่พบบรรทัดสรุปของ pytest\n{tail}"
    if proc.returncode == 0:
        return "pass", tail
    if proc.returncode == 1:
        return "fail", tail
    return "infra", f"exit={proc.returncode}\n{tail}"


def main() -> int:
    touched = sorted({rel for _, _, edits, _ in MUTATIONS for rel, _, _ in edits})

    # 🛡️ ด่าน pre-flight: ต้องแน่ใจว่าไฟล์ตั้งต้น "สะอาด" ก่อนอ่านเป็น pristine
    #    ถ้ามี mutant ค้างจากรอบที่ถูกฆ่า ไฟล์นั้นจะกลายเป็น baseline ใหม่เงียบ ๆ
    #    ⇒ md5 self-check ตอนจบจะ "ผ่าน" ทั้งที่โค้ดจริงเสียหาย
    dirty = [rel for rel in touched if MARKER in (BACKEND / rel).read_text(encoding="utf-8")]
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>` หรือคัดลอกจากสำเนาสำรอง) แล้วรันใหม่")
        return 2

    # 📌 สำเนาตั้งต้นในหน่วยความจำ — ใช้ทั้ง "สร้าง mutant" และ "คืนสภาพ" ⇒ อ่านครั้งเดียว
    pristine = {rel: (BACKEND / rel).read_text(encoding="utf-8") for rel in touched}
    before = {rel: md5(BACKEND / rel) for rel in touched}

    only = {a.upper() for a in sys.argv[1:]}
    selected = [m for m in MUTATIONS if not only or m[0].split()[0].upper() in only]
    if only:
        print(f"🎯 เลือกรันเฉพาะ: {', '.join(sorted(only))} ({len(selected)} mutation)\n", flush=True)

    results = []
    for name, expect, edits, targets in selected:
        files = sorted({rel for rel, _, _ in edits})
        stale = None
        for rel, old, _new in edits:
            text = pristine[rel]
            if old not in text:
                stale = f"ไม่พบข้อความเป้าหมายใน {rel} — ตกยุค ต้องอัปเดตสคริปต์"
                break
            if text.count(old) != 1:
                stale = f"ข้อความเป้าหมายใน {rel} ซ้ำ {text.count(old)} ที่"
                break
        if stale:
            results.append((name, "STALE"))
            print(f"⚠️  {name}: STALE — {stale}", flush=True)
            continue

        caught, tail = False, ""
        try:
            for rel in files:
                mutated = pristine[rel]
                for r, old, new in edits:
                    if r == rel:
                        mutated = mutated.replace(old, new)
                (BACKEND / rel).write_text(mutated, encoding="utf-8")

            state, tail = run_pytest(targets)
            if state == "pass":
                # ถอยไปรันทั้งไฟล์ — mutation อาจถูกจับโดยเทสต์ตัวอื่น
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                state, tail = run_pytest([HTTP])
                verdict = ("จับโดยเทสต์อื่นในไฟล์ ✅" if state == "fail"
                           else "รอด (ไม่มีเทสต์จับ)")
            else:
                verdict = "จับโดยเทสต์ที่เล็ง ✅"
            caught = state == "fail"
            infra = state == "infra"
        finally:
            for rel in files:
                (BACKEND / rel).write_text(pristine[rel], encoding="utf-8")

        if infra:
            status, icon = "INFRA", "🛑"
        elif caught:
            status, icon = "CATCH", "✅"
        else:
            status, icon = ("EQUIV", "🟡") if expect == "equiv" else ("SURVIVE", "❌")
        results.append((name, status, tail if status in ("INFRA", "SURVIVE") else ""))
        print(f"{icon} {name}: {verdict}", flush=True)

    print("\n" + "═" * 78)
    for name, status, _ in results:
        print(f"{status:<10} {name}")
    print("═" * 78)
    n_catch = sum(1 for _, s, _ in results if s == "CATCH")
    n_equiv = sum(1 for _, s, _ in results if s == "EQUIV")
    n_surv = sum(1 for _, s, _ in results if s == "SURVIVE")
    n_infra = sum(1 for _, s, _ in results if s == "INFRA")
    print(f"จับได้ {n_catch}/{len(results)} | equivalent (รอดตามคาด) {n_equiv}"
          f" | รอดผิดคาด {n_surv} | infra พัง {n_infra}")
    for name, status, tail in results:
        if status in ("INFRA", "SURVIVE"):
            print(f"\n── {name} [{status}] ──\n{tail}")

    print("\n── ตรวจความสมบูรณ์ของไฟล์ ──")
    ok = True
    for rel in touched:
        same = md5(BACKEND / rel) == before[rel]
        ok &= same
        print(f"{'✅' if same else '❌'} {rel} {'คืนสภาพเดิม' if same else 'md5 เปลี่ยน!'}")
    print("✅ ไฟล์ทั้งหมดกลับสภาพเดิม" if ok else "❌ มีไฟล์ไม่กลับสภาพ — ตรวจด้วย git diff ทันที")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
