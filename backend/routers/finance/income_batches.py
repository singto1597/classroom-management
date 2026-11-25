"""💰 [FIN-V2 / P4.4] ใบรับเงินหลายบรรทัด — สร้าง/รายการ/รายละเอียด

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
⚠️ ลำดับ route: static (`/income-batches`) ก่อน dynamic (`/income-batches/{id}`)
⚠️ 409 (คีย์เดิม payload ต่าง) ต้องแยกจาก 400 — หน้าจอจะเปิดใบเดิมแทนการสร้างใหม่
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    IncomeBatchCreate, IncomeBatchDetailResponse, IncomeBatchListResponse,
    IncomeBatchResponse,
)
from services.finance.income_batches import (
    IncomeBatchIdempotencyConflict, IncomeBatchNotFoundError,
)
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status ตามกติกา routers

    🔴 `IncomeBatchIdempotencyConflict` ต้องมาก่อน `ValueError` เสมอ — มันสืบทอด
       มาจาก ValueError ถ้าตรวจแบบ reversed แมทช์เป็น 400 แล้วหน้าจอจะโหลดใบเดิมไม่ได้
    """
    if isinstance(e, (RoomNotFoundError, IncomeBatchNotFoundError)):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, IncomeBatchIdempotencyConflict):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.post("/{target_id}/finance/income-batches", response_model=IncomeBatchResponse)
async def create_income_batch(
    req: IncomeBatchCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """สร้างใบรับเงิน (MANAGE_FINANCE) — 1 ใบ = N transactions + N journals + 1 INC

    🔁 คีย์เดิม + payload เดิม ⇒ คืนใบเดิม (`reused=true`) · payload ต่าง ⇒ 409
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_income_batch(
            pool=pool, req=req, user_id=user_ctx["user_id"],
            # 🖊️ ชื่อผู้ออกมาจาก payload ก่อน; ถ้าไม่มี service จะอ่านจากโปรไฟล์ผู้ใช้
            user_name=(req.user_name or "").strip(),
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/income-batches", response_model=IncomeBatchListResponse)
async def list_income_batches(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    status: Optional[str] = Query(default=None),
):
    """รายการใบรับเงินของห้อง (สมาชิกอ่านได้) — เรียงใหม่สุดก่อน"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_income_batches(
            pool=pool, client_source=client_source, actor_identifier=actor,
            from_date=from_date, to_date=to_date, status=status,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/income-batches/{batch_id}",
    response_model=IncomeBatchDetailResponse,
)
async def get_income_batch(
    batch_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียดใบรับเงิน — บรรทัด + ลายเซ็น + เลข INC (สมาชิกอ่านได้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_income_batch(
            pool=pool, batch_id=batch_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)
