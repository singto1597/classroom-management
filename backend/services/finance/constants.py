"""ค่าคงที่กลางของโมดูลการเงิน (cutoff / labels / seed defaults / num formats)"""
from datetime import date
from zoneinfo import ZoneInfo

THAI_TZ = ZoneInfo("Asia/Bangkok")

# [ROUTER] 🗓️ จุดแบ่งยุค (Cut-off) ระหว่างระบบ Single-Entry (legacy) กับ Double-Entry
# =================================================================================
# วันที่ 2026-09-01 เป็นวันที่ยอดยกมา (Opening Balance, Phase 2.5) เข้า journal_entries
# → ข้อมูลก่อนวันนี้ อ่านจากตารางเก่า (finance_transactions) เท่านั้น
# → ข้อมูลตั้งแต่วันนี้ขึ้นไป อ่านจากระบบบัญชีคู่ (journal_entries/journal_lines)
#   เพื่อไม่ให้รายการเก่า/ยอดยกมา เบิ้ลหรือตกหล่น
CUTOFF_DATE = date(2026, 9, 1)

# [F4] `reference_type` ของเงินรับล่วงหน้า — **ต้องใช้ค่าคงที่ ไม่พิมพ์สตริงเอง**
# ⚠️ เหตุผลเดียวกับ `DOC_STATUS_*`: `reference_type` ถูกใช้เป็น **เงื่อนไขกรอง** ใน
#    `budgets.py` (รายได้จากการหักเครดิตต้องถูกนับเข้างบ) และใน
#    `_classify_journal_entry` (ต้องไม่โผล่ในประวัติเงินเคลื่อนไหว) ⇒ พิมพ์ผิด
#    แล้วไม่มี error ให้เห็น มีแต่ "ยอดหายเงียบ ๆ" ซึ่งเป็นความผิดพลาดที่แพงที่สุด
REFERENCE_TYPE_CREDIT_TOPUP = "student_credit_topup"
REFERENCE_TYPE_CREDIT_APPLY = "student_credit_apply"

# [ACCRUAL] reference_type ของรายการที่เกี่ยวกับผู้ค้างชำระ/ค่าปรับ
# 🔴 ใช้ค่าคงที่เสมอ — ค่าเหล่านี้ถูกใช้เป็น "เงื่อนไขกรอง" ทั้งใน `_bill_ar_source`,
#    opening script, และรายงาน ⇒ พิมพ์ผิดแล้วยอดขาด/เบิ้ลแบบไม่มี error ให้เห็น
REFERENCE_TYPE_BILL_ISSUE = "student_payment_issue"          # ออกบิล → Dr AR / Cr รายได้
REFERENCE_TYPE_OPENING_RECEIVABLE = "opening_receivable"      # ยอดยกมา AR → Dr AR / Cr equity
REFERENCE_TYPE_BILL_REVERSAL = "student_payment_reversal"     # ลบบิล/ยกเลิก → กลับ accrual
REFERENCE_TYPE_COLLECTION_ADJUSTMENT = "fee_collection_adjustment"  # แก้ยอดบิล
REFERENCE_TYPE_FINE_ADJUSTMENT = "fine_adjustment"            # แก้ยอดค่าปรับก่อนจ่าย
REFERENCE_TYPE_FINE_CANCEL = "fine_cancel"                    # ยกเลิกค่าปรับก่อนจ่าย
REFERENCE_TYPE_FINE_WAIVER = "fine_waiver"                    # ยกเว้น/ลด
REFERENCE_TYPE_FINE_REFUND = "fine_refund"                    # คืนเงินหลังจ่าย

# 📚 ฉลากไทยของ reference_type สำหรับคอลัมน์ Reference ใน export สมุดรายวัน
# (reference_id ที่เก็บไว้ = id ของเอกสารต้นทาง เช่น legacy_transaction_id / transfer_group_id)
REFERENCE_TYPE_LABELS = {
    "manual_transaction": "รายการ",
    "transfer": "โอนเงิน",
    "student_payment": "ชำระเงิน",
    "opening_balance": "ยอดยกมา",
    "adjustment": "ปรับปรุงยอด",
    # [F4] เงินรับล่วงหน้า (เครดิตคงเหลือรายนักเรียน) — ดู services/finance/credits.py
    # 🔴 สองตัวนี้ **ไม่ใช่** รายได้/รายจ่ายทั้งคู่ในตัวเอง:
    #    topup = รับเงินเข้ามาพัก (สินทรัพย์ ↔ หนี้สิน) / apply = ปล่อยรายได้ (หนี้สิน ↔ รายได้)
    REFERENCE_TYPE_CREDIT_TOPUP: "รับเงินล่วงหน้า",
    REFERENCE_TYPE_CREDIT_APPLY: "หักเงินรับล่วงหน้าปิดบิล",
    # [ACCRUAL] ผู้ค้างชำระ / ค่าปรับ
    REFERENCE_TYPE_BILL_ISSUE: "ออกบิล (ผู้ค้างชำระ)",
    REFERENCE_TYPE_OPENING_RECEIVABLE: "ยอดยกมาผู้ค้างชำระ",
    REFERENCE_TYPE_BILL_REVERSAL: "กลับรายการออกบิล",
    REFERENCE_TYPE_COLLECTION_ADJUSTMENT: "ปรับยอดบิล",
    REFERENCE_TYPE_FINE_ADJUSTMENT: "ปรับยอดค่าปรับ",
    REFERENCE_TYPE_FINE_CANCEL: "ยกเลิกค่าปรับ",
    REFERENCE_TYPE_FINE_WAIVER: "ยกเว้น/ลดค่าปรับ",
    REFERENCE_TYPE_FINE_REFUND: "คืนเงินค่าปรับ",
}

# =====================================================================
# [F4] เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน
# =====================================================================

# =====================================================================
# [F4] เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน
# =====================================================================
# 🔴 รหัสบัญชี "เงินรับล่วงหน้า" — **หนี้สิน ไม่ใช่รายได้**
#    เงินที่รับมาก่อนที่จะมีบิลยังไม่ใช่รายได้ของห้อง (ยังไม่มีสิ่งที่ส่งมอบให้)
#    ⇒ รับเงิน = Dr สินทรัพย์ / Cr หนี้สิน, และรายได้เกิดตอน **หักปิดบิล** เท่านั้น
#    ดู docs/skills.md หัวข้อ "ขาเงินพักต้องเป็น liability/equity"
#
# ⚠️ รหัสนี้อยู่ใน "ชุดที่ระบบ provision เอง" ไม่ใช่ 1xxxx/4xxxx/5xxxx/3000/3001 ที่ผูกกับ
#    ตาราง legacy — เป็น ledger ที่ไม่มี `legacy_account_id` (ดูกติกาใน `_resolve_advance_ledger`)
ADVANCE_LIABILITY_CODE = "2099"
ADVANCE_LIABILITY_NAME = "เงินรับล่วงหน้า (เครดิตนักเรียน)"

# ประเภทของรายการใน `student_credits` — ต้องตรงกับ `chk_student_credit_entry_type`
# (ใช้ค่าคงที่ ไม่พิมพ์สตริงเอง ด้วยเหตุผลเดียวกับ DOC_STATUS_* ข้างบน)
CREDIT_ENTRY_TOPUP = "topup"      # รับเงินเข้ามาพัก → เครดิตเพิ่ม
CREDIT_ENTRY_APPLY = "apply"      # หักไปปิดบิล → เครดิตลด + เกิดรายได้
CREDIT_ENTRY_REVERSE = "reverse"  # ยกเลิกการหัก → เครดิตคืน

# [RECONCILE] ค่าคงที่สำหรับรายการกระทบยอด (Reconciliation) ระหว่างระบบ Legacy กับบัญชีคู่
# - reference_type 'adjustment' = รายการปรับปรุงยอด (สร้างโดย script reconcile_finance เท่านั้น)
# - equity ledger '3001' = ขาสะท้อน (mirror) ของส่วนต่าง → ไม่กระทบ Net Worth (คิดเฉพาะ asset)
#   และไม่ปน income statement (ต่างจาก '3000' ทุน-ยอดยกมา ของ opening_balance)
RECONCILE_REFERENCE_TYPE = "adjustment"
RECONCILE_EQUITY_CODE = "3001"
RECONCILE_EQUITY_NAME = "ปรับปรุงยอด (Reconciliation)"

# =====================================================================
# [ACCRUAL] ผู้ค้างชำระ (Accounts Receivable) + ค่าปรับ
# =====================================================================
# 🔴 รหัสบัญชี **5 หลักแบบมาตรฐาน** (อนุมัติ 24 พ.ย. 2026) — ระบบ provision เอง
#    ต่อห้องแบบ find-or-create ไม่ผ่าน legacy mapping (`legacy_*_id` ต้องเป็น NULL)
#
# ⚠️ รหัสชุดนี้อาจชนกับรหัสที่ระบบสร้างอัตโนมัติ:
#      สินทรัพย์ = '1' || LPAD(finance_accounts.id, 4, '0')  → id 1001 = 11001
#      รายได้/ค่าใช้จ่าย = '4'/'5' || LPAD(finance_categories.id, 4, '0') → id 9001
#    ⇒ migration 0010 มี preflight กันไว้แล้ว และ `_resolve_system_ledger` ตรวจซ้ำ
#      ตอนรัน (ชื่อ/ประเภท/legacy mapping ไม่ตรง = raise ห้ามใช้บัญชีผิดเงียบ ๆ)
#    ถ้า production ชนจริง ต้องเลือกชุดใหม่ (เช่น 11011/11012/31012/49011/49012/49013/59011)
AR_PROJECT_CODE = "11001"
AR_PROJECT_NAME = "ผู้ค้างชำระค่าโครงการ"
AR_FINE_CODE = "11002"
AR_FINE_NAME = "ผู้ค้างชำระค่าปรับ"
OPENING_AR_EQUITY_CODE = "31002"
OPENING_AR_EQUITY_NAME = "ยอดยกมาบัญชีเปิด – ผู้ค้างชำระ"
FINE_REVENUE_CODE = "49001"
FINE_REVENUE_NAME = "รายได้ค่าปรับ"
FINE_DISCOUNT_CODE = "49002"
FINE_DISCOUNT_NAME = "ส่วนลดค่าปรับ"
FINE_REFUND_CODE = "49003"
FINE_REFUND_NAME = "คืนค่าปรับ"
FINE_BAD_DEBT_CODE = "59001"
FINE_BAD_DEBT_NAME = "หนี้สูญค่าปรับ"

# {code: (name, account_type)} — ลำดับคือลำดับการสร้าง (AR ก่อน เพื่อ error เร็ว)
SYSTEM_LEDGER_SPECS: dict[str, tuple[str, str]] = {
    AR_PROJECT_CODE: (AR_PROJECT_NAME, "asset"),
    AR_FINE_CODE: (AR_FINE_NAME, "asset"),
    OPENING_AR_EQUITY_CODE: (OPENING_AR_EQUITY_NAME, "equity"),
    FINE_REVENUE_CODE: (FINE_REVENUE_NAME, "revenue"),
    FINE_DISCOUNT_CODE: (FINE_DISCOUNT_NAME, "revenue"),
    FINE_REFUND_CODE: (FINE_REFUND_NAME, "revenue"),
    FINE_BAD_DEBT_CODE: (FINE_BAD_DEBT_NAME, "expense"),
}

# รหัสบัญชี AR ทั้งสอง — ใช้รวมยอด "ผู้ค้างชำระ" และเป็นตัวกรองใน opening script
AR_LEDGER_CODES: tuple[str, ...] = (AR_PROJECT_CODE, AR_FINE_CODE)

# ชนิดของ fee_collections (บังคับที่ service — ไม่ใส่ CHECK เพื่อให้ migration idempotent)
COLLECTION_KIND_PROJECT = "project"
COLLECTION_KIND_FINE = "fine"

# ⏰ นโยบายค่าปรับจ่ายล่าช้า (Phase 6.5) — เก็บที่ `fee_collections.late_fee_mode`
#    `none` = ไม่ปรับ (ค่าเริ่มต้น) · `fixed` = จำนวนเงินคงที่ · `percent` = % ของยอดคงเหลือ
LATE_FEE_MODE_NONE = "none"
LATE_FEE_MODE_FIXED = "fixed"
LATE_FEE_MODE_PERCENT = "percent"
LATE_FEE_MODES: tuple[str, ...] = (
    LATE_FEE_MODE_NONE, LATE_FEE_MODE_FIXED, LATE_FEE_MODE_PERCENT,
)
LATE_FEE_MODE_LABELS = {
    LATE_FEE_MODE_NONE: "ไม่ปรับ",
    LATE_FEE_MODE_FIXED: "ปรับเป็นจำนวนเงิน",
    LATE_FEE_MODE_PERCENT: "ปรับเป็นเปอร์เซ็นต์",
}
# ชื่อที่แสดงบนค่าปรับที่ระบบออกให้ (ไม่มีประเภทความผิดจริง — `fine_type_id` เป็น NULL)
LATE_FEE_FINE_TYPE_NAME = "ค่าปรับจ่ายล่าช้า"
# จำนวนวันให้ชำระหลังระบบออกค่าปรับล่าช้า
LATE_FEE_DUE_DAYS = 7

# สถานะค่าปรับ — ต้องตรงกับ CHECK ใน migration 0010
FINE_STATUS_ISSUED = "issued"
FINE_STATUS_PARTIALLY_PAID = "partially_paid"
FINE_STATUS_PAID = "paid"
FINE_STATUS_WAIVED = "waived"
FINE_STATUS_CANCELLED = "cancelled"
FINE_STATUS_REFUNDED = "refunded"
FINE_STATUS_LABELS = {
    FINE_STATUS_ISSUED: "ออกแล้ว",
    FINE_STATUS_PARTIALLY_PAID: "ชำระบางส่วน",
    FINE_STATUS_PAID: "ชำระแล้ว",
    FINE_STATUS_WAIVED: "ยกเว้น/ลด",
    FINE_STATUS_CANCELLED: "ยกเลิก",
    FINE_STATUS_REFUNDED: "คืนเงินแล้ว",
}

# เหตุผลการยกเว้น — แยกบัญชีตามเหตุผล (ผู้ใช้เลือก)
FINE_WAIVER_CATEGORY_DISCOUNT = "discount"          # ยกเว้น/ลด → contra-revenue 49002
FINE_WAIVER_CATEGORY_UNCOLLECTIBLE = "uncollectible"  # ตามไม่ได้ → หนี้สูญ 59001
FINE_WAIVER_CATEGORY_LABELS = {
    FINE_WAIVER_CATEGORY_DISCOUNT: "ยกเว้น/ลด",
    FINE_WAIVER_CATEGORY_UNCOLLECTIBLE: "ตามไม่ได้ (หนี้สูญ)",
}

# สถานะคำขอ (waiver/refund) — ต้องตรงกับ CHECK ใน migration 0010
REQUEST_STATUS_PENDING = "pending"
REQUEST_STATUS_APPROVED = "approved"
REQUEST_STATUS_REJECTED = "rejected"
REQUEST_STATUS_CANCELLED = "cancelled"

# ประเภทความผิดเริ่มต้น 5 รายการ — migration 0010 seed ให้ห้องที่มีอยู่แล้ว
# และ `room_service.create_room` ใช้กับห้องใหม่ (Phase 3)
# ⚠️ จำนวน 0 = ต้องกรอกเอง (ใช้กับ "อื่น ๆ") — service ต้องปฏิเสธถ้าไม่ได้ override
DEFAULT_FINE_TYPES: tuple[dict, ...] = (
    {"name": "มาสาย / ไม่ทำเวร", "default_amount": 20.0, "default_due_days": 7,
     "description": "มาสายหรือไม่ทำเวรตามที่ได้รับมอบหมาย", "sort_order": 10},
    {"name": "ขาดเวรทำความสะอาด", "default_amount": 20.0, "default_due_days": 7,
     "description": "ไม่มาทำความสะอาดตามเวรที่จัดไว้", "sort_order": 20},
    {"name": "ไม่ส่งงาน", "default_amount": 20.0, "default_due_days": 7,
     "description": "ไม่ส่งงานหรือการบ้านตามกำหนด", "sort_order": 30},
    {"name": "ใช้โทรศัพท์ในเวลาเรียน", "default_amount": 20.0, "default_due_days": 7,
     "description": "ใช้โทรศัพท์ระหว่างเรียนโดยไม่ได้รับอนุญาต", "sort_order": 40},
    {"name": "อื่น ๆ (กรอกยอดเอง)", "default_amount": 0.0, "default_due_days": 7,
     "description": "ใช้เมื่อไม่ตรงกับประเภทที่มี — ต้องกรอกจำนวนเงินเอง", "sort_order": 50},
)

# =====================================================================
# [EXPORT-ERP] ค่าคงที่กลางสำหรับ Excel Export ระดับ Enterprise
# =====================================================================
# รูปแบบตัวเลข: เงินใช้ #,##0.00 (ตามสเปค), % ใช้ 0.00"%" (เลข 50 → แสดง "50.00%")
MONEY_NUM_FMT = "#,##0.00"
PCT_NUM_FMT = '0.00"%"'

# ฉลากไทยของ account_type สำหรับงบการเงิน (GL / Trial Balance / Balance Sheet)
ACCOUNT_TYPE_LABELS = {
    "asset": "สินทรัพย์",
    "liability": "หนี้สิน",
    "equity": "ส่วนของเจ้าของ",
    "revenue": "รายได้",
    "expense": "ค่าใช้จ่าย",
}

# ฉลากไทยของ fee_collections.status
COLLECTION_STATUS_LABELS = {
    "active": "กำลังเก็บ",
    "closed": "ปิดแล้ว",
    "draft": "ร่าง",
}

# สี Tab Sheet — แยกหมวดรายงาน: Management (โทนน้ำเงิน) vs Accounting (โทนเขียวเข้ม/ม่วง)
MANAGEMENT_TAB_COLORS = ["1D4ED8", "2563EB", "0E9F6E", "DB2777"]
ACCOUNTING_TAB_COLORS = ["0F766E", "047857", "115E59", "4C1D95", "6D28D9", "4338CA"]
# [CLAMP] ข้อความหมายเหตุสำหรับฟังก์ชันงบการเงิน (journal-native) เมื่อช่วงที่ขอแตะก่อนวันที่ตัด
_CLAMP_START_NOTE = ("หมายเหตุ: ช่วงก่อนวันที่ 2026-09-01 (ก่อนขึ้นระบบบัญชีคู่) ไม่มีข้อมูลในงบชุดนี้"
                     " — แสดงผลตั้งแต่วันที่ 2026-09-01 เป็นต้นไป")
_CLAMP_EMPTY_NOTE = ("หมายเหตุ: ช่วงเวลาที่ขออยู่ก่อนวันที่ 2026-09-01 (ก่อนขึ้นระบบบัญชีคู่)"
                     " — ไม่มีรายการในระบบบัญชีคู่")
# 🎯 หมวดหมู่รายรับ/รายจ่ายค่าเริ่มต้น — seed ให้ทุกห้องทันทีที่สร้างห้อง
# (RoomManagementService.create_room นำไป INSERT ลง finance_categories)
DEFAULT_INCOME_CATEGORIES = [
    "📥 เก็บเงินห้องปกติ",
    "💸 เงินตกหล่น/เก็บได้",
    "🎉 รายได้จากกิจกรรม",
    "⚖️ ค่าปรับ",
    "♻️ เงินทอน/เงินคืน",
    "💰 เงินสนับสนุน",
    "♻️ ขายขยะขวดพลาสติก/กระดาษ",
    "📈 ดอกเบี้ยธนาคาร",
    "💖 ผู้ใหญ่ใจดี/สปอนเซอร์",
    "🛒 กำไรจากการขายของ",
    "📈 ปรับปรุงยอด (เงินเกิน)",
]

DEFAULT_EXPENSE_CATEGORIES = [
    "✏️ เครื่องเขียน/อุปกรณ์การเรียน",
    "🧹 อุปกรณ์ทำความสะอาด",
    "📄 ชีทเรียน/ถ่ายเอกสาร",
    "🔬 อุปกรณ์ทำโครงงาน",
    "🏆 กีฬาสี",
    "🙏 วันไหว้ครู",
    "🎄 กิจกรรมอื่นๆ",
    "💊 สวัสดิการเพื่อน/พยาบาล",
    "🎂 ของขวัญ/รางวัล",
    "💸 ค่าธรรมเนียม/อื่นๆ",
    "💻 เซิร์ฟเวอร์/โดเมน/ไอที",
    "⚙️ อุปกรณ์ IoT/อิเล็กทรอนิกส์",
    "🧪 สารเคมี/อุปกรณ์ทดลอง",
    "🖨️ ค่ารูปเล่ม/พอร์ตโฟลิโอ",
    "🧻 ของใช้สิ้นเปลือง",
    "💡 ซ่อมแซม/บำรุงรักษา",
    "🪴 ตกแต่งห้องเรียน",
    "⛺ ค่ายวิชาการ/ทัศนศึกษา",
    "☕ เลี้ยงรับรอง/ซัพพอร์ตครู",
    "📸 อัดรูป/ถ่ายภาพ",
    "📉 ปรับปรุงยอด (เงินขาด)",
]

# 🎯 บัญชีเงินสดค่าเริ่มต้น — seed ให้ทุกห้องทันทีที่สร้างห้อง
# (RoomManagementService.create_room นำไป INSERT ลง finance_accounts)
DEFAULT_FINANCE_ACCOUNTS = [
    "🪙 กระเป๋าเงินสด",
    "🏦 บัญชีธนาคารห้อง",
]

# =====================================================================
# [F3] เอกสารการเงิน — ใบเสร็จ (receipt) / ใบแจ้งหนี้ (invoice)
# =====================================================================
DOC_TYPE_RECEIPT = "receipt"
DOC_TYPE_INVOICE = "invoice"
# [F4] ใบรับเงินล่วงหน้า — เอกสารที่ **ไม่มีบิลรองรับ** (คนละรูปร่างกับ receipt/invoice)
# ใช้แทนหลักฐานการรับเงินตอนเติมเครดิต ⇒ ต้องมี `_issue_deposit` แยก (reuse `_issue_one` ไม่ได้)
DOC_TYPE_DEPOSIT = "deposit"
# [F6] ใบสำคัญจ่าย — เอกสารที่ออก **ให้รายจ่ายที่บันทึกเอง** (`add_transaction` type='expense')
# 🔴 ชนิดนี้ **ไม่ใช่ใบเสร็จ** ⇒ `is_receipt` ต้องเป็น False ไม่งั้นเทมเพลตจะพิมพ์
#    "เรียกเก็บจาก"/"ยอดค้างชำระ" บนใบจ่าย (ดู `_document_context`)
DOC_TYPE_PAYMENT_VOUCHER = "payment_voucher"
# [F6] ใบรับเงิน — เอกสารที่ออก **ให้รายรับที่บันทึกเอง** (`add_transaction` type='income')
# ℹ️ ต่างจาก `receipt` (ผูกบิลผ่าน student_payment_id) และ `deposit` (เครดิตล่วงหน้า)
#    ⇒ ทั้งสามชนิดเป็น "เงินเข้า" เหมือนกันแต่คนละที่มาและคนละคีย์กันซ้ำ
DOC_TYPE_INCOME = "income"
# 🚫 สถานะเอกสาร — ต้องตรงกับ `chk_receipt_status` ใน init_db.py
# ⚠️ ใช้ค่าคงที่ ไม่พิมพ์สตริงเอง เพราะ **พิมพ์ผิดใน "เงื่อนไขกรอง" ไม่มี error ให้เห็น**:
#    `WHERE status = 'actve'` แค่คืนศูนย์แถวเงียบ ๆ ⇒ ใบเสร็จทั้งห้องหายจากหน้าจอโดยไม่มีใครรู้
#    (ทิศทางกลับกันคือ UPDATE ตั้งค่าผิด → ชน CHECK constraint → 500 อย่างน้อยก็รู้ตัว)
DOC_STATUS_ACTIVE = "active"
DOC_STATUS_VOIDED = "voided"
DOC_TYPE_LABELS = {
    DOC_TYPE_RECEIPT: "ใบเสร็จรับเงิน",
    DOC_TYPE_INVOICE: "ใบแจ้งหนี้",
    DOC_TYPE_DEPOSIT: "ใบรับเงินล่วงหน้า",
    DOC_TYPE_PAYMENT_VOUCHER: "ใบสำคัญจ่าย",
    DOC_TYPE_INCOME: "ใบรับเงิน",
}

# 🧾 ชนิดที่เป็น **"เงินเข้ามือแล้ว"** ⇒ พิมพ์ด้วยถ้อยคำของใบเสร็จ ("ได้รับเงินจาก" /
#    "คงเหลือ" / "ผู้ชำระเงิน") ไม่ใช่ถ้อยคำของใบแจ้งหนี้ ("เรียกเก็บจาก" / "ยอดค้างชำระ" /
#    "ผู้รับแจ้ง") ซึ่งกลับความหมายทั้งใบโดยไม่มี error ให้เห็น
#
# 🔴 **แหล่งเดียวของคำตอบนี้** — ทั้งสองปลายทางต้องอ่านจาก tuple นี้เท่านั้น:
#    • กระดาษ → `_document_context` (ใบสำคัญจ่ายต้องได้ False)
#    • หน้าจอ → `_shape_receipt` ส่งออกเป็นฟิลด์ `is_receipt` ใน API
#    เดิมแต่ละฝั่งเขียน tuple ของตัวเอง ⇒ เพิ่มชนิดที่ 4 แล้วลืมแก้ฝั่งใดฝั่งหนึ่ง
#    = เอกสารที่อ่านผิดทั้งใบโดยไม่มีอะไรฟ้อง (รอยแผลที่ `ReceiptDetail.vue` เขียนเตือนไว้)
RECEIPT_LIKE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT, DOC_TYPE_INCOME)

# =====================================================================
# [F5] ชุดเอกสาร — "ที่มาของชุด" (ต้องตรงกับ `chk_receipt_batch_source` ใน init_db.py)
# =====================================================================
# ⚠️ ต้องอยู่ในไฟล์นี้ **ไม่ใช่** ใน `receipt_batches.py`: `receipts.py` ต้องใช้ค่าพวกนี้
#    ตอนเรียก `_attach_issuance_batch` แต่ `receipt_batches.py` import `_RECEIPT_COLUMNS`
#    จาก `receipts.py` อยู่ ⇒ ถ้าค่าคงที่อยู่ฝั่งนั้นจะเกิด import วงกลมจริง
#    (`constants.py` ไม่ import ใครในโมดูลนี้ ⇒ ปลอดภัยทั้งสองทิศ)
BATCH_SOURCE_AUTO = "auto"      # ออกเอกสารทีละหลายใบในรอบเดียว (กดติ๊กหลายบิล/หลายคน)
BATCH_SOURCE_ROOM = "room"      # ออกให้ทั้งห้องในคำสั่งเดียว (issue_invoices_for_room)
BATCH_SOURCE_MANUAL = "manual"  # ผู้ใช้จัดกลุ่มทีหลัง
# 🔢 จำนวนใบขั้นต่ำที่จะ "จัดชุดให้อัตโนมัติ" — ใบเดียวไม่มีอะไรให้ยุบในทะเบียน
AUTO_BATCH_MIN = 2
# 🚧 เพดานจำนวนใบต่อชุด = เพดาน PDF รวม (`RECEIPTS_PER_PDF_MAX`)
#    ⇒ "โหลดทั้งชุดเป็นไฟล์เดียว" ทำงานได้เสมอไม่ว่าชุดจะถูกสร้างมาอย่างไร
BATCH_RECEIPTS_MAX = 100
# คำนำหน้าเลขเอกสารต่อชนิด — ยาว 2–4 ตัวอักษร ต้องตรงกับ `RECEIPT_NO_PATTERN`
# ℹ️ เดิมคอมเมนต์ตรงนี้เขียนว่า "บังคับ `[A-Z]{3}` ⇒ เพิ่มชนิดใหม่ต้องเป็น 3 ตัวอักษรเท่านั้น"
#    ซึ่ง **เป็นคำโกหกหลัง F6** — pattern ถูกผ่อนเป็น `[A-Z]{2,3}` แล้ว (ดูเหตุผลที่ตัว pattern)
#    ⇒ `PV` (2 ตัว) ใช้ได้ · [FIN-V2] ผ่อนต่อเป็น `[A-Z]{2,4}` ⇒ `CERT` (4 ตัว) ใช้ได้
#    · เก็บหมายเหตุนี้ไว้เพราะคอมเมนต์ที่ค้างความจริงอันตรายกว่าการไม่มีคอมเมนต์
DOC_TYPE_PREFIXES = {
    DOC_TYPE_RECEIPT: "REC",
    DOC_TYPE_INVOICE: "INV",
    DOC_TYPE_DEPOSIT: "DEP",
    DOC_TYPE_PAYMENT_VOUCHER: "PV",
    # 🔑 เลือก `INC` ไม่เลือก `RCV`: บนกระดาษที่พิมพ์แจก `RCV` ต่างจาก `REC` แค่ตัวเดียว
    #    ⇒ คนอ่านด้วยตาเปล่าแยกไม่ออกว่ากำลังถือใบเสร็จหรือใบรับเงิน
    DOC_TYPE_INCOME: "INC",
}

# 🔁 ชนิดเอกสารที่ "ออกซ้ำได้เลขเดิม" (idempotent) — ยึด "เหตุการณ์ต้นทาง" เป็นคีย์
#    ต่างจาก invoice ที่เป็น point-in-time ⇒ กดซ้ำได้เลขใหม่ทุกครั้งโดยเจตนา
#
# ℹ️ `receipt` และ `deposit` ต่างก็ idempotent แต่ **คนละคีย์กัน** จึงไม่ใช้คอนสแตนต์
#    ร่วมกัน: receipt คีย์ที่ `(student_payment_id, legacy_transaction_id)` และ
#    deposit คีย์ที่ `legacy_transaction_id` เดี่ยว ๆ (ไม่มีบิล) ⇒ คนละ index
#    ⇒ การรวมเป็นทูเพิลเดียวจะทำให้อ่านแล้วเข้าใจว่าคีย์เดียวกัน ซึ่งไม่จริง
# 🔒 รูปแบบเลขเอกสาร: PREFIX-ปี พ.ศ. 4 หลัก-ลำดับ 4 หลัก เช่น REC-2569-0042
# router ใช้ pattern นี้กับ Path(...) โดยตรง — แก้ที่เดียวต้องแก้ทั้งสองที่
RECEIPT_NO_TEMPLATE = "{prefix}-{year_be:04d}-{seq:04d}"
# 🔑 [F6] ผ่อนจาก `[A-Z]{3}` เป็น `[A-Z]{2,3}` เพื่อให้ `PV` (ใบสำคัญจ่าย) ใช้ได้
# 🔑 [FIN-V2 / P1.1] ผ่อนต่อเป็น `[A-Z]{2,4}` เพื่อให้ `CERT` (4 ตัว) ใช้ได้ —
#    `CERT` เป็นคำนำหน้าที่ยาวที่สุดในชุดเอกสาร v2 (ACK/INC/PV ยังอยู่ 2–3 ตัว)
#    ⚠️ ยัง **ไม่ผ่อนเป็น `[A-Z]+`** โดยเจตนา: pattern นี้คือ path param ของ
#       GET detail/PDF ⇒ ยิ่งกว้างยิ่งเปิดช่องให้สตริงแปลก ๆ วิ่งเข้า query เปล่า ๆ
#       ชนิดใหม่ในอนาคตควรมีคำนำหน้าไม่เกิน 4 ตัว ถ้าต้องยาวกว่านี้ให้ขยาย **อย่างมีเหตุผล**
RECEIPT_NO_PATTERN = r"^[A-Z]{2,4}-\d{4}-\d{4}$"

# 🚧 เพดานลำดับที่ **ต้อง** มี เพราะสองที่นี้ผูกกันด้วยจำนวนหลัก:
#    `{seq:04d}` เกิน 9999 แล้ว *กว้างขึ้นเอง* เป็น 5 หลัก (ไม่ error) แต่ `RECEIPT_NO_PATTERN`
#    บังคับ 4 หลัก และ pattern นั้นคือ path param ของ GET detail/PDF
#    ⇒ ใบที่ 10000 จะ INSERT สำเร็จและโผล่ในรายการได้ แต่ **เปิด/พิมพ์ซ้ำไม่ได้ตลอดกาล (422)**
#    ทั้งที่พิมพ์แจกผู้ปกครองไปแล้ว — เอกสารที่เปิดกลับไม่ได้คือเอกสารที่ตรวจสอบไม่ได้
#    เกินเพดานจึงต้อง "ไม่ให้ออก" ตั้งแต่แรก (และไม่กินเลข เพราะ transaction rollback)
RECEIPT_SEQ_MAX = 9999
RECEIPT_SEQ_OVERFLOW_MSG = (
    "เลขเอกสารของปีนี้เต็มแล้ว (ครบ 9999 ฉบับ) — กรุณาติดต่อผู้ดูแลระบบ "
    "เพื่อขยายรูปแบบเลขเอกสารก่อนออกฉบับต่อไป"
)

# 🔎 ข้อความของด่าน "ล่วงหน้า" (`_assert_receipt_seq_budget`) — คนละจังหวะกับตัวข้างบน
#
# 🔴 ทำไมต้องมีด่านล่วงหน้า ทั้งที่ `_issue_one` ก็ตรวจอยู่แล้ว:
#    การรับเงินรวบยอด **รับเงินก่อน แล้วค่อยออกเอกสาร** ⇒ ถ้าปล่อยให้ไปตายที่ `_issue_one`
#    ความล้มเหลวจะเกิด "กลางลูป" หลังบิลหลายใบถูกเขียนไปแล้ว (แม้จะ rollback ทั้งหมด
#    แต่ครูเห็นข้อความกว้าง ๆ ที่ไม่บอกว่าติดตรงไหนและต้องทำอะไรต่อ)
#    ด่านนี้ยิง **ก่อนที่เงินบาทแรกจะถูกเขียน** ⇒ ข้อความบอกได้ตรง ๆ ว่าติดที่เลขเอกสาร
#    และ "ยังไม่มีอะไรถูกบันทึก" ซึ่งเป็นสิ่งที่ครูกังวลที่สุด ณ จังหวะนั้น
#
# ⚠️ เป็นด่าน UX ไม่ใช่ด่านความปลอดภัย — **ด่านจริงยังอยู่ที่ `_issue_one`**
#    (`seq > RECEIPT_SEQ_MAX`) ซึ่งอยู่ใน transaction เดียวกันและยังกันได้ครบ
#    ⇒ ระหว่างที่ด่านนี้ผ่านกับตอนที่ `_issue_one` จองเลขจริงมีช่องว่างให้ replica
#      อื่นแย่งเลขไปได้ (อ่านโดยไม่ล็อก) ⇒ ผลลัพธ์คือยังได้ 400 เหมือนเดิม ไม่ใช่ข้อมูลพัง
RECEIPT_SEQ_BUDGET_MSG = (
    "เลขเอกสารของปีนี้เหลือไม่พอสำหรับการรับเงินครั้งนี้ "
    "(ต้องใช้ {need} เลข แต่เหลือ {left} เลข) — ยังไม่มีรายการใดถูกบันทึก "
    "กรุณาติดต่อผู้ดูแลระบบเพื่อขยายรูปแบบเลขเอกสารก่อน"
)

# 🖨️ ข้อความแจ้งผู้ใช้เมื่อเรนเดอร์ PDF ไม่ผ่าน — **ห้ามใส่ URL/hostname ภายในลงไป**
#    เส้นทางดาวน์โหลด PDF เปิดให้แค่ `require_member` (ไม่ต้องมี MANAGE_FINANCE)
#    ⇒ ข้อความนี้ไปถึง "สมาชิกทุกคนของห้อง" ⇒ ที่อยู่ service ภายใน
#      (เช่น `*_pdf_gotenberg:3000`) และข้อความดิบจาก Gotenberg
#      ไม่ใช่ข้อมูลที่ผู้ใช้ต้องรู้และไม่ควรเปิดเผย — รายละเอียดจริงไปที่ log ฝั่ง server
#    (ข้อความต้องไม่ชี้ว่าเป็นความผิดของผู้ใช้ และต้องบอกว่าลองใหม่ได้)
PDF_RENDER_UNAVAILABLE_MSG = (
    "สร้างไฟล์ PDF ไม่สำเร็จชั่วคราว (ระบบสร้างเอกสารไม่ตอบสนอง) — กรุณาลองใหม่อีกครั้ง"
)
PDF_RENDER_FAILED_MSG = (
    "สร้างไฟล์ PDF ไม่สำเร็จ (ระบบสร้างเอกสารตอบกลับผิดพลาด) — กรุณาลองใหม่อีกครั้ง"
)
# 🔒 ชุดเดียวกันแต่คนละสาเหตุ: "ไฟล์ประกอบของฝั่งเราหาย" (ฟอนต์ / เทมเพลต / jinja2)
#    เดิมข้อความพวกนี้ใส่ **path เต็มบนเซิร์ฟเวอร์** ลงไปตรง ๆ (`/app/assets/fonts/...`)
#    ⇒ หลุดทาง 502 detail ของเส้นทาง PDF ที่เปิดแค่ `require_member` เท่ากับข้อความข้างบน
#    ⚠️ บทเรียน: การซานิไทซ์ต้องไล่ให้ครบ **ทุกจุดที่ raise** ไม่ใช่แค่จุดที่รายงานมา
#       (แก้ไปรอบหนึ่งแล้วเหลืออีก 3 จุดเพราะดูแค่ฟังก์ชันที่ถูกชี้) — path จริงไปที่ log
PDF_ASSET_MISSING_MSG = (
    "ระบบสร้างเอกสารยังไม่พร้อมใช้งาน (ไฟล์แม่แบบหรือฟอนต์ไม่ครบ) — กรุณาแจ้งผู้ดูแลระบบ"
)

# 📄 จำนวนเอกสารสูงสุดต่อการสร้าง PDF รวม **หนึ่งไฟล์**
#    เท่ากับเพดานของ batch รับเงิน (100) โดยเจตนา — "หนึ่ง HTTP request" ของระบบนี้คือ 100
#    ⚠️ เพดานนี้ผูกกับ **เวลาจัดหน้า** ของ Chromium (ประมาณ 0.1–0.3 วิ/หน้า) ไม่ใช่ขนาดไฟล์
#       (ฟอนต์ฝังครั้งเดียว ~122 KB ⇒ 100 ใบยังไม่ถึง 400 KB) ⇒ ต้องสอดคล้องกับ
#       `PDF_BATCH_TIMEOUT` ด้านล่างและ `--api-timeout` ของ Gotenberg
RECEIPTS_PER_PDF_MAX = 100

# ⏱️ เวลารอ Gotenberg ของ **ไฟล์รวมหลายใบ** — ตั้งใจให้ต่างจากใบเดียว
#    ใบเดียว 100% อยู่ใน 30 วิเสมอ แต่ไฟล์รวม 100 หน้าใช้เวลามากกว่านั้นได้จริง
#    🔴 ต้อง **ไม่สั้นกว่า** `--api-timeout` ของ Gotenberg ใน docker-compose.pdf.yml
#       ถ้าฝั่งเราสั้นกว่า Gotenberg จะยังทำงานอยู่แต่เราเลิกรอ ⇒ ผู้ใช้ได้ 502
#       ทั้งที่ไฟล์กำลังจะเสร็จ (และ retry จะกินเวลาซ้ำ)
#       ⇒ สองค่านี้เป็นคู่ที่ต้องแก้พร้อมกัน ไม่ใช่ค่าอิสระ
PDF_BATCH_TIMEOUT = 120.0

# 📅 ปี พ.ศ. ของ "เหตุการณ์รับเงิน" — ต้องคิดจาก paid_at ในเวลาไทย ไม่ใช่ UTC
# (UTC+7 ทำให้รายการช่วง 17:00–24:00 UTC ตกเป็น "วันรุ่งขึ้น" ของไทย → ข้ามปี พ.ศ. ได้)
BUDDHIST_ERA_OFFSET = 543

# 🗓️ ชื่อเดือนไทยแบบย่อ **ต้องตรงกับ `toLocaleString('th-TH', {month:'short'})` ของเบราว์เซอร์**
#    เพราะสตริงชุดเดียวกันนี้ถูกพิมพ์ทั้งบนกระดาษ (เทมเพลต Jinja2) และบนจอ (period.ts)
#    ⇒ เพี้ยนแม้ตัวเดียว = ผู้ปกครองเทียบจอกับใบเสร็จแล้วเห็นไม่เหมือนกัน
#    (ชุดนี้ probe มาจาก Node/ICU จริง ไม่ได้พิมพ์จากความจำ)
THAI_MONTHS_SHORT = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)

# 🖨️ เทมเพลต PDF — อยู่ฝั่ง backend ไม่ใช่หน้า Vue เพราะหน้า print ต้องไม่มี auth guard
# และต้องพิมพ์ได้แม้ frontend ไม่ได้ออนไลน์
RECEIPT_TEMPLATE_DIR = "templates/finance"
RECEIPT_TEMPLATE_NAME = "receipt.html"
# 🖨️ [A4] shell ตามมาตรฐานเอกสาร A4 — ใช้เฉพาะชุดที่มีเอกสาร v2 (`body_template`
#    ลงท้าย `_v2.html`) ส่วนชุด legacy ล้วนยังใช้ `receipt.html` เดิม ⇒ ไบต์ของใบเก่า
#    ไม่ขยับ (digest test) และใบ legacy ที่ปนในชุดผสมได้สไตล์เดิมผ่าน `.legacy-doc`
RECEIPT_V2_TEMPLATE_NAME = "receipt_v2.html"
# 🏷️ ชื่อแบรนด์บนหัวกระดาษ — ค่าคงที่ **ห้าม derive จากข้อมูลห้อง** (ทุกเอกสารต้อง
#    ดูเป็นชุดเดียวกัน) ตรงกับ `APP_NAME` ของแอป (`frontend/src/router/meta.ts`)
PDF_BRAND_NAME = "SYNCROOM"
# 🌐 ที่อยู่เว็บที่พิมพ์บนหัวเอกสาร — ค่าคงที่ **ไม่ derive จาก env/ข้อมูลห้อง**
#    เพื่อให้กระดาษทุกใบ (รวมที่พิมพ์จาก staging) ชี้ที่เว็บจริงที่ผู้ปกครองใช้
PDF_BRAND_URL = "class.singto1597.xyz"
# ฟอนต์ไทยต้อง "ส่งไปกับ request" เสมอ — Gotenberg เรนเดอร์ใน container ของตัวเอง
# URL แบบ file:///app/... จึงไป resolve ที่ filesystem ของ Gotenberg ไม่ใช่ของ backend
RECEIPT_FONT_DIR = "assets/fonts"

# 🔴 ต้องเป็นฟอนต์ **static** (แยกไฟล์ตามน้ำหนัก) ห้ามใช้ variable font
#    ทดลองแล้ว (13 ก.ย. 2026): NotoSansThai-Variable.ttf + `font-weight: 100 900`
#    → Chromium/Skia embed ฟอนต์ตัวแปรลง PDF ไม่ได้ จึงถอยไปวาด glyph เป็น **Type 3**
#      (pdffonts: `[none]  Type 3  emb yes sub no` × 11 ก้อน, ไฟล์ 92 KB)
#    → เปลี่ยนเป็น static 2 ไฟล์ (400/700) ได้ **CID TrueType + subset** จริง
#      (pdffonts: `AAAAAA+NotoSansThai-Bold  CID TrueType  emb yes sub yes`, ไฟล์ 17 KB)
#    ต่างกัน 5.5 เท่าและได้ฟอนต์จริงที่ร้านพิมพ์/โปรแกรมอ่านออกเสียงยอมรับ
#    ⇒ เพิ่ม/ลดน้ำหนักต้องเพิ่มไฟล์ที่นี่ **ไม่ใช่** ใส่ `font-weight: <ช่วง>` ในเทมเพลต
RECEIPT_FONT_FILES = {
    "regular": ("NotoSansThai-Regular.ttf", 400),
    "bold": ("NotoSansThai-Bold.ttf", 700),
}

# ชื่อ family ที่ประกาศใน @font-face ของเทมเพลต — ต้องตรงกันทั้งสองฝั่ง
# (ทุกน้ำหนักใช้ชื่อ family เดียวกัน แล้วแยกด้วย `font-weight` ของแต่ละ @font-face)
RECEIPT_FONT_FAMILY = "NotoSansThai"

# 🖊️ น้ำหนักที่เทมเพลตใช้อ้างอิง — ต้องมีไฟล์ครบทุกตัว ไม่งั้น Chromium จะ synthesize
#    ตัวหนาเองแล้วสระ/วรรณยุกต์ไทยจะเพี้ยน (มีเทสต์กันไว้)
RECEIPT_FONT_WEIGHTS = tuple(weight for _, weight in RECEIPT_FONT_FILES.values())

# =====================================================================
# [FIN-V2 / P1.1] เอกสารชุดใหม่ของ Finance v2 — ชนิด/คำนำหน้า/ledger
# =====================================================================
# ℹ️ เพิ่ม "รายการใน dict" แทนการประกาศ dict ใหม่ทั้งก้อน — การ re-declare จะทับ
#    ของเดิม (REC/INV/DEP/PV/INC) และทำให้เลขเอกสารเก่าใช้ไม่ได้ทันที
DOC_TYPE_ACKNOWLEDGEMENT = "acknowledgement"
DOC_TYPE_CERTIFICATE = "certificate"
# monthly_report ไม่มีคำนำหน้าใน DOC_TYPE_PREFIXES โดยเจตนา: RPT ไม่จองเลขผ่าน
# `receipt_sequences` แต่ใช้ `finance_monthly_reports.version` (ดู doc-matrix §3)
DOC_TYPE_MONTHLY_REPORT = "monthly_report"

DOC_TYPE_LABELS[DOC_TYPE_ACKNOWLEDGEMENT] = "ใบรับทราบยอดค้าง"
DOC_TYPE_LABELS[DOC_TYPE_CERTIFICATE] = "ใบรับรองแทนใบเสร็จ"
DOC_TYPE_LABELS[DOC_TYPE_MONTHLY_REPORT] = "รายงานปิดงบ"

DOC_TYPE_PREFIXES[DOC_TYPE_ACKNOWLEDGEMENT] = "ACK"
DOC_TYPE_PREFIXES[DOC_TYPE_CERTIFICATE] = "CERT"

# ℹ️ ไม่เพิ่ม ACK/CERT เข้า RECEIPT_LIKE_DOC_TYPES โดยเจตนา:
#    - ACK ไม่มีการรับเงิน (ลายเซ็น ≠ เงิน) ⇒ ห้ามพิมพ์ถ้อยคำ "ได้รับเงินจาก"
#    - CERT เป็นใบรับรองแทนใบเสร็จ ⇒ ต้องใช้ถ้อยคำของตัวเอง (ดู docs/skills.md
#      เรื่อง "เอกสารที่ไม่มีบิลต้องมีถ้อยคำของตัวเอง")

# 🏦 ledger ของระบบ: หนี้สูญของบิลโครงการ (59001 = หนี้สูญค่าปรับอยู่แล้ว)
#    ℹ️ ใส่ใน `SYSTEM_LEDGER_SPECS` เดียวกันเพื่อให้ `_resolve_system_ledger`
#       ตรวจชื่อ/ประเภท/collision guard ให้ฟรี — ห้ามสร้าง ledger ตรง ๆ ใน service
PROJECT_BAD_DEBT_CODE = "59002"
PROJECT_BAD_DEBT_NAME = "หนี้สูญ (โครงการ)"
SYSTEM_LEDGER_SPECS[PROJECT_BAD_DEBT_CODE] = (PROJECT_BAD_DEBT_NAME, "expense")

# =====================================================================
# [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — ชนิดที่รับ + เพดานหน้า
# =====================================================================
# 📚 ลำดับนี้คือลำดับที่ผู้ใช้เห็นในตัวกรองของหน้าทะเบียน (P5.2)
# ⚠️ ทุกค่าต้องมีใน `DOC_TYPE_LABELS` (มีเทสต์ตรวจ) — ชนิดที่ไม่มีคำนำหน้า
#    (`monthly_report`) ก็อยู่ในลิสต์เพราะทะเบียนรวม RPT ด้วย
REGISTRY_DOC_TYPES = (
    DOC_TYPE_RECEIPT,
    DOC_TYPE_INVOICE,
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_DEPOSIT,
    DOC_TYPE_PAYMENT_VOUCHER,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_INCOME,
    DOC_TYPE_MONTHLY_REPORT,
)
# 📄 pagination แบบ offset — ทะเบียนสูงสุดหลักพันต่อห้อง, การเปลี่ยนตัวกรองบ่อย
#    ทำให้ offset ตรงกับที่ผู้ใช้คาดมากกว่า cursor
REGISTRY_PAGE_DEFAULT = 50
REGISTRY_PAGE_MAX = 200


def doc_type_label(doc_type: str) -> str:
    """ชื่อไทยของชนิดเอกสาร — ถอยไปใช้ค่าดิบถ้ายังไม่มีป้าย (ไม่ raise)"""
    return DOC_TYPE_LABELS.get(doc_type, doc_type)
