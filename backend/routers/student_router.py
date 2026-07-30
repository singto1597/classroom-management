from fastapi import APIRouter, Depends, HTTPException, Header, Query, Path, Request
import asyncpg
from typing import List, Literal, Optional
from pydantic import BaseModel

from models.student_schemas import (
    SuccessResponse, StudentAddRequest, StudentBulkAddRequest, StudentUpdateRequest, 
    StudentResponse, StudentExportRequest, StudentStatusUpdate, 
    UserRoomResponse, StudentDeleteRequest, StudentSummaryResponse,
    DiscordSyncRequest
)
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError, ValidationError
from services.student_service import StudentService
from fastapi.responses import StreamingResponse

router = APIRouter()

class TargetResolution(BaseModel):
    server_id: Optional[int] = None
    room_id: Optional[int] = None

def get_target(
    target_id: int = Path(...),
    target_type: Literal["server", "room"] = Query("server")
) -> TargetResolution:
    return TargetResolution(
        server_id=target_id if target_type == "server" else None,
        room_id=target_id if target_type == "room" else None
    )

# 🌟 ฟังก์ชันแกะรอย
def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier

@router.post("/{target_id}/students", response_model=SuccessResponse)
async def add_student(req: StudentAddRequest, request: Request, target: TargetResolution = Depends(get_target), pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        await StudentService.add_student(
            pool, req.student_no, req.first_name, req.last_name, req.user_name,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message=f"Added student No. {req.student_no}")
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/students/bulk", response_model=SuccessResponse)
async def bulk_add_students(req: StudentBulkAddRequest, request: Request, target: TargetResolution = Depends(get_target), pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        students_dict = [s.model_dump() for s in req.students]
        await StudentService.bulk_add_students(
            pool, students_dict, req.user_name,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message=f"Successfully bulk added {len(req.students)} students.")
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{user_id}/rooms", response_model=List[UserRoomResponse])
async def get_user_rooms(user_id: int, request: Request, pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    client_source, actor = get_audit_context(request, user_ctx)
    if user_id != user_ctx["user_id"]: raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ดูข้อมูลห้องของผู้อื่น")
    return await StudentService.get_user_rooms(pool, user_id, client_source=client_source, actor_identifier=actor)

@router.get("/{target_id}/students/profile/{student_no}", response_model=StudentResponse)
async def get_student_by_no(student_no: int, request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await StudentService.get_student_profile(
            pool, student_no, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
    except ForbiddenError as e: raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{target_id}/students/{student_no}", response_model=SuccessResponse)
async def update_student(student_no: int, req: StudentUpdateRequest, request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        update_data = req.model_dump(exclude_unset=True) 
        await StudentService.update_student(
            pool, student_no, update_data, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message="Student updated successfully.")
    except ForbiddenError as e: raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/students/{student_no}", response_model=SuccessResponse)
async def delete_student(student_no: int, req: StudentDeleteRequest, request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        await StudentService.delete_student(
            pool, student_no, req.user_name, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message=f"Student No. {student_no} has been soft-deleted.")
    except ForbiddenError as e: raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/students/{student_no}/permanent", response_model=SuccessResponse)
async def delete_student_permanent(student_no: int, req: StudentDeleteRequest, request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        await StudentService.delete_student_permanent(
            pool, student_no, req.user_name, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message=f"Permanently deleted student No. {student_no}")
    except ForbiddenError as e: raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e: raise HTTPException(status_code=400, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/students/me", response_model=StudentResponse)
async def get_my_profile(request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await StudentService.get_student_by_user_id(
            pool, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/students", response_model=List[StudentSummaryResponse])
async def get_all_students(request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await StudentService.get_all_students(
            pool, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
    except ForbiddenError as e: raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))
    
@router.post("/{target_id}/export")
async def export_students(req: StudentExportRequest, request: Request, target: TargetResolution = Depends(get_target), user_ctx: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db_pool)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        excel_file = await StudentService.export_students_excel(
            pool, req.fields, req.user_name, user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        ref_id = target.server_id or target.room_id
        return StreamingResponse(
            excel_file, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=students_export_{ref_id}.xlsx"}
        )
    except (ForbiddenError, ValidationError) as e: raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@router.get("/{target_id}/search")
async def search_students(request: Request, target: TargetResolution = Depends(get_target), q: str = Query(...), pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await StudentService.search_students(
            pool, q,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{target_id}/students/{student_no}/status")
async def deactivate_student(student_no: int, req: StudentStatusUpdate, request: Request, target: TargetResolution = Depends(get_target), pool: asyncpg.Pool = Depends(get_db_pool), user_ctx: dict = Depends(get_current_user)):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        await StudentService.update_status(
            pool, student_no, req.status, req.user_name,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id
        )
        return SuccessResponse(message=f"Status of No. {student_no} changed to {req.status}")
    except (StudentNotFoundError, RoomNotFoundError) as e: raise HTTPException(status_code=404, detail=str(e))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.post("/discord/sync")
async def sync_discord(
    req: DiscordSyncRequest,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    x_discord_id: Optional[str] = Header(None),
    x_discord_username: Optional[str] = Header(None),
):
    if not x_discord_id:
        raise HTTPException(status_code=400, detail="Missing X-Discord-Id header")
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        await StudentService.sync_discord_account(
            pool,
            room_code=req.room_code,
            student_no=req.student_no,
            discord_id=x_discord_id,
            discord_username=x_discord_username or "",
            client_source=client_source,
            actor_identifier=actor,
        )
        return SuccessResponse(message="Discord account synced successfully.")
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
