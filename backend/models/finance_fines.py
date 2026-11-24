"""Pydantic v2 — ค่าปรับ (ประเภทความผิด / บิลค่าปรับ / คำขอยกเว้น / คำขอคืนเงิน / aging)

💰 ชนิดเงินใช้ `float` ตามสไตล์ `finance_schemas.py` (service แปลงเป็น Decimal เอง
   และปัด 2 ตำแหน่งทุกก้าว) · วันที่ใช้ `date`/`datetime` เสมอ — ห้าม `str`
   (กันบั๊ก `toordinal()` ที่เคยเกิดกับ query param)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

WaiverCategory = Literal["discount", "uncollectible"]


# ============================================================ ประเภทความผิด
class FineTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    default_amount: float = Field(0.0, ge=0)
    default_due_days: int = Field(7, ge=0, le=365)
    description: Optional[str] = Field(None, max_length=500)
    sort_order: int = 0


class FineTypeUpdate(BaseModel):
    """PATCH — ส่งมาแต่ฟิลด์ที่จะแก้ (`model_dump(exclude_unset=True)`)"""

    name: Optional[str] = Field(None, min_length=1, max_length=150)
    default_amount: Optional[float] = Field(None, ge=0)
    default_due_days: Optional[int] = Field(None, ge=0, le=365)
    description: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class FineTypeResponse(BaseModel):
    id: int
    name: str
    default_amount: float
    default_due_days: int
    description: Optional[str] = None
    is_active: bool
    sort_order: int


class FineTypeCreatedResponse(BaseModel):
    """ผลสร้างประเภท — คืน `id` ให้ฟอร์มออกค่าปรับใช้ต่อได้ทันที"""

    status: str = "success"
    message: Optional[str] = None
    id: int


# ================================================================= ออกค่าปรับ
class FineIssueStudent(BaseModel):
    student_id: int
    # 💡 override ยอดต่อคน (เช่น "อื่น ๆ" ที่ default_amount = 0 ต้องกรอกเอง)
    amount: Optional[float] = Field(None, gt=0)


class FineIssueRequest(BaseModel):
    fine_type_id: int
    students: List[FineIssueStudent] = Field(..., min_length=1)
    incident_date: date
    due_date: Optional[date] = None
    reason: str = Field(..., min_length=1, max_length=1000)
    evidence_url: Optional[str] = Field(None, max_length=1000)
    note: Optional[str] = Field(None, max_length=1000)
    # 🔑 บังคับ — double-submit / retry ต้องไม่สร้างบิลซ้ำ
    idempotency_key: str = Field(..., min_length=8, max_length=100)
    user_name: Optional[str] = Field(None, max_length=100)


class FineUpdateRequest(BaseModel):
    """แก้ค่าปรับ **ก่อนมีคนจ่าย** — เปลี่ยนยอดได้ (journal ปรับส่วนต่าง)"""

    amount: Optional[float] = Field(None, gt=0)
    incident_date: Optional[date] = None
    due_date: Optional[date] = None
    reason: Optional[str] = Field(None, min_length=1, max_length=1000)
    evidence_url: Optional[str] = Field(None, max_length=1000)
    note: Optional[str] = Field(None, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineResponse(BaseModel):
    id: int
    room_id: int
    batch_id: Optional[int] = None
    fine_type_id: Optional[int] = None
    fine_type_name: str
    student_id: int
    student_no: Optional[int] = None
    student_name: Optional[str] = None
    hidden_collection_id: Optional[int] = None
    student_payment_id: int
    invoice_receipt_id: Optional[int] = None
    invoice_no: Optional[str] = None
    incident_date: date
    due_date: date
    reason: str
    original_amount: float
    amount: float
    waived_amount: float
    refunded_amount: float
    paid_amount: float = 0.0
    outstanding: float = 0.0
    status: str
    evidence_url: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    collection_kind: str = "fine"


class FineBatchResponse(BaseModel):
    id: int
    fine_type_id: Optional[int] = None
    fine_type_name: str
    incident_date: date
    due_date: date
    reason: str
    amount_per_student: float
    student_count: int
    total_amount: float


class FineIssueResponse(BaseModel):
    batch: FineBatchResponse
    fines: List[FineResponse]
    totals: Dict[str, float]
    invoice_nos: List[str]
    reused: bool = False


class FineListResponse(BaseModel):
    fines: List[FineResponse]
    total: int


class FineDetailResponse(FineResponse):
    """รายละเอียด + ประวัติคำขอ (waiver/refund) — เรียงใหม่→เก่า"""

    waivers: List[Dict[str, Any]] = []
    refunds: List[Dict[str, Any]] = []


# ============================================================ คำขอยกเว้น/ลด
class FineWaiverCreate(BaseModel):
    amount: float = Field(..., gt=0)
    reason_category: WaiverCategory
    reason: str = Field(..., min_length=1, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineWaiverDecision(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineWaiverResponse(BaseModel):
    id: int
    room_id: int
    fine_id: int
    amount: float
    reason_category: str
    reason: str
    status: str
    requested_by: Optional[int] = None
    requested_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None


class FineWaiverCreatedResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    id: int


class FineWaiverListResponse(BaseModel):
    waivers: List[FineWaiverResponse]
    total: int


class FineWaiverDecisionResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    waiver: FineWaiverResponse


# ================================================================== คืนเงิน
class FineRefundCreate(BaseModel):
    account_id: int
    amount: float = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineRefundDecision(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)
    user_name: Optional[str] = Field(None, max_length=100)


class FineRefundResponse(BaseModel):
    id: int
    room_id: int
    fine_id: int
    account_id: int
    amount: float
    reason: str
    status: str
    requested_by: Optional[int] = None
    requested_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None
    transaction_id: Optional[int] = None
    document_id: Optional[int] = None


class FineRefundCreatedResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    id: int


class FineRefundListResponse(BaseModel):
    refunds: List[FineRefundResponse]
    total: int


class FineRefundDecisionResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None
    refund: FineRefundResponse
    receipt_no: Optional[str] = None


# ============================================================== รายงาน / aging
class AgingBucketResponse(BaseModel):
    label: str
    bucket: str
    count: int
    amount: float
    # ยอดแยกตามที่มาของหนี้ — ให้ frontend วาด stacked bar ได้โดยไม่ต้องคำนวณเอง
    project_amount: float = 0.0
    fine_amount: float = 0.0


class AgingRowResponse(BaseModel):
    payment_id: int
    student_id: int
    student_no: Optional[int] = None
    student_name: str
    collection_id: int
    collection_title: str
    collection_kind: str
    fine_id: Optional[int] = None
    due_date: Optional[date] = None
    outstanding: float
    overdue_days: int
    bucket: str
    bucket_label: str


class AgingResponse(BaseModel):
    as_of: date
    project_total: float
    fine_total: float
    grand_total: float
    buckets: List[AgingBucketResponse]
    rows: List[AgingRowResponse]


class FineSummaryStatusRow(BaseModel):
    status: str
    count: int
    amount: float
    outstanding: float


class FineSummaryTypeRow(BaseModel):
    fine_type_name: str
    count: int
    amount: float
    outstanding: float


class FineSummaryDebtorRow(BaseModel):
    student_id: int
    student_no: Optional[int] = None
    student_name: str
    count: int
    outstanding: float


class FineSummaryResponse(BaseModel):
    as_of: date
    totals: Dict[str, Any]
    by_status: List[FineSummaryStatusRow] = []
    by_type: List[FineSummaryTypeRow] = []
    top_debtors: List[FineSummaryDebtorRow] = []
