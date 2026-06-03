import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException, status
from core.config import settings
import asyncpg

DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

async def exchange_code_for_token(code: str) -> str:
    # (ฟังก์ชันเดิม - นำ code ไปแลก token ของ Discord)
    data = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "client_secret": settings.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        response = await client.post(DISCORD_TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Discord token exchange failed")
        return response.json()["access_token"]

async def get_discord_user_profile(access_token: str) -> dict:
    """ ดึง Profile เต็มจาก Discord เพื่อเอาไป Sync กับ DB """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(DISCORD_USER_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")
        return response.json()

async def get_google_user_profile(access_token: str) -> dict:
    """ ดึง Profile เต็มจาก Google """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user")
        return response.json()

async def sync_user_to_db(pool: asyncpg.Pool, provider: str, profile_data: dict) -> int:
    """ 
    Upsert ข้อมูลลงตาราง users 
    - ถ้าเคย Login ด้วย Provider นี้แล้ว จะทำการ Update และคืนค่า id (user_id)
    - ถ้ายัง จะ Insert ใหม่
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            if provider == "discord":
                discord_id = int(profile_data["id"])
                username = profile_data.get("username")
                email = profile_data.get("email") # อาจจะ None ได้ถ้าไม่ได้ขอ scope email
                
                # Upsert สำหรับ Discord
                user_id = await conn.fetchval("""
                    INSERT INTO users (discord_id, username, email)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (discord_id) 
                    DO UPDATE SET username = EXCLUDED.username, 
                                  updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """, discord_id, username, email)
                
            elif provider == "google":
                google_id = profile_data["sub"]
                email = profile_data["email"]
                first_name = profile_data.get("given_name")
                last_name = profile_data.get("family_name")
                
                # Upsert สำหรับ Google (ใช้ Email เป็นตัวเชื่อมหลักถ้าเป็นไปได้ แต่เบื้องต้นใช้ google_id)
                user_id = await conn.fetchval("""
                    INSERT INTO users (google_id, email, first_name, last_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (google_id) 
                    DO UPDATE SET first_name = EXCLUDED.first_name, 
                                  last_name = EXCLUDED.last_name,
                                  updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """, google_id, email, first_name, last_name)
                
            return user_id

def create_access_token(data: dict) -> str:
    """ สร้าง JWT Token โดยฝัง user_id (PK ของระบบ) ลงไปด้วย """
    to_encode = data.copy()
    tz_bangkok = timezone(timedelta(hours=7))
    expire = datetime.now(tz_bangkok) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt