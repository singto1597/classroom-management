"""👜 [FIN-V2 / P3.1] เงินสดรอส่งมอบ — กระเป๋าผู้ถือ + การส่งมอบ + เคลื่อนไหว

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
   (ห้าม router แปลงเอง) · ทุก mutation ต้องมี `x_discord_id` ตาม pattern เดิม

⚠️ ลำดับ route: ประกาศ static (`/custody/accounts`, `/custody/handover`) ก่อน
   dynamic (`/custody/{person_id}/movements`) ตามกติกา static ก่อน dynamic

⚠️ error 409 ต้องแยกจาก 400 — FE ต้องแยก "ยกเลิกไม่ได้เพราะเงินถูกใช้แล้ว"
   ออกจาก "ข้อมูลไม่ถูกต้อง" ได้
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError, StudentNotFoundError
from models.finance_schemas import (
    CustodyAccountCreate, CustodyAccountResponse, CustodyHandoverCreate,
    CustodyHandoverResponse, CustodyHandoverVoid, CustodyListResponse,
    CustodyMovementListResponse, SuccessResponse,
)
from services.finance.custody import (
    CustodyConflictError, CustodyNotFoundError, CustodyPersonNotFoundError,
)
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status ตามกติกา routers"""
    if isinstance(e, (RoomNotFoundError, StudentNotFoundError,
                      CustodyNotFoundError, CustodyPersonNotFoundError)):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, CustodyConflictError):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get("/{target_id}/finance/custody", response_model=CustodyListResponse)
async def list_custody(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ทุกคนที่มีกระเป๋าเงินสดรอส่งมอบ + ยอดถือรวม (สมาชิกห้องอ่านได้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_custody(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# 🔴 static ก่อน dynamic — ประกาศก่อน `/custody/{person_id}/movements`
@router.post("/{target_id}/finance/custody/accounts", response_model=CustodyAccountResponse)
async def create_custody_account(
    req: CustodyAccountCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """สร้างกระเป๋า custody ให้ผู้เกี่ยวข้อง (ต้องมีสิทธิ์ MANAGE_FINANCE)

    🔁 เรียกซ้ำคนเดิมได้ผลเดิม (คืนกระเป๋าใบเดิม) — ไม่สร้างซ้ำ
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_custody_account(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post("/{target_id}/finance/custody/handover", response_model=CustodyHandoverResponse)
async def create_handover(
    req: CustodyHandoverCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ส่งมอบเงินระหว่างกระเป๋า — อย่างน้อยหนึ่งฝั่งต้องเป็นกระเป๋า custody

    🔁 idempotent: retry ด้วย `idempotency_key` เดิมได้ผลเดิม (200)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_handover(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/custody/{person_id}/movements",
    response_model=CustodyMovementListResponse,
)
async def get_custody_movements(
    person_id: int,
    request: Request,
    from_date: Optional[date] = Query(None, description="เริ่มต้น (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="สิ้นสุด (YYYY-MM-DD, รวมวันนั้น)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายการเคลื่อนไหวของกระเป๋า custody ของคนนี้ (ส่งมอบ + รายรับ/รายจ่าย)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_custody_movements(
            pool=pool, person_id=person_id,
            client_source=client_source, actor_identifier=actor,
            from_date=from_date, to_date=to_date,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/custody/handovers/{handover_id}/void",
    response_model=SuccessResponse,
)
async def void_handover(
    handover_id: int,
    req: CustodyHandoverVoid,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกการส่งมอบ — คืนยอดสองฝั่ง + void journal เดิม + journal กลับรายการ

    🛡️ 409 เมื่อเงินปลายทางถูกใช้ไปแล้ว (คืนจากปลายทางไม่ได้)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.void_handover(
            pool=pool, handover_id=handover_id, reason=req.reason,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)
