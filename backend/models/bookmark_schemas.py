"""Pydantic schemas ของบุ๊กมาร์ก "บันทึกไว้" (P3.4)

🔑 `available` ไม่ได้หมายความว่า "ยังไม่ถูกลบ" เท่านั้น — หน้าเว็บใช้ค่านี้ตัดสินว่า
จะให้กดเข้าไปหรือแสดง "รายการนี้ถูกลบแล้ว" แทน เพื่อไม่พาผู้ใช้ไป 404
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

BookmarkEntityType = Literal["announcement", "activity"]


class BookmarkCreateRequest(BaseModel):
    entity_type: BookmarkEntityType
    entity_id: int = Field(gt=0, description="id ของประกาศหรือกิจกรรม")


class BookmarkItem(BaseModel):
    bookmark_id: int
    entity_type: BookmarkEntityType
    entity_id: int
    title: str
    snippet: str = Field("", description="เนื้อหาย่อ 160 ตัวอักษรแรก")
    occurred_on: Optional[date] = Field(
        None, description="ประกาศ = วันที่โพสต์ · กิจกรรม = วันที่จัด"
    )
    url: str = Field(description="เส้นทางในแอป (ใช้เฉพาะเมื่อ available = true)")
    available: bool = Field(True, description="false = เป้าหมายถูกลบแล้ว ลิงก์ใช้ไม่ได้")
    created_at: datetime = Field(description="เวลาที่บันทึกไว้ (ใช้เรียงลำดับ)")


class BookmarkListResponse(BaseModel):
    items: list[BookmarkItem] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: Optional[str] = Field(None, description="ส่งกลับเป็น ?cursor= เพื่อดึงหน้าเก่ากว่า")


class BookmarkCreateResponse(BaseModel):
    id: int
    entity_type: BookmarkEntityType
    entity_id: int
    created_at: datetime
    created: bool = Field(
        description="false = รายการนี้ถูกบันทึกไว้อยู่แล้ว (คำขอซ้ำไม่มีผลข้างเคียง)"
    )


class BookmarkStateResponse(BaseModel):
    bookmarked: bool
    bookmark_id: Optional[int] = Field(None, description="id สำหรับส่งเข้า DELETE เมื่อต้องการยกเลิก")
