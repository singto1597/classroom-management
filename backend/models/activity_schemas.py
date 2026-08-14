from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import date, datetime

# --- Common ---
class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None


class ActionWithUserRequest(BaseModel):
    """body ขั้นต่ำสำหรับ DELETE — แค่ user_name (ใครเป็นคนทำ)"""
    user_name: str = Field(..., min_length=1, max_length=100)


# --- Activity Status / Participant Role enum-like helpers ---
ActivityStatus = Literal["upcoming", "ongoing", "completed", "cancelled"]
RoleType = Literal["participant", "staff", "leader"]
ParticipantStatus = Literal["confirmed", "cancelled", "attended"]


# --- Participant Schemas (single row inside create/update activity) ---
class ActivityParticipantIn(BaseModel):
    """ผู้เข้าร่วม 1 คนตอนสร้าง/แก้กิจกรรม — student_no คือตัวระบุ (ฝั่ง backend resolve เป็น student_id)"""
    student_no: int = Field(..., description="เลขที่นักเรียนในห้องนี้")
    role_type: RoleType = "participant"
    role_detail: Optional[str] = Field(None, max_length=255)
    earned_hours: float = Field(0.0, ge=0.0)
    status: ParticipantStatus = "confirmed"
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 🌟 เบอร์รถบัส, ห้องพัก, ไซส์เสื้อ ฯลฯ


class ActivityParticipantResponse(BaseModel):
    """ผู้เข้าร่วมที่คืนกลับ — มี student_no + ชื่อ + Type A Profile Fields (JOIN จาก users)"""
    id: int
    activity_id: int
    student_id: int
    student_no: int
    first_name: str
    last_name: str
    nickname: Optional[str] = None
    role_type: str
    role_detail: Optional[str] = None
    earned_hours: float
    status: str
    metadata: Dict[str, Any] = {}
    recorded_by: Optional[str] = None
    # 🌟 Type A — อ่านจากโปรไฟล์ users โดยตรง (READ ONLY ในบริบทกิจกรรม — ห้ามบันทึกซ้ำลง metadata)
    blood_group: Optional[str] = None
    shirt_size: Optional[str] = None
    food_allergy: Optional[str] = None
    congenital_disease: Optional[str] = None
    phone_number: Optional[str] = None
    phone_number_parent: Optional[str] = None


# --- Create / Update Activity ---
class ActivityCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    activity_date: date  # ต้องเป็น date object (กันบั๊ก toordinal)
    base_hours: float = Field(0.0, ge=0.0)
    status: ActivityStatus = "upcoming"
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 🌟 พิกัด, กำหนดการ, ลิ้งก์รูป, แท็ก
    participants: List[ActivityParticipantIn] = Field(default_factory=list)
    user_name: str = Field(..., min_length=1, max_length=100)


class ActivityUpdateRequest(BaseModel):
    """PATCH — ทุกฟิลด์ optional; ใช้ model_dump(exclude_unset=True) ใน router
    participants ถ้าส่งมา → reconcile ผู้เข้าร่วมทั้งชุด (เพิ่ม/แก้/ลบ/กู้คืน) แทนชุดเดิม"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    activity_date: Optional[date] = None
    base_hours: Optional[float] = Field(None, ge=0.0)
    status: Optional[ActivityStatus] = None
    metadata: Optional[Dict[str, Any]] = None
    participants: Optional[List[ActivityParticipantIn]] = Field(
        default=None,
        description="ถ้าส่งมา → แทนที่ผู้เข้าร่วมทั้งชุด (เพิ่ม/อัปเดต/ลบ soft-delete/กู้คืน soft-deleted)"
    )
    user_name: str = Field(..., min_length=1, max_length=100)


# --- Add / Update Participant (standalone endpoints) ---
class ParticipantAddRequest(BaseModel):
    student_no: int
    role_type: RoleType = "participant"
    role_detail: Optional[str] = Field(None, max_length=255)
    earned_hours: float = Field(0.0, ge=0.0)
    status: ParticipantStatus = "confirmed"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    user_name: str = Field(..., min_length=1, max_length=100)


class ParticipantUpdateRequest(BaseModel):
    """PATCH participant — ทุกฟิลด์ (ยกเว้น student_no/user_name) optional"""
    role_type: Optional[RoleType] = None
    role_detail: Optional[str] = Field(None, max_length=255)
    earned_hours: Optional[float] = Field(None, ge=0.0)
    status: Optional[ParticipantStatus] = None
    metadata: Optional[Dict[str, Any]] = None
    user_name: str = Field(..., min_length=1, max_length=100)


class ParticipantStatusUpdate(BaseModel):
    """เปลี่ยนสถานะ participant (เช่น เช็คอิน/ยกเลิก) — ส่งแค่ status + user_name"""
    status: ParticipantStatus
    user_name: str = Field(..., min_length=1, max_length=100)


class BatchParticipantItem(BaseModel):
    """1 รายการใน Batch Update — อัปเดต metadata ของ participant (merge กับของเดิม)"""
    participant_id: int
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 🌟 Type B ค่าที่จะ merge


class BatchParticipantUpdateRequest(BaseModel):
    """Batch Apply (คลุมดำตั้งค่า) — อัปเดตหลาย participants ใน transaction เดียว
    ใช้เมื่อ frontend ตั้งค่าเช่น bus_number กลุ่มใหญ่ แล้วยิง payload ก้อนเดียว"""
    items: List[BatchParticipantItem] = Field(..., min_length=1)
    user_name: str = Field(..., min_length=1, max_length=100)


# --- Response ---
class ActivityResponse(BaseModel):
    id: int
    room_id: int
    title: str
    description: Optional[str] = None
    activity_date: date
    base_hours: float
    status: str
    metadata: Dict[str, Any] = {}
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    participant_count: int = 0
    participants: List[ActivityParticipantResponse] = Field(default_factory=list)


class ActivityListResponse(BaseModel):
    total_count: int
    items: List[ActivityResponse]


# --- Export ---
class ActivityExportRequest(BaseModel):
    activity_id: int
    # 🌟 คอลัมน์ที่ต้องการดึงจาก metadata ของผู้เข้าร่วมแต่ละคนออกมาเป็นคอลัมน์ Excel
    metadata_keys: List[str] = Field(default_factory=list)
    user_name: str = Field(..., min_length=1, max_length=100)


class ActivityExportResponse(BaseModel):
    status: str = "success"
    file_url: Optional[str] = None
    message: Optional[str] = None
