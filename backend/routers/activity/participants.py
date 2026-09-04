"""ผู้เข้าร่วมกิจกรรม (activity_participants)"""
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

@router.post("/{target_id}/activities/{activity_id}/participants", response_model=SuccessResponse, summary="เพิ่มผู้เข้าร่วมทีละคน")
async def add_participant(
    activity_id: int,
    req: ParticipantAddRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        result = await ActivityService.add_participant(
            pool=pool,
            activity_id=activity_id,
            student_no=req.student_no,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
            role_type=req.role_type,
            role_detail=req.role_detail,
            earned_hours=req.earned_hours,
            status=req.status,
            metadata=req.metadata,
        )
        return SuccessResponse(message=f"เพิ่มผู้เข้าร่วมเลขที่ {req.student_no} สำเร็จ (ID: {result['participant_id']})")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{target_id}/activities/{activity_id}/participants/batch", response_model=SuccessResponse, summary="Batch Apply — ตั้งค่า metadata หลายคนพร้อมกัน (atomic)")
async def batch_update_participants(
    activity_id: int,
    req: BatchParticipantUpdateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    PATCH /{target_id}/activities/{activity_id}/participants/batch
    body: {"items": [{"participant_id": 1, "metadata": {"bus_number": "1"}}, ...], "user_name": "..."}
    → อัปเดต metadata ของทุกคนในชุด (merge กับของเดิม) ภายใน transaction เดียว — atomic
    ใช้กับ UI คลุมดำตั้งค่า (Batch Apply) แล้วยิง payload ก้อนเดียว
    ⚠️ ต้องประกาศก่อน /participants/{participant_id} (literal segment ชน path param ได้)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        items = [i.model_dump() for i in req.items]
        result = await ActivityService.batch_update_participants(
            pool=pool,
            activity_id=activity_id,
            items=items,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"อัปเดต metadata ผู้เข้าร่วม {result['updated_count']} คนสำเร็จ (atomic)")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{target_id}/activities/{activity_id}/participants/{participant_id}", response_model=SuccessResponse, summary="แก้ไขผู้เข้าร่วม (รวม metadata)")
async def update_participant(
    activity_id: int,
    participant_id: int,
    req: ParticipantUpdateRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        update_data = req.model_dump(exclude_unset=True)
        update_data.pop("user_name", None)
        await ActivityService.update_participant(
            pool=pool,
            activity_id=activity_id,
            participant_id=participant_id,
            update_data=update_data,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"แก้ไขผู้เข้าร่วม ID: {participant_id} สำเร็จ")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{target_id}/activities/{activity_id}/participants/{participant_id}/status", response_model=SuccessResponse, summary="เปลี่ยนสถานะผู้เข้าร่วม (เช็คอิน/ยกเลิก)")
async def update_participant_status(
    activity_id: int,
    participant_id: int,
    req: ParticipantStatusUpdate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ActivityService.update_participant_status(
            pool=pool,
            activity_id=activity_id,
            participant_id=participant_id,
            status=req.status,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"เปลี่ยนสถานะผู้เข้าร่วมเป็น '{req.status}' เรียบร้อย")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{target_id}/activities/{activity_id}/participants/{participant_id}", response_model=SuccessResponse, summary="นำผู้เข้าร่วมออก (soft delete)")
async def remove_participant(
    activity_id: int,
    participant_id: int,
    req: ActionWithUserRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ActivityService.remove_participant(
            pool=pool,
            activity_id=activity_id,
            participant_id=participant_id,
            user_name=req.user_name,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
        return SuccessResponse(message=f"นำผู้เข้าร่วม ID: {participant_id} ออกจากกิจกรรมแล้ว")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ParticipantNotFoundError, ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{target_id}/activities/{activity_id}/participants/available", response_model=List[AvailableStudentResponse], summary="รายชื่อนักเรียนที่ยังไม่ได้เข้าร่วมกิจกรรม")
async def list_available_students(
    activity_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """GET /activities/{activity_id}/participants/available → students active ในห้องที่ยังไม่เข้า (เป็น member ได้)
    ⚠️ ต้องประกาศก่อน /participants/{participant_id} (literal "available" ชน path param ได้)"""
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await ActivityService.list_available_students(
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


@router.post("/{target_id}/activities/{activity_id}/participants/batch", response_model=SuccessResponse, summary="เพิ่มผู้เข้าร่วมหลายคนพร้อมกัน (atomic, revive-or-insert)")
async def batch_add_participants(
    activity_id: int,
    req: ParticipantBatchAddRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """POST /activities/{activity_id}/participants/batch — body: {items: [{student_no, ...}], user_name}
    ⚠️ ต้องประกาศก่อน /participants/{participant_id} (literal "batch" ชน path param ได้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        items = [i.model_dump() for i in req.items]
        result = await ActivityService.batch_add_participants(
            pool=pool,
            activity_id=activity_id,
            items=items,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
        )
        return SuccessResponse(message=f"เพิ่มผู้เข้าร่วม {result['updated_count']} คนสำเร็จ")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
