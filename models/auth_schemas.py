from pydantic import BaseModel
from typing import Optional

class ProviderLoginRequest(BaseModel):
    code: Optional[str] = None  # สำหรับ Discord
    access_token: Optional[str] = None # สำหรับส่ง Token จากฝั่ง Client (Google Login)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # 🔥 แก้ไขจุดตายตรงนี้: เปลี่ยน int เป็น str เพื่อกัน JavaScript ปัดเศษ!
    user_id: str