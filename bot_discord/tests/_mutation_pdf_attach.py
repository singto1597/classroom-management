#!/usr/bin/env python3
"""🧬 Mutation harness ฝั่งบอท — F5/PR-3 (แนบ PDF ใบเสร็จเข้า Discord)

═══════════════════════════════════════════════════════════════════════════════
🎯 เป้าหมาย
═══════════════════════════════════════════════════════════════════════════════
เทสต์ที่ "เขียว" ไม่ได้แปลว่ามีฟัน สคริปต์นี้ **ทำลายโค้ดจริง** ทีละจุด แล้วดูว่าเทสต์ล้มจริง:

  • ถูกจับ (เทสต์ล้ม) = เทสต์มีฟัน ✅   • รอด (เทสต์เขียว) = เทสต์หลอกตัวเอง ❌

⚠️ mutant ทุกตัวในตารางนี้คือ **ความล้มเหลวจริงที่ออกแบบไว้กัน** ไม่ใช่การพลิก boolean
   ให้ดูตลก: BM1 คือข้อความการเงินหายเพราะไฟล์แนบ · BM2/BM3 คือยิง Discord ด้วยไฟล์ที่
   ใหญ่เกินจน **ทั้งข้อความถูกปฏิเสธ** · BM4 คือลูปฟัง Redis หยุดรอ Gotenberg 60-120 วิ
   (การแจ้งเตือนอื่นทั้งระบบหยุดตาม) · BM5 คือฟีเจอร์หายเงียบโดยไม่มีอะไร error

═══════════════════════════════════════════════════════════════════════════════
⚠️ ทำไมสคริปต์นี้ใช้ `docker run` + `unittest` ไม่ใช่ pytest/compose เหมือนฝั่ง backend
═══════════════════════════════════════════════════════════════════════════════
image ของบอท (`classroom-classroom-bot:latest`) **ไม่มี pytest** และเทสต์ชุดนี้ไม่ต้องใช้
Postgres เลย ⇒ รันด้วย stdlib `unittest` ใน image เดิมได้ทันที ไม่ต้องติดตั้งอะไรเพิ่ม
(เหตุผลเดียวกับที่ `tests/__init__.py` อธิบายไว้)

รัน (จาก **repo root**):
    python3 bot_discord/tests/_mutation_pdf_attach.py          # ทั้งหมด
    python3 bot_discord/tests/_mutation_pdf_attach.py BM1 BM4  # เฉพาะบางตัว
"""
import hashlib
import re
import signal
import subprocess
import sys
from pathlib import Path

# 🔴 บรรทัดสรุปที่ **unittest ผลิตเองเท่านั้น** (`OK` / `FAILED (failures=1)`)
#    ใช้เป็นหลักฐานว่าเทสต์รันจริง — ถ้าไม่มี แปลว่า container/การ import พัง ไม่ใช่ "จับได้"
#    (บทเรียนจากฝั่ง backend: การอ่าน infra พังเป็น "mutant ถูกจับ" คือผลบวกลวงที่อันตรายสุด)
UNITTEST_SUMMARY_RE = re.compile(r"^(?:OK|FAILED)\b", re.MULTILINE)

REPO = Path(__file__).resolve().parent.parent.parent
BOT = REPO / "bot_discord"
IMAGE = "classroom-classroom-bot:latest"

TESTS = "tests.test_pdf_attach"
ACTION = "services/action_service.py"
PDF_ATTACH = "services/pdf_attach.py"
LISTENER = "cogs/redis_listener.py"
API_CLIENT = "services/api_client.py"

T_OVERSIZED = f"{TESTS}.BuildReceiptFilesTest.test_oversized_pdf_is_refused_with_real_size"
T_CHUNK = f"{TESTS}.BuildReceiptFilesTest.test_over_chunk_limit_refuses_without_fetching"
T_ATTACH = f"{TESTS}.NotifyFinancePaymentTest.test_attaches_file_and_adds_no_note"
T_SURVIVE = f"{TESTS}.NotifyFinancePaymentTest.test_message_survives_discord_rejecting_the_file"
T_NONBLOCK = f"{TESTS}.ProcessEventConcurrencyTest.test_payment_with_receipts_is_not_awaited_inline"
T_FILENAME = f"{TESTS}.FilenameHeaderTest.test_prefers_rfc5987_filename_star"

# ─────────────────────────────────────────────────────────────────────────────
# (id+ชื่อ, expect, [(ไฟล์, ข้อความเดิม, ข้อความใหม่), ...], เทสต์ที่ควรจับ)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    (
        "BM1 ⭐ ถอด retry เมื่อ Discord ปฏิเสธไฟล์ ⇒ ข้อความ 'รับเงินแล้ว' หายทั้งใบ",
        "catch",
        [(ACTION,
          "        try:\n"
          "            await channel.send(content=content, embed=embed, files=files)\n"
          "        except discord.HTTPException as e:\n"
          '            logger.error(f"❌ ส่งข้อความพร้อมไฟล์แนบไม่สำเร็จ ({e}) — ส่งใหม่โดยไม่มีไฟล์")\n'
          '            embed.add_field(name="🧾 ใบเสร็จ", value=ATTACH_FAILED_NOTE, inline=False)\n'
          "            await channel.send(content=content, embed=embed)\n",
          "        # MUTANT: ไม่มีชั้นที่ 3\n"
          "        await channel.send(content=content, embed=embed, files=files)\n")],
        [T_SURVIVE],
    ),
    (
        "BM2 ⭐ ถอดเพดานขนาดไฟล์ ⇒ ยิงไฟล์ 10MB+ ให้ Discord ปฏิเสธทั้งข้อความ",
        "catch",
        [(PDF_ATTACH,
          "    if len(pdf_bytes) > DISCORD_ATTACH_MAX_BYTES:\n",
          "    if False:  # MUTANT: ไม่ตรวจขนาดไฟล์\n")],
        [T_OVERSIZED],
    ),
    (
        "BM3 ถอดการงดแนบเมื่อเกิน PDF_CHUNK_SIZE ⇒ ยิงคำขอที่ backend ต้องปฏิเสธ",
        "catch",
        [(PDF_ATTACH,
          "    if len(nos) > PDF_CHUNK_SIZE:\n",
          "    if False:  # MUTANT: ไม่ตรวจจำนวนใบ\n")],
        [T_CHUNK],
    ),
    (
        "BM4 ⭐ กลับไป await งานแนบไฟล์ในลูปฟัง Redis ⇒ การแจ้งเตือนอื่นหยุดรอ 60-120 วิ",
        "catch",
        [(LISTENER,
          '            if data.get("receipt_nos"):\n'
          "                self._spawn_pdf_task(server_id, data)\n"
          "            else:\n"
          "                await self.action_service.notify_finance_payment(server_id, data)\n",
          "            # MUTANT: กลับไป await ตรง ๆ\n"
          "            await self.action_service.notify_finance_payment(server_id, data)\n")],
        [T_NONBLOCK],
    ),
    (
        "BM5 ไม่แนบไฟล์เลย (ส่ง `[]` แทน `files`) ⇒ ฟีเจอร์หายเงียบโดยไม่มี error",
        "catch",
        [(ACTION,
          '                channel, self._build_content(data, "✅ จ่ายเงินแล้ว"), embed, files\n',
          '                channel, self._build_content(data, "✅ จ่ายเงินแล้ว"), embed, []  # MUTANT\n')],
        [T_ATTACH],
    ),
    (
        "BM6 ทิ้ง `filename*` (RFC 5987) ⇒ ชื่อไฟล์ไทยเพี้ยน ทั้งที่ header ส่งมาครบ",
        "catch",
        [(API_CLIENT,
          "    if encoded_name:\n",
          "    if False:  # MUTANT: ไม่ใช้ filename*\n")],
        [T_FILENAME],
    ),
]

MARKER = "MUTANT"

# 🔴 `finally` ไม่รันเมื่อถูก SIGTERM ⇒ mutant ค้างในไฟล์จริง และรอบถัดไปจะอ่านไฟล์ที่ค้าง
#    เป็น "pristine" ⇒ md5 self-check ผ่านทั้งที่ baseline เสีย
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, lambda *_: sys.exit(130))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_unittest(target: str) -> tuple[str, str]:
    """คืน (สถานะ, ข้อความท้ายสุด) — สถานะ ∈ {"pass", "fail", "infra"}"""
    cmd = ["docker", "run", "--rm", "-v", f"{BOT}:/app:z", "-w", "/app",
           IMAGE, "python", "-m", "unittest", target, "-v"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-25:])
    if not UNITTEST_SUMMARY_RE.search(out):
        # ไม่มี `OK`/`FAILED` ⇒ import พัง/หาเทสต์ไม่เจอ ⇒ ห้ามเดาว่า "จับได้"
        return "infra", f"exit={proc.returncode} · ไม่พบบรรทัดสรุปของ unittest\n{tail}"
    if proc.returncode == 0:
        return "pass", tail
    if proc.returncode == 1:
        return "fail", tail
    return "infra", f"exit={proc.returncode}\n{tail}"


def main() -> int:
    touched = sorted({rel for _, _, edits, _ in MUTATIONS for rel, _, _ in edits})

    # 🛡️ pre-flight: ต้องแน่ใจว่าไฟล์ตั้งต้นสะอาดก่อนถูกอ่านเป็น pristine
    dirty = [rel for rel in touched if MARKER in (BOT / rel).read_text(encoding="utf-8")]
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

    pristine = {rel: (BOT / rel).read_text(encoding="utf-8") for rel in touched}
    before = {rel: md5(BOT / rel) for rel in touched}

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
                (BOT / rel).write_text(mutated, encoding="utf-8")

            state, tail = run_unittest(targets[0])
            if state == "pass":
                # ถอยไปรันทั้งไฟล์ — mutation อาจถูกจับโดยเทสต์ตัวอื่น
                print(f"   ↳ {name}: เทสต์ที่เล็งไม่ล้ม → ถอยไปรันทั้งไฟล์", flush=True)
                state, tail = run_unittest("tests.test_pdf_attach")
                verdict = ("จับโดยเทสต์อื่นในไฟล์ ✅" if state == "fail" else "รอด (ไม่มีเทสต์จับ)")
            else:
                verdict = "จับโดยเทสต์ที่เล็ง ✅"
            caught = state == "fail"
            infra = state == "infra"
        finally:
            for rel in files:
                (BOT / rel).write_text(pristine[rel], encoding="utf-8")

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
    n_surv = sum(1 for _, s, _ in results if s == "SURVIVE")
    n_infra = sum(1 for _, s, _ in results if s == "INFRA")
    n_stale = sum(1 for _, s, _ in results if s == "STALE")
    print(f"จับได้ {n_catch}/{len(results)} | รอดผิดคาด {n_surv} | infra พัง {n_infra}"
          f" | ตกยุค {n_stale}")
    for name, status, tail in results:
        if status in ("INFRA", "SURVIVE", "STALE"):
            print(f"\n── {name} [{status}] ──\n{tail}")

    print("\n── ตรวจความสมบูรณ์ของไฟล์ ──")
    ok = True
    for rel in touched:
        same = md5(BOT / rel) == before[rel]
        ok &= same
        print(f"{'✅' if same else '❌'} {rel} {'คืนสภาพเดิม' if same else 'md5 เปลี่ยน!'}")
    print("✅ ไฟล์ทั้งหมดกลับสภาพเดิม" if ok else "❌ มีไฟล์ไม่กลับสภาพ — ตรวจด้วย git diff ทันที")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
