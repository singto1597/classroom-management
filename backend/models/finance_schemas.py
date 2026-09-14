from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import date, datetime
from dataclasses import dataclass
from fastapi import Query

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

# --- Schemas สำหรับส่งออกประวัติการเงิน (Excel) ---
class FinanceExportRequest(BaseModel):
    """
    ตัวกรองช่วงเวลาสำหรับ export ประวัติการทำรายการของห้อง
    - ระบุ start_date + end_date: ช่วงวันที่ที่ต้องการ (ถ้าให้แค่ตัวเดียว → ตัวเดียวนั้นบังคับ)
    - month + year: เอาเฉพาะเดือน (ต้องให้ครบคู่เสมอ)
    - ไม่ระบุอะไรเลย: ดึงทุกอย่าง (ทั้งหมด)
    """
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    month: Optional[int] = Field(None, ge=1, le=12, description="เดือนที่ต้องการ (ให้พร้อม year เสมอ)")
    year: Optional[int] = Field(None, ge=2000, le=2200, description="ปี ค.ศ. ที่ต้องการ")
    user_name: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _validate_period(self):
        # กัน day ผิดใน start_date/end_date ผ่าน: ถ้ามีเดือนให้แบบตรง ๆ เอา month/year เป็นหลัก
        if (self.month is None) != (self.year is None):
            raise ValueError("ต้องระบุทั้ง month และ year พร้อมกัน หรือไม่ระบุทั้งคู่")
        if self.month is not None and self.year is not None:
            if self.start_date or self.end_date:
                raise ValueError("ไม่สามารถใช้ทั้ง month/year และ start_date/end_date พร้อมกันได้")
        return self

# --- Schemas สำหรับดึงรายชื่อนักเรียน (ใหม่) ---
class StudentBasicInfo(BaseModel):
    id: int
    student_no: int
    first_name: str
    last_name: Optional[str]
    nickname: Optional[str]
    first_name_en: Optional[str] = None
    last_name_en: Optional[str] = None
    nickname_en: Optional[str] = None

# --- Schemas สำหรับรับข้อมูล (Requests) ---
class AccountCreate(BaseModel):
    account_name: str = Field(..., max_length=100)
    initial_balance: float = Field(0.0, ge=0.0)
    user_name: Optional[str] = Field(None, max_length=100)

class TransactionCreate(BaseModel):
    account_id: int
    category_id: int
    amount: float = Field(..., gt=0.0)
    description: str = Field(..., max_length=255)
    transaction_type: str = Field(..., pattern="^(income|expense)$")
    slip_image_url: Optional[str] = None
    user_name: str

class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float = Field(..., gt=0.0)
    description: str = Field(..., max_length=255)
    user_name: str

class FeeCollectionCreate(BaseModel):
    title: str = Field(..., max_length=150)
    amount: float = Field(..., gt=0.0)
    due_date: date
    # ✨ อนุญาตให้ส่งรายชื่อเด็กที่ต้องการเรียกเก็บ (ถ้าเป็น None คือเก็บทุกคน)
    student_ids: Optional[List[int]] = None 
    user_name: Optional[str] = Field(None, max_length=100)

class PaymentConfirm(BaseModel):
    paid_to_account_id: int
    paid_amount: float = Field(..., gt=0.0)
    slip_image_url: Optional[str] = None
    user_name: str

# ✨ รับเงินรวบยอด (Batch) — ปลดหนี้หลายรายการของนักเรียน 1 คนในครั้งเดียว
# เพื่อให้แจ้งเตือน Discord เป็นรอบเดียว ไม่เด้งหลาย embed
class BatchPaymentItem(BaseModel):
    payment_id: int
    paid_amount: float = Field(..., gt=0.0)

class BatchPaymentConfirm(BaseModel):
    items: List[BatchPaymentItem] = Field(..., min_length=1)  # บิลพร้อมยอดที่รับต่อบิล
    paid_to_account_id: int
    slip_image_url: Optional[str] = None
    user_name: str

# --- Schemas สำหรับส่งออกข้อมูล (Responses) ---
class AccountResponse(BaseModel):
    id: int
    account_name: str
    balance: float

class TransactionResponse(BaseModel):
    id: int
    amount: float
    description: str
    transaction_type: str
    created_at: datetime
    slip_image_url: Optional[str]
    recorded_by: Optional[str]
    account_name: Optional[str]
    category_name: Optional[str]
    transfer_group_id: Optional[int] = None

class TransactionListResponse(BaseModel):
    total_count: int
    items: List[TransactionResponse]

class StudentPaymentSummary(BaseModel):
    total: int
    paid: int
    pending: int

class StudentPaymentDetail(BaseModel):
    payment_id: int
    status: str
    paid_amount: float 
    total_amount: float
    paid_at: Optional[datetime]
    slip_image_url: Optional[str]
    student_id: int  # ✨ เพิ่ม student_id กลับไปเผื่อใช้ลบ
    student_no: int
    first_name: str
    last_name: str
    nickname: Optional[str]
    first_name_en: Optional[str] = None
    last_name_en: Optional[str] = None
    nickname_en: Optional[str] = None

class CollectionStatusResponse(BaseModel):
    collection_id: int
    summary: StudentPaymentSummary
    students: List[StudentPaymentDetail]

@dataclass
class TransactionFilter:
    limit: int = Query(50, gt=0)
    offset: int = Query(0, ge=0)
    start_date: Optional[date] = Query(None)
    end_date: Optional[date] = Query(None)
    account_id: Optional[int] = Query(None)
    category_id: Optional[int] = Query(None)
    transaction_type: Optional[str] = Query(None, pattern="^(income|expense)$")

# --- Schemas สำหรับ Categories ---
class CategoryCreate(BaseModel):
    category_name: str = Field(..., max_length=100)
    category_type: str = Field(..., pattern="^(income|expense)$")
    user_name: Optional[str] = Field(None, max_length=100)

class CategoryResponse(BaseModel):
    id: int
    category_name: str
    category_type: str

# --- Schemas สำหรับลบรายการ ---
class ActionWithUserRequest(BaseModel):
    user_name: str

# --- Schemas สำหรับ Summary (สรุปยอด) ---
class CategoryBreakdown(BaseModel):
    category_name: str
    total_amount: float

class FinanceSummaryResponse(BaseModel):
    net_worth: float
    total_income: float   
    total_expense: float 
    pending_collection_amount: float 
    period: str 
    expense_breakdown: List[CategoryBreakdown]

# --- Schemas สำหรับ Student Debt ---
class StudentDebtItem(BaseModel):
    payment_id: int
    collection_id: int
    title: str
    amount: float
    due_date: Optional[date] = None
    collection_status: str

class StudentDebtProfileResponse(BaseModel):
    student_id: int
    student_name: str
    total_pending_amount: float
    debts: List[StudentDebtItem]

class FeeCollectionResponse(BaseModel):
    id: int
    title: str
    amount: float
    due_date: Optional[date] = None
    status: str

class FeeCollectionUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0.0)
    due_date: Optional[date] = None
    status: Optional[str] = Field(None, pattern="^(active|closed)$")
    user_name: Optional[str] = Field(None, max_length=100)

# --- Schemas สำหรับ Account Management ---
class AccountUpdate(BaseModel):
    account_name: str = Field(..., max_length=100)
    user_name: Optional[str] = Field(None, max_length=100)

# --- Schemas สำหรับ ทวงหนี้รวม ---
class DebtorItem(BaseModel):
    student_id: int
    student_no: int
    student_name: str
    overdue_count: int
    total_pending_amount: float

class CategoryUpdate(BaseModel):
    category_name: str = Field(..., max_length=100)
    user_name: Optional[str] = Field(None, max_length=100)

# =============================================================================
# 📊 งบการเงิน (Financial Statements) — งบทดลอง / งบกำไรขาดทุน / งบดุล
# =============================================================================
# ⚠️ ห้ามเพิ่ม `__all__` ในไฟล์นี้ — backend/routers/finance/{reporting,export}.py
#    ทำ `from models.finance_schemas import *` และพึ่ง `date`/`datetime`/`Query`
#    ที่ re-export มาจากไฟล์นี้ (ไฟล์นี้ไม่มี __all__ จึงกวาดทุกชื่อสาธารณะ)
#    เติม __all__ = router ทั้งสอง import ไม่ผ่านตั้งแต่ต้น (NameError: date)


class TrialBalanceLedgerRow(BaseModel):
    """แถวบัญชีในงบทดลอง — ยอดสะสม YTD (≤ as_of) ของ ledger หนึ่งตัว."""
    ledger_id: int
    # account_code เป็น NULL ได้ใน DB (query สั่ง `ORDER BY account_code NULLS LAST`)
    account_code: Optional[str] = None
    account_name: str
    account_type: str
    total_debit: float
    total_credit: float
    balance: float


class TrialBalanceResponse(BaseModel):
    """งบทดลอง — total_debit/total_credit เป็นผลรวม "ยอดรวม" (ไม่ใช่สุทธิ) จึงเท่ากันเสมอถ้า journal สมดุล"""
    ledgers: List[TrialBalanceLedgerRow]
    total_debit: float
    total_credit: float
    is_balanced: bool
    # ⚠️ ต้องมี default เสมอ — service ใส่ `note` เฉพาะเส้นทางที่ถูก clamp
    #    ถ้าประกาศเป็น required เส้นทางปกติ (happy path) จะ 500
    note: Optional[str] = None


class StatementLine(BaseModel):
    """บรรทัดรายได้/ค่าใช้จ่ายในงบกำไรขาดทุน"""
    account_name: str
    amount: float


class IncomeStatementResponse(BaseModel):
    """งบกำไรขาดทุนของงวด.

    start_date/end_date เป็น **ISO string** ที่ service echo กลับมา (`.isoformat()`)
    และเป็น **ค่าที่ผู้ใช้ส่งมา ไม่ใช่ค่าที่ถูก clamp แล้ว** — ตัวเลขอาจครอบช่วงแคบกว่านั้น
    frontend ต้องแสดง `note` ให้เด่น ไม่งั้นอ่านผิด (ดู docs/skills.md)
    """
    start_date: str
    end_date: str
    revenues: List[StatementLine]
    expenses: List[StatementLine]
    total_revenue: float
    total_expense: float
    net_income: float
    note: Optional[str] = None


class BalanceSheetAccountRow(TrialBalanceLedgerRow):
    """แถวบัญชีในงบดุล — โครงเดียวกับงบทดลองเป๊ะ.

    สืบทอดมาแทนการก๊อปฟิลด์ เพราะ `_compose_balance_sheet` ส่ง ledger dict
    ชุดเดียวกับ `_fetch_trial_balance_ledgers` มาตรง ๆ — ถ้าอนาคตงบดุลต้องการ
    ฟิลด์ต่างออกไป ค่อยแตกออกจากกันตอนนั้น (ตอนนี้ยังเหมือนกัน 100%)
    """


class BalanceSheetResponse(BaseModel):
    """งบแสดงฐานะการเงิน ณ วันที่.

    สมการที่ต้องเป็นจริง: `assets_total == total_liabilities_and_equity`
    โดย `total_liabilities_and_equity = liability_total + total_equity_side`

    - `total_equity_side` = equity_total + retained_earnings (คงความหมายเดิมจากเวอร์ชันแรก)
    - `period_net_income` เป็น **memo** ให้ผู้ตรวจเทียบ งบกำไรขาดทุน ↔ งบดุล
      จึงต้องมาคู่กับ `period_start`/`period_end` เสมอ ไม่งั้นเป็นตัวเลขลอยที่ไม่รู้ที่มา
    """
    as_of: str
    assets: List[BalanceSheetAccountRow]
    assets_total: float
    liabilities: List[BalanceSheetAccountRow]
    liability_total: float
    equities: List[BalanceSheetAccountRow]
    equity_total: float
    retained_earnings: float
    total_equity_side: float
    total_liabilities_and_equity: float
    is_balanced: bool
    period_net_income: float
    period_start: str
    period_end: str
    note: Optional[str] = None


# =============================================================================
# 💰 งบประมาณ (Budget) — F2
# =============================================================================
# 📌 สัญญาที่สำคัญ: `start_date`/`end_date` คือ **แหล่งความจริงเดียว** ของช่วงที่ใช้คิดยอดจริง
#    ส่วน `period_type`/`period_year`/`period_month` เป็น **ฟิลด์แสดงผลที่ service derive เอง**
#    จากช่วงนั้น (ไม่รับจาก client) ⇒ เป็นไปไม่ได้ที่ป้าย "เดือน ก.ย. 2569" จะขัดกับตัวเลข
#    ที่คิดจากช่วงจริง — ถ้าให้ client ส่งมาเอง มันจะเพี้ยนกันได้ทันทีที่มีคนแก้วันที่ทีหลัง
class BudgetCreate(BaseModel):
    category_id: int
    amount: float = Field(..., gt=0.0, description="วงเงินงบประมาณ (บาท)")
    start_date: date
    end_date: date
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _validate_period(self):
        if self.end_date < self.start_date:
            raise ValueError("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")
        return self


class BudgetUpdate(BaseModel):
    """PATCH — ส่งมาแค่ฟิลด์ที่จะแก้ (service ใช้ `model_dump(exclude_unset=True)`)."""
    amount: Optional[float] = Field(None, gt=0.0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _validate_period(self):
        # ตรวจได้เฉพาะเมื่อส่งมาทั้งคู่ — เคสส่งตัวเดียวต้องเทียบกับค่าที่มีอยู่ใน DB
        # ซึ่ง service ทำอีกชั้น (คืน 400 ไม่ใช่ 422 เพราะต้องอ่าน DB ก่อน)
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")
        return self


class BudgetResponse(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    period_type: str
    period_year: int
    period_month: Optional[int] = None
    start_date: date
    end_date: date
    amount: float
    note: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class BudgetItem(BaseModel):
    """หนึ่งงบ + ยอดใช้จริงในช่วงของ **ตัวมันเอง** (ไม่ใช่ช่วงที่ผู้ใช้กรอง)"""
    budget_id: int
    category_id: int
    category_name: str
    category_type: str
    amount: float
    used: float
    # ติดลบได้เมื่อใช้เกินงบ — เป็นสัญญาณที่มีประโยชน์ จึงไม่ clamp ที่ 0
    remaining: float
    usage_pct: Optional[float] = None
    is_over: bool
    is_near: bool
    period_start: date
    period_end: date
    period_type: str
    note: Optional[str] = None


class BudgetOverviewResponse(BaseModel):
    start_date: date
    end_date: date
    items: List[BudgetItem]
    total_budget: float
    total_used: float
    over_count: int
    warning_count: int


# =====================================================================
# [F3] ใบเสร็จ / ใบแจ้งหนี้
# =====================================================================
class ReceiptIssueRequest(BaseModel):
    """ออกใบเสร็จ/ใบแจ้งหนี้ 1 ใบ"""
    payment_id: int = Field(..., gt=0, description="student_payments.id ของบิล")
    # 🎯 ไม่ส่ง = ใช่งวดรับเงินล่าสุดของบิลนั้น (ตรงกับ student_payments.transaction_id)
    #    ส่ง = ระบุ "งวด" ที่ต้องการออกใบเสร็จ (finance_transactions.id ของงวดนั้น)
    transaction_id: Optional[int] = Field(None, gt=0)
    doc_type: str = Field("receipt", pattern="^(receipt|invoice)$")
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class ReceiptBatchIssueRequest(BaseModel):
    """ออกใบเสร็จหลายบิลพร้อมกัน (all-or-nothing)"""
    # จำกัด 100 ใบ/ครั้ง — มากกว่านี้ควรเป็นงานเบื้องหลัง ไม่ใช่ HTTP request
    payment_ids: List[int] = Field(..., min_length=1, max_length=100)
    doc_type: str = Field("receipt", pattern="^(receipt|invoice)$")
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class ReceiptInvoiceIssueRequest(BaseModel):
    """ออกใบแจ้งหนี้ **ยอดค้างรวมต่อคน** ให้กลุ่มนักเรียนที่เลือก — 1 คน = 1 ใบ

    🎯 ไม่รับ `payment_id` โดยเจตนา: ยอดบนใบคือยอดค้างรวม **ทุกบิลที่ยัง pending**
       ของคนนั้น ⇒ "จะแจ้งหนี้บิลไหน" ไม่ใช่คำถามที่มีความหมายอีกต่อไป
       สิ่งที่ผู้ใช้เลือกคือ **"คน"** ไม่ใช่ "บิล"
    """
    # 🚧 เพดาน 100 คน/ครั้ง: คำขอเดียว = การเขียน 100 แถว + 100 เลข INV
    #    (เท่ากับเพดานของ `ReceiptBatchIssueRequest` โดยเจตนา — "หนึ่ง HTTP request"
    #     ของระบบนี้มีขนาดเท่ากันไม่ว่าจะเป็นเส้นทางไหน)
    student_ids: List[int] = Field(..., min_length=1, max_length=100)
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class ReceiptRoomInvoiceRequest(BaseModel):
    """ออกใบแจ้งหนี้ให้ **ทุกคนที่มียอดค้าง** ในห้อง — ระบบเป็นคนหาว่าใครค้างเอง

    ⇒ ไม่รับ `student_ids` เลยโดยเจตนา: ถ้ารับ ผู้เรียกจะกลายเป็นคนตัดสินว่าใครควรได้ใบ
      ซึ่งเป็นสิ่งที่ผู้ใช้เลือกไม่ถูก (เขาไม่รู้ว่าใครค้างเท่าไร ณ วินาทีที่กด)
    """
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class ReceiptCombinedPdfRequest(BaseModel):
    """รวมเอกสารหลายใบเป็น PDF ไฟล์เดียว (หน้าละใบ)

    ⚠️ **ไม่** ใส่ `max_length` ที่นี่โดยเจตนา: เพดาน 100 ฉบับถูกบังคับใน service
       ซึ่งตอบเป็นข้อความไทยที่บอกทางออก ("แบ่งดาวน์โหลดเป็นรอบละไม่เกิน 100 ฉบับ")
       ส่วน `max_length` ของ Pydantic จะกลายเป็น 422 ที่ frontend แปลงได้แค่
       "ข้อมูลไม่ถูกต้อง" ⇒ ผู้ใช้ที่เลือก 101 ใบจะไม่รู้ว่าต้องทำอย่างไรต่อ
       (ต่างจาก `student_ids` ข้างบนที่เพดานเป็นเรื่อง "ขนาดงานที่ยอมรับ" ไม่ใช่ "วิธีแก้")
    """
    receipt_nos: List[str] = Field(..., min_length=1)


class ReceiptLineItem(BaseModel):
    """หนึ่งบรรทัดในตารางแจกแจงของใบแจ้งหนี้รวมยอด (**snapshot** ณ วันออกเอกสาร)

    🔴 ค่าชุดนี้ถูกอ่านจาก `finance_receipts.line_items` ตรง ๆ **ไม่คำนวณใหม่** —
       ใบที่พิมพ์ซ้ำหลังนักเรียนจ่ายบางส่วนต้องได้บรรทัดเดิมเป๊ะ ไม่งั้นผลรวมของบรรทัด
       จะไม่เท่ากับยอดพาดหัว (ที่เก็บไว้ตอนออก) = เอกสารขัดแย้งตัวเอง
    """
    title: Optional[str] = None
    amount: float
    # 📅 ISO `YYYY-MM-DD` (JSON ไม่มีชนิด DATE) — frontend จัดรูปเป็นไทยเองที่เดียวกับ
    #    วันที่อื่น ๆ ในระบบ ⇒ จอกับกระดาษได้สตริงเดียวกันจาก `THAI_MONTHS_SHORT`
    due_date: Optional[str] = None


class ReceiptResponse(BaseModel):
    id: int
    receipt_no: str
    doc_type: str
    doc_type_label: Optional[str] = None
    year_be: int
    seq: int
    student_payment_id: Optional[int] = None
    legacy_transaction_id: Optional[int] = None
    student_id: Optional[int] = None
    collection_id: Optional[int] = None
    amount: float
    amount_text: Optional[str] = None
    paid_total_after: float
    issued_to_name: Optional[str] = None
    issued_by_name: Optional[str] = None
    note: Optional[str] = None
    # 📋 ตารางแจกแจงของใบแจ้งหนี้รวมยอด — `None` = เอกสารใบเดียวต่อหนึ่งบิล (ใบเสร็จทุกใบ)
    #    ⚠️ ใน **ทะเบียนเอกสาร** (`GET /finance/receipts`) ค่านี้เป็น None เสมอโดยเจตนา
    #       (คิวรีนั้นไม่ดึง jsonb มาด้วย — โหลดได้ถึง 500 แถว) ⇒ ไม่ใช่บั๊ก
    line_items: Optional[List[ReceiptLineItem]] = None
    # 🗓️ "วันที่ของเอกสาร" = เวลาของ **เหตุการณ์** (รับเงิน / ออกใบแจ้งหนี้) ไม่ใช่วันที่กดพิมพ์
    #    ⇒ frontend ต้องแสดงค่านี้ ไม่ใช่ issued_at ไม่งั้นจอกับกระดาษลงคนละวัน
    #    (ของเดิมที่มีอยู่ก่อนเพิ่มคอลัมน์นี้จะไม่มีค่า → frontend ถอยไปใช้ issued_at)
    event_at: Optional[datetime] = None
    # 🚫 active | voided — ใบที่ void แล้วจะไม่ถูกคืนจาก list/detail เว้นแต่ส่ง include_voided=true
    status: str = "active"
    voided_at: Optional[datetime] = None
    void_reason: Optional[str] = None
    # issued_at เป็น timestamptz → tz-aware เสมอ (กฎเดียวกับ TransactionResponse.created_at)
    # ⚠️ สำหรับใบแจ้งหนี้ `event_at == issued_at` เป๊ะ (ทั้งคู่อ่านจาก DB เวลาเดียวกัน)
    issued_at: Optional[datetime] = None


class ReceiptListItem(ReceiptResponse):
    """แถวในหน้ารายการ — แนบชื่อแคมเปญ/เลขที่นักเรียนมาให้ตารางแสดงได้โดยไม่ต้องยิงเพิ่ม"""
    collection_title: Optional[str] = None
    student_no: Optional[int] = None


class ReceiptDetailResponse(ReceiptListItem):
    collection_amount: Optional[float] = None
    collection_due_date: Optional[date] = None
    room_name: Optional[str] = None
    room_code: Optional[str] = None


class ReceiptIssueResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    receipt: ReceiptResponse
    # 🔁 True = คืนใบเดิมที่มีอยู่แล้ว (ไม่ใช่ error — การพิมพ์ซ้ำต้องปลอดภัย)
    reused: bool = False


class TransactionRevertResponse(SuccessResponse):
    """คำตอบของ `DELETE /finance/transactions/{id}`

    🧾 ต้องประกาศ `voided_receipts` ที่นี่ **ไม่ใช่ปล่อยให้ service คืนดิกชันลอย ๆ**:
    route นี้มี `response_model` ⇒ ฟิลด์ที่ไม่อยู่ในโมเดลจะถูก **ตัดทิ้งเงียบ ๆ**
    ⇒ ตัวเลขใบเสร็จที่ถูกยกเลิกจะไม่ถึงผู้ใช้เลยทั้งที่ service ใส่มาครบ
    (และไม่มีเทสต์ไหนจับได้ถ้าไม่ได้ตรวจ body — ตรวจแต่ status 200)
    """
    # เลขที่ใบเสร็จทั้งหมดที่ถูกยกเลิกเพราะรายการนี้ (ว่าง = รายการนี้ไม่มีใบเสร็จผูกอยู่)
    voided_receipts: List[str] = []


class ReceiptBatchIssueResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    receipts: List[ReceiptResponse]
    issued_count: int
    reused_count: int


class InvoiceSkipItem(BaseModel):
    """นักเรียนที่ **ถูกข้าม** ในการออกใบแจ้งหนี้ทั้งห้อง พร้อมเหตุผลที่ข้าม

    🎯 มีไว้เพื่อให้ผู้ใช้ตอบได้ว่า "ทำไมออกได้ 38 ใบทั้งที่มี 40 คน" โดยไม่ต้องไล่เปิด
       หน้าลูกหนี้ทีละคน — ถ้าไม่มีเหตุผลกำกับ ผู้ใช้จะเห็นเป็นความผิดพลาดของระบบ
    """
    student_id: int
    student_no: Optional[int] = None
    student_name: Optional[str] = None
    reason: str


class InvoiceBatchIssueResponse(BaseModel):
    """คำตอบของเส้นทางออกใบแจ้งหนี้ (เลือกเป็นรายคน / ทั้งห้อง)

    🔴 `skipped` **ต้อง** ประกาศที่นี่: route มี `response_model` ⇒ ฟิลด์ที่ไม่อยู่ในโมเดล
       ถูกตัดทิ้งเงียบ ๆ ⇒ ผู้ใช้จะเห็น "ออก 38 ฉบับ" โดยไม่มีทางรู้ว่ามี 2 คนถูกข้าม
       (กับดักเดียวกับที่ `TransactionRevertResponse` เตือนไว้ — อ่านคอมเมนต์ที่นั่น)
    ⚠️ `issued_count` = `len(receipts)` **ไม่นับ** คนที่ถูกข้าม (คนละความหมายกับ `skipped`)
    """
    status: str = "success"
    message: Optional[str] = None
    receipts: List[ReceiptResponse]
    issued_count: int
    skipped: List[InvoiceSkipItem] = []