from fastapi import APIRouter, HTTPException, status, Depends, Request
from services import auth_service
from core.dependencies import get_current_user, get_db_pool
import asyncpg

# ✨ Import Schema ที่เราแยกไฟล์ออกมา
from auth_schemas import ProviderLoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/discord/login", response_model=TokenResponse)
async def discord_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        # 1. แลก Code เป็น Access Token
        if not payload.code:
             raise HTTPException(status_code=400, detail="code is required for Discord login")
             
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        
        # 2. ดึง Profile
        profile = await auth_service.get_discord_user_profile(discord_token)
        
        # 3. Sync ลงฐานข้อมูลกลาง
        user_id = await auth_service.sync_user_to_db(pool, "discord", profile)
        
        # 4. ออก JWT โดยฝัง user_id และ discord_id (ครอบด้วย str() เพื่อความปลอดภัย 100%)
        access_token = auth_service.create_access_token(
            data={"user_id": str(user_id), "discord_id": str(profile["id"])} 
        )
        
        # 🔥 Return กลับไปโดยแปลง user_id เป็น String
        return TokenResponse(
            access_token=access_token, 
            user_id=str(user_id) 
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/google/login", response_model=TokenResponse)
async def google_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        if not payload.access_token:
            raise HTTPException(status_code=400, detail="access_token is required for Google login")
            
        profile = await auth_service.get_google_user_profile(payload.access_token)
        user_id = await auth_service.sync_user_to_db(pool, "google", profile)
        
        # ฝังตัวแปรเป็น str()
        access_token = auth_service.create_access_token(
            data={"user_id": str(user_id)}
        )
        
        # 🔥 Return กลับไปโดยแปลง user_id เป็น String
        return TokenResponse(
            access_token=access_token, 
            user_id=str(user_id)
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))