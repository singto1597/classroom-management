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
    ActivityCompareRequest,
    ActivityCompareResponse,
    CombinedExportRequest,
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


# 🌟 ประกาศ route ที่มี literal segment ('compare' / 'export/combined') ไว้บนสุด ก่อน route
# ที่มี path param — กันอนาคตมีคนเพิ่ม POST /{target_id}/activities/{activity_id} แล้วมันบังกัน
@router.post(
    "/{target_id}/activities/compare",
    response_model=ActivityCompareResponse,
    summary="เทียบผู้เข้าร่วม 2–3 กิจกรรม (Intersection / Union / ลบ)",
)
async def compare_activities(
    req: ActivityCompareRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    POST /api/classroom/{room_id}/activities/compare
    body: {"activity_ids": [3, 7]}

    → คืนกิจกรรมที่เลือก + ภูมิภาคของแผนภาพเวน (ใครอยู่กิจกรรมชุดไหน — ชื่อเล่นเท่านั้น)
    เปิดให้ **สมาชิกห้องทุกคน** อ่านได้ (require_member) จึงไม่คืน PII จากโปรไฟล์เลย
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await ActivityService.compare_activities(
            pool=pool,
            activity_ids=req.activity_ids,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ActivityNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        # 🔴 ห้าม echo str(e) ที่นี่ — endpoint นี้สมาชิกห้องทุกคนเรียกได้ ข้อความดิบอาจมี
        #    DSN/hostname ของ DB ติดมา (บทเรียน error message ที่เปิดกว้างเกินไปใน docs/skills.md)
        raise HTTPException(status_code=500, detail="เปรียบเทียบกิจกรรมไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")


@router.post("/{target_id}/activities/export/combined", summary="Export Excel รวมหลายกิจกรรม (ตามภูมิภาคที่เลือก)")
async def export_activities_combined_excel(
    req: CombinedExportRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """
    POST /api/classroom/{room_id}/activities/export/combined
    body: {"activity_ids": [3, 7], "region_keys": ["3-7"], "include_activity_fields": false, "user_name": "..."}

    → คืน .xlsx (2 แผ่น: สรุป + รายชื่อรวม) ของคนในภูมิภาคที่เลือก
    `region_keys` ต้องเป็นคีย์ที่ได้จาก /activities/compare เท่านั้น (service ตรวจกับ DB อีกชั้น)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        excel_file = await ActivityService.export_activities_combined_excel(
            pool=pool,
            activity_ids=req.activity_ids,
            region_keys=req.region_keys,
            metadata_keys=req.metadata_keys,
            include_activity_fields=req.include_activity_fields,
            user_name=req.user_name,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            room_id=room_id,
        )
        # 🌟 ชื่อไฟล์มาจาก service (ชื่อกิจกรรมทุกตัวต่อกัน) — RFC 5987 filename*= กันชื่อไทยเพี้ยน
        filename = getattr(excel_file, "filename", "combined_activities.xlsx")
        ascii_fallback = "combined_activities.xlsx"
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
