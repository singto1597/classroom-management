import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Central API (Classroom & Finance)"
    PROJECT_VERSION: str = "1.0.0"
    
    DATABASE_URL: str
    API_KEY: str
    SECRET_KEY: str
    SUPER_ADMIN_ID: int = 0

    # Discord OAuth2
    DISCORD_CLIENT_ID: str
    DISCORD_CLIENT_SECRET: str
    DISCORD_REDIRECT_URI: str

    # Google OAuth2
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    # JWT Settings
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days

    # 🔴 ต้องระบุจาก .env / docker-compose เสมอ — ไม่มีค่า default เพราะถ้าเผลอชี้ผิด instance
    # บอทจะฟัง channel ไม่ได้ยิน (backend publish กับ bot subscribe คนละ Redis)
    REDIS_URL: str

    # 🖨️ [F3] Gotenberg (headless Chromium) สำหรับเรนเดอร์ใบเสร็จ/ใบแจ้งหนี้เป็น PDF
    # ⚠️ มี default ได้ (ต่างจาก REDIS_URL) เพราะ **ไม่ใช่ dependency ของทุก request** —
    #    เฉพาะเส้นทาง /receipts/{no}/pdf เท่านั้น ถ้าไม่มี default เทสต์ทั้งชุดจะ ImportError
    #    ทันทีที่ import settings ทั้งที่ไม่ได้แตะ PDF เลย
    #    ตอน deploy docker-compose.app.yml ต้อง override เป็น service name จริงเสมอ
    GOTENBERG_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()