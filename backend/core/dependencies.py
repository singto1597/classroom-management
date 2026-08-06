from fastapi import Request, Security, HTTPException, status, Header, Depends, Query, Path
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import asyncpg
from typing import Optional, Literal
from core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

async def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool

def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return api_key

# 🚀 1. แปลงทุกอย่างให้เป็น user_id
async def get_current_user(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
    x_discord_id: Optional[str] = Header(None),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth)
) -> dict:
    """
    Return: {"user_id": int} เท่านั้น! (ไม่มี discord_id หลุดเข้าไปในระบบแล้ว)
    """
    # กรณี 1: มาจาก Discord Bot
    if x_api_key:
        if x_api_key == settings.API_KEY:
            if not x_discord_id:
                raise HTTPException(status_code=400, detail="X-Discord-Id header is required")
            try:
                discord_id = int(x_discord_id)
                pool: asyncpg.Pool = request.app.state.db_pool
                async with pool.acquire() as conn:
                    # แปลง discord_id เป็น user_id ตรงนี้เลย
                    user_id = await conn.fetchval("SELECT id FROM users WHERE discord_id = $1", discord_id)
                
                if not user_id:
                    raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้ที่ผูกกับ Discord ID นี้")
                
                return {"user_id": user_id}
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid X-Discord-Id format")
        else:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    # กรณี 2: มาจาก Web (SPA)
    if auth:
        try:
            token = auth.credentials
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("user_id")
            
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid token: Missing user_id")
                
            return {"user_id": int(user_id)}
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Not authenticated: API Key or Bearer Token required")

# 🚀 1.5 สำหรับ System RPC ที่บอท (bot application) ต้องเรียกได้โดยไม่ต้องเป็น user จริง
# เช่น GET /{target_id} (หา announcement_channel_id) — บอทส่ง X-Discord-Id = bot user id
# ที่ไม่มีใน users table → ไม่ 404 แต่คืน {"user_id": None, "is_bot_system": True}
# (Web path ยังเหมือนเดิม — ต้อง JWT จริง)
async def get_current_user_or_bot(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
    x_discord_id: Optional[str] = Header(None),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth)
) -> dict:
    # กรณี 1: มาจาก Discord Bot
    if x_api_key:
        if x_api_key == settings.API_KEY:
            if not x_discord_id:
                raise HTTPException(status_code=400, detail="X-Discord-Id header is required")
            try:
                discord_id = int(x_discord_id)
                pool: asyncpg.Pool = request.app.state.db_pool
                async with pool.acquire() as conn:
                    user_id = await conn.fetchval("SELECT id FROM users WHERE discord_id = $1", discord_id)
                if user_id:
                    return {"user_id": user_id, "is_bot_system": False}
                # 🤖 bot application — มี API key ถูกต้อง แต่ไม่ใช่ user จริงในระบบ
                # (X-Discord-Id = self.bot.user.id) → ให้ผ่านเป็น system bot
                return {"user_id": None, "is_bot_system": True}
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid X-Discord-Id format")
        else:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    # กรณี 2: มาจาก Web (SPA) — เหมือน get_current_user เดิม
    if auth:
        try:
            token = auth.credentials
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("user_id")
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid token: Missing user_id")
            return {"user_id": int(user_id), "is_bot_system": False}
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Not authenticated: API Key or Bearer Token required")

# 🚀 2. ฟังก์ชันใหม่! แปลง Target ให้กลายเป็น room_id เลยทันที (ลบ TargetResolution ทิ้งได้เลย)
async def resolve_target_to_room_id(
    target_id: int = Path(...),
    target_type: Literal["server", "room"] = Query("room", description="ระบุ 'room' สำหรับเว็บ หรือ 'server' สำหรับบอท"),
    pool: asyncpg.Pool = Depends(get_db_pool)
) -> int:
    """
    แปลง server_id หรือ room_id ให้กลายเป็น room_id สุทธิ
    ทำให้ Router และ Service ไม่ต้องสนใจเรื่องข้ามแพลตฟอร์มอีกต่อไป
    """
    async with pool.acquire() as conn:
        if target_type == "room":
            exists = await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", target_id)
            if not exists:
                raise HTTPException(status_code=404, detail=f"ไม่พบห้องเรียน ID: {target_id}")
            return target_id
            
        elif target_type == "server":
            room_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", target_id)
            if not room_id:
                raise HTTPException(status_code=404, detail=f"ไม่พบห้องเรียนที่ผูกกับ Server ID: {target_id}")
            return room_id