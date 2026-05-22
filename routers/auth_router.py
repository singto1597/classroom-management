from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from services import auth_service
from core.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class DiscordLoginRequest(BaseModel):
    code: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/discord/login", response_model=TokenResponse)
async def discord_login(payload: DiscordLoginRequest):
    """
    Endpoint สำหรับแลก code จาก Discord เป็น JWT ของระบบ
    """
    try:
        # 1. แลก code เป็น Discord Access Token
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        
        # 2. เอา Discord Token ไปดึง user_id
        discord_id = await auth_service.get_discord_user_id(discord_token)
        
        # 3. สร้าง JWT โดยฝัง discord_id
        access_token = auth_service.create_access_token(data={"discord_id": discord_id})
        
        return TokenResponse(access_token=access_token)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )

@router.get("/me")
async def get_me(discord_id: int = Depends(get_current_user)):
    """
    Endpoint สำหรับเช็คว่า Token หรือ API Key ยังใช้งานได้ไหม
    และดึง Discord ID ของตัวเองออกมา
    """
    return {"discord_id": discord_id}
