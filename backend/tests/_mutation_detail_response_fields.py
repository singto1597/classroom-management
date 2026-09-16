#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับบั๊ก "กดดูเอกสารในมือถือแล้วได้หน้าขาว" (2026-09)

═══════════════════════════════════════════════════════════════════════════════
🎯 บั๊กที่ harness นี้เฝ้า
═══════════════════════════════════════════════════════════════════════════════
`ReceiptDetailResponse` ไม่ได้ประกาศฟิลด์ของใบสำคัญ (ทั้ง 9 ตัว) ⇒
`response_model=` ซึ่งเป็น **ตัวกรองขาออก** ตัด `budgets` ทิ้งเงียบ ๆ ⇒ ฝั่งหน้าจอ
`detail.budgets` เป็น `undefined` ⇒ `ReceiptDetail.vue` เข้าถึง `.length` **throw ตอน render**
⇒ Vue ทิ้ง subtree ทั้งหน้า เหลือแต่ skeleton "กำลังโหลดข้อมูล" ค้างบนพื้นขาว
**โดยไม่มี error ฝั่งเซิร์ฟเวอร์เลย** และเทสต์ทุกตัวยังเขียว

🔎 ทำไมเทสต์เดิม 1,100+ บรรทัดจับไม่ได้: เทสต์ใบสำคัญทุกตัววิ่งผ่านเส้นทาง **PDF**
   (`GET /{no}/pdf`) ซึ่ง **ไม่ประกาศ `response_model`** (คืน binary stream)
   ⇒ ไม่มีเทสต์ใดแตะเส้นทาง JSON ที่หน้าจอเรียกจริง

🧬 mutation ที่ต้อง **ถูกจับ** (ไม่ใช่แค่ "รันแล้วเขียว"):
   M1–M5  ฟิลด์ของใบสำคัญหายจาก `VoucherFields`/`VoucherBudget` (จอขาวกลับมา)
   M6–M7  `room_name` หายจาก router/model ของ `POST /join` (ชื่อห้องหายทั้งระบบ เงียบ ๆ)
   M8     `account_kind` ถูกจำกัดค่า ⇒ ค่าที่ไม่รู้จักกลายเป็น 500 ทั้งหน้า
   M9–M10 ใบสำคัญ **ในชุดเอกสาร** สูญเสียฟิลด์ของตัวเอง (SELECT ตกหล่น / model แคบเกิน)

🔧 **วิธีรัน: จาก host** (ไม่ใช่ในคอนเทนเนอร์ — ไม่มี docker CLI ข้างใน)
       python3 backend/tests/_mutation_detail_response_fields.py          # ทั้งหมด
       python3 backend/tests/_mutation_detail_response_fields.py M1 M9    # เฉพาะบางตัว

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433 ร่วมกัน
   ⇒ สอง container พร้อมกันจะชนกัน
⚠️ container mount `./backend` **สด** ⇒ ห้ามแก้ไฟล์ backend ขณะ pytest กำลังวิ่ง
   (สคริปต์นี้แก้ → รัน → คืนไฟล์ ในลูปเดียว จึงปลอดภัยโดยโครงสร้าง)
"""
import re
import signal
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# 🔴 บรรทัดสรุปที่ **pytest ผลิตเองเท่านั้น** — ใช้เป็นหลักฐานว่า "เทสต์รันจริง"
#    ไม่มีบรรทัดนี้ = infra พัง ไม่ว่า exit code จะเป็นอะไร
#    ⚠️ จงใจ **ไม่** รับ `N error` — collection error ไม่ใช่ "เทสต์ล้ม"
PYTEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")

# 🔴 **ห้ามต่อ `| tail`** — `sh` เป็น dash ⇒ exit code ของ pipeline คือของตัวสุดท้าย
#    ⇒ `proc.returncode` เป็น 0 เสมอ ⇒ harness รายงาน CATCH ให้ทุก mutant
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

DOCS = "tests/test_finance_transaction_documents.py"
ROOM = "tests/test_room.py"
BATCH = "tests/test_finance_receipt_batches.py"

SCHEMAS = "models/finance_schemas.py"
ROOM_SCHEMAS = "models/room_schemas.py"
ROOM_ROUTER = "routers/room_router.py"
BATCHES = "services/finance/receipt_batches.py"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    # ── 🔴 ตัวต้นเหตุจริง: ฟิลด์ใบสำคัญไม่ถูกประกาศ ⇒ response_model ตัดทิ้ง ──
    (
        "M1 ถอด `VoucherFields` ออกจาก `ReceiptDetailResponse` (บั๊กต้นฉบับเป๊ะ)",
        SCHEMAS,
        "class ReceiptDetailResponse(ReceiptListItem, VoucherFields):",
        "class ReceiptDetailResponse(ReceiptListItem):  # MUTANT",
        [f"{DOCS}::test_voucher_detail_json_carries_every_snapshot_field"],
    ),
    (
        "M2 ถอด `budgets` ออกจาก `VoucherFields` (คีย์ที่ทำให้จอขาว)",
        SCHEMAS,
        "    budgets: List[VoucherBudget] = []",
        "    # MUTANT: ตัด budgets ออก",
        [f"{DOCS}::test_voucher_detail_json_carries_every_snapshot_field"],
    ),
    (
        "M3 ถอด `approver_name` ออกจาก `VoucherFields`",
        SCHEMAS,
        "    approver_name: Optional[str] = None",
        "    # MUTANT: ตัด approver_name ออก",
        [f"{DOCS}::test_voucher_detail_json_carries_every_snapshot_field"],
    ),
    (
        "M4 ถอด `bank_account_no` ออกจาก `VoucherFields`",
        SCHEMAS,
        "    bank_account_no: Optional[str] = None\n"
        "    bank_account_name: Optional[str] = None\n"
        "    category_name: Optional[str] = None",
        "    bank_account_name: Optional[str] = None\n"
        "    category_name: Optional[str] = None\n"
        "    # MUTANT: ตัด bank_account_no ออก",
        [f"{DOCS}::test_voucher_detail_json_carries_every_snapshot_field"],
    ),
    (
        "M5 ถอด `start_date` ออกจาก `VoucherBudget`",
        SCHEMAS,
        "    # 📅 ISO `YYYY-MM-DD` (JSON ไม่มีชนิด DATE) — เหตุผลเดียวกับ "
        "`ReceiptLineItem.due_date`\n    start_date: str",
        "    # MUTANT: ตัด start_date ออก",
        [f"{DOCS}::test_voucher_detail_json_carries_every_snapshot_field"],
    ),
    # ── 🔴 `POST /join` ลืมส่ง `room_name` ⇒ ชื่อห้องหายทั้งระบบ เงียบ ๆ ──────
    (
        "M6 router ไม่ส่งต่อ `room_name` (บั๊กที่เจอจริงตอนสแกน)",
        ROOM_ROUTER,
        '            room_name=result.get("room_name"),\n',
        "",
        [f"{ROOM}::test_join_http_response_carries_the_room_name"],
    ),
    (
        "M7 ถอด `room_name` ออกจาก `JoinRoomResponse`",
        ROOM_SCHEMAS,
        "    room_name: Optional[str] = None\n",
        "",
        [f"{ROOM}::test_join_http_response_carries_the_room_name"],
    ),
    # ── 🧨 การจำกัดค่าที่ "ไม่รู้จัก" ให้กลายเป็น 500 ────────────────────────
    (
        "M8 จำกัด `account_kind` ด้วย pattern ⇒ ค่าใหม่กลายเป็น 500 ทั้งหน้า",
        SCHEMAS,
        "    account_kind: Optional[str] = None",
        '    account_kind: Optional[str] = Field(None, pattern="^(cash|transfer)$")  # MUTANT',
        [f"{DOCS}::test_voucher_detail_json_reports_an_unknown_account_kind_verbatim"],
    ),
    # ── 🔴 ใบสำคัญ **ในชุดเอกสาร** สูญเสียฟิลด์ของตัวเอง ────────────────────
    (
        "M9 ถอด `R.voucher_snapshot` จาก SELECT ของ `receipt-batches/{id}`",
        BATCHES,
        "                rows = await conn.fetch(\n"
        "                    f\"\"\"SELECT {_RECEIPT_COLUMNS}, R.line_items, R.voucher_snapshot,",
        "                rows = await conn.fetch(  # MUTANT: ตัด voucher_snapshot ออก\n"
        "                    f\"\"\"SELECT {_RECEIPT_COLUMNS}, R.line_items,",
        [f"{BATCH}::test_batch_detail_carries_the_voucher_fields_of_its_members"],
    ),
    (
        "M10 แคบ `receipts` ของ `ReceiptBatchDetailResponse` เป็น `ReceiptListItem`",
        SCHEMAS,
        "    receipts: List[ReceiptDetailResponse]",
        "    receipts: List[ReceiptListItem]  # MUTANT",
        [f"{BATCH}::test_batch_detail_carries_the_voucher_fields_of_its_members"],
    ),
]


def run_pytest(targets: list[str]) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}

    🔴 แยก "เทสต์ล้ม" ออกจาก "container/collection พัง" ให้ออก — ถ้ารวมเป็น boolean
       เดียว การที่ docker ดึง image ไม่ได้ / pytest ไม่เก็บเทสต์เลย (exit 5) จะถูกอ่านเป็น
       "mutant ถูกจับ" ซึ่งเป็นผลบวกลวงที่อันตรายที่สุดของ harness แบบนี้
       📌 pytest exit code: 0 = ผ่านหมด · 1 = มีเทสต์ล้ม · 5 = ไม่เก็บเทสต์เลย
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
#    และรอบถัดไปจะอ่านไฟล์ที่ค้างเป็น "original" เงียบ ๆ ⇒ ต้องจับสัญญาณแล้ว raise
#    SystemExit เพื่อให้ finally ได้คืนไฟล์ + มีด่าน pre-flight กัน baseline เสียอีกชั้น
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
                # ถอยไปรันทั้งไฟล์ — mutation อาจถูกจับโดยเทสต์ตัวอื่น
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                state, tail = run_pytest([DOCS, ROOM, BATCH])
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
    # 🛑 infra = "ไม่รู้ผล" ไม่ใช่ "ผ่าน" ⇒ ต้อง exit ไม่เป็นศูนย์ให้คนเห็น
    return 1 if n_infra else 0


if __name__ == "__main__":
    sys.exit(main())
