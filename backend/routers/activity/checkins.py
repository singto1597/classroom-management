"""แผ่นเช็คชื่อ (activity_checkin_sheets) + บันทึกเช็คอิน"""
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

@router.get("/{target_id}/activities/{activity_id}/checkins", response_model=List[CheckinSheetResponse], summary="รายการแผ่นเช็คชื่อ")
async def list_checkin_sheets(
    activity_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """GET /api/classroom/{room_id}/activities/{activity_id}/checkins → รายการแผ่นเช็คชื่อ + checked/total"""
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.list_checkin_sheets(
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


@router.post("/{target_id}/activities/{activity_id}/checkins", response_model=SuccessResponse, summary="สร้างแผ่นเช็คชื่อ")
async def create_checkin_sheet(
    activity_id: int,
    req: CheckinSheetCreateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """POST /activities/{activity_id}/checkins — body: {title, event_date?, user_name}"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        result = await ActivityService.create_checkin_sheet(
            pool=pool,
            activity_id=activity_id,
            title=req.title,
            event_date=req.event_date,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"สร้างแผ่นเช็คชื่อ '{req.title}' สำเร็จ (ID: {result['sheet_id']})")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{target_id}/activities/{activity_id}/checkins/{sheet_id}", response_model=CheckinSheetDetailResponse, summary="ดูแผ่นเช็คชื่อ + ผู้เข้าร่วม + เครื่องหมาย")
async def get_checkin_sheet(
    activity_id: int,
    sheet_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.get_checkin_sheet(
            pool=pool,
            activity_id=activity_id,
            sheet_id=sheet_id,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            user_id=user_ctx.get("user_id"),
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (CheckinSheetNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{target_id}/activities/{activity_id}/checkins/{sheet_id}", response_model=SuccessResponse, summary="แก้ไขแผ่นเช็คชื่อ")
async def update_checkin_sheet(
    activity_id: int,
    sheet_id: int,
    req: CheckinSheetUpdateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        update_data = req.model_dump(exclude_unset=True)
        update_data.pop("user_name", None)
        await ActivityService.update_checkin_sheet(
            pool=pool,
            activity_id=activity_id,
            sheet_id=sheet_id,
            update_data=update_data,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"แก้ไขแผ่นเช็คชื่อ ID: {sheet_id} สำเร็จ")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (CheckinSheetNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{target_id}/activities/{activity_id}/checkins/{sheet_id}", response_model=SuccessResponse, summary="ลบแผ่นเช็คชื่อ (soft delete + records)")
async def delete_checkin_sheet(
    activity_id: int,
    sheet_id: int,
    req: ActionWithUserRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ActivityService.delete_checkin_sheet(
            pool=pool,
            activity_id=activity_id,
            sheet_id=sheet_id,
            user_name=req.user_name,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
        return SuccessResponse(message=f"ลบแผ่นเช็คชื่อ ID: {sheet_id} แล้ว")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (CheckinSheetNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{target_id}/activities/{activity_id}/checkins/{sheet_id}/records/{participant_id}", response_model=SuccessResponse, summary="เช็คชื่อ 1 คน (upsert)")
async def upsert_checkin_record(
    activity_id: int,
    sheet_id: int,
    participant_id: int,
    req: CheckinRecordUpsertRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """PUT /activities/{activity_id}/checkins/{sheet_id}/records/{participant_id} — body: {is_present, user_name}"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        result = await ActivityService.upsert_checkin_record(
            pool=pool,
            activity_id=activity_id,
            sheet_id=sheet_id,
            participant_id=participant_id,
            is_present=req.is_present,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"เช็คชื่อผู้เข้าร่วม ID: {participant_id} เรียบร้อย (ID: {result['record_id']})")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (CheckinSheetNotFoundError, ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{target_id}/activities/{activity_id}/checkins/{sheet_id}/records", response_model=SuccessResponse, summary="เช็คชื่อหลายคน (batch, atomic)")
async def batch_update_checkin_records(
    activity_id: int,
    sheet_id: int,
    req: CheckinRecordsBatchRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """POST /activities/{activity_id}/checkins/{sheet_id}/records — body: {records: [{participant_id, is_present}], user_name}"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        records = [r.model_dump() for r in req.records]
        result = await ActivityService.batch_update_checkin_records(
            pool=pool,
            activity_id=activity_id,
            sheet_id=sheet_id,
            records=records,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"เช็คชื่อ {result['updated_count']} คนสำเร็จ (atomic)")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (CheckinSheetNotFoundError, ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
