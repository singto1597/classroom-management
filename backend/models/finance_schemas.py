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