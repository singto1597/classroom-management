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

# 📚 ฉลากไทยของ reference_type สำหรับคอลัมน์ Reference ใน export สมุดรายวัน
# (reference_id ที่เก็บไว้ = id ของเอกสารต้นทาง เช่น legacy_transaction_id / transfer_group_id)
REFERENCE_TYPE_LABELS = {
    "manual_transaction": "รายการ",
    "transfer": "โอนเงิน",
    "student_payment": "ชำระเงิน",
    "opening_balance": "ยอดยกมา",
    "adjustment": "ปรับปรุงยอด",
}

# [RECONCILE] ค่าคงที่สำหรับรายการกระทบยอด (Reconciliation) ระหว่างระบบ Legacy กับบัญชีคู่
# - reference_type 'adjustment' = รายการปรับปรุงยอด (สร้างโดย script reconcile_finance เท่านั้น)
# - equity ledger '3001' = ขาสะท้อน (mirror) ของส่วนต่าง → ไม่กระทบ Net Worth (คิดเฉพาะ asset)
#   และไม่ปน income statement (ต่างจาก '3000' ทุน-ยอดยกมา ของ opening_balance)
RECONCILE_REFERENCE_TYPE = "adjustment"
RECONCILE_EQUITY_CODE = "3001"
RECONCILE_EQUITY_NAME = "ปรับปรุงยอด (Reconciliation)"

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
