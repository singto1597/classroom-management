from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel
from services import auth_service
from core.dependencies import get_current_user, get_db_pool
import asyncpg

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class ProviderLoginRequest(BaseModel):
    code: str  # สำหรับ Discord
    access_token: str = None # สำหรับส่ง Token จากฝั่ง Client (Google Login)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int

@router.post("/discord/login", response_model=TokenResponse)
async def discord_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        # 1. แลก Code เป็น Access Token
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        
        # 2. ดึง Profile
        profile = await auth_service.get_discord_user_profile(discord_token)
        
        # 3. Sync ลงฐานข้อมูลกลาง
        user_id = await auth_service.sync_user_to_db(pool, "discord", profile)
        
        # 4. ออก JWT โดยฝัง user_id เป็นหลัก (อาจฝัง discord_id ไปด้วยเผื่อจำเป็น)
        access_token = auth_service.create_access_token(
            data={"user_id": user_id, "discord_id": int(profile["id"])}
        )
        
        return TokenResponse(access_token=access_token, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/google/login", response_model=TokenResponse)
async def google_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        # สมมติว่า Frontend ใช้ Google SDK ล็อกอินแล้วส่ง access_token (หรือ id_token) มาให้
        if not payload.access_token:
            raise HTTPException(status_code=400, detail="access_token is required for Google login")
            
        profile = await auth_service.get_google_user_profile(payload.access_token)
        user_id = await auth_service.sync_user_to_db(pool, "google", profile)
        
        access_token = auth_service.create_access_token(data={"user_id": user_id})
        
        return TokenResponse(access_token=access_token, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/me")
async def get_me(user_context: dict = Depends(get_current_user)):
    # Dependency ใหม่จะ Return เป็น Dictionary แทน
    return user_context