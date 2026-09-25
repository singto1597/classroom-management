from pydantic import BaseModel
from typing import Optional
from pydantic import EmailStr
from pydantic import Field
from datetime import date


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

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

class UserProfileResponse(BaseModel):
    """โปรไฟล์ของผู้ใช้ที่ล็อกอินอยู่ — `GET`/`PATCH /api/auth/me`

    🔴 ผลตรวจระบบ 2026-09-23 → M4: เดิม `GET /me` คืน `dict(user)` ดิบ ๆ โดยไม่มี
       `response_model` ⇒ **คอลัมน์ไหนถูกเพิ่มเข้า SELECT ก็หลุดออก API ทันที**
       โดยไม่มีใครตั้งใจและไม่มีอะไรเตือน (และเป็นวิธีที่ฟิลด์ภายในรั่วออกไปจริง ๆ)
       การประกาศ `response_model` ทำให้รายการฟิลด์ที่ส่งออกเป็น **สัญญาที่เขียนไว้**
       ไม่ใช่ผลข้างเคียงของคำสั่ง SQL

    ⚠️ ชนิดข้อมูลคงเดิมทุกตัวตามที่ asyncpg อ่านจากคอลัมน์ — **ไม่ปรับให้สวยขึ้น**
       เพราะ frontend ประกาศ `discord_id: number | null` ไว้แล้ว (services/auth.ts)
       การเปลี่ยนเป็น str จะเป็นการเปลี่ยนรูปข้อมูลบนสายแบบเงียบ ๆ
    ⚠️ `discord_id` เป็น snowflake 19 หลักซึ่ง **เกินเพดานจำนวนเต็มปลอดภัยของ
       JavaScript (2^53)** ⇒ ฝั่ง frontend ต้องแปลงเป็นสตริงก่อนใช้ (ทำอยู่แล้วใน
       stores/auth.ts: `String(data.discord_id)`) — อย่าส่งค่านี้ออกไปเป็นตัวเลข
       แล้วเอาไปใช้คำนวณฝั่งเบราว์เซอร์
    """
    id: int
    prefix: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name_en: Optional[str] = None
    last_name_en: Optional[str] = None
    username: Optional[str] = None
    nickname: Optional[str] = None
    nickname_en: Optional[str] = None
    birthday: Optional[date] = None
    phone_number: Optional[str] = None
    line_id: Optional[str] = None
    address_house_no: Optional[str] = None
    address_road: Optional[str] = None
    address_sub_district: Optional[str] = None
    address_district: Optional[str] = None
    address_province: Optional[str] = None
    address_post_code: Optional[str] = None
    discord_id: Optional[int] = None
    google_id: Optional[str] = None

class UserProfileUpdate(BaseModel):
    prefix: str = Field(..., max_length=10, description="คำนำหน้า")
    first_name: str = Field(..., max_length=100, description="ชื่อจริง (ไทย)")
    last_name: str = Field(..., max_length=100, description="นามสกุล (ไทย)")
    nickname: str = Field(..., max_length=50, description="ชื่อเล่น")
    # 🌟 ชื่อภาษาอังกฤษ — กุญแจตัวตนหลัก (identity/dedupe/search); optional จนกว่าจะกรอก
    first_name_en: Optional[str] = Field(None, max_length=100, description="ชื่อจริง (ภาษาอังกฤษ)")
    last_name_en: Optional[str] = Field(None, max_length=100, description="นามสกุล (ภาษาอังกฤษ)")
    nickname_en: Optional[str] = Field(None, max_length=50, description="ชื่อเล่น (ภาษาอังกฤษ)")
    birthday: date = Field(..., description="วันเกิด (YYYY-MM-DD)")
    phone_number: str = Field(..., max_length=20, description="เบอร์โทรศัพท์")
    line_id: str = Field(..., max_length=50, description="LINE ID")
    address_house_no: str = Field(..., max_length=20, description="เลขที่บ้าน")
    address_road: Optional[str] = Field(None, max_length=100, description="ถนน (ถ้ามี)")
    address_sub_district: str = Field(..., max_length=100, description="ตำบล/แขวง")
    address_district: str = Field(..., max_length=100, description="อำเภอ/เขต")
    address_province: str = Field(..., max_length=100, description="จังหวัด")
    address_post_code: str = Field(..., max_length=10, description="รหัสไปรษณีย์")
