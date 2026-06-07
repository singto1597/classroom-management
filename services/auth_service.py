import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException, status
from core.config import settings
import asyncpg
from typing import Optional

DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

async def exchange_code_for_token(code: str) -> str:
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
            raise HTTPException(status_code=400, detail="Discord token exchange failed")
        return response.json()["access_token"]

async def exchange_google_code_for_token(code: str) -> str:
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Google token exchange failed")
        return response.json()["access_token"]

async def get_discord_user_profile(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(DISCORD_USER_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")
        return response.json()

async def get_google_user_info(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user")
        return response.json()

async def process_user_login(
    pool: asyncpg.Pool, 
    email: str, 
    google_id: Optional[str] = None, 
    discord_id: Optional[int] = None, 
    first_name: Optional[str] = None, 
    last_name: Optional[str] = None,
    username: Optional[str] = None
) -> dict:
    """ 
    Unified Login Processor: ค้นหาด้วย Email หากเจอจะทำการ Link Account
    หากไม่เจอจะทำการสร้าง User ใหม่
    """
    async with pool.acquire() as conn:
        # ใช้ COALESCE เพื่อป้องกันการทับข้อมูลเดิมที่มีอยู่แล้วด้วยค่า NULL
        query = """
            INSERT INTO users (email, google_id, discord_id, first_name, last_name, username)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (email) 
            DO UPDATE SET 
                google_id = COALESCE(users.google_id, EXCLUDED.google_id),
                discord_id = COALESCE(users.discord_id, EXCLUDED.discord_id),
                first_name = COALESCE(users.first_name, EXCLUDED.first_name),
                last_name = COALESCE(users.last_name, EXCLUDED.last_name),
                username = COALESCE(users.username, EXCLUDED.username),
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, discord_id;
        """
        result = await conn.fetchrow(
            query, email, google_id, discord_id, first_name, last_name, username
        )
        
        return {
            "user_id": result["id"], 
            "discord_id": result["discord_id"]
        }

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    tz_bangkok = timezone(timedelta(hours=7))
    expire = datetime.now(tz_bangkok) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt