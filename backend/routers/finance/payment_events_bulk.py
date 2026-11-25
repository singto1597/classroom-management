"""📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว (bulk receive)

POST `/{target_id}/finance/payment-events/bulk` — 1 คำขอ = 1 transaction
= all-or-nothing (นักเรียน N คน = N events + REC/DEP ของตัวเอง)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`

🔴 route นี้ถูก include **ก่อน** `payment_events_router` ใน `__init__.py` ตามกติกา
   static path ก่อน dynamic (`/{event_id}`) — กัน 422 จาก FastAPI ตอนแปลง path

🔒 ต้อง `MANAGE_FINANCE` (service ตรวจใต้ transaction)
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import (
    ForbiddenError, PaymentNotFoundError, RoomNotFoundError, StudentNotFoundError,
)
from models.finance_schemas import BulkPaymentEventCreate, BulkPaymentEventResponse
from services.finance.allocation import AllocationError, ChannelNotFoundError
from services.finance.bulk_receive import BulkPaymentFailure
from services.finance.payment_events import PaymentEventAccountNotFoundError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status

    - `BulkPaymentFailure` ที่มี `student_id` → detail object (หน้าจอไฮไลต์แถวได้)
    - `BulkPaymentFailure` ก่อนเขียน (student_id=None) → detail string
    """
    if isinstance(e, BulkPaymentFailure):
        if e.student_id is not None:
            raise HTTPException(
                status_code=e.status_code,
                detail={
                    "code": "BULK_ITEM_FAILED",
                    "message": e.message,
                    "student_id": e.student_id,
                    "item_code": e.item_code,
                },
            )
        raise HTTPException(
            status_code=e.status_code,
            detail=f"{e.item_code}: {e.message}",
        )
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
    "/{target_id}/finance/payment-events/bulk",
    response_model=BulkPaymentEventResponse,
)
async def create_bulk_payment_events(
    req: BulkPaymentEventCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """บันทึกรับเงินหลายคน — atomic ทั้งรอบ (ไม่มีใครถูกบันทึกถ้ามีคนใดล้ม)

    🔁 ยิงซ้ำด้วย `idempotency_key` + `reference_no` เดิม ⇒ คืนผลเดิม
    (`reused=true`) ไม่สร้าง event/REC ซ้ำ และไม่แจ้ง Discord อีก
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_bulk_payment_events(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], req=req,
        )
    except Exception as e:
        _raise_translated(e)
