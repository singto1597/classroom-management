import logging

from fastapi import APIRouter, HTTPException, status, Depends, Request
from services import auth_service
from core.dependencies import get_current_user, get_db_pool
from core.exceptions import ForbiddenError
from routers._common import get_audit_context
import asyncpg

from models.auth_schemas import (
    ProviderLoginRequest, TokenResponse, OAuthProfilePayload, UserProfileUpdate,
    UserProfileResponse, SuccessResponse,
)

logger = logging.getLogger("API_AUTH")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# =====================================================================================
# 🔴 ผลตรวจระบบ 2026-09-23 → M6/M7: การจัดการข้อผิดพลาดในไฟล์นี้
# =====================================================================================
# เดิมทุก endpoint ปิดท้ายด้วย
#
#     except Exception as e:
#         raise HTTPException(status_code=..., detail=str(e))
#
# ซึ่งมีบั๊กสองชั้นพร้อมกัน
#
# 1) **4xx ที่ตั้งใจตอบ กลับกลายเป็น 500**
#    `HTTPException` สืบทอดจาก `Exception` (ไม่ใช่ `BaseException`)
#    ⇒ `raise HTTPException(400, "code is required")` ที่อยู่ **ภายใน** try
#      ถูกตัวดักล่างจับไปแปลงเป็น 500 พร้อมข้อความที่ถูก stringify
#      ⇒ ผู้ใช้ที่ส่ง request ผิดเห็น 500 ซึ่งสื่อว่า "เซิร์ฟเวอร์พัง" ทั้งที่ความจริง
#        เป็นความผิดของ request และฝั่ง client ก็จะไม่พยายามแก้ที่ต้นเหตุ
#      ⚠️ `PATCH /me` เคยถูกแก้จุดนี้ไว้แล้ว (`except HTTPException as he: raise he`)
#         แต่ `login` สองตัวยังไม่ได้แก้ ⇒ เป็นตัวอย่างว่าทำไมต้องมีเทสต์คุม ไม่ใช่ความจำ
#
# 2) **`str(e)` รั่วข้อมูลภายใน**
#    ข้อความ exception ของ asyncpg / httpx มีชื่อตารางและคอลัมน์, SQL ที่ล้มเหลว
#    และบางครั้งก็มีที่อยู่ภายใน ⇒ ไม่ควรไปถึง client (บันทึกที่ log แทน)
#
# ⇒ ลำดับ `except` ต้องเป็น **แคบ → กว้าง** เสมอ: `HTTPException` ก่อน แล้วค่อย `Exception`
# =====================================================================================


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("เข้าสู่ระบบด้วย Discord ล้มเหลว")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เข้าสู่ระบบด้วย Discord ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        )

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
    except HTTPException:
        raise
    except Exception:
        logger.exception("เข้าสู่ระบบด้วย Google ล้มเหลว")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="เข้าสู่ระบบด้วย Google ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        )

@router.post("/discord/link", response_model=SuccessResponse)
async def link_discord(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        discord_token = await auth_service.exchange_code_for_token(payload.code)
        profile = await auth_service.get_discord_user_profile(discord_token)
        return await auth_service.link_oauth_account(
            pool, user_ctx["user_id"], "discord", profile,
            client_source=client_source, actor_identifier=actor
        )
    except HTTPException:
        raise
    except ForbiddenError as e:
        # ⚠️ `ForbiddenError` เป็น **ข้อความที่ตั้งใจให้ผู้ใช้เห็น** ไม่ใช่ข้อความภายใน
        #    ("บัญชีนี้ผูกกับ discord ID ... อยู่แล้ว กรุณาใช้ ID เดิม")
        #    ⇒ ต้องส่งต่อ ห้ามกลืนเข้าข้อความกลาง ไม่งั้นผู้ใช้จะไม่รู้ว่าต้องทำอะไรต่อ
        #    ⚠️ คงรหัส 400 เดิมไว้ (ไม่เปลี่ยนเป็น 403) — งานนี้คือ "คืนข้อความที่หายไป"
        #       ไม่ใช่เปลี่ยนสัญญาบนสาย
        logger.warning("ผูกบัญชี Discord ถูกปฏิเสธ: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        # ⚠️ คงรหัส 400 เดิมไว้ — การผูกบัญชีล้มเหลวเกือบทั้งหมดมาจากฝั่ง request
        #    (code หมดอายุ / บัญชีนั้นถูกผูกกับคนอื่นแล้ว) งานนี้แก้เรื่อง "ข้อความที่รั่ว"
        #    ไม่ใช่เรื่องรหัสสถานะ ⇒ เปลี่ยนรหัสเป็นงานคนละเรื่องที่ควรมีเทสต์คุมเอง
        logger.exception("ผูกบัญชี Discord ล้มเหลว (user_id=%s)", user_ctx.get("user_id"))
        raise HTTPException(status_code=400, detail="ผูกบัญชี Discord ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")

@router.post("/google/link", response_model=SuccessResponse)
async def link_google(payload: ProviderLoginRequest, request: Request, pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        google_token = await auth_service.exchange_google_code_for_token(payload.code)
        profile = await auth_service.get_google_user_info(google_token)
        return await auth_service.link_oauth_account(
            pool, user_ctx["user_id"], "google", profile,
            client_source=client_source, actor_identifier=actor
        )
    except HTTPException:
        raise
    except ForbiddenError as e:
        # ⚠️ เหตุผลเดียวกับ `link_discord` — ข้อความนี้ตั้งใจให้ผู้ใช้เห็น
        logger.warning("ผูกบัญชี Google ถูกปฏิเสธ: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("ผูกบัญชี Google ล้มเหลว (user_id=%s)", user_ctx.get("user_id"))
        raise HTTPException(status_code=400, detail="ผูกบัญชี Google ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    user_id = current_user.get("user_id")
    if not user_id: raise HTTPException(status_code=404, detail="User mapping not found.")

    # 🔴 M5: SQL เดิมอยู่ตรงนี้ตรง ๆ — ย้ายไป services/auth_service.get_user_profile()
    #    ตามกฎชั้นสถาปัตยกรรม (routers/ ห้ามมี SQL)
    profile = await auth_service.get_user_profile(pool, int(user_id))
    if not profile: raise HTTPException(status_code=404, detail="User not found in database.")
    return profile

@router.patch("/me", response_model=SuccessResponse, summary="อัปเดตข้อมูลโปรไฟล์ส่วนตัว (Onboarding)")
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

    except HTTPException:
        raise
    except Exception:
        logger.exception("อัปเดตโปรไฟล์ล้มเหลว (user_id=%s)", current_user.get("user_id"))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="อัปเดตโปรไฟล์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        )
