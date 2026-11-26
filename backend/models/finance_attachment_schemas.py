"""📎 Schemas ของไฟล์หลักฐานการเงิน (รูปภาพ + PDF)

`url` / `thumb_url` เป็น **path relative** (`/api/finance-files/...`) — frontend เติม
`VITE_API_BASE_URL` เอง (backend ไม่รู้ว่าเบราว์เซอร์เข้าผ่านโดเมนไหน)

⚠️ ไม่มี `storage_path` / `thumb_path` ใน response โดยเจตนา — path ภายในไฟล์
    ไม่ควรหลุดถึง client (ถูกแก้ใน DB แล้วยังใช้เปิดไฟล์ไม่ได้อยู่ดี แต่ไม่ต้องเปิดเผย)
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class FinanceAttachmentOut(BaseModel):
    id: str
    owner_type: str
    owner_id: int
    file_kind: str = Field(..., description="image | pdf")
    kind: str
    original_name: Optional[str] = None
    url: str
    thumb_url: Optional[str] = Field(None, description="มีเฉพาะรูปภาพ (PDF ไม่มี thumbnail)")
    mime: str
    width: Optional[int] = None
    height: Optional[int] = None
    page_count: Optional[int] = Field(None, description="จำนวนหน้า (PDF เท่านั้น)")
    bytes: int
    uploaded_by: Optional[int] = None
    created_at: datetime


class FinanceAttachmentLimitsOut(BaseModel):
    max_per_owner: int
    max_per_request: int
    image_size_limit_mb: int
    document_size_limit_mb: int
    max_total_mb: int
    max_pdf_pages: int


class FinanceAttachmentListOut(BaseModel):
    items: List[FinanceAttachmentOut]
    limits: FinanceAttachmentLimitsOut
