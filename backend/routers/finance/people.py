"""👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + ตั้งค่าการเงินของห้อง

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
   ⇒ service เป็นผู้ resolve เป็น room_id (ห้าม router แปลงเอง)

⚠️ ลำดับ route: `POST /finance/people/sync-students` ประกาศ **ก่อน** route ที่มี
   `{person_id}` — ชนิด method ต่างกันจึงไม่ชนกันจริงในเวอร์ชันนี้ แต่การวางตาม
   ลำดับนี้กันกับดัก "literal ถูกตีเป็น path param" ถ้าวันหนึ่งมี `POST /{person_id}`
   (บทเรียนเดียวกับ `credits.py` / `budgets.py`)

⚠️ ทุก endpoint ประกาศ `response_model` — ฟิลด์ภายใน (`linked_user_id`) ต้องไม่หลุด
"""
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    FinanceSettingsResponse, FinanceSettingsUpdate,
    PeopleSyncResponse, PersonCreate, PersonListResponse, PersonResponse,
    PersonUpdate, SuccessResponse,
)
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status ตามกติกา routers

    ⚠️ `UniqueViolationError` = 409 (คำขอนี้ชนของเดิม) ไม่ใช่ 400 — ผู้ใช้กด
       บันทึกซ้ำจากสองแท็บไม่ควรเห็นข้อความ "ข้อมูลไม่ถูกต้อง"
    """
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, asyncpg.UniqueViolationError):
        raise HTTPException(status_code=409, detail="มีข้อมูลนี้อยู่แล้วในทะเบียนของห้อง")
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get("/{target_id}/finance/people", response_model=PersonListResponse)
async def list_people(
    request: Request,
    person_type: Optional[Literal["student", "teacher", "external"]] = Query(
        None, alias="type", description="กรองตามประเภทผู้เกี่ยวข้อง"
    ),
    active: Optional[bool] = Query(None, description="กรองตามสถานะใช้งาน"),
    q: Optional[str] = Query(None, description="ค้นหาชื่อหรือเบอร์โทร"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายชื่อผู้เกี่ยวข้องทางการเงินของห้อง (ซ่อนรายการที่ปิดใช้งาน/ลบแล้ว)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        people = await FinanceService.list_people(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
            person_type=person_type, active=active, q=q,
        )
        return {"people": people}
    except Exception as e:
        _raise_translated(e)


@router.post("/{target_id}/finance/people", response_model=PersonResponse)
async def create_person(
    req: PersonCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """เพิ่มผู้เกี่ยวข้อง 1 คน (ต้องมีสิทธิ์ MANAGE_FINANCE)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_person(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# 🔴 ต้องมาก่อน route ที่มี `{person_id}` — ดูคำเตือนบนหัวไฟล์
@router.post("/{target_id}/finance/people/sync-students", response_model=PeopleSyncResponse)
async def sync_students(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ซิงก์รายชื่อนักเรียนที่ active ทุกคนเข้าทะเบียนผู้เกี่ยวข้อง (idempotent)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.sync_students(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.patch("/{target_id}/finance/people/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: int,
    req: PersonUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """แก้ไขผู้เกี่ยวข้อง — ส่งมาเฉพาะฟิลด์ที่จะเปลี่ยน"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_person(
            pool=pool, person_id=person_id, req=req,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.delete("/{target_id}/finance/people/{person_id}", response_model=SuccessResponse)
async def delete_person(
    person_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ปิดใช้งานผู้เกี่ยวข้อง (soft delete) — แถวเดิมยังอยู่เพื่อการตรวจสอบ"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.delete_person(
            pool=pool, person_id=person_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/settings", response_model=FinanceSettingsResponse)
async def get_finance_settings(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ค่าเริ่มต้นของหน้าจอรับเงิน — ไม่มีแถวก็คืนค่า default (ไม่ 404)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_settings(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.patch("/{target_id}/finance/settings", response_model=FinanceSettingsResponse)
async def update_finance_settings(
    req: FinanceSettingsUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ตั้งค่าผู้รับเงินเริ่มต้น / กระเป๋าเริ่มต้น / บังคับเลือกผู้รับ / หมายเหตุใบเสร็จ"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_settings(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)
