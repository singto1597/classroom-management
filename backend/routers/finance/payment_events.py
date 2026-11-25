"""🧾 [FIN-V2 / P2.1] รายการรับเงิน (payment event)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`

🔴 **ลำดับ route สำคัญ**: `/finance/payment-events/preview` (static, P1.5) ถูกประกาศ
   ใน `__init__.py` **ก่อน** router นี้ จึงชนะ `/{event_id}` ของเรา — ถ้าย้าย router นี้
   ขึ้นก่อน ค่า "preview" จะถูกแปลงเป็น int แล้วตอบ 422 (กับดักเดียวกับ `fines/summary`)

🔒 POST ต้อง `MANAGE_FINANCE` · GET ใช้ `require_member` (service ตรวจเอง)
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import (
    ForbiddenError, PaymentNotFoundError, RoomNotFoundError, StudentNotFoundError,
)
from models.finance_schemas import (
    PaymentEventCreate, PaymentEventDetailResponse, PaymentEventListResponse,
    PaymentEventResponse, VoidRequest, VoidResponse,
)
from services.finance.allocation import AllocationError, ChannelNotFoundError
from services.finance.payment_events import PaymentEventAccountNotFoundError
from services.finance.voids import VoidConflictError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status (เหมือน `routers/finance/allocation.py`)"""
    if isinstance(e, AllocationError):
        if e.code == "BILL_NOT_OPEN":
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, (
        StudentNotFoundError, RoomNotFoundError, ChannelNotFoundError,
        PaymentEventAccountNotFoundError, PaymentNotFoundError,
    )):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.post(
    "/{target_id}/finance/payment-events",
    response_model=PaymentEventResponse,
)
async def create_payment_event(
    req: PaymentEventCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """บันทึกรับเงิน 1 ครั้ง — atomic ทั้งก้อน (event + REC/DEP + journal)

    🔁 ยิงซ้ำด้วย `idempotency_key` เดิม ⇒ ได้ event เดิม (`reused=true`) ไม่ charge ซ้ำ
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_payment_event(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], req=req,
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/payment-events",
    response_model=PaymentEventListResponse,
)
async def list_payment_events(
    request: Request,
    date_from: Optional[date] = Query(None, description="วันที่เริ่ม (เวลาไทย)"),
    date_to: Optional[date] = Query(None, description="วันที่สิ้นสุด (เวลาไทย)"),
    student_id: Optional[int] = Query(None, gt=0),
    receiver_id: Optional[int] = Query(None, gt=0, description="id ผู้รับเงิน (finance_people)"),
    channel_id: Optional[int] = Query(None, gt=0),
    q: Optional[str] = Query(None, description="ค้นชื่อผู้จ่าย/เลขอ้างอิง"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายการรับเงินของห้อง (ใหม่→เก่า, ไม่เกิน 200 รายการ)"""
    try:
        return await FinanceService.list_payment_events(
            pool=pool, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
            date_from=date_from, date_to=date_to, student_id=student_id,
            receiver_id=receiver_id, channel_id=channel_id, q=q,
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/payment-events/{event_id}",
    response_model=PaymentEventDetailResponse,
)
async def get_payment_event(
    event_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียด event + บรรทัด + เอกสาร (REC/DEP)"""
    try:
        return await FinanceService.get_payment_event(
            pool=pool, server_id=target.server_id, room_id=target.room_id,
            event_id=event_id, user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# 🚫 [FIN-V2 / P6.1] void event — ต้องยกเลิกทั้ง event (REC+DEP+เครดิต+journal) พร้อมกัน
#    🔴 จับ `VoidConflictError` **ก่อน** `ValueError` — ไม่งั้น 409 จะกลายเป็น 400
@router.post(
    "/{target_id}/finance/payment-events/{event_id}/void",
    response_model=VoidResponse,
)
async def void_payment_event(
    event_id: int,
    req: VoidRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกรายการรับเงิน (MANAGE_FINANCE) — คืนเงิน/บิล/เครดิต + void REC/DEP"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.void_payment_event(
            pool=pool, event_id=event_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except (PaymentNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except VoidConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
