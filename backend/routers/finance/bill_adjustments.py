"""✂️ [FIN-V2 / P6.2] ตัดจำหน่าย/ให้ส่วนลดบิล + fund_type + เตือนชื่อซ้ำ — HTTP layer เท่านั้น

- `POST /finance/payments/{payment_id}/write-off` — ตัดจำหน่ายหนี้บิลโครงการ
- `POST /finance/payments/{payment_id}/discount`  — ให้ส่วนลดบิลโครงการ
- `GET  /finance/payments/{payment_id}/adjustments` — ประวัติการปรับบิลของบิล
- `GET  /finance/fee-collections/duplicate-check?title=` — เตือนชื่อโครงการซ้ำ
- `PATCH /finance/fee-collections/{collection_id}/fund-type` — มิติรายงาน

⚠️ `{target_id}` = room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
⚠️ **static ก่อน dynamic**: `duplicate-check` (static) ต้องประกาศก่อน route
   `{collection_id}/fund-type` เพื่อไม่ให้ถูก parse เป็น `{id}` แล้วตอบ 422
   (กับดักเดียวกับ `budgets/overview`, ดู `docs/skills.md`)
🔴 จับ `BillAdjustmentConflictError` **ก่อน** `ValueError` — ตัวหลังเป็น base class
   ของตัวแรก ถ้าสลับลำดับ 409 จะกลายเป็น 400 หมด
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_current_user, get_db_pool
from core.exceptions import ForbiddenError, PaymentNotFoundError, RoomNotFoundError
from models.finance_schemas import (
    BillAdjustmentListResponse,
    BillAdjustmentRequest,
    BillAdjustmentResponse,
    DuplicateTitleResponse,
    FundTypeResponse,
    FundTypeUpdateRequest,
)
from services.finance.bill_adjustments import BillAdjustmentConflictError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_audit_context, get_target

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """service exception → HTTP (conflict ก่อน ValueError เพราะเป็น subclass ของกัน)"""
    if isinstance(e, PaymentNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, BillAdjustmentConflictError):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ static ก่อน dynamic — ประกาศก่อนทุก route ที่มี `{collection_id}`
# ══════════════════════════════════════════════════════════════════════════════
@router.get(
    "/{target_id}/finance/fee-collections/duplicate-check",
    response_model=DuplicateTitleResponse,
)
async def check_duplicate_collection_title(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    title: str = Query(..., description="ชื่อโครงการที่จะสร้าง (ตรวจตรงตัว ไม่สนตัวพิมพ์)"),
):
    """เตือนชื่อโครงการซ้ำ — non-blocking (สร้างซ้ำได้ตามแผน)"""
    try:
        return await FinanceService.check_duplicate_collection_title(
            pool=pool, title=title,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# ══════════════════════════════════════════════════════════════════════════════
# ปรับบิล: ตัดจำหน่าย / ให้ส่วนลด / ประวัติ
# ══════════════════════════════════════════════════════════════════════════════
@router.post(
    "/{target_id}/finance/payments/{payment_id}/write-off",
    response_model=BillAdjustmentResponse,
)
async def write_off_bill(
    payment_id: int,
    req: BillAdjustmentRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ตัดจำหน่ายหนี้บิลโครงการ — Dr 59002 หนี้สูญ / Cr 11001 AR (ไม่แตะ paid_amount)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.write_off_bill(
            pool=pool, payment_id=payment_id, req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/payments/{payment_id}/discount",
    response_model=BillAdjustmentResponse,
)
async def discount_bill(
    payment_id: int,
    req: BillAdjustmentRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ให้ส่วนลดบิลโครงการ — Dr 49002 ส่วนลดค่าปรับ / Cr 11001 AR"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.discount_bill(
            pool=pool, payment_id=payment_id, req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/payments/{payment_id}/adjustments",
    response_model=BillAdjustmentListResponse,
)
async def list_bill_adjustments(
    payment_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ประวัติการปรับบิลของบิลหนึ่ง (สมาชิกอ่านได้) — ใหม่สุดก่อน"""
    try:
        return await FinanceService.list_bill_adjustments(
            pool=pool, payment_id=payment_id,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# ══════════════════════════════════════════════════════════════════════════════
# โครงการ: มิติรายงาน fund_type (ไม่แตะเงิน)
# ══════════════════════════════════════════════════════════════════════════════
@router.patch(
    "/{target_id}/finance/fee-collections/{collection_id}/fund-type",
    response_model=FundTypeResponse,
)
async def set_collection_fund_type(
    collection_id: int,
    req: FundTypeUpdateRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ตั้ง `room_fund` / `pass_through` — มิติรายงานเท่านั้น (MANAGE_FINANCE)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.set_collection_fund_type(
            pool=pool, collection_id=collection_id, fund_type=req.fund_type,
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except Exception as e:
        _raise_translated(e)
