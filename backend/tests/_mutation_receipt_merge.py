#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับงาน F6/PR-4 (ยุบใบเสร็จเป็นหน้าเดียว)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
การยุบเป็น **การจัดกลุ่มตอนเรนเดอร์** ล้วน ๆ — ไม่มีสกีมาใหม่ ไม่มี index ใหม่
⇒ ถ้า `_merge_key` หลุดเงื่อนไขใดไป จะ **ไม่มี error ใด ๆ** โผล่ขึ้นมา มีแต่กระดาษ
ที่ผิด (ใบเสร็จของเด็กสองคนรวมกัน / ใบที่ยกเลิกแล้วอ่านเหมือนใบปกติ / ยอดรวมไม่ตรง)
สคริปต์นี้จึง **ทำลายโค้ดจริง** ทีละจุด แล้วดูว่าเทสต์ล้มจริงไหม:

  • mutation ถูกจับ (เทสต์ล้ม)  = เทสต์มีฟัน ✅
  • mutation รอด (เทสต์เขียว)   = เทสต์หลอกตัวเอง ❌  ← ต้องแก้เทสต์

⚠️ mutation ที่ "รอด" อาจเป็น **equivalent mutant** (เปลี่ยนโค้ดแต่พฤติกรรมเท่ากัน)
   ⇒ ก่อนแก้เทสต์ให้ถอยไปตรวจ invariant ก่อนเสมอ (ดู `docs/skills.md`)

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

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** (`1 failed in 5.05s` / `130 passed`)
#    = หลักฐานว่า "เทสต์รันจริง" · ไม่มีบรรทัดนี้ = infra พัง ไม่ว่า exit code จะเป็นอะไร
#    ⚠️ จงใจ **ไม่** รับ `N error` — collection error ไม่ใช่ "เทสต์ล้ม"
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

# 🔴 **ห้ามต่อ `| tail` ในคำสั่งนี้เด็ดขาด** — `sh` เป็น dash ⇒ exit code ของ pipeline
#    คือของ **ตัวสุดท้าย** ⇒ `proc.returncode` เป็น 0 เสมอ ⇒ harness รายงาน CATCH
#    ให้ mutant ทุกตัวโดยไม่มีเทสต์จับอะไรเลย (ดูบทเรียนเต็มใน `docs/skills.md`)
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

MERGE = "tests/test_finance_receipt_merge.py"
RECEIPTS = "services/finance/receipts.py"
# 🔴 PR-5 แตก `receipt.html` เป็น shell (`<style>` + `.doc` frame + `{% include %}`)
#    แล้วย้ายเนื้อในทั้งดุ้นไป partial นี้ **โดยไม่เปลี่ยน indent** ⇒ anchor ทุกตัวของ
#    ไฟล์นี้ (`is_merged` · `doc_no_text` · footer) ยังตรงเป๊ะ แต่ **path เก่าไม่เหลือ
#    ข้อความเหล่านั้นอยู่เลย** ⇒ harness จะขึ้น STALE ทุกตัว = mutation ไม่ถูกทดสอบ
TEMPLATE = "templates/finance/_receipt_body.html"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 1 — คีย์การยุบ: 4 เงื่อนไขที่กัน "ยุบผิดคน / ยุบผิดสถานะ"
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M1 🔑 ถอดด่าน `student_id IS NULL` (ใบของทุกคนที่ถูกลบจะยุบรวมกัน)",
        RECEIPTS,
        '        if d.get("student_id") is None:\n            return None\n',
        '        if False:  # MUTANT: ถอดด่าน student_id\n            return None\n',
        [f"{MERGE}::test_merge_never_groups_null_student_id"],
    ),
    (
        "M2 🔑 ถอด `status` ออกจากคีย์ (ใบที่ยกเลิกถูกกลืนเข้ากับใบที่ยังใช้ได้)",
        RECEIPTS,
        '        return (d["student_id"], d["doc_type"], d.get("status"))\n',
        '        return (d["student_id"], d["doc_type"])  # MUTANT: ถอด status\n',
        [f"{MERGE}::test_merge_never_mixes_voided_with_active"],
    ),
    (
        "M3 🔑 ใส่ `event_at` เข้าไปในคีย์ (กลับไปหน้าละวัน = ทิ้งสิ่งที่ผู้ใช้เลือก)",
        RECEIPTS,
        '        return (d["student_id"], d["doc_type"], d.get("status"))\n',
        '        return (d["student_id"], d["doc_type"], d.get("status"),\n'
        '                d.get("event_at"))  # MUTANT: ยุบเฉพาะวันเดียวกัน\n',
        [f"{MERGE}::test_merge_spans_different_dates_and_prints_a_range"],
    ),
    (
        "M4 🔴 ยุบตาม `issued_to_name` แทน `student_id` (เด็กสองคนชื่อซ้ำ = ใบปนกัน)",
        RECEIPTS,
        '        if d.get("student_id") is None:\n'
        '            return None\n'
        '        return (d["student_id"], d["doc_type"], d.get("status"))\n',
        '        if not d.get("issued_to_name"):  # MUTANT: ยุบตามชื่อ\n'
        '            return None\n'
        '        return (d["issued_to_name"], d["doc_type"], d.get("status"))\n',
        [f"{MERGE}::test_merge_never_crosses_students"],
    ),
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 2 — ยอดรวม/เพดาน/ลำดับ
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M5 🔴 ยอดรวมของกลุ่ม = ยอดของใบแรก (ตัวเลขบนกระดาษไม่ตรงกับตาราง)",
        RECEIPTS,
        '        total = round(sum(m["amount"] for m in members), 2)\n',
        '        total = round(float(members[0]["amount"]), 2)  # MUTANT: ยอดใบแรก\n',
        [f"{MERGE}::test_merged_page_prints_the_grand_total_in_thai_words"],
    ),
    (
        "M6 เพดานสมาชิก `>` → `>=` (กลุ่มขนาด 12 ไม่ยุบทั้งที่ควรยุบ)",
        RECEIPTS,
        "            elif len(payload) > _MAX_MERGED_MEMBERS:",
        "            elif len(payload) >= _MAX_MERGED_MEMBERS:  # MUTANT",
        [f"{MERGE}::test_group_exactly_at_cap_still_merges"],
    ),
    (
        "M7 🔴 กลุ่มขนาด 1 ตกไปที่ `_merged_context` (ใบเดี่ยวได้หัวใบ 'รวม 1 ฉบับ')",
        RECEIPTS,
        "            elif len(payload) == 1:\n"
        "                # 🔑 กลุ่มขนาด 1 = เอกสารเดี่ยว ⇒ **ต้องได้ context เหมือนเดิมทุกไบต์**\n"
        "                #    ไม่งั้น \"โหลดทีละใบ\" กับ \"โหลดรวม\" จะได้กระดาษคนละแบบโดยไม่มีใครรู้\n"
        "                contexts.append(cls._document_context(payload[0]))\n",
        "            elif False:  # MUTANT: ใบเดี่ยวกลายเป็นกลุ่ม\n"
        "                contexts.append(cls._document_context(payload[0]))\n",
        [f"{MERGE}::test_group_of_one_is_byte_identical_to_single_document"],
    ),
    (
        "M8 🔴 ยุบ `invoice` ด้วย (snapshot สองช่วงถูกบวกกัน = ยอดค้างที่ไม่มีอยู่จริง)",
        RECEIPTS,
        "_MERGEABLE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT)",
        "_MERGEABLE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT, DOC_TYPE_INVOICE)  # MUTANT",
        [f"{MERGE}::test_invoice_documents_are_never_merged"],
    ),
    (
        "M9 เรียงหน้าตามเลขที่แทนลำดับที่ผู้ใช้ติ๊ก",
        RECEIPTS,
        "        contexts = []\n        for kind, payload in order:\n",
        "        contexts = []\n"
        "        order = sorted(order, key=lambda kv: (  # MUTANT: เรียงตามเลขที่\n"
        "            kv[1][0][\"receipt_no\"] if kv[0] == \"group\" else kv[1][\"receipt_no\"]))\n"
        "        for kind, payload in order:\n",
        [f"{MERGE}::test_grouping_preserves_the_order_the_user_selected"],
    ),
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 3 — วันที่: กับดัก timezone ที่รีโปนี้เจ็บมาหลายรอบ
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M10 🗓️ ตัดวันที่รายบรรทัดจาก UTC ตรง ๆ (วันเพี้ยนสำหรับรายการหลัง 17:00 UTC)",
        RECEIPTS,
        "        return cls._thai_date_text(aware_dt.astimezone(THAI_TZ).date())\n",
        "        return cls._thai_date_text(aware_dt.date())  # MUTANT: ไม่แปลงเป็นเวลาไทย\n",
        [f"{MERGE}::test_row_date_is_thai_local_not_utc"],
    ),
    (
        "M11 🗓️ พิมพ์ช่วงวันที่เสมอ แม้วันเดียวกันทั้งกลุ่ม",
        RECEIPTS,
        "        elif len(set(days)) == 1:\n            span = days[0]\n",
        "        elif False:  # MUTANT: ไม่ยุบช่วงวันที่เดียว\n            span = days[0]\n",
        [f"{MERGE}::test_merge_same_day_prints_a_single_date_not_a_range"],
    ),
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 4 — เทมเพลต: กับดัก `format(None)` = 500 ไม่ใช่ตัวเลขเพี้ยน
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M12 🔴 ถอดด่านใบที่ถูกยุบรอบบล็อกสรุป (format(None) = 500)",
        TEMPLATE,
        "  {%- if not d.is_merged -%}  {# 🔴 **บังคับ ไม่ใช่ความสวย**: บล็อกนี้พิมพ์",
        "  {%- if True -%}  {# MUTANT: ถอดด่านใบที่ถูกยุบ · บล็อกนี้พิมพ์",
        [f"{MERGE}::test_merged_page_renders_without_a_paid_total_row"],
    ),
    (
        "M13 หัวใบพิมพ์ `receipt_no` ตรง ๆ (ใบที่ถูกยุบได้หัวใบว่าง)",
        TEMPLATE,
        '      <div class="label">เลขที่ {{ d.doc_no_text or d.receipt_no }}</div>\n',
        '      <div class="label">เลขที่ {{ d.receipt_no }}</div>  {# MUTANT #}\n',
        [f"{MERGE}::test_merged_page_renders_without_a_paid_total_row"],
    ),
    # ── เพิ่มรอบสอง (หลังรันรอบแรกแล้วพบว่า M13 รอด — assertion เดิมแคบเกินไป) ──
    (
        "M15 🔴 ท้ายใบพิมพ์ `receipt_no` ตรง ๆ (ท้ายใบของใบที่ถูกยุบเป็น 'เลขที่ None')",
        TEMPLATE,
        "    เอกสารฉบับนี้ออกโดยระบบบริหารจัดการห้องเรียน — เลขที่ "
        "{{ d.doc_no_text or d.receipt_no }}\n",
        "    เอกสารฉบับนี้ออกโดยระบบบริหารจัดการห้องเรียน — เลขที่ "
        "{{ d.receipt_no }}  {# MUTANT #}\n",
        [f"{MERGE}::test_merged_page_renders_without_a_paid_total_row"],
    ),
    (
        "M16 🔴 แถว 'รวมเอกสาร' ในตาราง meta ขึ้นทุกใบ (ใบเดี่ยวอ่านเหมือนใบที่ยุบ)",
        TEMPLATE,
        "      <td class=\"k\">{% if d.is_merged %}รวมเอกสาร{% elif d.doc_type == 'deposit' %}ประเภท",
        "      <td class=\"k\">{% if True %}รวมเอกสาร  {# MUTANT #}"
        "{% elif d.doc_type == 'deposit' %}ประเภท",
        [f"{MERGE}::test_unmerged_page_shows_no_trace_of_the_merge_feature"],
    ),
    (
        "M17 🔴 กลับด้านเงื่อนไขของตาราง (ใบที่ยุบได้ตารางใบเดียว)",
        TEMPLATE,
        "  {%- if d.is_merged %}  {# ══",
        "  {%- if not d.is_merged %}  {# MUTANT: กลับด้าน ══",
        [f"{MERGE}::test_merged_page_renders_without_a_paid_total_row"],
    ),
    (
        "M14 🔴 ตัดสาย: `_render_documents_pdf` กลับไปเรียก context ต่อใบ (ปิดการยุบทั้งงาน)",
        RECEIPTS,
        "            html = render_receipts_html(cls._document_contexts(docs))\n",
        "            html = render_receipts_html(\n"
        "                [cls._document_context(d) for d in docs])  # MUTANT: ปิดการยุบ\n",
        [f"{MERGE}::test_combined_pdf_route_merges_three_receipts_of_one_student"],
    ),
]


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    🔴 **แยก "เทสต์ล้ม" ออกจาก "container/collection พัง" ให้ออก** — ถ้ารวมเป็น boolean
       เดียว การที่ docker ดึง image ไม่ได้ / pytest ไม่เก็บเทสต์เลย (exit 5) จะถูกอ่านเป็น
       "mutant ถูกจับ" ซึ่งเป็นผลบวกลวงที่อันตรายที่สุดของ harness แบบนี้
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

# 🔴 `finally` **ไม่รัน** เมื่อถูก SIGTERM (TaskStop / kill) ⇒ mutant ค้างในไฟล์จริง
#    และรอบถัดไปจะอ่านไฟล์ที่ค้างเป็น "original" ⇒ ไม่มีอะไรฟ้องว่า baseline เสีย
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def main() -> int:
    results = []
    # 🛡️ ด่าน pre-flight: ห้ามเริ่มถ้ามี mutant ค้างจากรอบที่ถูกฆ่า
    dirty = sorted({
        rel for _, rel, _, _, _ in MUTATIONS
        if MARKER in (BACKEND / rel).read_text(encoding="utf-8")
    })
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

    only = {a.upper() for a in sys.argv[1:]}
    selected = [m for m in MUTATIONS if not only or m[0].split()[0].upper() in only]
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
                state, tail = run_pytest([MERGE])
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
    return 1 if n_infra else 0


if __name__ == "__main__":
    sys.exit(main())
