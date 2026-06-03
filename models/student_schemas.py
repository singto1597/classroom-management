from pydantic import BaseModel, Field, model_validator
from datetime import date, datetime
from typing import Optional, List

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

class StudentExportRequest(BaseModel):
    fields: List[str]
    user_name: str

class StudentStatusUpdate(BaseModel):
    status: str
    user_name: str

class StudentDeleteRequest(BaseModel):
    user_name: str

class StudentQuickAdd(BaseModel):
    student_no: int
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)

class StudentBulkAddRequest(BaseModel):
    students: List[StudentQuickAdd]
    user_name: str

class StudentAddRequest(StudentQuickAdd):
    user_name: str

class StudentUpdateRequest(BaseModel):
    student_id: Optional[str] = Field(None, max_length=10)
    prefix: Optional[str] = Field(None, max_length=20)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    nickname: Optional[str] = Field(None, max_length=50)
    birthday: Optional[date] = None
    
    class_role: Optional[str] = Field(None, max_length=50)
    cleaning_duty: Optional[str] = Field(None, max_length=50)
    olympic_camp: Optional[str] = Field(None, max_length=100)
    portfolio: Optional[str] = Field(None, max_length=1000)
    target_faculty: Optional[str] = Field(None, max_length=100)
    
    blood_group: Optional[str] = Field(None, max_length=3)
    shirt_size: Optional[str] = Field(None, max_length=10)
    food_allergy: Optional[str] = Field(None, max_length=255)
    congenital_disease: Optional[str] = Field(None, max_length=255)
    
    phone_number: Optional[str] = Field(None, max_length=20)
    phone_number_parent: Optional[str] = Field(None, max_length=20)
    phone_number_parent_relation: Optional[str] = Field(None, max_length=50)
    line_id: Optional[str] = Field(None, max_length=50)
    ig_username: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    
    address_house_no: Optional[str] = Field(None, max_length=50)
    address_road: Optional[str] = Field(None, max_length=100)
    address_sub_district: Optional[str] = Field(None, max_length=100)
    address_district: Optional[str] = Field(None, max_length=100)
    address_province: Optional[str] = Field(None, max_length=100)
    address_post_code: Optional[str] = Field(None, max_length=10)

class SyncDiscordRequest(BaseModel):
    student_no: int
    discord_id: int
    user_name: str

class ChangeStatusRequest(BaseModel):
    status: str = Field(..., description="เช่น active, inactive, graduated")
    user_name: str

class StudentCompletionStatus(BaseModel):
    percentage: int
    missing_fields: List[str]

class StudentResponse(BaseModel):
    id: int
    room_id: int
    discord_id: Optional[int]
    discord_id_str: Optional[str] = None
    
    student_no: int
    student_id: Optional[str]
    prefix: Optional[str]
    first_name: str
    last_name: str
    nickname: Optional[str]
    birthday: Optional[date]
    
    class_role: str
    cleaning_duty: Optional[str]
    olympic_camp: Optional[str] = None
    portfolio: Optional[str] = None
    target_faculty: Optional[str] = None
    
    blood_group: Optional[str]
    shirt_size: Optional[str]
    food_allergy: Optional[str]
    congenital_disease: Optional[str]
    
    phone_number: Optional[str]
    phone_number_parent: Optional[str]
    phone_number_parent_relation: Optional[str]
    line_id: Optional[str]
    ig_username: Optional[str]
    email: Optional[str]
    
    address_house_no: Optional[str]
    address_road: Optional[str]
    address_sub_district: Optional[str]
    address_district: Optional[str]
    address_province: Optional[str]
    address_post_code: Optional[str]
    
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    data_completion: Optional[StudentCompletionStatus] = None

    @model_validator(mode='after')
    def set_discord_id_str(self):
        if self.discord_id is not None:
            self.discord_id_str = str(self.discord_id)
        return self


class UserRoomResponse(BaseModel):
    room_id: int # 🚨 เพิ่มสำหรับการทำงาน Web-Centric
    server_id: Optional[int] = None # 🚨 ปรับเป็น Optional ให้สอดคล้องกับ DB
    server_id_str: Optional[str] = None
    room_name: str
    role: str

    @model_validator(mode='after')
    def set_server_id_str(self):
        if self.server_id is not None:
            self.server_id_str = str(self.server_id)
        return self

class StudentSummaryResponse(BaseModel):
    id: int
    student_no: int
    student_id: Optional[str] = None
    first_name: str
    last_name: str
    nickname: Optional[str] = None
    class_role: str
    status: str
    discord_id_str: Optional[str] = None
    data_completion: Optional[StudentCompletionStatus] = None