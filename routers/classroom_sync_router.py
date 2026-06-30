from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg
from datetime import date
from typing import List

from models.classroom_sync_schemas import (
    SuccessResponse, RoomSetupRequest, ChannelSetRequest, TimeSetRequest, RoomNotifyResponse,
    DefaultScheduleRequest, OverrideScheduleRequest,
    TaskCreateRequest, TaskEditRequest, TaskResponse, TaskActionResponse,
    DailyNoteRequest, DailyNoteDeletedResponse, DailySummaryResponse, TaskStatus, ActionWithUserRequest, RoomDataResponse
)
# 🚨 เพิ่มการ Import verify_api_key เข้ามา
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id, verify_api_key
from core.exceptions import TaskNotFoundError, ForbiddenError
from services.classroom_sync_service import ClassroomService

router = APIRouter()

@router.post("/setup", response_model=SuccessResponse)
async def setup_room(
    req: RoomSetupRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    await ClassroomService.setup_room(pool, req.room_name, req.user_name, server_id=req.server_id)
    return SuccessResponse(message=f"Setup room {req.room_name} completed.")

# 🌟 ฟังก์ชันแจ้งเตือนบอทอัตโนมัติ (แก้ไขระบบสิทธิ์ให้บอทเข้าถึงได้โดยไม่ต้องยืนยันตัวตนมนุษย์)
@router.get("/notifications/targets", response_model=List[RoomNotifyResponse])
async def get_rooms_to_notify(
    current_time: str = Query(...), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    api_key: str = Depends(verify_api_key) # 🚨 เปลี่ยนมาใช้ตรวจสอบแค่ API Key แทน!
):
    return await ClassroomService.get_rooms_to_notify(pool, current_time)

@router.get("/{target_id}", response_model=RoomDataResponse)
async def get_room_data(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await ClassroomService.get_room_data(pool, room_id=room_id)

@router.put("/{target_id}/channel", response_model=SuccessResponse)
async def set_channel(
    req: ChannelSetRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.set_channel(pool, req.channel_id, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{target_id}/time", response_model=SuccessResponse)
async def set_notify_time(
    req: TimeSetRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.set_notify_time(pool, req.notify_time, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/schedule/default", response_model=SuccessResponse)
async def set_default_schedule(
    req: DefaultScheduleRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.set_default_schedule(pool, req.day_of_week, req.attire, req.subjects, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/schedule/override", response_model=SuccessResponse)
async def set_override(
    req: OverrideScheduleRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.set_override(pool, req.target_date, req.new_attire, req.note, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/tasks", response_model=SuccessResponse)
async def add_task(
    req: TaskCreateRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    await ClassroomService.add_task(pool, req.task_name, req.task_detail, req.due_date, req.user_name, room_id=room_id)
    return SuccessResponse()

@router.get("/{target_id}/tasks", response_model=List[TaskResponse])
async def get_tasks(
    room_id: int = Depends(resolve_target_to_room_id),
    status: TaskStatus = Query(TaskStatus.PENDING), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await ClassroomService.get_tasks(pool, status.value, room_id=room_id)

@router.get("/{target_id}/tasks/deleted", response_model=List[TaskResponse])
async def get_deleted_tasks(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await ClassroomService.get_deleted_tasks(pool, room_id=room_id)

@router.get("/{target_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(
    task_id: int, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await ClassroomService.get_task_by_id(pool, task_id, room_id=room_id)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{target_id}/tasks/{task_id}", response_model=SuccessResponse)
async def edit_task(
    task_id: int, 
    req: TaskEditRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.edit_task(pool, task_id, req.task_name, req.task_detail, req.due_date, req.user_name, room_id=room_id)
        return SuccessResponse()
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/{target_id}/tasks/{task_id}", response_model=TaskActionResponse)
async def delete_task(
    task_id: int, 
    req: ActionWithUserRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.delete_task(pool, task_id, req.user_name, user_ctx["user_id"], room_id=room_id)
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.patch("/{target_id}/tasks/{task_id}/done", response_model=TaskActionResponse)
async def mark_task_done(
    task_id: int, 
    req: ActionWithUserRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.mark_task_done(pool, task_id, req.user_name, room_id=room_id)
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{target_id}/tasks/{task_id}/restore", response_model=TaskActionResponse)
async def restore_task(
    task_id: int, 
    req: ActionWithUserRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.restore_task(pool, task_id, req.user_name, room_id=room_id)
        return TaskActionResponse(task_name=task_name)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{target_id}/notes", response_model=SuccessResponse)
async def add_daily_note(
    req: DailyNoteRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await ClassroomService.add_daily_note(pool, req.target_date, req.bring_items, req.announcement, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse()
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{target_id}/notes/{target_date}", response_model=DailyNoteDeletedResponse)
async def delete_daily_note(
    target_date: date, 
    req: ActionWithUserRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        data = await ClassroomService.delete_daily_note(pool, target_date, req.user_name, user_ctx["user_id"], room_id=room_id)
        return DailyNoteDeletedResponse(bring_items=data["bring_items"], announcement=data["announcement"])
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    target_date: date, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool)
    # user_ctx: dict = Depends(get_current_user)
):
    return await ClassroomService.get_daily_summary(pool, target_date, room_id=room_id)

@router.get("/{target_id}/logs")
async def get_logs(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await ClassroomService.get_audit_logs(pool, room_id=room_id)