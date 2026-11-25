"""👤 [FIN-V2 / P1.3] บัญชีรายบุคคล + statement (อ่านอย่างเดียว)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
   ⇒ service เป็นผู้ resolve เป็น room_id + ตรวจสมาชิก (ห้าม router แปลงเอง)

⚠️ ลำดับ route: `/individual-accounts/{student_id}/statement` ประกาศ **ก่อน**
   `/individual-accounts/{student_id}` — path ต่างกันจริงจึงไม่ชนในเวอร์ชันนี้
   แต่การวางแบบนี้กันกับดัก "route ยาวถูกกลืนโดย route สั้น" ที่เคยเจอใน `credits.py`

⚠️ ทุก endpoint ประกาศ `response_model` — เงินทุกฟิลด์เป็น string 2 ตำแหน่ง
   และฟิลด์ภายในของ service (`_…`) ต้องไม่หลุด

⚠️ `status`/`fund_type` รับเป็น `str` ไม่ใช่ `Literal` โดยเจตนา: ให้ค่าแปลกปลอม
   ตกไปที่ `ValueError` ของ service → **400 ภาษาไทย** แทน 422 ของ Pydantic
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError, StudentNotFoundError
from models.finance_schemas import (
    IndividualAccountDetailResponse, IndividualAccountListResponse,
    StudentStatementResponse,
)
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status ตามกติกา routers

    `StudentNotFoundError` = 404 ผู้ใช้เห็นว่าคนนี้ไม่มีในห้อง — ไม่ใช่ 500
    และไม่ใช่ 403 (ซึ่งจะทำให้เดาไม่ออกว่าห้องผิดหรือคนผิด)
    """
    if isinstance(e, StudentNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get(
    "/{target_id}/finance/individual-accounts",
    response_model=IndividualAccountListResponse,
)
async def list_individual_accounts(
    request: Request,
    status: Optional[str] = Query(
        None,
        description="ตัวกรองสถานะ: all | outstanding | credit | settled (default = all)",
    ),
    q: Optional[str] = Query(None, description="ค้นหารหัสนักเรียนหรือชื่อ"),
    fund_type: Optional[str] = Query(
        None, description="กรองบิลตามประเภทเงิน: room_fund | pass_through"
    ),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """บัญชีรายบุคคลทุกคนของห้อง — สมาชิกห้องอ่านได้ (ไม่ต้อง MANAGE_FINANCE)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_individual_accounts(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
            status=status, q=q, fund_type=fund_type,
        )
    except Exception as e:
        _raise_translated(e)


# 🔴 ต้องมาก่อน route `/{student_id}` — ดูคำเตือนบนหัวไฟล์
@router.get(
    "/{target_id}/finance/individual-accounts/{student_id}/statement",
    response_model=StudentStatementResponse,
)
async def get_student_statement(
    student_id: int,
    request: Request,
    date_from: Optional[date] = Query(None, alias="from", description="เริ่มช่วง (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, alias="to", description="สิ้นสุดช่วง (YYYY-MM-DD)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """statement ของนักเรียน (เดินบัญชี: บิล/รับเงิน/เครดิต) — เกิน 2000 แถว = 400"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_student_statement(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
            student_id=student_id, date_from=date_from, date_to=date_to,
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/individual-accounts/{student_id}",
    response_model=IndividualAccountDetailResponse,
)
async def get_individual_account(
    student_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """บัญชีของนักเรียน 1 คน — 404 ถ้าไม่ใช่สมาชิกของห้องนี้"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_individual_account(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], student_id=student_id,
        )
    except Exception as e:
        _raise_translated(e)
