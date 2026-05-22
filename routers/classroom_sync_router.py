from fastapi import APIRouter, Depends, HTTPException, Query, Header
import asyncpg
from datetime import date
from typing import List, Optional

from models.classroom_sync_schemas import (
    SuccessResponse, RoomSetupRequest, ChannelSetRequest, TimeSetRequest, RoomNotifyResponse,
    DefaultScheduleRequest, OverrideScheduleRequest,
    TaskCreateRequest, TaskEditRequest, TaskResponse, TaskActionResponse,
    DailyNoteRequest, DailyNoteDeletedResponse, DailySummaryResponse, TaskStatus, ActionWithUserRequest, RoomDataResponse
)
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, TaskNotFoundError, ForbiddenError
from services.classroom_sync_service import ClassroomService

router = APIRouter()

@router.post("/setup", response_model=SuccessResponse)
async def setup_room(
    req: RoomSetupRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    await ClassroomService.setup_room(pool, req.server_id, req.room_name, req.user_name)
    return SuccessResponse(message=f"Setup room {req.room_name} completed.")

@router.get("/{server_id}", response_model=RoomDataResponse)
async def get_room_data(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    """ดึงข้อมูลการตั้งค่าของห้องเรียน (เช่น ช่องแจ้งเตือนหลัก, เวลาแจ้งเตือน)"""
    try:
        return await ClassroomService.get_room_data(pool, server_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{server_id}/channel", response_model=SuccessResponse)
async def set_channel(
    server_id: int, 
    req: ChannelSetRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.set_channel(pool, server_id, req.channel_id, req.user_name, discord_id)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{server_id}/time", response_model=SuccessResponse)
async def set_notify_time(
    server_id: int, 
    req: TimeSetRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.set_notify_time(pool, server_id, req.notify_time, req.user_name, discord_id)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/notifications/targets", response_model=List[RoomNotifyResponse])
async def get_rooms_to_notify(
    current_time: str = Query(...), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    return await ClassroomService.get_rooms_to_notify(pool, current_time)

@router.post("/{server_id}/schedule/default", response_model=SuccessResponse)
async def set_default_schedule(
    server_id: int, 
    req: DefaultScheduleRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.set_default_schedule(pool, server_id, req.day_of_week, req.attire, req.subjects, req.user_name, discord_id)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{server_id}/schedule/override", response_model=SuccessResponse)
async def set_override(
    server_id: int, 
    req: OverrideScheduleRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.set_override(pool, server_id, req.target_date, req.new_attire, req.note, req.user_name, discord_id)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{server_id}/tasks", response_model=SuccessResponse)
async def add_task(
    server_id: int, 
    req: TaskCreateRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.add_task(pool, server_id, req.task_name, req.task_detail, req.due_date, req.user_name)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{server_id}/tasks", response_model=List[TaskResponse])
async def get_tasks(
    server_id: int, 
    status: TaskStatus = Query(TaskStatus.PENDING), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await ClassroomService.get_tasks(pool, server_id, status.value)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{server_id}/tasks/deleted", response_model=List[TaskResponse])
async def get_deleted_tasks(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    return await ClassroomService.get_deleted_tasks(pool, server_id)

@router.get("/{server_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(
    server_id: int, 
    task_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await ClassroomService.get_task_by_id(pool, server_id, task_id)
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{server_id}/tasks/{task_id}", response_model=SuccessResponse)
async def edit_task(
    server_id: int, 
    task_id: int, 
    req: TaskEditRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.edit_task(pool, server_id, task_id, req.task_name, req.task_detail, req.due_date, req.user_name)
        return SuccessResponse()
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/{server_id}/tasks/{task_id}", response_model=TaskActionResponse)
async def delete_task(
    server_id: int, 
    task_id: int, 
    req: ActionWithUserRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.delete_task(pool, server_id, task_id, req.user_name, discord_id)
        return TaskActionResponse(task_name=task_name)
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    

@router.patch("/{server_id}/tasks/{task_id}/done", response_model=TaskActionResponse)
async def mark_task_done(
    server_id: int, 
    task_id: int, 
    req: ActionWithUserRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.mark_task_done(pool, server_id, task_id, req.user_name)
        return TaskActionResponse(task_name=task_name)
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{server_id}/tasks/{task_id}/restore", response_model=TaskActionResponse)
async def restore_task(
    server_id: int, 
    task_id: int, 
    req: ActionWithUserRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        task_name = await ClassroomService.restore_task(pool, server_id, task_id, req.user_name)
        return TaskActionResponse(task_name=task_name)
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{server_id}/notes", response_model=SuccessResponse)
async def add_daily_note(
    server_id: int, 
    req: DailyNoteRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        await ClassroomService.add_daily_note(pool, server_id, req.target_date, req.bring_items, req.announcement, req.user_name, discord_id)
        return SuccessResponse()
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{server_id}/notes/{target_date}", response_model=DailyNoteDeletedResponse)
async def delete_daily_note(
    server_id: int, 
    target_date: date, 
    req: ActionWithUserRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        data = await ClassroomService.delete_daily_note(pool, server_id, target_date, req.user_name, discord_id)
        return DailyNoteDeletedResponse(bring_items=data["bring_items"], announcement=data["announcement"])
    except (RoomNotFoundError, TaskNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{server_id}/summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    server_id: int, 
    target_date: date, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await ClassroomService.get_daily_summary(pool, server_id, target_date)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))



@router.get("/{server_id}/logs")
async def get_logs(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await ClassroomService.get_audit_logs(pool, server_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
