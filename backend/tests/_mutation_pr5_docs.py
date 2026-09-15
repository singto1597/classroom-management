#!/usr/bin/env python3
"""🧬 Mutation harness สำหรับงาน F6 (ใบสำคัญจ่าย + ใบรับเงิน)

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

⚠️ mutant ที่ "รอด" อาจเป็น **equivalent** โดยชอบธรรม — ต้องพิสูจน์เหตุผลก่อนสรุปว่าเทสต์หลอก
   ตัวเอง (ดู M7 ด้านล่างที่บันทึกไว้พร้อมหลักฐาน)

⚠️ รันแบบ **ทีละตัวเท่านั้น** — `docker-compose.test.yml` ใช้ Postgres พอร์ต 5433
   ร่วมกัน ⇒ สอง container พร้อมกันจะชนกัน

⚠️ สคริปต์นี้ **คืนไฟล์เสมอ** (finally) และยืนยันด้วย git status ตอนจบ

🧬 งานนี้รับช่วงจาก `_mutation_credits.py` (F4) / `_mutation_receipt_merge.py` (PR-4)
   🔴 **mutation ของ `_merge_key`/เทมเพลตที่ถูกยุบอยู่ในไฟล์ PR-4 แล้ว ไม่ทำซ้ำที่นี่**
      (M1 `student_id` · M2 `status` · M3 `event_at` · M5 ยอดรวม · M6 เพดาน ·
       M12 `{% if not d.is_merged %}`) — ที่นี่มีแต่สิ่งที่ PR-5 เพิ่มเข้ามา

🔧 **วิธีรัน: จาก host** (ไม่ใช่ในคอนเทนเนอร์ — ต่างจาก `_mutation_jsonb_meta.py`):
       python3 backend/tests/_mutation_pr5_docs.py            # ทั้งหมด
       python3 backend/tests/_mutation_pr5_docs.py M6 M8 M22  # เฉพาะบางตัว
   สคริปต์ shell ออกไปสั่ง `docker compose … test_runner` เองผ่าน `COMPOSE` ข้างล่าง
   ⇒ ถ้ารัน **ใน** คอนเทนเนอร์จะล้มเพราะไม่มี docker CLI (บทเรียน: harness ในโฟลเดอร์
   เดียวกัน **ไม่ได้ใช้วิธีรันเดียวกัน** — อ่านบรรทัดนี้ก่อนรันทุกครั้ง)
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
#    โดยไม่มีเทสต์จับอะไรเลย — ผลบวกลวงที่อันตรายกว่า false negative
COMPOSE = ["docker", "compose", "-f", "docker-compose.test.yml", "run", "--rm",
           "test_runner", "sh", "-c",
           "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest "
           "-p no:cacheprovider -q --no-header -x {targets} 2>&1"]

DOCS = "tests/test_finance_transaction_documents.py"
LOCK = "tests/test_finance_money_lock.py"
MERGE = "tests/test_finance_receipt_merge.py"

# ─────────────────────────────────────────────────────────────────────────────
# แต่ละ mutation: (ชื่อ, ไฟล์, ข้อความเดิม, ข้อความใหม่, เทสต์ที่ควรจับ)
# ─────────────────────────────────────────────────────────────────────────────
MUTATIONS = [
    # ── 🔁 การรับคืนรายการ: สองชนิดใหม่ต้องถูกยกเลิกพร้อมรายการ ──────────────
    (
        "M1 ถอด `payment_voucher` จาก `$5` ของ revert_transaction",
        "services/finance/transactions.py",
        "                        [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT,\n"
        "                         DOC_TYPE_INCOME, DOC_TYPE_PAYMENT_VOUCHER],\n"
        "                        DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED,",
        "                        [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT,\n"
        "                         DOC_TYPE_INCOME],  # MUTANT\n"
        "                        DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED,",
        [f"{DOCS}::test_revert_of_an_expense_voids_its_voucher"],
    ),
    (
        "M2 ถอด `income` จาก `$5` ของ revert_transaction",
        "services/finance/transactions.py",
        "                        [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT,\n"
        "                         DOC_TYPE_INCOME, DOC_TYPE_PAYMENT_VOUCHER],\n"
        "                        DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED,",
        "                        [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT,\n"
        "                         DOC_TYPE_PAYMENT_VOUCHER],  # MUTANT\n"
        "                        DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED,",
        [f"{DOCS}::test_revert_of_an_income_voids_its_income_document"],
    ),
    (
        # 🔴 ตัวนี้ยิง **สองจุดพร้อมกัน** (เทมเพลต + หน้าจอ) เพราะทั้งคู่อ่าน tuple กลางตัวเดียว
        "M3 ถอด `income` จาก RECEIPT_LIKE_DOC_TYPES (ใบรับเงินพูดแบบใบแจ้งหนี้)",
        "services/finance/constants.py",
        "RECEIPT_LIKE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT, DOC_TYPE_INCOME)",
        "RECEIPT_LIKE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT)  # MUTANT",
        [f"{DOCS}::test_income_document_renders_with_receipt_wording"],
    ),
    (
        "M4 ตั้ง `is_receipt=True` ให้ใบสำคัญจ่าย",
        "services/finance/receipts.py",
        '            "is_receipt": d["doc_type"] in RECEIPT_LIKE_DOC_TYPES,\n',
        '            "is_receipt": d["doc_type"] in RECEIPT_LIKE_DOC_TYPES\n'
        '            or d["doc_type"] == DOC_TYPE_PAYMENT_VOUCHER,  # MUTANT\n',
        [f"{DOCS}::test_income_context_is_a_receipt_but_a_voucher_is_not"],
    ),
    (
        "M17 กลับด้านตัวกรองสถานะของคำสั่ง void (`=` → `<>`)",
        "services/finance/transactions.py",
        "                             AND status = $6 AND deleted_at IS NULL",
        "                             AND status <> $6 AND deleted_at IS NULL  -- MUTANT",
        [f"{DOCS}::test_revert_of_an_expense_voids_its_voucher"],
    ),
    # ── 🔒 ล็อกห้อง: issuer ใหม่ต้องยึดล็อกเป็นคำสั่งแรก ────────────────────────
    (
        "M5 ถอด advisory lock ออกจาก `_issue_payment_voucher`",
        "services/finance/receipts.py",
        "        await _lock_room_money(conn, target_room_id)\n"
        "\n"
        "        document_amount = round(float(amount), 2)\n"
        "        if document_amount <= 0:\n"
        '            raise ValueError(\n'
        '                "ยอดจ่ายน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "',
        "        pass  # MUTANT: ถอดล็อกห้องออก\n"
        "\n"
        "        document_amount = round(float(amount), 2)\n"
        "        if document_amount <= 0:\n"
        '            raise ValueError(\n'
        '                "ยอดจ่ายน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "',
        # 🎯 เทสต์เชิงโครงสร้าง — `_issue_payment_voucher` ถูกเพิ่มเข้า `_LOCKING_HELPERS`
        #    แล้ว ⇒ การถอดล็อกจะล้มที่ `test_locking_helpers_take_the_lock_first`
        #    (ถ้าไม่เพิ่มเข้า `_LOCKING_HELPERS` mutant ตัวนี้จะ SURVIVE เพราะเทสต์
        #     พฤติกรรมจับ "ล็อกหาย" ไม่ได้ — ล็อกเป็นเรื่องลำดับ ไม่ใช่ผลลัพธ์)
        ["tests/test_finance_money_lock.py::test_locking_helpers_take_the_lock_first"],
    ),
    (
        # 🧷 คู่แฝดของ M5 — พิสูจน์ว่า `_LOCKING_HELPERS` ถูก **parametrize** จริง ไม่ได้
        #    ครอบแค่ตัวแรกในลิสต์ (ถ้าลิสต์ถูกอ่านแค่สมาชิกตัวแรก M21 จะ SURVIVE)
        "M21 ถอด advisory lock ออกจาก `_issue_income_doc`",
        "services/finance/receipts.py",
        "        await _lock_room_money(conn, target_room_id)\n"
        "\n"
        "        # 💰 ยอดต้อง > 0 **หลังปัดเป็นสตางค์** และต้องอยู่ **ก่อน** การจองเลข\n"
        "        #    ไม่งั้นเลขถูกกินไปฟรี (ด่านเดียวกับ `_issue_one`/`_issue_deposit`)\n"
        "        document_amount = round(float(amount), 2)\n",
        "        pass  # MUTANT: ถอดล็อกห้องออกจาก issuer ใบรับเงิน\n"
        "\n"
        "        # 💰 ยอดต้อง > 0 **หลังปัดเป็นสตางค์** และต้องอยู่ **ก่อน** การจองเลข\n"
        "        #    ไม่งั้นเลขถูกกินไปฟรี (ด่านเดียวกับ `_issue_one`/`_issue_deposit`)\n"
        "        document_amount = round(float(amount), 2)\n",
        ["tests/test_finance_money_lock.py::test_locking_helpers_take_the_lock_first"],
    ),
    # ── 🗓️ ปี พ.ศ. ต้องมาจาก "เหตุการณ์" ไม่ใช่วันที่พิมพ์ ──────────────────────
    (
        "M6 คิด `year_be` ของใบสำคัญจาก `issued_at_db` แทน `event_at_db`",
        "services/finance/receipts.py",
        "        year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET\n"
        "\n"
        "        seq = await conn.fetchval(\n"
        '            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)\n'
        "               VALUES ($1, $2, $3, 1)\n"
        "               ON CONFLICT (room_id, year_be, doc_type)\n"
        "               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,\n"
        "                             updated_at = CURRENT_TIMESTAMP\n"
        '               RETURNING last_seq""",\n'
        "            target_room_id, year_be, DOC_TYPE_PAYMENT_VOUCHER,",
        "        year_be = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET  # MUTANT\n"
        "\n"
        "        seq = await conn.fetchval(\n"
        '            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)\n'
        "               VALUES ($1, $2, $3, 1)\n"
        "               ON CONFLICT (room_id, year_be, doc_type)\n"
        "               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,\n"
        "                             updated_at = CURRENT_TIMESTAMP\n"
        '               RETURNING last_seq""",\n'
        "            target_room_id, year_be, DOC_TYPE_PAYMENT_VOUCHER,",
        [f"{DOCS}::test_voucher_year_comes_from_the_event_not_the_issue_time"],
    ),
    (
        # 🧷 คู่แฝดของ M6 สำหรับ issuer อีกตัว — `_issue_income_doc` เป็นฟังก์ชันคนละตัว
        #    ⇒ เทสต์ของใบสำคัญไม่ได้คุมใบรับเงิน (บทเรียนเดียวกับ M21)
        "M22 คิด `year_be` ของใบรับเงินจาก `issued_at_db` แทน `event_at_db`",
        "services/finance/receipts.py",
        # ⚠️ ต้อง mutate **บรรทัดคำนวณ `year_be` เอง** ไม่ใช่แค่อาร์กิวเมนต์ของ INSERT
        #    จองเลข — ถ้าแก้แค่ตัวหลัง เลขที่ประกอบขึ้นยังใช้ตัวแปรเดิม ⇒ เทสต์ผ่าน
        #    ทั้งที่ mutant เสีย (บทเรียนเดียวกับ M8 ที่วาง mutant ผิดที่)
        #    🔒 anchor ต้องยาวถึงคอมเมนต์ "จองเลข" เพราะบรรทัดคำนวณเฉย ๆ ซ้ำ 3 ที่
        "        year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET\n"
        "\n"
        "        # 🎫 จองเลข — ตัวนับเดิม (`receipt_sequences`) คนละแถวกับ receipt/invoice/deposit",
        "        year_be = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET  # MUTANT\n"
        "\n"
        "        # 🎫 จองเลข — ตัวนับเดิม (`receipt_sequences`) คนละแถวกับ receipt/invoice/deposit",
        [f"{DOCS}::test_income_year_comes_from_the_event_not_the_issue_time"],
    ),
    (
        "M14 ตัวนับของ `income` ไปกินแถวของ `receipt` (ตัวนับไม่แยกต่อชนิด)",
        "services/finance/receipts.py",
        '               RETURNING last_seq""",\n'
        "            target_room_id, year_be, DOC_TYPE_INCOME,",
        '               RETURNING last_seq""",\n'
        "            target_room_id, year_be, DOC_TYPE_RECEIPT,  # MUTANT",
        [f"{DOCS}::test_income_sequence_is_independent_from_the_receipt_sequence"],
    ),
    # ── 📸 snapshot ของใบสำคัญ: ต้องถูกอ่านและถูกใช้จริง ───────────────────────
    (
        "M8 ลืม `json.loads` ใน `_parse_voucher_snapshot` (asyncpg คืน jsonb เป็น str)",
        "services/finance/receipts.py",
        # ⚠️ รอบแรก mutant ตัวนี้ถูกวางไว้ **หลัง** `json.loads` ตัวจริง ⇒ กลายเป็น
        #    dead code ที่ `isinstance(raw, str)` เป็น False เสมอ = equivalent ปลอม
        #    (harness รายงาน SURVIVE ทั้งที่เทสต์ไม่ได้อ่อน) ⇒ ต้องปิด `json.loads`
        #    **ตัวจริง** ที่ `receipts.py:1336-1340` ไม่ใช่ต่อท้ายฟังก์ชัน
        "        if isinstance(raw, str):\n"
        "            try:\n"
        "                raw = json.loads(raw)\n"
        "            except (ValueError, TypeError):\n"
        "                return None\n"
        "        return raw if isinstance(raw, dict) else None",
        "        if isinstance(raw, str) and False:  # MUTANT: ลืม json.loads\n"
        "            try:\n"
        "                raw = json.loads(raw)\n"
        "            except (ValueError, TypeError):\n"
        "                return None\n"
        "        return raw if isinstance(raw, dict) else None",
        [f"{DOCS}::test_voucher_prints_a_covering_budget"],
    ),
    (
        "M9 `_document_context` ไม่คลี่ snapshot (ทุกใบสำคัญกลายเป็น 'ไม่อยู่ในงบ')",
        "services/finance/receipts.py",
        "        snapshot = cls._parse_voucher_snapshot(d.get(\"voucher_snapshot\"))\n"
        "        if snapshot:",
        "        snapshot = cls._parse_voucher_snapshot(d.get(\"voucher_snapshot\"))\n"
        "        if snapshot and False:  # MUTANT",
        [f"{DOCS}::test_voucher_prints_a_covering_budget"],
    ),
    (
        "M10 ตัดช่วงวันที่ของงบออกจาก query (งบที่ไม่ครอบก็ถูกพิมพ์เป็นงบของรายการ)",
        "services/finance/receipts.py",
        "                 AND B.start_date <= $3::date AND B.end_date >= $3::date",
        "                 -- MUTANT: ตัดช่วงวันที่ออก",
        [f"{DOCS}::test_voucher_prints_explicit_text_when_no_budget_covers_it"],
    ),
    (
        "M18 ไม่เก็บ `attachment_count` ลง snapshot (เอกสารแนบหายจากกระดาษ)",
        "services/finance/receipts.py",
        '            "attachment_count": int(attachment_count or 0),',
        '            "attachment_count": 0,  # MUTANT',
        [f"{DOCS}::test_voucher_renders_with_voucher_wording"],
    ),
    (
        "M19 ไม่เก็บ `approver_name` ลง snapshot (ชื่อผู้อนุมัติหายจากกระดาษ)",
        "services/finance/receipts.py",
        '            "approver_name": approver_name,',
        '            "approver_name": None,  # MUTANT',
        [f"{DOCS}::test_expense_creates_exactly_one_payment_voucher"],
    ),
    (
        "M11 เดาช่องทางจ่ายเป็น 'เงินสด' เมื่อไม่รู้ (ใบเก่าถูกกล่าวหาว่าจ่ายสด)",
        "services/finance/receipts.py",
        '        kind = d.get("account_kind")\n'
        "        if not kind:\n"
        "            return None",
        '        kind = d.get("account_kind")\n'
        "        if not kind:\n"
        '            return "เงินสด"  # MUTANT',
        [f"{DOCS}::test_voucher_channel_text_never_invents_a_channel"],
    ),
    (
        # 🔴 บั๊กจริงที่เทสต์ชุดนี้จับได้ตอนเขียน (2026-09-15) — ไม่ใช่ mutant สมมติ
        "M20 เปลี่ยน `_voucher_channel_text` จาก `@staticmethod` เป็น `@classmethod`",
        "services/finance/receipts.py",
        "    @staticmethod\n"
        "    def _voucher_channel_text(d: dict) -> Optional[str]:",
        "    @classmethod  # MUTANT\n"
        "    def _voucher_channel_text(d: dict) -> Optional[str]:",
        [f"{DOCS}::test_voucher_channel_text_never_invents_a_channel"],
    ),
    # ── 🗂️ ทางแยกของเทมเพลต ──────────────────────────────────────────────────
    (
        "M12 `body_template` ของใบสำคัญตกไปที่เนื้อในของใบเสร็จ",
        "services/finance/receipts.py",
        '            "body_template": (\n'
        "                _VOUCHER_BODY_TEMPLATE\n"
        '                if d["doc_type"] == DOC_TYPE_PAYMENT_VOUCHER\n'
        "                else _RECEIPT_BODY_TEMPLATE\n"
        "            ),",
        '            "body_template": _RECEIPT_BODY_TEMPLATE,  # MUTANT',
        [f"{DOCS}::test_voucher_renders_with_voucher_wording"],
    ),
    # ── 🔤 เลขเอกสาร: pattern + ชื่อไฟล์ ────────────────────────────────────
    (
        "M15 ย้อน `RECEIPT_NO_PATTERN` กลับเป็น `[A-Z]{3}` (ออกใบ PV ได้แต่เปิดไม่ได้)",
        "services/finance/constants.py",
        'RECEIPT_NO_PATTERN = r"^[A-Z]{2,3}-\\d{4}-\\d{4}$"',
        'RECEIPT_NO_PATTERN = r"^[A-Z]{3}-\\d{4}-\\d{4}$"  # MUTANT',
        [f"{DOCS}::test_income_prefix_and_pattern_are_usable_as_a_path_parameter"],
    ),
    (
        "M16 ตัด `payment_voucher` ออกจาก dict ของ `pdf_filename` (ชื่อไฟล์เป็น `document-`)",
        "services/finance/pdf.py",
        '        "payment_voucher": "payment_voucher",',
        '        # MUTANT: ตัด payment_voucher ออก',
        [f"{DOCS}::test_pdf_filename_covers_every_doc_type"],
    ),
]


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
        rel for _, rel, _, _, _ in MUTATIONS
        if MARKER in (BACKEND / rel).read_text(encoding="utf-8")
    })
    if dirty:
        print("🛑 พบ mutant ค้างในไฟล์ตั้งต้น — หยุดก่อน ไฟล์เหล่านี้ยับแล้ว:")
        for rel in dirty:
            print(f"   • {rel}")
        print("   ⇒ คืนสภาพก่อน (`git checkout -- <file>`) แล้วรันใหม่")
        return 2

    # 🎯 กรองได้ด้วย argv: `python tests/_mutation_pr5_docs.py M13 M14`
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
                state, tail = run_pytest([DOCS, MERGE, LOCK])
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
