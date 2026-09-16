from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

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
    """คำตอบของ `POST /api/classroom/join`

    🔴 `room_name` **ต้องประกาศที่นี่** — `join_room` คืนคีย์นี้มาเสมอ (ทั้งเส้นทาง
       "ขอเข้าร่วม" และ "ส่งคำขอยืนยันตัวตน") และ `Lobby.vue` ส่งต่อไป `authStore.setRoom`
       ทันที ⇒ ถ้า `response_model=` ตัดทิ้ง `currentRoomName` จะเป็น `undefined`
       แล้วถูกเก็บลง localStorage **โดยไม่มี error ใด ๆ** (ฝั่ง TS ประกาศ `room_name: string`
       ไว้แล้ว ⇒ ไม่มีใครจับได้ตอนคอมไพล์) — ชื่อห้องบนหัวจอหายทั้งระบบ

    ⚠️ บทเรียนเดียวกับ `ReceiptDetailResponse`/`ReceiptResponse.is_receipt`:
       `response_model=` เป็นตัวกรองขาออก คีย์ที่ไม่ประกาศ = คีย์ที่หายไป
    """
    room_id: int
    student_id: int
    room_name: Optional[str] = None
    message: str

class PendingRequestResponse(BaseModel):
    """รายการคำขอที่รอจัดการ (Consent Model) — request_type แยก:
    - join_request: ขอเข้าห้องเอง → รอแอดมินอนุมัติ
    - claim_request: ขออ้างสิทธิ์ ghost (มี ghost_* names ให้แอดมินตัดสิน) → รอแอดมินอนุมัติ
    - invite_pending: แอดมินแอดชื่อให้ → รอเจ้าตัวกดรับ (แอดมินอนุมัติแทนไม่ได้)"""
    id: int
    student_no: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name_en: Optional[str] = None
    last_name_en: Optional[str] = None
    created_at: Optional[datetime] = None
    identity_claimed: bool = False
    added_by: Optional[int] = None
    request_type: str = "join_request"
    ghost_first_name: Optional[str] = None
    ghost_last_name: Optional[str] = None
    ghost_first_name_en: Optional[str] = None
    ghost_last_name_en: Optional[str] = None
    name_match: Optional[bool] = None