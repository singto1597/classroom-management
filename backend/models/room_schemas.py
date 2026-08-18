from pydantic import BaseModel, Field
from typing import Optional

class RoomCreateRequest(BaseModel):
    room_name: str = Field(..., max_length=100, description="ชื่อห้องเรียน")

class RoomJoinRequest(BaseModel):
    room_code: str = Field(..., min_length=6, max_length=10, description="รหัสเข้าห้อง 6 หลัก")
    student_no: int = Field(..., gt=0, description="เลขที่นักเรียน")
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    # 🌟 ชื่ออังกฤษ — กุญแจตัวตนหลักสำหรับ ghost-merge; optional
    first_name_en: Optional[str] = Field(None, max_length=100)
    last_name_en: Optional[str] = Field(None, max_length=100)

class RoomResponse(BaseModel):
    room_id: int
    room_name: str
    room_code: str
    message: str

class JoinRoomResponse(BaseModel):
    room_id: int
    student_id: int
    message: str