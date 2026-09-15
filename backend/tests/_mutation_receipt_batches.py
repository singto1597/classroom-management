#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับงาน F5 (ชุดเอกสาร / Document Batch)

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

⚠️ mutation ที่ "รอด" อาจเป็น **equivalent mutant** (เปลี่ยนโค้ดแต่พฤติกรรมเท่ากัน)
   ⇒ ก่อนแก้เทสต์ให้ถอยไปตรวจ invariant ก่อนเสมอ (ดู `docs/skills.md`)

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

BATCHES = "tests/test_finance_receipt_batches.py"
LOCK = "tests/test_finance_money_lock.py"
SERVICE = "services/finance/receipt_batches.py"
RECEIPTS = "services/finance/receipts.py"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
#   เทสต์ที่ควรจับ = path ไฟล์::ชื่อเทสต์ (หรือ path ไฟล์ เพื่อรันทั้งไฟล์)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 1 — เทสต์เชิงโครงสร้างของล็อก: พิสูจน์ว่า marker ที่เพิ่งเพิ่มมีฟัน
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M1 ถอด advisory lock ออกจาก create_receipt_batch",
        SERVICE,
        "                    # 🔒 ล็อกห้องเป็นคำสั่งแรก — ทำให้คำขอซ้ำสองอัน serialize กันจริง\n"
        "                    #    (ถ้าไม่ล็อก สองคำขอที่มาพร้อมกันจะ \"ไม่เห็น\" ชุดของกันและกัน\n"
        "                    #     แล้วสร้างชุดซ้ำสองชุด ทั้งที่เช็ค idempotency ไว้แล้ว)\n"
        "                    await _lock_room_money(conn, target_room_id)",
        "                    pass  # MUTANT: ถอดล็อกห้องออก",
        [f"{LOCK}::test_every_money_path_takes_the_room_lock"
         "[receipt_batches-ReceiptBatchesMixin-create_receipt_batch]"],
    ),
    (
        "M2 ย้ายล็อกห้องไป **หลัง** การเขียนชุด (ล็อกยังอยู่ แต่สายเกินไป)",
        SERVICE,
        "                    await _lock_room_money(conn, target_room_id)\n"
        "\n"
        "                    receipt_ids = await cls._resolve_receipt_ids(",
        "                    receipt_ids = await cls._resolve_receipt_ids(",
        # ⚠️ ตัวนี้เล็ง "ลำดับ" โดยเฉพาะ — `test_every_money_path_takes_the_room_lock`
        #    รันซ้ำในลูปของ `_MONEY_WRITE_MARKERS` ⇒ ต้องล้มเพราะ marker มาก่อนล็อก
        [f"{LOCK}::test_every_money_path_takes_the_room_lock"
         "[receipt_batches-ReceiptBatchesMixin-create_receipt_batch]"],
    ),
    # ══════════════════════════════════════════════════════════════════════════
    # ชั้นที่ 2 — พฤติกรรม: 4 ข้อที่แผน F5 ระบุว่าพังแล้วเจ็บ
    # ══════════════════════════════════════════════════════════════════════════
    (
        "M3 🔑 ลากใบที่ถูก reuse เข้าชุดใหม่ (ชุดจะบวมขึ้นทุกรอบที่กดออกซ้ำ)",
        RECEIPTS,
        '                        if r["reused"]:\n'
        '                            reused += 1\n'
        '                        else:\n'
        '                            new_ids.append(r["receipt"]["id"])',
        '                        if r["reused"]:\n'
        '                            reused += 1\n'
        '                        new_ids.append(r["receipt"]["id"])  # MUTANT: นับใบ reused ด้วย',
        [f"{BATCHES}::test_reused_receipts_are_not_moved_into_a_new_batch"],
    ),
    (
        "M4 🔑 batch_size นับจากแถวที่รอดตัวกรอง (ป้าย 'แสดง N จาก M ใบ' กลายเป็นคำโกหก)",
        RECEIPTS,
        '                counts = await cls._load_batch_counts(\n'
        '                    conn, room_id=target_room_id, batch_ids=[d.get("batch_id") for d in result]\n'
        '                )',
        '                counts = {}  # MUTANT: นับจากแถวที่เห็น แทนที่จะถามขนาดจริงของชุด\n'
        '                for _d in result:\n'
        '                    _b = _d.get("batch_id")\n'
        '                    if _b is None:\n'
        '                        continue\n'
        '                    _c = counts.setdefault(_b, {"batch_size": 0, "batch_voided_count": 0})\n'
        '                    _c["batch_size"] += 1',
        [f"{BATCHES}::test_true_batch_size_survives_the_date_filter"],
    ),
    (
        "M5 ตัด batch_id ออกจาก SELECT ของ get_receipts (ทุกใบกลายเป็น 'ไม่มีชุด')",
        RECEIPTS,
        "R.issued_at,\n    R.batch_id\n",
        "R.issued_at\n    -- MUTANT: ตัด batch_id ออก\n",
        [f"{BATCHES}::test_true_batch_size_survives_the_date_filter",
         f"{BATCHES}::test_batch_issue_creates_a_batch_automatically"],
    ),
    (
        "M6 ปิดสาขา 'เซตเดิม → คืนชุดเดิม' (กดซ้ำได้ชุดที่สอง)",
        SERVICE,
        "                    if existing_id is not None:",
        "                    if False:  # MUTANT: ปิด idempotency ของ create",
        [f"{BATCHES}::test_create_batch_moves_receipts_and_is_idempotent"],
    ),
    (
        "M7 ถอดการปลดใบออกจากชุดตอนยุบชุด (ใบยังอ้างชุดที่ถูกลบแล้ว)",
        SERVICE,
        '                    await conn.execute(\n'
        '                        "UPDATE finance_receipts SET batch_id = NULL WHERE room_id = $1 AND batch_id = $2",\n'
        '                        target_room_id, batch_id,\n'
        '                    )',
        "                    pass  # MUTANT: ไม่ปลดใบออกจากชุด",
        [f"{BATCHES}::test_dissolve_detaches_but_never_touches_documents"],
    ),
    (
        "M8 ถอดการถอดใบที่หายจากลิสต์ใน set_batch_receipts (PUT กลายเป็น POST)",
        SERVICE,
        '                    await conn.execute(\n'
        '                        """UPDATE finance_receipts SET batch_id = NULL\n'
        '                           WHERE room_id = $1 AND batch_id = $2 AND deleted_at IS NULL\n'
        '                             AND NOT (id = ANY($3::int[]))""",\n'
        '                        target_room_id, batch_id, receipt_ids,\n'
        '                    )',
        "                    pass  # MUTANT: PUT semantics กลายเป็น add-only",
        [f"{BATCHES}::test_set_members_adds_and_detaches"],
    ),
    (
        "M9 ถอดด่าน 'เอกสารต้องอยู่ในห้องนี้' ออกจาก _resolve_receipt_ids",
        SERVICE,
        '            """SELECT id, receipt_no FROM finance_receipts\n'
        "               WHERE room_id = $1 AND receipt_no = ANY($2::text[])\n"
        "                 AND deleted_at IS NULL AND status = 'active'\"\"\",",
        '            """SELECT id, receipt_no FROM finance_receipts\n'
        "               WHERE ($1 IS NOT NULL) AND receipt_no = ANY($2::text[])  -- MUTANT: ตัดด่านห้อง\n"
        "                 AND deleted_at IS NULL AND status = 'active'\"\"\",",
        [f"{BATCHES}::test_create_batch_rejects_receipt_of_another_room"],
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
    # 🎯 กรองได้ด้วย argv: `python tests/_mutation_receipt_batches.py M3 M4`
    #    💡 มีไว้เพราะแต่ละ mutation ต้องสตาร์ท container ใหม่ (~1 นาที) ⇒ การรันทั้งชุด
    #       ใช้เวลาเป็นสิบนาที · ตอนแก้เทสต์ใหม่จึงอยากรันเฉพาะตัวที่เกี่ยวข้อง
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
                caught_by, tail = run_pytest([BATCHES, LOCK])
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
