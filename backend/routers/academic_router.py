"""HTTP layer ของปีการศึกษา/เทอม — ตัวกรองเวลาของสถิติ (P5)

- `GET    /{target_id}/academic/periods` — ปีทั้งหมด + เทอม + ธงปัจจุบัน (สมาชิกอ่านได้)
- `POST   /{target_id}/academic/years` — สร้างปี
- `PATCH  /{target_id}/academic/years/{year_id}` — แก้ชื่อ/ช่วงวัน
- `DELETE /{target_id}/academic/years/{year_id}` — ลบ (soft) + ลบเทอมในปีนั้น
- `POST   /{target_id}/academic/years/{year_id}/terms` — สร้างเทอม
- `PATCH  /{target_id}/academic/terms/{term_id}` — แก้เทอม
- `DELETE /{target_id}/academic/terms/{term_id}` — ลบเทอม (soft)
- `PUT    /{target_id}/academic/current` — ตั้ง/ปลดปี-เทอมปัจจุบัน

🔒 เขียน = `MANAGE_CLASSROOM_SETTINGS` (ตรวจใน service ในทรานแซกชันเดียวกับ audit)
📖 อ่าน = สมาชิกห้องเท่านั้น ⇒ ตัวกรองสถิติเปิดให้ทุกคนใช้ ไม่ใช่แค่ผู้ดูแล
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import (
    AcademicPeriodNotFoundError,
    ForbiddenError,
    ValidationError,
)
from models.academic_schemas import (
    AcademicPeriodsResponse,
    AcademicTermCreate,
    AcademicTermOut,
    AcademicTermUpdate,
    AcademicYearCreate,
    AcademicYearOut,
    AcademicYearUpdate,
    CurrentPeriodResponse,
    DeletePeriodResponse,
    SetCurrentPeriodRequest,
)
from routers._common import get_audit_context
from services import academic_service

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    """แปลง exception ของโดเมนเป็น HTTP

    · `ValidationError` → 400 (ค่าที่ส่งมาใช้ไม่ได้ เช่นเทอมทับกัน)
    · `AcademicPeriodNotFoundError` → 404 (ปี/เทอมถูกลบไปแล้วหรือไม่ใช่ของห้องนี้)
    · `ForbiddenError` → 403 (ไม่มี `MANAGE_CLASSROOM_SETTINGS`)
    """
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, AcademicPeriodNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=403, detail=str(exc))


@router.get(
    "/{target_id}/academic/periods",
    response_model=AcademicPeriodsResponse,
    summary="ปีการศึกษาและเทอมทั้งหมดของห้อง (สมาชิกอ่านได้)",
)
async def list_periods(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        data = await academic_service.list_periods(
            pool, room_id=room_id, user_id=int(user_ctx["user_id"])
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return AcademicPeriodsResponse(**data)


@router.post(
    "/{target_id}/academic/years",
    response_model=AcademicYearOut,
    summary="สร้างปีการศึกษา (ต้องมี MANAGE_CLASSROOM_SETTINGS)",
)
async def create_year(
    payload: AcademicYearCreate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        created = await academic_service.create_year(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_be=payload.year_be,
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_current=payload.is_current,
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return AcademicYearOut(**created)


@router.patch(
    "/{target_id}/academic/years/{year_id}",
    response_model=AcademicYearOut,
    summary="แก้ชื่อ/ช่วงวันของปี (ไม่แตะธงปัจจุบัน)",
)
async def update_year(
    year_id: int,
    payload: AcademicYearUpdate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    data = payload.model_dump(exclude_unset=True)
    try:
        updated = await academic_service.update_year(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_id=year_id,
            name=data.get("name"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return AcademicYearOut(**updated)


@router.delete(
    "/{target_id}/academic/years/{year_id}",
    response_model=DeletePeriodResponse,
    summary="ลบปีการศึกษา (soft) พร้อมเทอมในปีนั้น",
)
async def delete_year(
    year_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        result = await academic_service.delete_year(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_id=year_id,
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return DeletePeriodResponse(**result)


@router.post(
    "/{target_id}/academic/years/{year_id}/terms",
    response_model=AcademicTermOut,
    summary="สร้างเทอมในปีการศึกษา",
)
async def create_term(
    year_id: int,
    payload: AcademicTermCreate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        created = await academic_service.create_term(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_id=year_id,
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_current=payload.is_current,
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return AcademicTermOut(**created)


@router.patch(
    "/{target_id}/academic/terms/{term_id}",
    response_model=AcademicTermOut,
    summary="แก้ชื่อ/ช่วงวันของเทอม",
)
async def update_term(
    term_id: int,
    payload: AcademicTermUpdate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    data = payload.model_dump(exclude_unset=True)
    try:
        updated = await academic_service.update_term(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            term_id=term_id,
            name=data.get("name"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return AcademicTermOut(**updated)


@router.delete(
    "/{target_id}/academic/terms/{term_id}",
    response_model=DeletePeriodResponse,
    summary="ลบเทอม (soft)",
)
async def delete_term(
    term_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        result = await academic_service.delete_term(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            term_id=term_id,
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return DeletePeriodResponse(**result)


@router.put(
    "/{target_id}/academic/current",
    response_model=CurrentPeriodResponse,
    summary="ตั้ง/ปลดปีและเทอมปัจจุบัน (year_id=null = ปลด)",
)
async def set_current_period(
    payload: SetCurrentPeriodRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        result = await academic_service.set_current(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_id=payload.year_id,
            term_id=payload.term_id,
            client_source=client_source,
            actor_identifier=actor,
        )
    except (ForbiddenError, ValidationError, AcademicPeriodNotFoundError) as exc:
        raise _http_error(exc)
    return CurrentPeriodResponse(**result)
