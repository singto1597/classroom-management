from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
import asyncpg
from datetime import date
from typing import List, Literal

from models.classroom_sync_schemas import (
    SuccessResponse, RoomSetupRequest, ChannelSetRequest, TimeSetRequest, RoomNotifyResponse,
    DefaultScheduleRequest, OverrideScheduleRequest,
    TaskCreateRequest, TaskEditRequest, TaskResponse, TaskActionResponse,
    DailyNoteRequest, DailyNoteDeletedResponse, DailySummaryResponse, TaskStatus, ActionWithUserRequest, RoomDataResponse,
    AuditLogResponse
)
from core.dependencies import get_db_pool, get_current_user, get_current_user_or_bot, resolve_target_to_room_id, verify_api_key
from core.exceptions import TaskNotFoundError, ForbiddenError, RoomNotFoundError
from services.classroom_sync_service import ClassroomService

router = APIRouter()

# 🌟 ฟังก์ชันตัวช่วยสำหรับดึงข้อมูลลง Audit Log
def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier

@router.post("/setup", response_model=SuccessResponse)
async def setup_room(
    req: RoomSetupRequest,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.setup_room(
            pool, req.room_name, req.user_name,
            client_source=client_source, actor_identifier=actor,
            server_id=req.server_id, user_id=user_ctx.get("user_id")
        )
        return SuccessResponse(message=f"Setup room {req.room_name} completed.")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/notifications/targets", response_model=List[RoomNotifyResponse])
async def get_rooms_to_notify(
    request: Request,
    current_time: str = Query(...), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    api_key: str = Depends(verify_api_key) 
):
    client_source, actor = get_audit_context(request)
    return await ClassroomService.get_rooms_to_notify(
        pool, current_time, 
        client_source=client_source, actor_identifier=actor
    )

@router.get("/{target_id}", response_model=RoomDataResponse)
async def get_room_data(
    request: Request,
    target_id: int = Path(...),
    target_type: Literal["server", "room"] = Query("room", description="ระบุ 'server' สำหรับบอท (ค้นด้วย server_id) หรือ 'room' สำหรับเว็บ (ค้นด้วย id)"),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user_or_bot),
):
    client_source, actor = get_audit_context(request, user_ctx)
    # 🤖 Bot system (X-API-Key + bot user id ที่ไม่ใช่สมาชิก): บอทใช้ endpoint นี้
    # เพื่อหา announcement_channel_id → ข้าม require_member (ส่ง user_id=None)
    # (เป็น system RPC เดียวกับ get_daily_summary — ดู docs/skills.md)
    # 🌐 Web path (JWT) หรือ bot ที่เป็น user จริง: ยังบังคับ require_member กันอ่านข้ามห้อง
    is_bot_system = user_ctx.get("is_bot_system") is True
    try:
        return await ClassroomService.get_room_data(
            pool, target_id=target_id, target_type=target_type,
            client_source=client_source, actor_identifier=actor,
            user_id=None if is_bot_system else user_ctx.get("user_id")
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{target_id}/channel", response_model=SuccessResponse)
async def set_channel(
    req: ChannelSetRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.set_channel(
            pool, req.channel_id, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{target_id}/time", response_model=SuccessResponse)
async def set_notify_time(
    req: TimeSetRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.set_notify_time(
            pool, req.notify_time, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/schedule/default", response_model=SuccessResponse)
async def set_default_schedule(
    req: DefaultScheduleRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.set_default_schedule(
            pool, req.day_of_week, req.attire, req.subjects, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/schedule/override", response_model=SuccessResponse)
async def set_override(
    req: OverrideScheduleRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.set_override(
            pool, req.target_date, req.new_attire, req.note, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/tasks", response_model=SuccessResponse)
async def add_task(
    req: TaskCreateRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    await ClassroomService.add_task(
        pool, req.task_name, req.task_detail, req.due_date, req.user_name, room_id=room_id,
        client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
    )
    return SuccessResponse()

@router.get("/{target_id}/tasks", response_model=List[TaskResponse])
async def get_tasks(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    status: TaskStatus = Query(TaskStatus.PENDING), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    return await ClassroomService.get_tasks(
        pool, client_source=client_source, actor_identifier=actor,
        status=status.value, room_id=room_id, user_id=user_ctx.get("user_id")
    )

@router.get("/{target_id}/tasks/deleted", response_model=List[TaskResponse])
async def get_deleted_tasks(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    return await ClassroomService.get_deleted_tasks(
        pool, room_id=room_id,
        client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
    )

@router.get("/{target_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(
    task_id: int, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await ClassroomService.get_task_by_id(
            pool, task_id, room_id=room_id,
            client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
        )
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{target_id}/tasks/{task_id}", response_model=SuccessResponse)
async def edit_task(
    task_id: int, 
    req: TaskEditRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.edit_task(
            pool, task_id, req.task_name, req.task_detail, req.due_date, req.user_name, room_id=room_id,
            client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
        )
        return SuccessResponse()
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/{target_id}/tasks/{task_id}", response_model=TaskActionResponse)
async def delete_task(
    task_id: int, 
    req: ActionWithUserRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        task_name = await ClassroomService.delete_task(
            pool, task_id, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.patch("/{target_id}/tasks/{task_id}/done", response_model=TaskActionResponse)
async def mark_task_done(
    task_id: int, 
    req: ActionWithUserRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        task_name = await ClassroomService.mark_task_done(
            pool, task_id, req.user_name, room_id=room_id,
            client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
        )
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{target_id}/tasks/{task_id}/restore", response_model=TaskActionResponse)
async def restore_task(
    task_id: int, 
    req: ActionWithUserRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        task_name = await ClassroomService.restore_task(
            pool, task_id, req.user_name, room_id=room_id,
            client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
        )
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{target_id}/notes", response_model=SuccessResponse)
async def add_daily_note(
    req: DailyNoteRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await ClassroomService.add_daily_note(
            pool, req.target_date, req.bring_items, req.announcement, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{target_id}/notes/{target_date}", response_model=DailyNoteDeletedResponse)
async def delete_daily_note(
    target_date: date, 
    req: ActionWithUserRequest, 
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        data = await ClassroomService.delete_daily_note(
            pool, target_date, req.user_name, user_ctx["user_id"], room_id=room_id,
            client_source=client_source, actor_identifier=actor
        )
        return DailyNoteDeletedResponse(bring_items=data["bring_items"], announcement=data["announcement"])
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    request: Request,
    target_date: date, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    client_source, actor = get_audit_context(request)
    return await ClassroomService.get_daily_summary(
        pool, target_date, room_id=room_id,
        client_source=client_source, actor_identifier=actor
    )

@router.get("/{target_id}/logs", response_model=List[AuditLogResponse])
async def get_logs(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    return await ClassroomService.get_audit_logs(
        pool, room_id=room_id,
        client_source=client_source, actor_identifier=actor, user_id=user_ctx.get("user_id")
    )