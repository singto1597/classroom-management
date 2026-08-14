from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import asyncpg
from typing import List, Literal, Optional

from models.activity_schemas import (
    SuccessResponse,
    ActionWithUserRequest,
    ActivityCreateRequest,
    ActivityUpdateRequest,
    ActivityResponse,
    ParticipantAddRequest,
    ParticipantUpdateRequest,
    ParticipantStatusUpdate,
    ActivityExportRequest,
)
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id
from core.exceptions import (
    ActivityNotFoundError,
    ForbiddenError,
    ParticipantNotFoundError,
    RoomNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from services.activity_service import ActivityService

router = APIRouter()


# 🌟 ฟังก์ชันตัวช่วยสำหรับดึงข้อมูลลง Audit Log (copy pattern จาก router อื่น)
def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier


# ================================================================
# 🎪 Activities CRUD
# ================================================================
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
        return await ActivityService.update_activity(
            pool=pool,
            activity_id=activity_id,
            update_data=update_data,
            user_name=req.user_name,
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
            actor_user_id=user_ctx.get("user_id"),
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


# ================================================================
# 👥 Participants
# ================================================================
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


# ================================================================
# 📄 Excel Export
# ================================================================
@router.post("/{target_id}/activities/export", summary="Export ผู้เข้าร่วมกิจกรรมเป็น Excel")
async def export_activity_excel(
    req: ActivityExportRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    POST /api/classroom/{room_id}/activities/export
    body: {"activity_id": 1, "metadata_keys": ["bus_number", "shirt_size"], "user_name": "..."}
    → คืน .xlsx (2 แผ่น: สรุป + รายชื่อผู้เข้าร่วม) พร้อมคอลัมน์จาก metadata
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        excel_file = await ActivityService.export_activity_excel(
            pool=pool,
            activity_id=req.activity_id,
            metadata_keys=req.metadata_keys,
            user_name=req.user_name,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=activity_{req.activity_id}_participants.xlsx"},
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
