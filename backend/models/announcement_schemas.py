"""Pydantic schemas ของประกาศ (`/announcements`)"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ต้องตรงกับ CHECK ใน migration 0002 และ services/announcement_service.PRIORITIES
AnnouncementPriority = Literal["normal", "high", "urgent"]


class AnnouncementCreate(BaseModel):
    """สร้างประกาศ — ผู้เขียนไม่ต้องส่งชื่อตัวเอง (ระบบอ่านจาก DB กันการแอบอ้าง)"""

    title: str = Field(..., min_length=1, max_length=200, description="หัวข้อประกาศ")
    body: str = Field("", max_length=5000, description="รายละเอียด (ว่างได้ ถ้าหัวข้อพอ)")
    priority: AnnouncementPriority = Field(
        "normal", description="urgent เท่านั้นที่ทะลุ quiet hours และ @everyone ใน Discord"
    )
    pinned: bool = Field(False, description="ปักหมุดไว้บนสุดของหน้าแรก")


class AnnouncementUpdate(BaseModel):
    """PATCH — ส่งเฉพาะฟิลด์ที่ต้องการแก้ (`exclude_unset`)"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    body: Optional[str] = Field(None, max_length=5000)
    priority: Optional[AnnouncementPriority] = None
    pinned: Optional[bool] = None


class AnnouncementItem(BaseModel):
    id: int
    title: str
    body: str
    priority: AnnouncementPriority
    pinned: bool
    archived_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    is_unread: bool = Field(
        False,
        description="ยังไม่อ่าน = มีแถวแจ้งเตือนของผู้ใช้คนนี้ที่ read_at ยังว่าง",
    )


class AnnouncementListResponse(BaseModel):
    pinned: list[AnnouncementItem] = Field(
        default_factory=list, description="เฉพาะหน้าแรก — หน้าถัดไปส่งลิสต์ว่าง"
    )
    items: list[AnnouncementItem]
    has_more: bool


class AnnouncementCreateResponse(BaseModel):
    item: AnnouncementItem
    delivered_count: int = Field(
        ..., description="จำนวนสมาชิกที่ล็อกอินจริงซึ่งได้รับแจ้งเตือน (ไม่รวมผู้เขียน)"
    )


class MarkAnnouncementReadResponse(BaseModel):
    announcement_id: int
    marked: bool = Field(
        False, description="False = ไม่มีแถวแจ้งเตือนให้ทำเครื่องหมาย (ไม่ใช่ error)"
    )
