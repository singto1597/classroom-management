import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException, status
from core.config import settings

DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

async def exchange_code_for_token(code: str) -> str:
    """
    นำ code จาก Discord Login ไปแลก access_token
    """
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Discord token exchange failed: {response.text}",
            )
        return response.json()["access_token"]

async def get_discord_user_id(access_token: str) -> str:
    """
    ใช้ access_token ดึงข้อมูล User จาก Discord เพื่อเอา id
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(DISCORD_USER_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch Discord user: {response.text}",
            )
        return response.json()["id"]

def create_access_token(data: dict) -> str:
    """
    สร้าง JWT Token โดยฝัง discord_id และตั้งเวลาหมดอายุ
    """
    to_encode = data.copy()
    # ใช้เวลา Asia/Bangkok ตามกฎข้อ 6
    tz_bangkok = timezone(timedelta(hours=7))
    expire = datetime.now(tz_bangkok) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt
