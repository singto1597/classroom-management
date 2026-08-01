from pydantic import BaseModel
from typing import Optional
from pydantic import EmailStr
from pydantic import Field


class ProviderLoginRequest(BaseModel):
    code: Optional[str] = None  # สำหรับ Discord
    access_token: Optional[str] = None # สำหรับส่ง Token จากฝั่ง Client (Google Login)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # 🔥 จุดตาย: เปลี่ยน int เป็น str เพื่อกัน JavaScript ปัดเศษ!
    user_id: str

# 📦 Schema สำหรับรับข้อมูลโปรไฟล์จาก OAuth (Google/Discord) เพื่อส่งเข้า Service
class OAuthProfilePayload(BaseModel):
    email: EmailStr
    google_id: Optional[str] = None
    discord_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None

# 📦 Schema สำหรับส่งผลลัพธ์ (ID) จาก Service กลับไปให้ Router
class UserLoginResult(BaseModel):
    user_id: int
    discord_id: Optional[int] = None

class UserProfileUpdate(BaseModel):
    prefix: str = Field(..., max_length=10, description="คำนำหน้า")
    first_name: str = Field(..., max_length=100, description="ชื่อจริง")
    last_name: str = Field(..., max_length=100, description="นามสกุล")
