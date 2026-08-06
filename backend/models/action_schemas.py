from pydantic import BaseModel, Field

class CustomMessageRequest(BaseModel):
    """คำขอส่งประกาศจากเว็บเข้า Discord (event: CUSTOM_MESSAGE)"""
    title: str = Field(..., min_length=1, max_length=200, description="หัวข้อประกาศ")
    message: str = Field(..., min_length=1, max_length=2000, description="ข้อความประกาศ")
    user_name: str = Field(..., max_length=100, description="ชื่อผู้ประกาศ (โชว์ใน footer ของ embed)")

class CustomMessageResponse(BaseModel):
    status: str = "success"
    message: str
