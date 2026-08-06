from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg

from models.action_schemas import CustomMessageRequest, CustomMessageResponse
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id
from core.exceptions import RoomNotFoundError, ForbiddenError
from services.action_service import ActionService

router = APIRouter()

def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier

@router.post("/{target_id}/messages", response_model=CustomMessageResponse, summary="ส่งข้อความประกาศเข้า Discord (จากเว็บ)")
async def send_custom_message(
    req: CustomMessageRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    ฟีเจอร์เว็บ → Discord: ผู้ใช้พิมพ์ข้อความแล้วกดส่ง ระบบจะ push event CUSTOM_MESSAGE
    เข้า Redis (channel classroom_events) แล้วบอทจะประกาศเป็น Embed ในห้อง announcement

    - Web path: POST /api/classroom/{room_id}/messages?target_type=room
    - Bot path: POST /api/classroom/{server_id}/messages?target_type=server (X-API-Key + X-Discord-Id)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        result = await ActionService.send_custom_message(
            pool=pool,
            room_id=room_id,
            title=req.title,
            message=req.message,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx.get("user_id"),
        )
        return CustomMessageResponse(message=result["message"])
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
