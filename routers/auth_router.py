from fastapi import APIRouter, HTTPException, status, Depends, Request
from services import auth_service
from core.dependencies import get_current_user, get_db_pool
import asyncpg

from models.auth_schemas import ProviderLoginRequest, TokenResponse, OAuthProfilePayload, UserProfileUpdate

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# 🌟 ฟังก์ชันแกะรอยผู้ใช้งาน
def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier

@router.post("/discord/login", response_model=TokenResponse)
async def discord_login(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        client_source, actor = get_audit_context(request)
        if not payload.code: raise HTTPException(status_code=400, detail="code is required")
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        profile = await auth_service.get_discord_user_profile(discord_token)
        
        email = profile.get("email")
        if not email: raise HTTPException(status_code=400, detail="Verified email is required on your Discord account.")
        
        user_payload = OAuthProfilePayload(email=email, discord_id=int(profile["id"]), username=profile.get("username"))
        
        # 🚨 ส่งตัวแปร Log เข้าไป
        user_data = await auth_service.process_user_login(
            pool=pool, 
            payload=user_payload,
            client_source=client_source,
            actor_identifier=actor
        )
        
        token_payload = {"user_id": str(user_data.user_id)}
        if user_data.discord_id: token_payload["discord_id"] = str(user_data.discord_id)
            
        access_token = auth_service.create_access_token(data=token_payload)
        return TokenResponse(access_token=access_token, user_id=str(user_data.user_id))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/google/login", response_model=TokenResponse)
async def google_login(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        client_source, actor = get_audit_context(request)
        if not payload.code: raise HTTPException(status_code=400, detail="code is required")
        google_token = await auth_service.exchange_google_code_for_token(payload.code)
        profile = await auth_service.get_google_user_info(google_token)
        
        email = profile.get("email")
        if not email: raise HTTPException(status_code=400, detail="Email is required from Google.")
            
        user_payload = OAuthProfilePayload(
            email=email, google_id=profile.get("sub"),
            first_name=profile.get("given_name"), last_name=profile.get("family_name")
        )
        
        # 🚨 ส่งตัวแปร Log เข้าไป
        user_data = await auth_service.process_user_login(
            pool=pool, 
            payload=user_payload,
            client_source=client_source,
            actor_identifier=actor
        )
        
        token_payload = {"user_id": str(user_data.user_id)}
        access_token = auth_service.create_access_token(data=token_payload)
        
        return TokenResponse(access_token=access_token, user_id=str(user_data.user_id))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/discord/link")
async def link_discord(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        profile = await auth_service.get_discord_user_profile(discord_token)
        return await auth_service.link_oauth_account(
            pool, user_ctx["user_id"], "discord", profile,
            client_source=client_source, actor_identifier=actor
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/google/link")
async def link_google(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        google_token = await auth_service.exchange_google_code_for_token(payload.code)
        profile = await auth_service.get_google_user_info(google_token)
        return await auth_service.link_oauth_account(
            pool, user_ctx["user_id"], "google", profile,
            client_source=client_source, actor_identifier=actor
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    user_id = current_user.get("user_id")
    if not user_id: raise HTTPException(status_code=404, detail="User mapping not found.")
        
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, prefix, email, first_name, last_name, username, discord_id, google_id FROM users WHERE id = $1", user_id)
        if not user: raise HTTPException(status_code=404, detail="User not found in database.")
        return dict(user)

@router.patch("/me", summary="อัปเดตข้อมูลโปรไฟล์ส่วนตัว (Onboarding)")
async def update_my_profile(
    payload: UserProfileUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        client_source, actor = get_audit_context(request, current_user)
        user_id = current_user.get("user_id")
        if not user_id: 
            raise HTTPException(status_code=401, detail="User mapping not found.")
        
        return await auth_service.update_user_profile(
            pool, int(user_id), payload,
            client_source=client_source, actor_identifier=actor
        )
        
    except HTTPException as he:
        raise he 
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))