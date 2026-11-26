import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Central API (Classroom & Finance)"
    PROJECT_VERSION: str = "9.14.0"

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

    # ⚖️ [P6] เตือนผู้ค้างชำระรายวัน — worker `finance_reminder_worker` (1 replica)
    #    ทำงานวันละครั้งหลัง `FINANCE_REMINDER_HOUR:FINANCE_REMINDER_MINUTE` (Asia/Bangkok)
    #    ⚠️ การกันส่งซ้ำเป็นหน้าที่ของ `reminder_dispatch_log` (unique ต่อวัน/ช่อง)
    #    ⇒ เปิด worker ซ้ำ/รีสตาร์ทกลางวันไม่ทำให้ผู้ใช้ได้ข้อความซ้ำ
    FINANCE_REMINDER_ENABLED: bool = True
    FINANCE_REMINDER_HOUR: int = 9
    FINANCE_REMINDER_MINUTE: int = 0
    # ⚠️ ตั้งชื่อ namespaced โดยเจตนา — **ไม่ใช้ `TZ`** เพราะ container มักมี `TZ=UTC`
    #    อยู่แล้ว และการอ่านค่านั้นจะเลื่อนเส้นแบ่ง "วันนี้" ไป 7 ชั่วโมงเงียบ ๆ
    FINANCE_REMINDER_TZ: str = "Asia/Bangkok"

    # ⏰ [P6.5] ค่าปรับจ่ายล่าช้าอัตโนมัติ — รันก่อนส่งเตือนรายวันใน worker ตัวเดียวกัน
    #    นโยบายเป็นของแต่ละแคมเปญ (`fee_collections.late_fee_mode`) · ค่าเริ่มต้นเปิด
    #    ⚠️ เปิดก็ไม่กระทบแคมเปญเดิม เพราะทุกแคมเปญที่สร้างก่อน P6.5 เป็น `none`
    #    ⚠️ 1 บิลต้นทางออกค่าปรับได้ครั้งเดียวตลอดชีพ (unique `uq_fines_late_fee_source`)
    FINANCE_LATE_FEE_ENABLED: bool = True

    # 📎 [MEDIA] ไฟล์หลักฐานการเงิน — รูปภาพ + PDF เก็บบน named volume `${ENV_NAME}_media_data`
    #    mount ที่ `/data/media` (เฉพาะ backend) · local driver สำหรับ single-node Swarm
    #    ⚠️ ถ้าขยาย multi-node ต้องเปลี่ยน `MEDIA_STORAGE_BACKEND` ไป S3/R2 ผ่าน core/media
    MEDIA_STORAGE_BACKEND: str = "local"
    MEDIA_STORAGE_DIR: str = "/data/media"
    MEDIA_IMAGE_SIZE_LIMIT_MB: int = 10
    MEDIA_DOCUMENT_SIZE_LIMIT_MB: int = 20
    # 🚧 เพดานต่อ record (รูป + PDF นับรวมกัน) — ตั้งใจให้สูงกว่า PRSC (3) เพราะหลักฐาน
    #    การเบิกจ่ายมักมีหลายใบ แต่ยังคุมไม่ให้กลายเป็นอัลบั้ม
    MEDIA_MAX_FINANCE_ATTACHMENTS: int = 20
    # ต่อคำขอ — UI แบ่งชุดอัตโนมัติ ⇒ ไม่ต้อง buffer 20 × 20MB ใน memory ต่อ request
    MEDIA_MAX_UPLOAD_PER_REQUEST: int = 5
    MEDIA_MAX_UPLOAD_PER_HOUR: int = 100
    # เพดานขนาดรวมต่อ record — 20 ไฟล์ × 20MB = 400MB คือ worst case ที่ไม่ควรเกิด
    MEDIA_MAX_ATTACHMENT_BYTES_TOTAL_MB: int = 100
    MEDIA_MAX_PDF_PAGES: int = 30
    MEDIA_MAX_DIMENSION: int = 1600
    MEDIA_MIN_DIMENSION: int = 64
    MEDIA_THUMB_DIMENSION: int = 480
    MEDIA_WEBP_QUALITY: int = 80
    # อายุ signed URL 15 นาที ปัด exp เป็นรอบ 5 นาที (ดู core/media_signing.py)
    MEDIA_URL_SIGNING_TTL_SECONDS: int = 900
    MEDIA_URL_EXP_ROUND_SECONDS: int = 300
    MEDIA_PURGE_AFTER_DAYS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()