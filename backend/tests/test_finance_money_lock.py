"""🔒 Lock protocol ของทุกเส้นทางที่แตะเงิน (advisory lock ต่อห้อง)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมีไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
โปรโตคอลนี้ **พังทันทีถ้ามีเส้นทางเดียวที่ลืมยึดล็อก** — ไม่ใช่พังแบบเห็น ๆ แต่พังแบบ
"กลับมาเป็น deadlock 40P01 → 500 เป็นครั้งคราว" ซึ่ง debug ยากที่สุดในบรรดาบั๊กทั้งหมด

ไฟล์นี้จึงมีสองชั้น:
  1. **เชิงพฤติกรรม** — พิสูจน์ว่าล็อกถูกยึดจริง, เป็นรายห้อง, และ re-entrant
  2. **เชิงโครงสร้าง** — ไล่ทุกเส้นทางที่แตะเงิน แล้วยืนยันว่ายึดล็อก **ก่อน** เขียนเงิน
     (ชั้นนี้คือตัวที่จะ "ล้ม" ตอนมีคนเพิ่มเมธอดใหม่แล้วลืมยึดล็อก)

⚠️ ความซื่อสัตย์เรื่องขอบเขตของหลักฐาน — สิ่งที่ไฟล์นี้พิสูจน์ **ไม่ได้**:
   มันไม่ได้ยิงสอง transaction ให้ตายกันจริงเพื่อแสดงว่า deadlock หายไป
   (แบบนั้นพิสูจน์อะไรไม่ได้จริง และเคยหลอกตัวเองมาแล้วครั้งหนึ่ง — ดู §10 ของ
   `test_finance_receipts.py`) สิ่งที่พิสูจน์คือ **หลักการที่ทำให้ deadlock หายไป**:
   ถ้าทุกเส้นทางยึดล็อกห้องเป็นอย่างแรก ภายในห้องเดียวจะมีผู้ถือล็อกได้ทีละราย
   ⇒ ไม่มี interleaving ให้เกิดวงรอบรอ ABBA ตั้งแต่แรก
   ⇒ ชั้นที่ 2 จึงเป็นชั้นที่สำคัญที่สุด และต้องมีฟันจริง (ตรวจด้วย mutation แล้ว)
"""
import inspect
import uuid

import pytest

pytestmark = pytest.mark.asyncio


# ══════════════════════════════════════════════ 1. เชิงพฤติกรรม: ล็อกถูกยึดจริง
async def test_room_money_lock_blocks_same_room_but_not_other_rooms(db_pool):
    """ล็อกต้อง (ก) ถูกยึดจริง (ข) ผูกกับ room_id — ห้องอื่นต้องไม่ถูกบล็อกตาม

    🧪 ใช้ `pg_try_advisory_xact_lock` จากอีก connection = **ไม่รอ** แล้วตอบ true/false
       ⇒ deterministic 100% ไม่ต้องพึ่ง timeout หรือการแข่งกันของ thread
    """
    from services.finance.base import _MONEY_LOCK_NAMESPACE, _lock_room_money

    async with db_pool.acquire() as setup:
        room_id = await setup.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องทดสอบล็อกเงิน", f"MLK{uuid.uuid4().hex[:6].upper()}",
        )
        other_room_id = await setup.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องอื่น", f"MLX{uuid.uuid4().hex[:6].upper()}",
        )

    async with db_pool.acquire() as holder:
        async with holder.transaction():
            await _lock_room_money(holder, room_id)

            async with db_pool.acquire() as other:
                same_room = await other.fetchval(
                    "SELECT pg_try_advisory_xact_lock($1, $2)", _MONEY_LOCK_NAMESPACE, room_id,
                )
                assert same_room is False, "ห้องเดียวกันต้องถูกยึดอยู่ (l็อกไม่ได้ผล!)"

                diff_room = await other.fetchval(
                    "SELECT pg_try_advisory_xact_lock($1, $2)", _MONEY_LOCK_NAMESPACE, other_room_id,
                )
                assert diff_room is True, "ห้องอื่นต้องไม่ถูกบล็อกตาม — ไม่งั้นทั้งระบบวิ่งทีละห้อง"


async def test_room_money_lock_is_reentrant_within_one_transaction(db_pool):
    """เรียกซ้ำใน transaction เดียวกันต้องไม่บล็อกตัวเอง

    🎯 สำคัญเพราะ batch เรียกในลูป (`_issue_one` ถูกเรียกซ้ำทุกใบ) และเมธอดที่ delegate
       ต่อกัน (เช่น `confirm_payment` → `_confirm_single_payment`) จะยึดล็อกซ้ำ
       ถ้ามันบล็อกตัวเอง = **self-deadlock** ทันที ไม่ใช่แค่ช้า
    """
    from services.finance.base import _lock_room_money

    async with db_pool.acquire() as setup:
        room_id = await setup.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องทดสอบ reentrant", f"MLR{uuid.uuid4().hex[:6].upper()}",
        )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            for _ in range(3):
                await _lock_room_money(conn, room_id)
            # ถ้าบล็อกตัวเอง จะค้างจน statement_timeout ไม่มีทางมาถึงบรรทัดนี้
            assert await conn.fetchval("SELECT 1") == 1


# ═══════════════════════════════════════ 2. namespace ต้องมีตัวเดียวทั้งระบบ
async def test_only_one_money_lock_namespace_exists():
    """ต้องมี namespace เดียว — สอง namespace = ล็อกคนละดอก = โปรโตคอลเป็นโมฆะ

    🎯 บั๊กที่เทสต์นี้กัน: มีคนเพิ่ม `_SOMETHING_LOCK_NAMESPACE = 0x...` ใหม่ในโมดูลใดก็ตาม
       แล้วเส้นทางนั้นจะไม่เห็นล็อกของเส้นทางอื่นอีก ⇒ กลับเป็น deadlock โดยที่โค้ด "ดูล็อกครบ"
    """
    import re
    from pathlib import Path

    import services.finance as pkg

    finance_dir = Path(pkg.__file__).parent
    found = {}
    for py in sorted(finance_dir.glob("*.py")):
        for m in re.finditer(r"^(_[A-Z0-9_]*LOCK_NAMESPACE)\s*=\s*(0x[0-9a-fA-F]+)", py.read_text(encoding="utf-8"), re.M):
            found.setdefault(m.group(2).lower(), []).append(f"{py.name}:{m.group(1)}")

    assert len(found) == 1, (
        "พบ advisory-lock namespace มากกว่าหนึ่งค่า — โปรโตคอลจะไม่ทำงาน: "
        + repr(found)
    )
    only = next(iter(found))
    assert only == hex(0x52454350), f"ค่า namespace เปลี่ยนไปจากที่ตกลงกันไว้: {only}"


# ═══════════════════════ 3. เชิงโครงสร้าง: ทุกเส้นทางเงินต้องยึดล็อกก่อนเขียนเงิน
# รายการนี้คือ "สัญญา" ของโปรโตคอล — เพิ่มเมธอดที่แตะเงินใหม่แล้วไม่มาเพิ่มที่นี่
# เทสต์จะไม่จับ (ด่านสุดท้ายคือการรีวิว) แต่ถ้ามาเพิ่มแล้ว **ลืมยึดล็อกในเมธอด** เทสต์จับแน่นอน
_MONEY_PATHS = [
    # (โมดูล, คลาส, เมธอด)
    ("collections", "CollectionsMixin", "create_fee_collection"),
    ("collections", "CollectionsMixin", "update_collection"),
    ("collections", "CollectionsMixin", "confirm_payment"),
    ("collections", "CollectionsMixin", "batch_confirm_payments"),
    ("collections", "CollectionsMixin", "remove_student_from_collection"),
    ("collections", "CollectionsMixin", "add_student_to_collection"),
    ("transactions", "TransactionsMixin", "add_transaction"),
    ("transactions", "TransactionsMixin", "transfer_money"),
    ("transactions", "TransactionsMixin", "revert_transaction"),
    ("receipts", "ReceiptsMixin", "issue_receipt"),
    ("receipts", "ReceiptsMixin", "issue_receipts_batch"),
    # 🧾 ใบแจ้งหนี้ "ยอดค้างรวมต่อคน" — คนละเส้นทางกับใบเสร็จ (F3 รอบสอง)
    ("receipts", "ReceiptsMixin", "issue_invoices"),
    ("receipts", "ReceiptsMixin", "issue_invoices_for_room"),
    # 💰 [F4] เงินรับล่วงหน้า / เครดิตคงเหลือรายนักเรียน
    ("credits", "CreditsMixin", "top_up_credit"),
    ("credits", "CreditsMixin", "apply_credit"),
    ("credits", "CreditsMixin", "undo_credit_application"),
    ("accounts", "AccountsMixin", "create_account"),
    ("accounts", "AccountsMixin", "update_account"),
    ("accounts", "AccountsMixin", "delete_account"),
    ("categories", "CategoriesMixin", "create_category"),
    ("categories", "CategoriesMixin", "update_category"),
    ("categories", "CategoriesMixin", "delete_category"),
    ("budgets", "BudgetsMixin", "create_budget"),
    ("budgets", "BudgetsMixin", "update_budget"),
    ("budgets", "BudgetsMixin", "delete_budget"),
    ("ledger", "LedgerMixin", "reconcile_balances"),
    ("backfill", "BackfillMixin", "backfill_missing_journals"),
]

# 🔴 สิ่งที่ถือว่า "เขียนเงิน" — ใช้ตรวจ **ลำดับ** ว่าล็อกมาก่อนการเขียนจริง
#    ⚠️ การเรียก helper ที่เขียนเงินก็นับด้วย (SQL ไปอยู่ใน helper ไม่ใช่ในเมธอดนี้)
_MONEY_WRITE_MARKERS = [
    "INSERT INTO finance_transactions", "UPDATE finance_transactions",
    "INSERT INTO finance_accounts", "UPDATE finance_accounts",
    "INSERT INTO student_payments", "UPDATE student_payments", "DELETE FROM student_payments",
    "UPDATE fee_collections",
    "INSERT INTO finance_receipts", "INSERT INTO receipt_sequences",
    "INSERT INTO journal_entries",
    # 💰 [F4] บัญชีแยกประเภทเครดิต **รายคน** — ยอดเงินจริง ไม่ใช่บันทึกประกอบ
    #    ⇒ ต้องอยู่ใต้ล็อกห้องเหมือนตารางเงินอื่น (เพิ่มพร้อมงาน F4)
    "INSERT INTO student_credits", "UPDATE student_credits", "DELETE FROM student_credits",
    "INSERT INTO accounting_ledgers",
    "INSERT INTO finance_categories", "UPDATE finance_categories",
    "INSERT INTO finance_budgets", "UPDATE finance_budgets",
    # การ delegate ไป helper ที่เขียนเงิน — **helper เหล่านี้ไม่ยึดล็อกเอง**
    # ⇒ ผู้เรียกต้องยึดล็อกก่อนถึงบรรทัดนี้ (เทสต์ตัวนี้คือผู้บังคับข้อนั้น)
    "_confirm_single_payment(", "_write_backfill_journals(", "_scan_account_diffs(",
]

# 🪆 helper ที่ "ยึดล็อกให้ caller" — การเรียกตัวพวกนี้จึงนับเป็นจุดที่ปลอดภัยแล้ว
#    ⚠️ ข้อยกเว้นนี้ **ต้องจ่ายค่าตัวเอง** ด้วยเทสต์ `test_locking_helpers_take_the_lock_first`
#       ข้างล่าง ไม่งั้นมันจะเป็นรูรั่ว: ใครก็อ้างว่า "delegate ไป helper ที่ล็อก" แล้วรอด
#    ⚠️ ใส่ได้เฉพาะ helper ที่ยึดล็อกจริงเท่านั้น — `_confirm_single_payment` **ไม่เข้าเกณฑ์**
#       (มันเป็นผู้รับล็อกต่อจาก `confirm_payment`/`batch_confirm_payments` ไม่ใช่ผู้ยึด)
#    ⚠️ ชื่อ helper ถูกหาแบบ **substring** (`f"{helper}("`) ⇒ ห้ามตั้งชื่อใหม่ที่ขึ้นต้นด้วย
#       ชื่อเดิม (เช่น `_issue_one_invoice`) เพราะมันจะไปแมตช์จุดของ `_issue_one` ของเดิม
_LOCKING_HELPERS = ["_issue_one", "_issue_invoice_aggregate"]


def _first_line_with(lines: list[str], needle: str):
    """บรรทัดแรกที่มี `needle` แบบ "โค้ดจริง" (ข้ามคอมเมนต์) — คืน None ถ้าไม่มี"""
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            continue
        if needle in line:
            return i
    return None


def _resolve_method(module_name: str, class_name: str, method_name: str):
    module = __import__(f"services.finance.{module_name}", fromlist=[class_name])
    return getattr(getattr(module, class_name), method_name)


@pytest.mark.parametrize("module_name, class_name, method_name", _MONEY_PATHS)
async def test_every_money_path_takes_the_room_lock(module_name, class_name, method_name):
    """ทุกเส้นทางที่แตะเงินต้องยึดล็อกห้อง **ก่อน** คำสั่งเขียนเงินคำสั่งแรก

    🧪 เป็นเทสต์เชิงโครงสร้าง (อ่านซอร์ส) โดยเจตนา: "ยึดล็อกก่อนเขียน" สังเกตจาก HTTP
       ไม่ได้ — `TestClient` เป็น sync ยิงพร้อมกันจริงไม่ได้ และเราแทรก `lock_timeout`
       เข้า connection ของแอปไม่ได้ ⇒ พฤติกรรมของตัวช่วยถูกพิสูจน์แล้วในสองเทสต์ข้างบน
       ตัวนี้ทำหน้าที่จับ "มีคนย้าย/ลบ/ลืมคำสั่งล็อก" ซึ่งเทสต์เหล่านั้นจับไม่ได้

    🪆 ยอมรับการ delegate: `issue_receipt` ไม่ได้ยึดล็อกเอง แต่เรียก `_issue_one`
       ซึ่งยึดเป็นอย่างแรก ⇒ จุดที่ปลอดภัยคือ "บรรทัดที่ยึดล็อก **หรือ** เรียก helper ที่ยึดล็อก"
    """
    src = inspect.getsource(_resolve_method(module_name, class_name, method_name))
    lines = src.splitlines()

    safe_at = _first_line_with(lines, "await _lock_room_money(")
    for helper in _LOCKING_HELPERS:
        h = _first_line_with(lines, f"{helper}(")
        if h is not None and (safe_at is None or h < safe_at):
            safe_at = h

    assert safe_at is not None, (
        f"{class_name}.{method_name} แตะเงินแต่ไม่มีจุดที่ยึด advisory lock ของห้องเลย "
        f"— ต้องเรียก `await _lock_room_money(conn, target_room_id)` เป็นอย่างแรกใน transaction"
    )

    for marker in _MONEY_WRITE_MARKERS:
        i = _first_line_with(lines, marker)
        assert i is None or safe_at < i, (
            f"{class_name}.{method_name}: ยึดล็อกห้องช้ากว่าการเขียนเงิน "
            f"(`{marker}` อยู่บรรทัดที่ {i}, จุดที่ปลอดภัยอยู่บรรทัดที่ {safe_at}) "
            f"— ลำดับยังแข่งกันได้ ⇒ deadlock กลับมาได้"
        )


@pytest.mark.parametrize("helper_name", _LOCKING_HELPERS)
async def test_locking_helpers_take_the_lock_first(helper_name):
    """helper ที่ถูกนับว่า "ยึดล็อกให้ caller" ต้องยึดล็อกจริง ก่อนเขียนเงินคำสั่งแรก

    🎯 นี่คือ "ค่าตัว" ของข้อยกเว้นใน `_LOCKING_HELPERS`: ถ้าใครถอดล็อกออกจาก `_issue_one`
       เทสต์ตัวบนจะยังเขียว (เพราะ `issue_receipt` ยัง "delegate ไป helper ที่ล็อก")
       แต่เทสต์ตัวนี้จะล้มทันที ⇒ ข้อยกเว้นปิดรูไม่ได้
    """
    import services.finance as pkg
    from pathlib import Path

    src = None
    for py in sorted(Path(pkg.__file__).parent.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        if f"async def {helper_name}(" in text:
            rest = text[text.index(f"async def {helper_name}("):]
            nxt = rest.find("\n    async def ", 1)
            src = rest[: nxt if nxt != -1 else len(rest)]
            break
    assert src is not None, f"ไม่พบ helper `{helper_name}` — รายชื่อ `_LOCKING_HELPERS` ตกยุค"

    lines = src.splitlines()
    lock_at = _first_line_with(lines, "await _lock_room_money(")
    assert lock_at is not None, (
        f"`{helper_name}` ถูกอ้างว่าเป็น helper ที่ยึดล็อกให้ caller แต่ไม่มีคำสั่งยึดล็อกเลย"
    )
    for marker in _MONEY_WRITE_MARKERS:
        i = _first_line_with(lines, marker)
        assert i is None or lock_at < i, (
            f"`{helper_name}`: ยึดล็อกช้ากว่าการเขียนเงิน (`{marker}` บรรทัดที่ {i}) "
            f"⇒ ผู้เรียกที่พึ่งพา helper นี้ยังไม่ปลอดภัย"
        )


async def test_money_path_list_covers_every_manage_finance_entry_point():
    """กัน "เพิ่มเมธอดใหม่แล้วลืมเพิ่มในรายการ" — ไล่หาเมธอดที่ยึด `MANAGE_FINANCE` ทั้งหมด

    🎯 ตัวสัญญาณ: เมธอดสาธารณะที่เรียก `require_permission(..., "MANAGE_FINANCE")`
       และเปิด `conn.transaction()` ของตัวเอง = ต้องอยู่ใน `_MONEY_PATHS`
       (ข้อยกเว้นที่ตั้งใจ: เมธอดอ่านอย่างเดียว และ helper ที่ caller เป็นเจ้าของ transaction)
    """
    import re
    from pathlib import Path

    import services.finance as pkg

    declared = {(m, c, fn) for m, c, fn in _MONEY_PATHS}
    finance_dir = Path(pkg.__file__).parent
    missing = []

    for py in sorted(finance_dir.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        module_name = py.stem
        # แยกทีละเมธอดจาก "async def" ถึง "async def" ถัดไป (พอสำหรับตรวจระดับนี้)
        for m in re.finditer(r"\n    async def (\w+)\(.*?(?=\n    async def |\nclass |\Z)",
                             text, re.S):
            fn_name, body = m.group(1), m.group(0)
            if 'require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")' not in body:
                continue
            if "async with conn.transaction():" not in body:
                continue
            cls_match = re.search(r"^class (\w+)", text[:m.start()], re.M)
            # หาคลาสที่เมธอดนี้สังกัด (คลาสสุดท้ายก่อนตำแหน่งเมธอด)
            classes = re.findall(r"^class (\w+)", text[:m.start()], re.M)
            class_name = classes[-1] if classes else (cls_match.group(1) if cls_match else "?")
            if (module_name, class_name, fn_name) not in declared:
                missing.append(f"{module_name}.{class_name}.{fn_name}")

    assert not missing, (
        "พบเมธอดที่เขียนเงิน (มี MANAGE_FINANCE + transaction ของตัวเอง) "
        "แต่ไม่ได้อยู่ในสัญญา `_MONEY_PATHS` ⇒ ยังไม่มีใครตรวจว่ายึดล็อกห้องหรือไม่: "
        + ", ".join(missing)
    )
