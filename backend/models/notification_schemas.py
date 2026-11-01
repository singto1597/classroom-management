from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# กลุ่มแจ้งเตือน — ต้องตรงกับ CHECK ของตาราง notifications / notification_preferences
# ⚠️ `announcement` ไม่อยู่ในชุดที่ผู้ใช้ปรับได้ (ประกาศของห้องปิดไม่ได้)
NotificationGroup = Literal["task", "finance", "activity", "member", "announcement"]
MutableNotificationGroup = Literal["task", "finance", "activity", "member"]
NotificationPriority = Literal["normal", "high", "urgent"]


class NotificationItem(BaseModel):
    id: int
    group_type: NotificationGroup
    type: str
    priority: NotificationPriority
    title: str
    body: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    url: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    # จำนวนที่ยังไม่อ่าน "ของห้องนี้" — ให้กระดิ่งใช้ตัวเลขเดียวกับที่หน้ารายการแสดง
    unread_count: int
    # ยังมีหน้าเก่ากว่านี้ให้โหลดต่อหรือไม่ (pagination แบบ cursor ด้วย id)
    has_more: bool


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    notification_id: int
    # False = แถวนี้ไม่ใช่ของผู้ขอ (หรือไม่มีอยู่) ⇒ ไม่บอกใบ้ว่ามีแจ้งเตือนคนอื่นไหม
    marked: bool


class MarkAllReadResponse(BaseModel):
    marked_count: int


class PreferenceItem(BaseModel):
    group_type: MutableNotificationGroup
    inapp: bool
    push: bool


class PreferenceUpdate(BaseModel):
    group_type: MutableNotificationGroup
    inapp: bool
    push: bool


class PreferenceListResponse(BaseModel):
    items: list[PreferenceItem] = Field(default_factory=list)
