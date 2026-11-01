"""Pydantic schemas ของหน้าหลัก (`/home/summary`) — P3

🔑 กติกาของก้อนนี้: **ทุกตัวเลขที่กดได้ต้องมีปลายทางที่กรองตรงกับตัวเลขนั้น**
⇒ ฟิลด์ทุกตัวถูกนับด้วย predicate เดียวกับ endpoint รายการที่มันจะพาไป
(เช่น `overdue` ใช้ `due_date < today AND status='pending'` ตัวเดียวกับ
`GET /tasks?filter=overdue` ฝั่งหน้า)
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class HomeTaskItem(BaseModel):
    id: int
    task_name: str
    due_date: date
    status: str


class HomeTaskSummary(BaseModel):
    pending_total: int = Field(description="งานที่ยังไม่เสร็จทั้งห้อง → /tasks?filter=pending")
    due_today: int = Field(description="งานที่ยังไม่เสร็จและครบกำหนดวันนี้ (เวลาไทย)")
    overdue: int = Field(description="งานที่ยังไม่เสร็จและเลยกำหนดแล้ว")
    items: list[HomeTaskItem] = Field(
        default_factory=list, description="ตัวอย่างงานที่ยังไม่เสร็จ เรียงตามกำหนดส่ง"
    )


class HomeNote(BaseModel):
    bring_items: Optional[str] = None
    announcement: Optional[str] = None


class HomeActivityItem(BaseModel):
    id: int
    title: str
    activity_date: date
    status: str
    base_hours: float


class HomeFinanceSummary(BaseModel):
    has_profile: bool = Field(description="ผู้ใช้มีแถว students ในห้องนี้หรือไม่")
    outstanding: float = Field(0.0, description="ยอดค้างชำระของฉันรวม")
    unpaid_bills: int = Field(0, description="จำนวนบิลที่ยังไม่ชำระครบ")


class HomeAnnouncementSummary(BaseModel):
    unread_count: int = Field(0, description="ประกาศที่ยังไม่อ่านและยังไม่ถูกเก็บถาวร")


class HomeSchedule(BaseModel):
    day_of_week: str
    attire: Optional[str] = None
    subjects: Optional[str] = None
    override_note: Optional[str] = None


class HomeSummaryResponse(BaseModel):
    today: date
    tasks: HomeTaskSummary
    note: Optional[HomeNote] = None
    activities: list[HomeActivityItem] = Field(
        default_factory=list, description="กิจกรรมที่ยังเปิดรับ เรียงใกล้วันก่อน สูงสุด 3 รายการ"
    )
    finance: HomeFinanceSummary
    announcements: HomeAnnouncementSummary
    schedule: HomeSchedule
