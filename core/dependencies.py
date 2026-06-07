from fastapi import Request, Security, HTTPException, status, Header, Depends
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import asyncpg
from typing import Optional
from core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

async def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool

def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return api_key

async def get_current_user(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
    x_discord_id: Optional[str] = Header(None),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth)
) -> dict:
    """
    The Bridge Dependency: รองรับทั้งระบบเก่าและใหม่แบบไร้รอยต่อ
    Return: {"user_id": int | None, "discord_id": int | None}
    """
    
    # 1. เช็คแบบ API Key (Discord Bot - ระบบเดิม)
    if x_api_key:
        if x_api_key == settings.API_KEY:
            if not x_discord_id:
                raise HTTPException(status_code=400, detail="X-Discord-Id header is required")
            try:
                discord_id = int(x_discord_id)
                
                # 🌉 Mapping discord_id เป็น user_id 
                pool: asyncpg.Pool = request.app.state.db_pool
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT id FROM users WHERE discord_id = $1", discord_id)
                
                user_id = row["id"] if row else None
                
                return {"user_id": user_id, "discord_id": discord_id}
                
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid X-Discord-Id format")
        else:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    # 2. เช็คแบบ JWT (Vue.js SPA - ระบบใหม่)
    if auth:
        try:
            token = auth.credentials
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            
            user_id = payload.get("user_id")
            discord_id = payload.get("discord_id") 
            
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid token: Missing user_id")
                
            return {
                "user_id": int(user_id) if user_id else None, 
                "discord_id": int(discord_id) if discord_id else None
            }
            
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Not authenticated: API Key or Bearer Token required")