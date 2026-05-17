from fastapi import APIRouter, Depends, HTTPException, Header, Query
import asyncpg
from typing import List
from models.student_schemas import (
    SuccessResponse, StudentAddRequest, StudentBulkAddRequest, StudentUpdateRequest, 
    SyncDiscordRequest, ChangeStatusRequest, StudentResponse,
    StudentExportRequest, StudentStatusUpdate, UserRoomResponse, StudentDeleteRequest
)
from core.dependencies import get_db_pool, verify_api_key
from services.student_service import StudentService, StudentNotFoundError, ForbiddenError, ValidationError, RoomNotFoundError
from fastapi.responses import StreamingResponse

router = APIRouter(dependencies=[Depends(verify_api_key)])

@router.post("/{server_id}/students", response_model=SuccessResponse)
async def add_student(server_id: int, req: StudentAddRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        await StudentService.add_student(pool, server_id, req.student_no, req.first_name, req.last_name, req.user_name)
        return SuccessResponse(message=f"Added student No. {req.student_no}")
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{server_id}/students/bulk", response_model=SuccessResponse)
async def bulk_add_students(server_id: int, req: StudentBulkAddRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        students_dict = [s.model_dump() for s in req.students]
        await StudentService.bulk_add_students(pool, server_id, students_dict, req.user_name)
        return SuccessResponse(message=f"Successfully bulk added {len(req.students)} students.")
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{server_id}/students/sync", response_model=SuccessResponse)
async def sync_discord(server_id: int, req: SyncDiscordRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        await StudentService.sync_discord(pool, server_id, req.student_no, req.discord_id, req.user_name)
        return SuccessResponse(message="Discord synced successfully.")
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{discord_id}/rooms", response_model=List[UserRoomResponse])
async def get_user_rooms(discord_id: int, pool = Depends(get_db_pool)):

    rooms = await StudentService.get_user_rooms(pool, discord_id)
    return rooms

@router.patch("/{server_id}/students/{student_no}", response_model=SuccessResponse)
async def update_student(
    server_id: int, 
    student_no: int, 
    req: StudentUpdateRequest, 
    x_discord_id: int = Header(..., description="Discord ID ของคนที่กดส่งคำสั่งมา"),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        # exclude_unset=True คือเคล็ดลับ! เอาเฉพาะ field ที่มีค่าส่งมาจริงๆ ไม่เอา None ที่ไม่ได้แก้
        update_data = req.model_dump(exclude_unset=True) 
        await StudentService.update_student(pool, server_id, student_no, update_data, x_discord_id)
        return SuccessResponse(message="Student updated successfully.")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{server_id}/students/{student_no}", response_model=SuccessResponse)
async def delete_student(
    server_id: int, 
    student_no: int, 
    req: StudentDeleteRequest, 
    x_discord_id: int = Header(..., description="Discord ID ของผู้สั่งลบ"),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        # เปลี่ยนมาใช้ Soft Delete ตามกฎใหม่
        await StudentService.delete_student(pool, server_id, student_no, req.user_name, x_discord_id)
        return SuccessResponse(message=f"Student No. {student_no} has been soft-deleted.")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{server_id}/students/{student_no}/permanent", response_model=SuccessResponse)
async def delete_student_permanent(
    server_id: int, 
    student_no: int, 
    req: StudentDeleteRequest, 
    x_discord_id: int = Header(..., description="Discord ID ของผู้สั่งลบ"),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        # Hard Delete สำหรับกรณีพิเศษที่ต้องการล้าง unique constraint
        await StudentService.delete_student_permanent(pool, server_id, student_no, req.user_name, x_discord_id)
        return SuccessResponse(message=f"Permanently deleted student No. {student_no}")
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{server_id}/students/me", response_model=StudentResponse)
async def get_my_profile(server_id: int, x_discord_id: int = Header(...), pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        data = await StudentService.get_student_by_discord(pool, server_id, x_discord_id)
        return data
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{server_id}/students", response_model=List[StudentResponse])
async def get_all_students(server_id: int, x_discord_id: int = Header(...), pool: asyncpg.Pool = Depends(get_db_pool)):
    """ดึงข้อมูลทั้งห้อง (เฉพาะคนที่ Header X-Discord-Id เป็นหัวหน้าเท่านั้นถึงจะผ่านได้)"""
    try:
        data = await StudentService.get_all_students(pool, server_id, x_discord_id)
        return data
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@router.post("/{server_id}/export")
async def export_students(server_id: int, req: StudentExportRequest, x_discord_id: str = Header(...), pool = Depends(get_db_pool)):
    # เจนไฟล์ Excel ในรูปแบบ Stream
    try:
        excel_file = await StudentService.export_students_excel(pool, server_id, req.fields, req.user_name, int(x_discord_id))
        
        filename = f"students_export_{server_id}.xlsx"
        return StreamingResponse(
            excel_file, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except (ForbiddenError, ValidationError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@router.get("/{server_id}/search")
async def search_students(server_id: int, q: str = Query(...), pool = Depends(get_db_pool)):
    # ระบบค้นหาเพื่อน
    try:
        results = await StudentService.search_students(pool, server_id, q)
        return results
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{server_id}/students/{student_no}/status")
async def deactivate_student(server_id: int, student_no: int, req: StudentStatusUpdate, pool = Depends(get_db_pool)):
    # เปลี่ยนสถานะ (Deactivate/Activate)
    try:
        await StudentService.update_status(pool, server_id, student_no, req.status, req.user_name)
        return SuccessResponse(message=f"Status of No. {student_no} changed to {req.status}")
    except (StudentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))