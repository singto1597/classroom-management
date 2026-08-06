import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/classroom")
API_KEY = os.getenv("API_KEY", "api-key-for-my-bot-1234") 

REDIS_URL = os.getenv("REDIS_URL")

if not REDIS_URL:
    # ⚠️ ไม่มี REDIS_URL ใน .env → จะอ่าน default ที่ docker-compose.app.yml ตั้งให้คือ:
    #   redis://${ENV_NAME}_infra_redis:6379/0
    # แต่ถ้ารันแบบ local (ไม่มี compose) ให้ fallback เป็น host เดียวกันกับ infra
    import socket
    _env_name = os.getenv("ENV_NAME", "")
    _host = f"{_env_name}_infra_redis" if _env_name else "staging_infra_redis"
    if not _env_name:
        try:
            socket.getaddrinfo(_host, 6379)
        except socket.gaierror:
            _host = "127.0.0.1"  # local dev ที่ยังไม่ได้ลาก Redis ขึ้น → ใช้ localhost
    REDIS_URL = f"redis://{_host}:6379/0"

# ✅ ยืนยัน format ก่อนใช้งาน (กันพลาดจาก .env ที่พิมพ์ syntax ของ Python ติดมา)
if "str =" in REDIS_URL or not REDIS_URL.startswith("redis://"):
    raise ValueError(
        f"REDIS_URL format ผิด: {REDIS_URL!r} — ต้องเป็น redis://host:port/db "
        "(ห้ามคัด syntax 'REDIS_URL: str = ...' จาก .env.example มา)"
    )