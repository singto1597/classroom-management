from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from dataclasses import dataclass
from fastapi import Query

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

# --- Schemas สำหรับรับข้อมูล (Requests) ---

class AccountCreate(BaseModel):
    account_name: str = Field(..., max_length=100)
    initial_balance: float = Field(0.0, ge=0.0)

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

class PaymentConfirm(BaseModel):
    paid_to_account_id: int
    paid_amount: float = Field(..., gt=0.0)
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
    student_no: int
    first_name: str
    last_name: str
    nickname: Optional[str]

class CollectionStatusResponse(BaseModel):
    collection_id: int
    summary: StudentPaymentSummary
    students: List[StudentPaymentDetail]

@dataclass
class TransactionFilter:
    limit: int = Query(50, gt=0)
    offset: int = Query(0, ge=0)
    start_date: Optional[str] = Query(None)
    end_date: Optional[str] = Query(None)
    account_id: Optional[int] = Query(None)
    category_id: Optional[int] = Query(None)
    transaction_type: Optional[str] = Query(None, pattern="^(income|expense)$")

# --- Schemas สำหรับ Categories ---
class CategoryCreate(BaseModel):
    category_name: str = Field(..., max_length=100)
    category_type: str = Field(..., pattern="^(income|expense)$")

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
    due_date: date

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

# --- Schemas สำหรับ Account Management ---
class AccountUpdate(BaseModel):
    account_name: str = Field(..., max_length=100)

# --- Schemas สำหรับ ทวงหนี้รวม ---
class DebtorItem(BaseModel):
    student_id: int
    student_no: int
    student_name: str
    overdue_count: int
    total_pending_amount: float

class CategoryUpdate(BaseModel):
    category_name: str = Field(..., max_length=100)