"""🧮 [FIN-V2 / P1.5] พรีวิวการจัดสรรเงินรับ (allocation preview)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
   ⇒ service เป็นผู้ resolve เป็น room_id + ตรวจสิทธิ์ (ห้าม router แปลงเอง)

🔴 **ลำดับ route สำคัญ**: `/finance/payment-events/preview` (static) ต้องถูกประกาศ
   **ก่อน** route `/finance/payment-events/{event_id}` ของ P2.1 เสมอ — ถ้า dynamic
   มาก่อน ค่า "preview" จะพยายามถูกแปลงเป็น int แล้วตอบ 422/404 แทนที่จะเข้า handler นี้
   (กับดักเดียวกับ `fines/summary` ที่เคยเจอ — ดู `routers/finance/fines.py`)

⚠️ preview เป็นการอ่าน: ไม่ล็อกห้อง ไม่เขียนเงิน/เอกสาร (commit อยู่ที่ P2.1)
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError, StudentNotFoundError
from models.finance_schemas import AllocationPreviewRequest, AllocationPreviewResponse
from services.finance.allocation import AllocationError, ChannelNotFoundError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status

    - `BILL_NOT_OPEN` = 409 (ข้อมูลที่ client เห็นเก่าไปแล้ว — ต้องโหลดใหม่)
    - `EXCESS_NOT_ALLOWED` / `INVALID_AMOUNT` = 400 (แก้ input ได้ทันที)
    - ช่องทาง/นักเรียน/ห้องที่ไม่มี = 404 · ไม่ใช่สมาชิก/ไม่มีสิทธิ์ = 403
    """
    if isinstance(e, AllocationError):
        if e.code == "BILL_NOT_OPEN":
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, (StudentNotFoundError, RoomNotFoundError, ChannelNotFoundError)):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.post(
    "/{target_id}/finance/payment-events/preview",
    response_model=AllocationPreviewResponse,
)
async def preview_allocation(
    req: AllocationPreviewRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """พรีวิวว่าเงินก้อนนี้ + เครดิตจะลงบิลไหนเท่าไร — ไม่เขียนอะไรลง DB

    🔒 ต้องมี `MANAGE_FINANCE` (ดูเหตุผลใน service) — สมาชิกทั่วไปจะได้ 403
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.preview_allocation(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], req=req,
        )
    except Exception as e:
        _raise_translated(e)
