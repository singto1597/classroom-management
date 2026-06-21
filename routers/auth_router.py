from fastapi import APIRouter, HTTPException, status, Depends
from services import auth_service
from core.dependencies import get_current_user, get_db_pool
import asyncpg

from models.auth_schemas import ProviderLoginRequest, TokenResponse, OAuthProfilePayload

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/discord/login", response_model=TokenResponse)
async def discord_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        if not payload.code:
             raise HTTPException(status_code=400, detail="code is required for Discord login")
             
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        profile = await auth_service.get_discord_user_profile(discord_token)
        
        email = profile.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Verified email is required on your Discord account.")
        
        user_payload = OAuthProfilePayload(
            email=email,
            discord_id=int(profile["id"]),
            username=profile.get("username")
        )
        
        user_data = await auth_service.process_user_login(pool=pool, payload=user_payload)
        
        # 🔑 สร้าง Token เก็บแค่ user_id สบายใจที่สุด
        token_payload = {"user_id": str(user_data.user_id)}
        access_token = auth_service.create_access_token(data=token_payload)
        
        return TokenResponse(
            access_token=access_token, 
            user_id=str(user_data.user_id) 
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/google/login", response_model=TokenResponse)
async def google_login(payload: ProviderLoginRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        if not payload.code:
            raise HTTPException(status_code=400, detail="code is required for Google login")
            
        google_token = await auth_service.exchange_google_code_for_token(payload.code)
        profile = await auth_service.get_google_user_info(google_token)
        
        email = profile.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required from Google.")
            
        user_payload = OAuthProfilePayload(
            email=email,
            google_id=profile.get("sub"),
            first_name=profile.get("given_name"),
            last_name=profile.get("family_name")
        )
        
        user_data = await auth_service.process_user_login(pool=pool, payload=user_payload)
        
        # 🔑 สร้าง Token เก็บแค่ user_id
        token_payload = {"user_id": str(user_data.user_id)}
        access_token = auth_service.create_access_token(data=token_payload)
        
        return TokenResponse(
            access_token=access_token, 
            user_id=str(user_data.user_id)
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/me")
async def get_current_user_profile(user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    user_id = user_ctx.get("user_id")
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT id, email, first_name, last_name, username, discord_id, google_id 
            FROM users 
            WHERE id = $1
        """, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found in database.")
        return dict(user)