import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Central API (Classroom & Finance)"
    PROJECT_VERSION: str = "9.13.0"

    # 🔖 Provenance: Commit SHA ของ image ที่รันอยู่ — ใส่มาจาก Docker build arg
    #    (ดู Dockerfile + pull_all.sh) ถ้ารันนอก container จะเป็น "unknown"
    GIT_SHA: str = os.getenv("GIT_SHA", "unknown")
    
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

    # 🔔 Web Push (VAPID) — ค่าเริ่มต้นว่าง = "ปิด push ทั้งระบบ" (ไม่ทำให้บูตพัง)
    #    ⚠️ ถ้าตั้งคีย์ไม่ครบ: endpoint subscribe จะตอบ 503 และ worker จะไม่ทำงาน
    #    ⇒ ในแอปยังได้แจ้งเตือนสดผ่าน SSE ครบถ้วน = degradation ที่ยอมรับได้
    #    สร้างคู่คีย์: `python -m workers.push_worker --generate-keys`
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    # ต้องเป็น mailto: หรือ https: ตามสเปก VAPID (ผู้ให้บริการ push ใช้ติดต่อเจ้าของ)
    VAPID_SUBJECT: str = "mailto:admin@localhost"

    # 🌐 [P6.1] จำนวน reverse proxy ที่เชื่อถือได้หน้า backend — ใช้ตัดสินว่าจะเชื่อ
    #    `X-Forwarded-For` / `CF-Connecting-IP` หรือไม่ (ดู core/request_context.py)
    #    0 (ค่าเริ่มต้น) = ไม่เชื่อ header ใด ๆ ⇒ audit ได้ IP ของ Traefik/peer เท่านั้น
    #    1 = proxy ตัวเดียว (ใช้แค่ X-Forwarded-For) · 2 = Cloudflare + Traefik
    # 🔴 ห้ามตั้ง > 0 ถ้าพอร์ตของ backend/Traefik ยังเปิดให้ยิงตรงข้าม proxy ได้
    #    ไม่งั้นใครก็เขียน IP ปลอมลง audit_logs ได้ (แย่กว่าไม่มี IP)
    TRUSTED_PROXY_HOPS: int = 0

    # 🚦 [P6.3] จำกัดความเร็วคำขอของ endpoint สาธารณะ/ล็อกอิน (ดู core/rate_limit.py)
    #    เปิดโดยค่าเริ่มต้น · ปิดได้ด้วย `RATE_LIMIT_ENABLED=false` เมื่อจำเป็น
    #    ⚠️ Redis ล่ม = **ปล่อยผ่าน** (fail-open) — ไม่ใช่ปิดการล็อกอินทั้งระบบ
    RATE_LIMIT_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()