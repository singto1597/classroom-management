"""Excel export รายชื่อผู้เข้าร่วมกิจกรรม"""
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
        # 🌟 ชื่อไฟล์มาจาก service (ใช้ชื่อกิจกรรม เช่น "ไปทัศนศึกษา_รายชื่อผู้เข้าร่วม.xlsx")
        # ไม่ใช่ activity_<id>_participants.xlsx; RFC 5987 filename*= กันชื่อไฟล์ไทยเพี้ยน
        filename = getattr(excel_file, "filename", f"activity_{req.activity_id}_participants.xlsx")
        ascii_fallback = f"activity_{req.activity_id}.xlsx"
        headers = {
            "Content-Disposition": f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
        }
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
