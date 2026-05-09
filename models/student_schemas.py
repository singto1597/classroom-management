from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional, List

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

# สำหรับคำขอ Export ไฟล์
class StudentExportRequest(BaseModel):
    fields: List[str]  # รายชื่อฟิลด์ที่ต้องการ เช่น ["student_no", "first_name", "phone_number"]
    user_name: str     # ใครเป็นคนสั่ง Export (เอาไปลง Audit Log)

# สำหรับคำขอเปลี่ยนสถานะ (Deactivate)
class StudentStatusUpdate(BaseModel):
    status: str        # 'active' หรือ 'inactive'
    user_name: str

class StudentDeleteRequest(BaseModel):
    user_name: str

# ==========================================
# 1. สำหรับการเพิ่มข้อมูลแบบด่วน (Quick / Bulk Add)
# ==========================================
class StudentQuickAdd(BaseModel):
    student_no: int
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)

class StudentBulkAddRequest(BaseModel):
    students: List[StudentQuickAdd]
    user_name: str

class StudentAddRequest(StudentQuickAdd):
    user_name: str

# ==========================================
# 2. สำหรับอัปเดตข้อมูล (Partial Update)
# ส่งมาแค่ฟิลด์ที่อยากแก้ ฟิลด์ไหนไม่ส่งมาคือไม่แก้
# ==========================================
class StudentUpdateRequest(BaseModel):
    # Core
    student_id: Optional[str] = Field(None, max_length=10)
    prefix: Optional[str] = Field(None, max_length=20)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    nickname: Optional[str] = Field(None, max_length=50)
    birthday: Optional[date] = None
    
    # Academic
    class_role: Optional[str] = Field(None, max_length=50)
    cleaning_duty: Optional[str] = Field(None, max_length=50)
    olympic_camp: Optional[str] = Field(None, max_length=100)
    portfolio: Optional[str] = Field(None, max_length=1000)
    target_faculty: Optional[str] = Field(None, max_length=100)
    
    # Health
    blood_group: Optional[str] = Field(None, max_length=3)
    shirt_size: Optional[str] = Field(None, max_length=10)
    food_allergy: Optional[str] = Field(None, max_length=255)
    congenital_disease: Optional[str] = Field(None, max_length=255)
    
    # Social
    phone_number: Optional[str] = Field(None, max_length=20)
    phone_number_parent: Optional[str] = Field(None, max_length=20)
    phone_number_parent_relation: Optional[str] = Field(None, max_length=50)
    line_id: Optional[str] = Field(None, max_length=50)
    ig_username: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    
    # Address
    address_house_no: Optional[str] = Field(None, max_length=50)
    address_road: Optional[str] = Field(None, max_length=100)
    address_sub_district: Optional[str] = Field(None, max_length=100)
    address_district: Optional[str] = Field(None, max_length=100)
    address_province: Optional[str] = Field(None, max_length=100)
    address_post_code: Optional[str] = Field(None, max_length=10)

# ==========================================
# 3. สำหรับเชื่อม Discord ID
# ==========================================
class SyncDiscordRequest(BaseModel):
    student_no: int
    discord_id: int
    user_name: str

# ==========================================
# 4. สำหรับการจัดการ Status
# ==========================================
class ChangeStatusRequest(BaseModel):
    status: str = Field(..., description="เช่น active, inactive, graduated")
    user_name: str

# ==========================================
# 5. Schema ตอบกลับ (พร้อม % ความสมบูรณ์)
# ==========================================
class StudentCompletionStatus(BaseModel):
    percentage: int
    missing_fields: List[str]

class StudentResponse(BaseModel):
    # 🟢 [1] System IDs
    id: int
    room_id: int
    discord_id: Optional[int]
    
    # 🔵 [2] Core Identity
    student_no: int
    student_id: Optional[str]
    prefix: Optional[str]
    first_name: str
    last_name: str
    nickname: Optional[str]
    birthday: Optional[date]
    
    # 🟡 [3] Academic & Duties
    class_role: str
    cleaning_duty: Optional[str]
    olympic_camp: Optional[str] = None
    portfolio: Optional[str] = None
    target_faculty: Optional[str] = None
    
    # 🔴 [4] Physical & Health
    blood_group: Optional[str]
    shirt_size: Optional[str]
    food_allergy: Optional[str]
    congenital_disease: Optional[str]
    
    # 🟣 [5] Social & Contacts
    phone_number: Optional[str]
    phone_number_parent: Optional[str]
    phone_number_parent_relation: Optional[str]
    line_id: Optional[str]
    ig_username: Optional[str]
    email: Optional[str]
    
    # 🟤 [6] Address
    address_house_no: Optional[str]
    address_road: Optional[str]
    address_sub_district: Optional[str]
    address_district: Optional[str]
    address_province: Optional[str]
    address_post_code: Optional[str]
    
    # ⚫ [7] Status & Tracking
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    # ข้อมูลคำนวณ % ความสมบูรณ์ (Backend คำนวณให้แล้วยัดใส่มาตรงนี้)
    data_completion: Optional[StudentCompletionStatus] = None


class UserRoomResponse(BaseModel):
    server_id: int 
    room_name: str
    role: str