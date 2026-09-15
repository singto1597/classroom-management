#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับ F5/PR-3 (System PDF route ของบอท + แนบไฟล์เข้า Discord)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
เทสต์ที่ "เขียว" ไม่ได้แปลว่ามีฟัน — มันอาจเขียวเพราะไม่เคยแตะโค้ดที่มันอ้างว่าคุม
สคริปต์นี้จึง **ทำลายโค้ดจริง** ทีละจุด แล้วดูว่าเทสต์ล้มจริงไหม:

  • mutation ถูกจับ (เทสต์ล้ม)  = เทสต์มีฟัน ✅
  • mutation รอด (เทสต์เขียว)   = เทสต์หลอกตัวเอง ❌  ← ต้องแก้เทสต์

⚠️ mutant ในตารางนี้ **ทุกตัวคือช่องโหว่/บั๊กจริงที่สามารถเกิดขึ้นได้** ไม่มีตัวไหน
   เป็นการ "พลิก boolean ให้ดูตลก" — M1/M2 คือการเปิด/ปิดประตูหลัง · M3 คือด่านสมาชิก
   ที่ service · M4 คือด่านกันอ่านเอกสารข้ามห้อง · M7 คือ hole ที่ **เทสต์พฤติกรรม
   มองไม่เห็น** (เทสต์ที่ยิง HTTP ไม่มีทางรู้ว่า router แอบเขียน DB ในเส้นทางที่ไม่ถูกเรียก)

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433
   ร่วมกัน ⇒ สอง container พร้อมกันจะชนกัน · **ต้องรันจาก host** (สคริปต์เรียก
   `docker compose` เอง ไม่ได้รันใน container)

⚠️ สคริปต์นี้ **คืนไฟล์เสมอ** (finally) และตรวจ md5 เทียบสำเนาตั้งต้นตอนจบ

รัน:
    python3 backend/tests/_mutation_system_pdf.py            # ทั้งหมด
    python3 backend/tests/_mutation_system_pdf.py M1 M4      # เฉพาะบางตัว
"""
import hashlib
import re
import signal
import subprocess
import sys
from pathlib import Path

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** (`1 failed in 5.05s` / `18 passed in 49s`)
#    ใช้เป็น "หลักฐานว่าเทสต์รันจริง" — ถ้าไม่มีบรรทัดนี้ สถานะเป็น infra ทันที
#    ไม่ว่า exit code จะเป็นอะไร ⇒ กันทั้ง "container พังแล้ว exit 1" และ "ไม่มีเทสต์ถูกรัน"
#    ⚠️ จงใจ **ไม่** รับ `N error` — collection error ไม่ใช่ "เทสต์ล้ม"
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# 🔴 **ห้ามต่อ `| tail` ในคำสั่งนี้เด็ดขาด** — `sh` เป็น dash ⇒ exit code ของ pipeline
#    คือของ `tail` (ตัวสุดท้าย) **ไม่ใช่ของ pytest** ⇒ `returncode` เป็น 0 เสมอ
#    ⇒ ทุก mutant ถูกอ่านเป็น "เทสต์ผ่าน" ทั้งที่เทสต์ล้ม (บทเรียนจาก PR-2)
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

TESTS = "tests/test_finance_system_pdf.py"
ROUTER = "routers/finance/system.py"
RECEIPTS = "services/finance/receipts.py"

# 🎯 node id แบบเจาะจง — รันตัวเดียวเร็วกว่ารันทั้งไฟล์มาก (ไฟล์ละ ~50 วิ)
T_ALLOW = f"{TESTS}::test_system_pdf_serves_pdf_to_unregistered_bot_principal"
T_WEB = f"{TESTS}::test_system_pdf_rejects_web_jwt_of_non_member"
T_CROSS = f"{TESTS}::test_system_pdf_404_when_receipt_belongs_to_another_room"
T_DEDUPE = f"{TESTS}::test_system_pdf_dedupes_repeated_receipt_numbers"
T_AUDIT = f"{TESTS}::test_system_pdf_audit_records_the_bot_actor"
T_NODB = f"{TESTS}::test_system_pdf_router_contains_no_database_access"
T_ONEDOOR = f"{TESTS}::test_the_membership_bypass_lives_in_exactly_one_place"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (id+ชื่อ, expect, [(ไฟล์, ข้อความเดิม, ข้อความใหม่), ...], เทสต์ที่ควรจับ)
#   • `expect`: "catch" = ต้องล้ม / "equiv" = รอดโดยชอบธรรม (ต้องมีเหตุผลกำกับ)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    (
        "M1 ⭐ ตัด ternary `is_bot_system` — บอทระบบถูกส่งไปทางที่ต้องเป็นสมาชิก",
        "catch",
        [(ROUTER,
          "        if is_bot_system:\n",
          "        if False:  # MUTANT: ปิดสาขาของบอทระบบ\n")],
        [T_ALLOW],
    ),
    (
        "M2 ⭐ เปิดสาขาระบบให้ทุกคน (`if is_bot_system:` → `if True:`) = ประตูหลังทั้งบาน",
        "catch",
        [(ROUTER,
          "        if is_bot_system:\n",
          "        if True:  # MUTANT: ทุกคนได้สิทธิ์ระบบ\n")],
        [T_WEB],
    ),
    (
        "M3 ถอดด่านสมาชิกที่ service (`if enforce_membership:`)",
        "catch",
        [(RECEIPTS,
          "                if enforce_membership:\n"
          "                    await require_member(conn, target_room_id, user_id)\n",
          "                pass  # MUTANT: ถอดด่านสมาชิก\n")],
        [T_WEB],
    ),
    (
        "M4 ⭐ ตัดตัวกรองห้องใน SQL — เลขของห้องอื่นจะถูกพิมพ์ให้ (อ่านข้ามห้อง)",
        "catch",
        [(RECEIPTS,
          "                    WHERE R.room_id = $1 AND R.receipt_no = ANY($2::text[])\n",
          "                    WHERE R.room_id = R.room_id AND R.receipt_no = ANY($2::text[])\n"
          "                      AND $1 = $1  -- MUTANT: ไม่กรองห้อง\n")],
        [T_CROSS],
    ),
    (
        "M5 ตัด dedupe เลขซ้ำ (ใบเดียวจะกลายเป็นหลายหน้า)",
        "catch",
        [(RECEIPTS,
          "        wanted = list(dict.fromkeys(receipt_nos or []))\n",
          "        wanted = list(receipt_nos or [])  # MUTANT: ไม่ dedupe\n")],
        [T_DEDUPE],
    ),
    (
        "M6 ส่ง `user_ctx` เข้า `get_audit_context` ⇒ audit บันทึก `user_id:None`",
        "catch",
        [(ROUTER,
          "    client_source, actor = get_audit_context(request, None if is_bot_system else user_ctx)\n",
          "    client_source, actor = get_audit_context(request, user_ctx)  # MUTANT\n")],
        [T_AUDIT],
    ),
    (
        "M7 ⭐ ให้ router เขียน DB เอง — hole ที่เทสต์พฤติกรรม (HTTP) มองไม่เห็น",
        "catch",
        [(ROUTER,
          '    is_bot_system = user_ctx.get("is_bot_system") is True\n',
          '    is_bot_system = user_ctx.get("is_bot_system") is True\n'
          "    # MUTANT: router แตะ DB เอง (ไม่มีเทสต์ที่ยิง HTTP จับได้)\n"
          "    async with pool.acquire() as _mconn:\n"
          '        await _mconn.execute("UPDATE finance_receipts SET note = note WHERE room_id = $1", 0)\n')],
        [T_NODB],
    ),
    (
        "M8 ⭐ พลิกธงปิดด่าน (`enforce_membership=False` → `True`) = บอทระบบกลายเป็นต้องเป็นสมาชิก",
        "catch",
        [(RECEIPTS,
          "            enforce_membership=False,\n",
          "            enforce_membership=True,  # MUTANT: ปิดประตูของบอทระบบ\n")],
        [T_ONEDOOR, T_ALLOW],
    ),
]


MARKER = "MUTANT"

# 🔴 `finally` **ไม่รัน** เมื่อถูก SIGTERM (TaskStop / kill) ⇒ mutant ค้างในไฟล์จริง
#    และรอบถัดไปจะอ่านไฟล์ที่ค้างเป็น "pristine" ⇒ md5 self-check ผ่านทั้งที่ baseline เสีย
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    🔴 แยก "เทสต์ล้ม" ออกจาก "container/collection พัง" ให้ออก — ถ้ารวมเป็น boolean
       เดียว การที่ docker ดึง image ไม่ได้ / pytest ไม่เก็บเทสต์เลย (exit 5) จะถูกอ่านเป็น
       "mutant ถูกจับ" ซึ่งเป็น **ผลบวกลวงที่อันตรายที่สุดของ harness แบบนี้**
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


def main() -> int:
    touched = sorted({rel for _, _, edits, _ in MUTATIONS for rel, _, _ in edits})

    # 🛡️ ด่าน pre-flight: ไฟล์ตั้งต้นต้อง "สะอาด" ก่อนถูกอ่านเป็น pristine
    dirty = [rel for rel in touched if MARKER in (BACKEND / rel).read_text(encoding="utf-8")]
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

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
            results.append((name, "STALE", ""))
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
                state, tail = run_pytest([TESTS])
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
    n_stale = sum(1 for _, s, _ in results if s == "STALE")
    print(f"จับได้ {n_catch}/{len(results)} | equivalent {n_equiv} | รอดผิดคาด {n_surv}"
          f" | infra พัง {n_infra} | ตกยุค {n_stale}")
    for name, status, tail in results:
        if status in ("INFRA", "SURVIVE", "STALE"):
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
