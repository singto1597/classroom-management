"""Pydantic schemas ของ "ของฉัน" — `GET /me/activity` และ `GET /me/stats` (P3.3)

🔑 ข้อจำกัดที่ตัดสินใจแล้ว (และต้องไม่ลืมตอนขยาย):
   สคีมาก่อน P3 **ไม่มีคอลัมน์ "ผู้ทำ"** ของงานและโน้ต — `tasks` เป็นของทั้งห้อง
   และ `daily_notes` ไม่มีผู้เขียน/created_at ⇒ "งานเสร็จของฉัน" / "โน้ตที่ฉันเขียน"
   คำนวณไม่ได้ถ้าไม่แต่งตัวเลขขึ้นมา
   ⇒ ฟีดและสถิติส่วนตัวนับเฉพาะเหตุการณ์ที่แปลงเป็น `students.user_id` ได้จริง:
   ใบเสร็จที่ออกให้ฉัน + กิจกรรมที่ฉันเข้าร่วม (P3.4 เพิ่มบุ๊กมาร์ก)
   ⇒ ตัวเลขระดับห้องที่ใส่เข้ามาเพื่อบริบทตั้งชื่อว่า `room_*` ให้อ่านไม่ออกว่าเป็นของฉัน
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

MeActivityKind = Literal["payment", "activity"]


class MeActivityItem(BaseModel):
    kind: MeActivityKind
    entity_id: int = Field(description="id ของแหล่งเหตุการณ์ (receipt id / activity id)")
    title: str
    detail: Optional[str] = None
    happened_at: datetime
    amount: Optional[float] = Field(None, description="เฉพาะ payment — ยอดที่จ่ายครั้งนั้น")
    reference: Optional[str] = Field(None, description="เฉพาะ payment — เลขที่ใบเสร็จ")
    status: Optional[str] = None
    activity_date: Optional[date] = Field(None, description="เฉพาะ activity — วันที่จัดกิจกรรม")
    url: str = Field(description="เส้นทางในแอปสำหรับกดดูรายละเอียด")


class MeActivityResponse(BaseModel):
    items: list[MeActivityItem] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: Optional[str] = Field(
        None, description="ส่งกลับเป็น ?cursor= เพื่อดึงหน้าเก่ากว่า (ไม่มีค่า = หน้าสุดท้าย)"
    )


class MeStatsResponse(BaseModel):
    has_profile: bool = Field(description="ผู้ใช้มีแถว students ในห้องนี้หรือไม่")
    term: Optional[dict] = Field(
        None, description="P5 จะเติม {year_id, term_id, name} — ตอนนี้ null = ทั้งหมด"
    )
    activities_joined: int = Field(0, description="กิจกรรมที่ฉันเข้าร่วม (ไม่นับที่ยกเลิก)")
    activity_hours: float = Field(0.0, description="ชั่วโมงกิจกรรมรวมจาก activity_participants")
    paid_total: float = Field(0.0, description="ยอดที่ฉันจ่ายจริง (ใบเสร็จ active)")
    outstanding: float = Field(0.0, description="ยอดค้างชำระของฉัน (predicate เดียวกับ home/summary)")
    unpaid_bills: int = Field(0, description="จำนวนบิลที่ยังชำระไม่ครบ")
    room_tasks_done: int = Field(0, description="งานของ *ห้อง* ที่ทำเสร็จแล้ว — ไม่ใช่ของฉัน")
    room_tasks_pending: int = Field(0, description="งานของ *ห้อง* ที่ยังค้าง — ไม่ใช่ของฉัน")
