from fastapi import Request, Security, HTTPException, status, Header
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid API Key"
        )
    return api_key

async def get_current_user(
    x_api_key: Optional[str] = Security(api_key_header),
    x_discord_id: Optional[str] = Header(None),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth)
) -> int:
    """
    Dependency ตรวจสอบสิทธิ์รองรับ 2 รูปแบบ:
    1. API Key + X-Discord-Id (สำหรับ Discord Bot)
    2. JWT Bearer Token (สำหรับ Vue.js SPA)
    Return: discord_id (int)
    """
    
    # 1. เช็คแบบ API Key (Discord Bot)
    if x_api_key:
        if x_api_key == settings.API_KEY:
            if not x_discord_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="X-Discord-Id header is required when using API Key"
                )
            try:
                return int(x_discord_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid X-Discord-Id format"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key"
            )

    # 2. เช็คแบบ JWT (Vue.js)
    if auth:
        try:
            token = auth.credentials
            payload = jwt.decode(
                token, 
                settings.JWT_SECRET, 
                algorithms=[settings.JWT_ALGORITHM]
            )
            discord_id: str = payload.get("discord_id")
            if discord_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: Missing discord_id"
                )
            return int(discord_id)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid discord_id format in token"
            )

    # ถ้าไม่เข้าเงื่อนไขไหนเลย
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated: API Key or Bearer Token required"
    )
