"""💳 [FIN-V2 / P2.4] ช่องทางชำระเงิน + PromptPay QR

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
   ⇒ service เป็นผู้ resolve เป็น room_id (ห้าม router แปลงเอง)

🔴 **ลำดับ route สำคัญ**: `POST /finance/payment-channels/preview-qr` ต้องประกาศ
   **ก่อน** `GET /finance/payment-channels/{channel_id}/qr.svg` (static ก่อน dynamic)
   — ถ้าเปลี่ยนลำดับ "preview-qr" จะถูกแปลงเป็น int แล้วตอบ 422
   (กับดักเดียวกับ `payment-events/preview`)

🔒 อ่าน/QR = `require_member` (พ่อแม่ต้องเปิด QR เพื่อจ่ายได้)
   เขียน = `MANAGE_FINANCE` · ทุก endpoint ประกาศ `response_model`
   ⇒ เลขบัญชี/PromptPay เต็มไม่มีทางหลุดออก response
"""
from decimal import Decimal
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    PaymentChannelCreate, PaymentChannelListResponse, PaymentChannelResponse,
    PaymentChannelUpdate, QrPreviewRequest, QrPreviewResponse, SuccessResponse,
)
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status (เหมือน `routers/finance/people.py`)

    ⚠️ `QrError` สืบทอด `ValueError` ⇒ ได้ 400 พร้อมข้อความไทยอยู่แล้ว
    ⚠️ `UniqueViolationError` = 409 (primary ชนกันเมื่อมีคำขอพร้อมกัน)
    """
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, asyncpg.UniqueViolationError):
        raise HTTPException(status_code=409, detail="ช่องทางชำระเงินชนกับรายการที่มีอยู่")
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get(
    "/{target_id}/finance/payment-channels",
    response_model=PaymentChannelListResponse,
)
async def list_payment_channels(
    request: Request,
    include_inactive: bool = Query(
        False, description="รวมช่องทางที่ปิดใช้งาน (สำหรับหน้าตั้งค่า)"
    ),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายชื่อช่องทางของห้อง — primary มาก่อน"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        channels = await FinanceService.list_payment_channels(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], include_inactive=include_inactive,
        )
        return {"channels": channels}
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/payment-channels",
    response_model=PaymentChannelResponse,
)
async def create_payment_channel(
    req: PaymentChannelCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """เพิ่มช่องทางชำระเงิน (ต้องมีสิทธิ์ MANAGE_FINANCE)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_payment_channel(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# 🔴 ต้องมาก่อน route ที่มี `{channel_id}` — ดูคำเตือนบนหัวไฟล์
@router.post(
    "/{target_id}/finance/payment-channels/preview-qr",
    response_model=QrPreviewResponse,
)
async def preview_channel_qr(
    req: QrPreviewRequest,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """พรีวิว SVG ของ QR — คืนเฉพาะ `svg` (ไม่มี payload/เลขพร้อมเพย์)"""
    try:
        return await FinanceService.preview_channel_qr(
            pool=pool, req=req,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/payment-channels/{channel_id}/qr.svg")
async def get_channel_qr_svg(
    channel_id: int,
    amount: Optional[Decimal] = Query(
        None, description="ระบุเมื่อช่องทางเป็น QR แบบ fixed — ห้ามส่งมาถ้า open",
    ),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """SVG ของ PromptPay QR — `no-store` เพราะยอดแบบ fixed เปลี่ยนได้"""
    try:
        svg = await FinanceService.get_channel_qr_svg(
            pool=pool, channel_id=channel_id, amount=amount,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as e:
        _raise_translated(e)


@router.patch(
    "/{target_id}/finance/payment-channels/{channel_id}",
    response_model=PaymentChannelResponse,
)
async def update_payment_channel(
    channel_id: int,
    req: PaymentChannelUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """แก้ไขช่องทาง — ส่งมาเฉพาะฟิลด์ที่จะเปลี่ยน"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_payment_channel(
            pool=pool, channel_id=channel_id, req=req,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.delete(
    "/{target_id}/finance/payment-channels/{channel_id}",
    response_model=SuccessResponse,
)
async def delete_payment_channel(
    channel_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ปิดใช้งานช่องทาง (soft delete)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.delete_payment_channel(
            pool=pool, channel_id=channel_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)
