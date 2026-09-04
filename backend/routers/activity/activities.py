"""CRUD กิจกรรม (activities) + บทบาทของฉัน"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import asyncpg
from typing import List, Literal, Optional
from urllib.parse import quote

from models.activity_schemas import (
    SuccessResponse,
    ActionWithUserRequest,
    ActivityCreateRequest,
    ActivityUpdateRequest,
    ActivityResponse,
    ParticipantAddRequest,
    ParticipantUpdateRequest,
    ParticipantStatusUpdate,
    BatchParticipantUpdateRequest,
    ActivityExportRequest,
    CheckinSheetCreateRequest,
    CheckinSheetUpdateRequest,
    CheckinSheetResponse,
    CheckinSheetDetailResponse,
    CheckinRecordUpsertRequest,
    CheckinRecordsBatchRequest,
    ParticipantBatchAddRequest,
    AvailableStudentResponse,
)
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id
from core.exceptions import (
    ActivityNotFoundError,
    CheckinSheetNotFoundError,
    ForbiddenError,
    ParticipantNotFoundError,
    RoomNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from services.activity_service import ActivityService

from routers._common import get_audit_context

router = APIRouter()

@router.post("/{target_id}/activities", response_model=SuccessResponse, summary="สร้างกิจกรรม + ผู้เข้าร่วม")
async def create_activity(
    req: ActivityCreateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    สร้างกิจกรรมใหม่ พร้อมรายชื่อผู้เข้าร่วม (หลายคน) ภายใน transaction เดียว
    - Web: POST /api/classroom/{room_id}/activities?target_type=room (JWT)
    - Bot: POST /api/classroom/{server_id}/activities?target_type=server (X-API-Key + X-Discord-Id)
    - RBAC: MANAGE_ACTIVITIES
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        participants = [p.model_dump() for p in req.participants]
        result = await ActivityService.create_activity(
            pool=pool,
            title=req.title,
            description=req.description,
            activity_date=req.activity_date,
            base_hours=req.base_hours,
            status=req.status,
            metadata=req.metadata,
            participants=participants,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"สร้างกิจกรรม '{req.title}' สำเร็จ (ID: {result['activity_id']})")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{target_id}/activities", response_model=List[ActivityResponse], summary="รายการกิจกรรมทั้งหมด")
async def list_activities(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    status: Optional[str] = None,
    include_participants: bool = False,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    ดึงรายการกิจกรรมของห้อง (เรียงตามวัน activity_date)
    - query param status: upcoming/ongoing/completed/cancelled (ไม่ส่ง = ทั้งหมด)
    - query param include_participants=true: แนบรายชื่อผู้เข้าร่วมในแต่ละกิจกรรม (ใช้หน้า detail)
    """
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.list_activities(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            user_id=user_ctx.get("user_id"),
            status=status,
            include_participants=include_participants,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{target_id}/activities/me/roles", response_model=List[dict], summary="กิจกรรม + หน้าที่ของฉัน")
async def get_my_activity_roles(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    คืนกิจกรรมทั้งหมดที่ user นี้เข้าร่วม พร้อม role_detail + metadata (เบอร์รถบัส ฯลฯ)
    ใช้กับบอท /my_roles — bot path ส่ง X-Discord-Id + X-API-Key ผ่าน get_current_user
    ⚠️ ต้องประกาศก่อน /{activity_id} ไม่งั้น FastAPI จะ match "me" เป็น activity_id → 422
    """
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.get_student_activity_roles(
            pool=pool,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{target_id}/activities/{activity_id}", response_model=ActivityResponse, summary="ดูรายละเอียดกิจกรรม + ผู้เข้าร่วม")
async def get_activity(
    activity_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.get_activity(
            pool=pool,
            activity_id=activity_id,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            user_id=user_ctx.get("user_id"),
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{target_id}/activities/{activity_id}", response_model=ActivityResponse, summary="แก้ไขกิจกรรม")
async def update_activity(
    activity_id: int,
    req: ActivityUpdateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    PATCH กิจกรรม — ส่งแค่ฟิลด์ที่อยากแก้ (exclude_unset=True)
    metadata ที่ส่งมาจะ merge กับของเดิม (ไม่ทับคีย์ที่ไม่ได้ส่ง)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        update_data = req.model_dump(exclude_unset=True)
        update_data.pop("user_name", None)
        participants = update_data.pop("participants", None)
        return await ActivityService.update_activity(
            pool=pool,
            activity_id=activity_id,
            update_data=update_data,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
            participants=participants,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{target_id}/activities/{activity_id}", response_model=SuccessResponse, summary="ลบกิจกรรม (soft delete)")
async def delete_activity(
    activity_id: int,
    req: ActionWithUserRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ActivityService.delete_activity(
            pool=pool,
            activity_id=activity_id,
            user_name=req.user_name,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
        return SuccessResponse(message=f"ลบกิจกรรม ID: {activity_id} เรียบร้อยแล้ว (soft delete)")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
