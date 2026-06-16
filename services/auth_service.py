import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException, status
from core.config import settings
import asyncpg
from typing import Optional
from models.auth_schemas import OAuthProfilePayload, UserLoginResult

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

async def process_user_login(pool: asyncpg.Pool, payload: OAuthProfilePayload) -> UserLoginResult:
    """ 
    Unified Login & Merge Processor: 
    ระบบผสานร่างบัญชีขั้นสูง ถ้าเจอว่า 1 คนมี 2 บัญชี ระบบจะโอนกรรมสิทธิ์และรวมข้อมูลให้ทันที
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. หาบัญชีจาก Provider ID (Discord หรือ Google)
            existing_by_provider = await conn.fetchrow(
                "SELECT * FROM users WHERE (discord_id = $1 AND $1 IS NOT NULL) OR (google_id = $2 AND $2 IS NOT NULL) LIMIT 1",
                payload.discord_id, payload.google_id
            )
            
            # 2. หาบัญชีจาก Email
            existing_by_email = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1", payload.email
            )

            master_id = None

            # 🔥 กรณีสุดวิสัย: มี 2 บัญชีแยกกัน -> ต้อง MERGE ร่าง!
            if existing_by_provider and existing_by_email and existing_by_provider['id'] != existing_by_email['id']:
                
                # ให้ยึดบัญชีเก่าที่มี Provider เป็นร่างหลัก
                id_to_keep = existing_by_provider['id']
                id_to_delete = existing_by_email['id']
                row_to_delete = existing_by_email
                
                # ก้าวที่ 1: โอนกรรมสิทธิ์นักเรียนในห้องเรียนทั้งหมด ไปให้ร่างหลัก
                await conn.execute("UPDATE students SET user_id = $1 WHERE user_id = $2", id_to_keep, id_to_delete)
                
                # ก้าวที่ 2: ล้างค่า Unique ของร่างโคลนทิ้ง เพื่อหลบ Error
                await conn.execute("UPDATE users SET email = NULL, google_id = NULL, discord_id = NULL WHERE id = $1", id_to_delete)
                
                # ก้าวที่ 3: ดูดข้อมูลจากร่างโคลน มารวมในร่างหลัก (ข้อมูล payload ใหม่ทับของเดิม)
                await conn.execute("""
                    UPDATE users SET 
                        email = COALESCE($1, email, $2),
                        google_id = COALESCE($3, google_id, $4),
                        discord_id = COALESCE($5, discord_id, $6),
                        first_name = COALESCE($7, first_name),
                        last_name = COALESCE($8, last_name)
                    WHERE id = $9
                """, 
                payload.email, row_to_delete['email'],
                payload.google_id, row_to_delete['google_id'],
                payload.discord_id, row_to_delete['discord_id'],
                payload.first_name or row_to_delete['first_name'], 
                payload.last_name or row_to_delete['last_name'],
                id_to_keep)
                
                # ก้าวที่ 4: สังหารร่างโคลนทิ้ง
                await conn.execute("DELETE FROM users WHERE id = $1", id_to_delete)
                master_id = id_to_keep

            # 🟢 กรณีทั่วไป: เจออันเดียว หรือ ทั้งคู่ชี้ไปที่ไอดีเดียวกันอยู่แล้ว
            else:
                master_id = existing_by_provider['id'] if existing_by_provider else (existing_by_email['id'] if existing_by_email else None)
                
                if master_id:
                    await conn.execute("""
                        UPDATE users SET 
                            email = COALESCE($1, email),
                            google_id = COALESCE($2, google_id),
                            discord_id = COALESCE($3, discord_id),
                            first_name = COALESCE($4, first_name),
                            last_name = COALESCE($5, last_name),
                            username = COALESCE($6, username),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = $7
                    """, payload.email, payload.google_id, payload.discord_id, payload.first_name, payload.last_name, payload.username, master_id)
                else:
                    # 🔵 กรณีหน้าใหม่แกะกล่อง: สร้างใหม่!
                    master_id = await conn.fetchval("""
                        INSERT INTO users (email, google_id, discord_id, first_name, last_name, username)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING id
                    """, payload.email, payload.google_id, payload.discord_id, payload.first_name, payload.last_name, payload.username)

            # ดึง ID สุทธิ 
            final_user = await conn.fetchrow("SELECT id, discord_id FROM users WHERE id = $1", master_id)
            
            # 🎁 ส่งกลับเป็น Pydantic Object แทน Dict
            return UserLoginResult(
                user_id=final_user["id"], 
                discord_id=final_user["discord_id"]
            )

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    tz_bangkok = timezone(timedelta(hours=7))
    expire = datetime.now(tz_bangkok) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt