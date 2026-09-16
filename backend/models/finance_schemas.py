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

    # ── 🏦 [F6] ช่องทางจ่ายเงินของกระเป๋า ─────────────────────────────────────
    # 🔴 "จ่ายเงินผ่านช่องทางไหน" เป็นคุณสมบัติของ **กระเป๋า** ไม่ใช่ของรายการ
    #    (ข้อตกลงข้อ 6) ⇒ กรอกครั้งเดียวที่หน้าตั้งกระเป๋า แล้วใบสำคัญจ่ายดึงไปพิมพ์เอง
    #    ⇒ ผู้ใช้ไม่ต้องเลือก "เงินสด/โอน" ทุกครั้งที่บันทึกรายจ่าย ซึ่งเป็นจุดที่คนลืม
    #    ⚠️ `cash` เป็นค่าตั้งต้น เพราะกระเป๋าที่มีอยู่เดิมทั้งระบบเป็นเงินสด
    #       (คอลัมน์มี DEFAULT 'cash' เหมือนกัน — ค่าใหม่ต้องไม่ทำให้ของเก่าพัง)
    account_kind: str = Field("cash", pattern="^(cash|transfer)$")
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_account_no: Optional[str] = Field(None, max_length=50)
    bank_account_name: Optional[str] = Field(None, max_length=150)

class TransactionCreate(BaseModel):
    account_id: int
    category_id: int
    amount: float = Field(..., gt=0.0)
    description: str = Field(..., max_length=255)
    transaction_type: str = Field(..., pattern="^(income|expense)$")
    slip_image_url: Optional[str] = None
    user_name: str

    # ── [F6] ข้อมูลที่ใบสำคัญจ่าย / ใบรับเงิน ต้องพิมพ์ ───────────────────────────
    # 🔴 **ไม่บังคับที่ Pydantic โดยเจตนา** — บังคับใน service (`add_transaction`)
    #    เพื่อให้ผู้ใช้ได้ **400 ภาษาไทยที่บอกทางออก** ("ต้องระบุผู้เบิก/ผู้รับเงิน")
    #    ไม่ใช่ 422 ดิบของ Pydantic ที่พูดถึง JSON schema
    #    💡 ผลพลอยได้ที่สำคัญ: เทสต์ที่ POST รายจ่ายโดยคาด 400 จากเหตุอื่น
    #       (ยอดเกิน / หมวดผิด) **ยังทดสอบสิ่งที่มันตั้งใจทดสอบ** ไม่กลายเป็น
    #       false positive ที่ผ่านเพราะไปติดด่านใหม่นี้แทน (ดู `docs/skills.md`)
    #    ⚠️ `payee_name` ใช้ทั้งสองทิศ: ฝั่งรายจ่าย = "ผู้เบิก/ผู้รับเงิน"
    #       ฝั่งรายรับ = "ผู้จ่ายเงิน (คนที่ให้เงินกับห้อง)" — เพราะเอกสารทั้งสองใบ
    #       ต้องระบุ "อีกฝ่าย" เสมอ · ช่องเดียวที่ป้ายเปลี่ยนตามแท็บ ดีกว่าสองช่องที่ไม่มีใครรู้ว่าต่างกันยังไง
    payee_name: Optional[str] = Field(None, max_length=150)
    approver_name: Optional[str] = Field(None, max_length=150)
    attachment_count: int = Field(0, ge=0)


class TransactionCreateResponse(SuccessResponse):
    """ผลของ `POST /finance/transactions` — **รวมเลขเอกสารที่เพิ่งออก**

    🔴 ทำไมต้องมีคลาสนี้แทน `SuccessResponse` เฉย ๆ: FastAPI ตัดฟิลด์ที่ไม่อยู่ใน
       `response_model` ทิ้ง **เงียบ ๆ** ⇒ ต่อให้ service คืน `receipt_no` มา หน้าจอก็ไม่เห็น
       และจะไม่มีอะไรฟ้องเลย — เจอเป็น **ครั้งที่สอง** ในโปรเจกต์นี้ (ครั้งแรกคือ
       `BatchPaymentConfirmResponse`) ⇒ ถ้าไม่ประกาศคลาสนี้ ผู้ใช้จะบันทึกรายจ่ายสำเร็จ
       แต่ **ไม่มีทางรู้เลขใบสำคัญจ่ายที่เพิ่งออก** ทั้งที่มันถูกเขียนลง DB แล้ว

    📄 หน้าจอใช้ `receipt_no` + `doc_type` สร้างลิงก์ดาวน์โหลด PDF ทันทีหลังบันทึก
       (reuse `downloadReceiptPdf` เดิม) ⇒ ไม่ต้องยิง `GET /finance/receipts` ซ้ำ
       แล้วเดาว่าใบไหนคือ "ใบที่เพิ่งออก"
    """

    receipt_no: Optional[str] = None
    doc_type: Optional[str] = None
    doc_type_label: Optional[str] = None

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
    # 🧾 [F5] ออกใบเสร็จให้ทุกรายการที่รับเงินไปในรอบนี้ — **default เปิด** ตามคำขอผู้ใช้
    #    ("กดเคลียร์หนี้แล้วอยากได้ใบเสร็จมาพร้อมกันหมดเลย") ⇒ ปิดได้ด้วยติ๊กในโมดัล
    #    ⚠️ การออกใบเสร็จเกิด **ใน transaction เดียวกับการรับเงิน** ⇒ ถ้าเลขเอกสารไม่พอ
    #       จะไม่มีการรับเงินเกิดขึ้นเลย ไม่ใช่รับเงินแล้วไม่มีใบเสร็จ
    issue_receipts: bool = True

# --- Schemas สำหรับส่งออกข้อมูล (Responses) ---
class AccountResponse(BaseModel):
    id: int
    account_name: str
    balance: float
    # 🏦 [F6] ช่องทางจ่ายเงิน — 🔴 **ต้องประกาศที่นี่ ไม่งั้นถูกตัดทิ้งเงียบ ๆ**
    #    `routers/finance/accounts.py:41` ใช้ `response_model=List[AccountResponse]`
    #    ⇒ service ส่งมาครบแต่หน้าจอไม่เห็น แล้วจะไม่มีเทสต์ไหนจับได้ถ้าตรวจแค่ status
    #    (กับดักเดียวกับ `TransactionCreateResponse`/`DebtorItem.credit_balance`)
    #    ⚠️ `account_kind` มีค่า default เพื่อให้แถวที่ service ไม่ได้เลือกคอลัมน์นี้
    #       (ถ้ามีในอนาคต) ไม่ทำให้ route ล้มทั้งอัน
    account_kind: str = "cash"
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None

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
    """PATCH กระเป๋าเงิน — **ทุกฟิลด์ไม่บังคับ** (ส่งมาแต่ตัวที่จะแก้)

    🔴 `account_name` เปลี่ยนจาก *บังคับ* เป็น *ไม่บังคับ* พร้อมกับที่ service เปลี่ยนไปใช้
       `model_dump(exclude_unset=True)`: หน้าจอมีสองกรณีที่ต้องแก้ **เฉพาะช่องทางจ่าย**
       (สลับ เงินสด ↔ โอน) โดยไม่แตะชื่อ ⇒ ถ้ายังบังคับ ช่องทางจะแก้ไม่ได้เลย
       เว้นแต่ frontend จะส่งชื่อเดิมกลับมา ซึ่งเป็นสัญญาที่เปราะ (ชื่อเปลี่ยนที่อื่นแล้วพังเงียบ)

    ⚠️ `exclude_unset` แปลว่า "ส่ง `null` มา" = **ล้างค่านั้นจริง** ไม่ใช่ "ไม่แตะ"
       ⇒ การแยกสองกรณีนี้ออกเป็นหน้าที่ของ service (`_ACCOUNT_PATCHABLE`)
    """
    account_name: Optional[str] = Field(None, max_length=100)
    user_name: Optional[str] = Field(None, max_length=100)
    # 🏦 ช่องทางจ่ายเงิน — ดูเหตุผลเต็มที่ `AccountCreate`
    account_kind: Optional[str] = Field(None, pattern="^(cash|transfer)$")
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_account_no: Optional[str] = Field(None, max_length=50)
    bank_account_name: Optional[str] = Field(None, max_length=150)

# --- Schemas สำหรับ ทวงหนี้รวม ---
class DebtorItem(BaseModel):
    student_id: int
    student_no: int
    student_name: str
    overdue_count: int
    # 💵 ยอดค้าง **ดิบ** (ไม่หักเครดิต) — ความหมายเดิม ไม่เปลี่ยน
    total_pending_amount: float
    # 🎯 [F4] ยอดที่ต้องเก็บจริงหลังหักเครดิตคงเหลือ + ยอดเครดิตที่หักได้
    #    ⚠️ ต้องประกาศในนี้ ไม่งั้น route ที่มี `response_model` จะ **ตัดทิ้งเงียบ ๆ**
    #    (กับดักเดียวกับที่ `TransactionRevertResponse` เตือนไว้ — service ส่งมาครบ
    #     แต่ผู้ใช้ไม่เห็น แล้วจะไม่มีเทสต์ไหนจับได้ถ้าตรวจแค่ status code)
    credit_balance: float = 0.0
    net_pending_amount: float = 0.0

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
    # 🧾 เอกสารนี้พูดด้วยถ้อยคำของ **ใบเสร็จ** (เงินเข้ามือแล้ว) หรือ **ใบแจ้งหนี้** (ยังไม่ได้รับ)?
    #
    # 🔴 ส่งมาจาก backend เพื่อให้จอกับกระดาษตอบเหมือนกันจากแหล่งเดียว
    #    (`RECEIPT_LIKE_DOC_TYPES` ใน `services/finance/constants.py`) — เดิมหน้าจอคำนวณ
    #    เองจาก `doc_type` ⇒ เพิ่มชนิดใหม่แล้วลืมแก้ฝั่งจอ = แสดง "เรียกเก็บจาก"/"ยอดค้างชำระ"
    #    บนใบรับเงิน **โดยไม่มี error ให้เห็น** (กับดักที่ `ReceiptDetail.vue` เขียนเตือนไว้เอง)
    #    ⚠️ ฟิลด์นี้ต้องประกาศที่นี่เสมอ ไม่งั้น `response_model=` จะตัดทิ้งเงียบ ๆ
    is_receipt: bool = False
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
    # 📚 ชุดเอกสารที่ใบนี้สังกัด (None = ไม่ได้จัดกลุ่ม) — [F5]
    #    อยู่บน base ไม่ใช่ list item เพราะ "การออกเอกสาร" ก็ต้องบอกได้ว่าเพิ่งสร้างชุดไหน
    #    (ผู้ใช้กดออก 20 ใบแล้วอยากโหลดทั้งชุดทันที ⇒ ต้องรู้ `batch_id` จากคำตอบนั้นเลย)
    batch_id: Optional[int] = None


class ReceiptListItem(ReceiptResponse):
    """แถวในหน้ารายการ — แนบชื่อแคมเปญ/เลขที่นักเรียนมาให้ตารางแสดงได้โดยไม่ต้องยิงเพิ่ม"""
    collection_title: Optional[str] = None
    student_no: Optional[int] = None
    # 📚 [F5] ข้อมูลชุดสำหรับ "ยุบการแสดงผล" ในทะเบียน
    #    🔴 `batch_size` = สมาชิก **ทั้งชุด** ไม่ใช่จำนวนแถวที่รอดตัวกรองของหน้าจอ
    #       (คำนวณจากคำขอที่สองใน `_load_batch_counts`) — ตัวเลขนี้คือสิ่งที่ทำให้ป้าย
    #       "แสดง 12 จาก 20 ใบ" พูดความจริงเมื่อผู้ใช้กรองช่วงวันที่
    batch_title: Optional[str] = None
    batch_size: Optional[int] = None
    batch_voided_count: Optional[int] = None


class VoucherBudget(BaseModel):
    """งบหนึ่งก้อนที่ **ครอบวันของรายการ** — snapshot ณ วันออกเอกสาร

    🔎 งบเป็น implicit: `finance_budgets` ไม่มี FK มาหารายการ ผูกด้วย
       `room_id + category_id + ช่วงวันที่` เท่านั้น ⇒ ก้อนนี้คือคำตอบที่คำนวณไว้ตอนออกใบ
       ไม่ใช่การ JOIN สด (งบที่ถูกแก้/ลบทีหลังต้องไม่เปลี่ยนใบที่พิมพ์ไปแล้ว)
    """
    id: int
    # 💰 cast float มาแล้วจาก service — DECIMAL กลับมาจาก asyncpg เป็น `Decimal`
    amount: float
    # 📅 ISO `YYYY-MM-DD` (JSON ไม่มีชนิด DATE) — เหตุผลเดียวกับ `ReceiptLineItem.due_date`
    start_date: str
    end_date: str
    period_type: str


class VoucherFields(BaseModel):
    """ฟิลด์ของ **ใบสำคัญจ่าย** — snapshot ทั้งชุด อ่านจาก `finance_receipts.voucher_snapshot`

    🔴 ทำไมต้องประกาศที่นี่เสมอ: `response_model=` ของ FastAPI เป็น **ตัวกรองขาออก** —
       คีย์ที่โมเดลไม่ได้ประกาศจะถูกตัดทิ้ง **เงียบ ๆ** ไม่มี warning และไม่มี error
       ⇒ `_shape_receipt_detail` ตั้งค่าครบทุกคีย์ (คอมเมนต์ของมันเขียนว่า "ตั้งเสมอ")
       แต่หน้าจอไม่เห็นอะไรเลย

    💥 เคสจริงที่เกิดขึ้น (2026-09): ฟิลด์ชุดนี้ถูกลืมที่นี่ ⇒ `GET /finance/receipts/{no}`
       คืน `budgets` เป็น `undefined` ⇒ `ReceiptDetail.vue` ที่เข้าถึง `detail.budgets.length`
       **throw ตอน render** ⇒ Vue ทิ้ง subtree ทั้งหน้า เหลือแต่ skeleton "กำลังโหลดข้อมูล"
       ค้างบนพื้นขาว = "หน้าขาว ๆ แปลก ๆ" ที่ผู้ใช้รายงาน **โดยไม่มี error ฝั่งเซิร์ฟเวอร์เลย**
       และเทสต์ทุกตัวยังเขียว เพราะเทสต์ของใบสำคัญจ่ายวิ่งผ่านเส้นทาง **PDF** ซึ่งไม่ประกาศ
       `response_model` (คืน binary stream) ⇒ ไม่มีเทสต์ใดแตะเส้นทาง JSON ที่หน้าจอใช้จริง

    ⚠️ บทเรียนเดียวกับ `is_receipt` ที่ `ReceiptResponse` เขียนเตือนไว้แล้ว — ครั้งนั้นจำได้
       ครั้งนี้ลืม ⇒ ถ้าเพิ่มฟิลด์ให้ใบสำคัญจ่าย ต้องมาเพิ่มที่นี่ด้วยเสมอ
    """
    approver_name: Optional[str] = None
    attachment_count: int = 0
    account_name: Optional[str] = None
    # 💰 cash | transfer — ใช้ `str` ไม่ใช่ Literal โดยเจตนา: ค่าที่ไม่รู้จักต้องไม่ทำให้
    #    หน้า detail เป็น 500 (frontend แสดงช่องทางเฉพาะที่รู้จัก ดู `voucherChannel`)
    account_kind: Optional[str] = None
    # 🏦 สามตัวนี้มีค่าเฉพาะ `account_kind == 'transfer'`
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None
    category_name: Optional[str] = None
    # 📋 **ลิสต์ว่าง = "ไม่อยู่ในงบประมาณที่ตั้งไว้"** ซึ่งต่างจาก "ยังไม่ได้ตั้งงบ"
    #    ⇒ ห้ามให้คีย์นี้หายไปแล้ว frontend ตีความเป็นอย่างใดอย่างหนึ่ง
    budgets: List[VoucherBudget] = []


class ReceiptDetailResponse(ReceiptListItem, VoucherFields):
    collection_amount: Optional[float] = None
    collection_due_date: Optional[date] = None
    room_name: Optional[str] = None
    room_code: Optional[str] = None


class BatchPaymentConfirmResponse(SuccessResponse):
    """ผลของ `PUT /finance/payments/batch` — เงินที่รับ **บวก** ใบเสร็จที่ออกให้ในรอบนั้น

    🔴 ทำไมต้องมีคลาสนี้แทน `SuccessResponse` เฉย ๆ: FastAPI ตัดฟิลด์ที่ไม่อยู่ใน
       `response_model` ทิ้ง **เงียบ ๆ** ⇒ ต่อให้ service คืน `receipts` มา หน้าจอก็ไม่เห็น
       และจะไม่มีอะไรฟ้องเลย (บทเรียนเดียวกับ `docs/skills.md` เรื่อง response_model)

    📄 `receipts` เป็น `ReceiptResponse` ทั้งก้อน (ไม่ใช่แค่เลขที่) เพื่อให้หน้าจอ
       **ดาวน์โหลด PDF รวมได้ทันที** จากคำตอบนี้โดยไม่ต้องยิง `GET /finance/receipts` ซ้ำ
       (ยิงซ้ำยังต้องเดาว่าจะกรองยังไงให้ได้ "เฉพาะใบที่เพิ่งออก" ซึ่งเปราะกว่ามาก)
    """
    receipts: List[ReceiptResponse] = []
    issued_count: int = 0
    reused_count: int = 0
    # 📚 ชุดที่ระบบจัดให้อัตโนมัติเมื่อออก ≥ 2 ใบ — `None` = ไม่ได้จัดชุด (ออกใบเดียว
    #    หรือผู้ใช้ปิดติ๊กออกใบเสร็จ) ⇒ หน้าจอใช้สร้างลิงก์ "ดูทั้งชุด" ได้
    batch_id: Optional[int] = None


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
    # 📚 [F5] ชุดที่ระบบสร้างให้รอบนี้ (None = ออกใบเดียว/ไม่มีใบใหม่ ⇒ ไม่มีชุด)
    batch_id: Optional[int] = None


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
    # 📚 [F5] ชุดที่ระบบสร้างให้รอบนี้ (None = ออกใบเดียว/ไม่มีใบใหม่ ⇒ ไม่มีชุด)
    batch_id: Optional[int] = None

# =====================================================================
# [F4] เงินรับล่วงหน้า / เครดิตคงเหลือรายนักเรียน
# =====================================================================
class CreditTopUpRequest(BaseModel):
    """เติมเงินล่วงหน้าให้นักเรียน 1 คน (รับเงินจริง → เก็บพักเป็นเครดิต)"""
    student_id: int = Field(..., gt=0)
    # 💰 `gt=0` ที่ชั้น schema เป็นด่านแรก (422 อ่านรู้เรื่องกว่า 400) ส่วนด่าน "ปัดเป็น
    #    สตางค์แล้วเหลือ 0" (0.004) อยู่ที่ service เพราะต้อง round ก่อนจึงจะรู้
    amount: float = Field(..., gt=0, description="ยอดที่รับเข้ามาพัก (บาท)")
    paid_to_account_id: int = Field(..., gt=0, description="กระเป๋าที่เงินเข้าจริง")
    slip_image_url: Optional[str] = Field(None, max_length=500)
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)
    # 🔑 บังคับ — ดูเหตุผลเต็มที่ `_normalize_idempotency_key` ใน services/finance/credits.py
    #    (ไม่มีค่านี้ = กันกดซ้ำให้ไม่ได้เลย เพราะการเติมเครดิตสร้าง transaction ใหม่ทุกครั้ง)
    idempotency_key: str = Field(
        ..., min_length=8, max_length=64,
        description="รหัสกันบันทึกซ้ำ สร้างฝั่ง client ต่อการกดหนึ่งครั้ง (UUID)",
    )


class CreditApplyRequest(BaseModel):
    """หักเครดิตไปปิดบิลของนักเรียนที่เลือก — ทั้งชุด all-or-nothing"""
    student_ids: List[int] = Field(..., min_length=1, max_length=100)
    user_name: Optional[str] = Field(None, max_length=100)


class CreditUndoRequest(BaseModel):
    """ยกเลิก 'การหักเครดิต' 1 รายการ (ไม่ใช่การเติม — การเติมต้องยกเลิกรายการธุรกรรม)"""
    credit_entry_id: int = Field(..., gt=0)
    reason: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class StudentCreditBalanceResponse(BaseModel):
    """แถวในหน้า "เงินรับล่วงหน้า" — นักเรียนทุกคนของห้อง (คนไม่มีเครดิตก็อยู่ ยอด 0)"""
    student_id: int
    student_no: int
    student_name: str
    credit_balance: float
    # 💵 ยอดค้าง **ดิบ** (ไม่หักเครดิต) — ชื่อบอกตัวเองว่าดิบ ไม่ใช่ยอดที่ต้องเก็บจริง
    total_pending_amount: float
    # 🎯 ยอดที่ต้องเก็บจริงหลังหักเครดิต — ตัวเลขที่ผู้ใช้ใช้ตัดสินใจ
    net_pending_amount: float


class StudentCreditEntryResponse(BaseModel):
    """1 แถวในประวัติเครดิต (append-only ledger)"""
    id: int
    # topup | apply | reverse
    entry_type: str
    entry_type_label: Optional[str] = None
    amount: float
    balance_after: float
    finance_transaction_id: Optional[int] = None
    student_payment_id: Optional[int] = None
    collection_id: Optional[int] = None
    note: Optional[str] = None
    recorded_by: Optional[str] = None
    # created_at เป็น timestamptz ⇒ tz-aware เสมอ (กฎเดียวกับ TransactionResponse.created_at)
    created_at: Optional[datetime] = None
    # 🧾 เลขใบรับเงินล่วงหน้า (DEP) ที่ผูกกับรายการเติมนี้ — None สำหรับรายการหัก
    receipt_no: Optional[str] = None
    receipt_event_at: Optional[datetime] = None
    collection_title: Optional[str] = None


class CreditTopUpResponse(BaseModel):
    """คำตอบของการเติมเครดิต — แนบ `receipt` ที่ออกให้ทันที"""
    status: str = "success"
    message: Optional[str] = None
    credit_entry_id: int
    student_id: int
    student_name: str
    amount: float
    balance_after: float
    finance_transaction_id: Optional[int] = None
    journal_entry_id: Optional[str] = None
    # 🧾 ใบรับเงินล่วงหน้า (DEP) ที่ออกให้ — แนบทั้งใบเพื่อให้ frontend พิมพ์ PDF /
    #    เปิดหน้ารายละเอียดได้ทันทีโดยไม่ต้องยิงไปถามเลขที่เอกสารอีกครั้ง
    receipt: Optional[ReceiptResponse] = None
    # 🔁 True = ใบ DEP นี้มีอยู่ก่อนแล้ว (กดซ้ำด้วยคีย์เดิม) — แยกจาก `reused` ข้างล่าง
    #    เพราะ "ซ้ำที่ใบเอกสาร" กับ "ซ้ำที่การรับเงิน" เป็นคนละคำถาม
    receipt_reused: bool = False
    # 🔁 True = คีย์นี้เคยบันทึกสำเร็จแล้ว (กดซ้ำ) — ไม่ใช่ error และ **ไม่ใช่การรับเงินรอบที่สอง**
    reused: bool = False


class CreditAllocationItem(BaseModel):
    """หนึ่งบิลที่จะถูกหัก (หรือถูกหักไปแล้ว)"""
    payment_id: int
    collection_id: int
    title: Optional[str] = None
    due_date: Optional[date] = None
    bill_total: float
    bill_paid_before: float
    bill_remaining_before: float
    apply_amount: float
    bill_paid_after: float
    bill_status_after: str
    remaining_after: float


class CreditPlanItem(BaseModel):
    """ข้อเสนอการหักของนักเรียน 1 คน"""
    student_id: int
    student_no: Optional[int] = None
    student_name: Optional[str] = None
    balance_before: float
    allocations: List[CreditAllocationItem] = []
    total_applied: float
    balance_after: float


class CreditApplyPlanResponse(BaseModel):
    """ข้อเสนอการหักทั้งชุด — ใช้ทั้งตอน **ดูตัวอย่าง** (`GET .../plan`) และตอน **ลงมือ**
    (`POST .../apply`) ⇒ สิ่งที่ครูเห็นก่อนกดกับสิ่งที่ระบบทำต้องหน้าตาเหมือนกันเป๊ะ"""
    status: str = "success"
    message: Optional[str] = None
    items: List[CreditPlanItem]
    total_applied: float
    total_balance_after: float
    # 📊 สรุปผลหลังลงมือ (0/None สำหรับเส้นทางดูตัวอย่าง)
    bills_paid: Optional[int] = None
    student_ids: Optional[List[int]] = None


class CreditOpenBillItem(BaseModel):
    """บิลที่ยังค้างของนักเรียน 1 คน (ยอดดิบ ยังไม่หักเครดิต)"""
    payment_id: int
    collection_id: int
    title: Optional[str] = None
    due_date: Optional[date] = None
    total_amount: float
    paid_amount: float
    remaining_amount: float


class CreditUndoResponse(BaseModel):
    """คำตอบของ `POST /finance/credits/undo`

    ⚠️ ไม่ใช่ `StudentCreditEntryResponse`: การยกเลิก **สร้างแถวใหม่** (reverse) และ
       **ลบแถวเดิม** (soft delete) ⇒ แถวที่ควรอธิบายให้ผู้ใช้เห็นคือ "ผลลัพธ์ที่เกิดขึ้น"
       ไม่ใช่รูปร่างของแถวใดแถวหนึ่ง (ถ้าฝืนใช้โมเดลนั้น ฟิลด์จะหายแล้วได้ 500
       ResponseValidationError แทนที่จะเป็นข้อความที่อ่านรู้เรื่อง)
    """
    status: str = "success"
    message: Optional[str] = None
    credit_entry_id: int
    reverse_entry_id: int
    student_id: int
    student_payment_id: Optional[int] = None
    reverted_amount: float
    bill_paid_amount: float
    bill_status: str
    credit_balance_after: float


class StudentCreditDetailResponse(BaseModel):
    """รายละเอียดเครดิตของนักเรียน 1 คน"""
    student_id: int
    student_no: int
    student_name: str
    credit_balance: float
    entries: List[StudentCreditEntryResponse]
    open_bills: List[CreditOpenBillItem]
    plan: CreditPlanItem


# =====================================================================
# [F5] ชุดเอกสาร (Document Batch)
# =====================================================================
class ReceiptBatchResponse(BaseModel):
    """ชุดเอกสาร 1 ชุด — ใช้ทั้งหน้ารายการชุดและคำตอบหลังเขียน

    🔴 `batch_size` = สมาชิก **ทั้งชุด** (ใบที่ยัง active + ใบที่ถูกยกเลิก/ลบ)
       ⇒ `batch_size - batch_voided_count` = จำนวนที่ทะเบียนควรแสดงเมื่อไม่กรองอะไร
       ตัวเลขนี้ต้องมาจากการนับทั้งชุดเสมอ ไม่ใช่จากการนับแถวที่รอดตัวกรอง
    ⚠️ `title` เป็น `None` ได้ = ให้หน้าจอประกอบชื่อเอง ("ชุดใบเสร็จ 20 ใบ · วันที่")
       — ห้ามเก็บสตริงที่ประกอบแล้วลง DB (จะกลายเป็น snapshot ที่โกหกเมื่อมีใบถูกยกเลิก)
    """
    id: int
    room_id: int
    title: Optional[str] = None
    # auto = ออกพร้อมกันในรอบเดียว · room = ออกให้ทั้งห้อง · manual = ผู้ใช้จัดกลุ่มทีหลัง
    source: str
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    # 📊 สรุปของชุด
    active_count: int = 0
    voided_count: int = 0
    batch_size: int = 0
    total_amount: float = 0.0
    # 🗓️ ช่วง "วันที่ของเอกสาร" ของสมาชิก (= `_DOC_DATE` ตัวเดียวกับที่พิมพ์บนกระดาษ)
    first_doc_at: Optional[datetime] = None
    last_doc_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReceiptBatchDetailResponse(BaseModel):
    """ชุด + เอกสารทุกใบในชุด (รวมใบที่ถูกยกเลิก — หน้าจอประทับป้ายเอง)

    ⚠️ อย่าเปลี่ยน `receipts` เป็น `List[ReceiptListItem]`: ที่นี่ต้องได้ข้อมูลครบระดับ
       หน้ารายละเอียด (`collection_amount`/`room_name`) เพราะผู้ใช้กด "ดูรายละเอียด"
       จากในชุดแล้วต้องไม่ต้องยิงซ้ำอีกรอบ
    """
    batch: ReceiptBatchResponse
    receipts: List[ReceiptDetailResponse]


class ReceiptBatchCreate(BaseModel):
    """สร้างชุดจากเลขที่เอกสารที่ติ๊กเลือก"""
    receipt_nos: List[str] = Field(..., min_length=1)
    title: Optional[str] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=255)
    user_name: Optional[str] = Field(None, max_length=100)


class ReceiptBatchSetReceipts(BaseModel):
    """**ตั้งสมาชิกทั้งชุด** = เพิ่มและถอดในคำขอเดียว (ไม่ใช่ "เพิ่มเข้า")

    🔒 ไม่รับ `receipt_nos` ทาง query string โดยเจตนา — เลี่ยงกับดัก axios ที่ serialize
       array เป็น `receipt_nos[]=...` (ดู `docs/skills.md`) ⇒ เลขที่ไปใน body เท่านั้น
    """
    receipt_nos: List[str] = Field(..., min_length=1)


class ReceiptBatchUpdate(BaseModel):
    """PATCH — ส่งมาแค่ฟิลด์ที่จะแก้ (service ใช้ `model_dump(exclude_unset=True)`)

    ⚠️ ส่ง `"title": null` = ล้างชื่อกลับไปใช้ชื่อที่หน้าจอประกอบ (ต่างจาก "ไม่ส่งมา")
    """
    title: Optional[str] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=255)


class ReceiptBatchMutationResponse(BaseModel):
    """คำตอบหลังสร้าง/แก้ชุด

    🔁 `created=False` = ไม่ได้สร้างใหม่ แต่คืนชุดเดิมที่มีสมาชิกชุดเดียวกันอยู่แล้ว
       (กดปุ่มซ้ำต้องไม่สร้างชุดซ้ำ — ดู `create_receipt_batch`)
    """
    batch: ReceiptBatchResponse
    created: bool = False


class ReceiptBatchDissolveResponse(BaseModel):
    """คำตอบหลังยุบชุด — คืนจำนวนใบที่ถูกปลดออกจากชุด (เอกสารไม่ถูกแตะ)"""
    batch_id: int
    detached_count: int
