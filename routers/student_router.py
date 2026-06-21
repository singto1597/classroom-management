from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg
from typing import List
from fastapi.responses import StreamingResponse

from models.student_schemas import (
    SuccessResponse, StudentAddRequest, StudentBulkAddRequest, StudentUpdateRequest, 
    SyncDiscordRequest, StudentResponse, StudentExportRequest, StudentStatusUpdate, 
    UserRoomResponse, StudentDeleteRequest, StudentSummaryResponse
)
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from services.student_service import StudentService

router = APIRouter()

@router.post("/{target_id}/students", response_model=SuccessResponse)
async def add_student(
    req: StudentAddRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await StudentService.add_student(
            pool, req.student_no, req.first_name, req.last_name, req.user_name, room_id=room_id
        )
        return SuccessResponse(message=f"Added student No. {req.student_no}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/students/bulk", response_model=SuccessResponse)
async def bulk_add_students(
    req: StudentBulkAddRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        students_dict = [s.model_dump() for s in req.students]
        await StudentService.bulk_add_students(pool, students_dict, req.user_name, room_id=room_id)
        return SuccessResponse(message=f"Successfully bulk added {len(req.students)} students.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/students/sync", response_model=SuccessResponse)
async def sync_discord(
    req: SyncDiscordRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await StudentService.sync_discord(
            pool, req.student_no, req.discord_id, req.user_name, room_id=room_id
        )
        return SuccessResponse(message="Discord synced successfully.")
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/my-rooms", response_model=List[UserRoomResponse])
async def get_my_rooms(
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    # ปรับ endpoint ไม่ต้องรับ parameter ไอดีละ เอาจาก Token/ด่านหน้าเลย
    rooms = await StudentService.get_user_rooms(pool, user_ctx["user_id"])
    return rooms

@router.get("/{target_id}/students/profile/{student_no}", response_model=StudentResponse)
async def get_student_by_no(
    student_no: int, 
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user), 
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        data = await StudentService.get_student_profile(pool, student_no, user_ctx["user_id"], room_id=room_id)
        return data
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{target_id}/students/{student_no}", response_model=SuccessResponse)
async def update_student(
    student_no: int, 
    req: StudentUpdateRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        update_data = req.model_dump(exclude_unset=True) 
        await StudentService.update_student(pool, student_no, update_data, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse(message="Student updated successfully.")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/students/{student_no}", response_model=SuccessResponse)
async def delete_student(
    student_no: int, 
    req: StudentDeleteRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        await StudentService.delete_student(pool, student_no, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse(message=f"Student No. {student_no} has been soft-deleted.")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/students/{student_no}/permanent", response_model=SuccessResponse)
async def delete_student_permanent(
    student_no: int, 
    req: StudentDeleteRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        await StudentService.delete_student_permanent(pool, student_no, req.user_name, user_ctx["user_id"], room_id=room_id)
        return SuccessResponse(message=f"Permanently deleted student No. {student_no}")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/students/me", response_model=StudentResponse)
async def get_my_profile(
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user), 
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        data = await StudentService.get_student_by_user_id(pool, user_ctx["user_id"], room_id=room_id)
        return data
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/students", response_model=List[StudentSummaryResponse])
async def get_all_students(
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user), 
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        data = await StudentService.get_all_students(pool, user_ctx["user_id"], room_id=room_id)
        return data
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@router.post("/{target_id}/export")
async def export_students(
    req: StudentExportRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    user_ctx: dict = Depends(get_current_user), 
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        excel_file = await StudentService.export_students_excel(
            pool, req.fields, req.user_name, user_ctx["user_id"], room_id=room_id
        )
        filename = f"students_export_room_{room_id}.xlsx"
        return StreamingResponse(
            excel_file, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except (ForbiddenError, ValidationError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@router.get("/{target_id}/search")
async def search_students(
    room_id: int = Depends(resolve_target_to_room_id),
    q: str = Query(...), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        results = await StudentService.search_students(pool, q, room_id=room_id)
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{target_id}/students/{student_no}/status")
async def deactivate_student(
    student_no: int, 
    req: StudentStatusUpdate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await StudentService.update_status(pool, student_no, req.status, req.user_name, room_id=room_id)
        return SuccessResponse(message=f"Status of No. {student_no} changed to {req.status}")
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))