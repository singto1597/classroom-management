"""💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว

POST `/{target_id}/finance/credits/rounds` — 1 คำขอ = 1 transaction
= all-or-nothing · 1 นักเรียน = 1 payment event แบบ credit-only (ไม่มี REC/DEP)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
   แต่เส้นทางนี้ต้องรู้ห้องจริงก่อนตรวจ replay ⇒ service รับ `target_room_id`

⚠️ path ขึ้นต้น `/finance/credits/rounds` ซึ่งไม่ซ้ำกับ route ใดของ
   `routers/finance/credits.py` (กลุ่มนั้นมี `/credits/apply`, `/credits/undo`,
   `/credits`, `/credits/plan`, `/credits/{student_id}`) ⇒ ลำดับ include ไม่มีผล
   กับความถูกต้อง แต่ประกาศท้ายไฟล์ตามกติกา append-only

🔒 ต้อง `MANAGE_FINANCE` (service ตรวจใต้ transaction)
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError, StudentNotFoundError
from models.finance_schemas import CreditRoundCreate, CreditRoundResponse
from services.finance.credit_rounds import CreditRoundConflictError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status

    🔴 `CreditRoundConflictError` ต้องถูกจับ **ก่อน** `ValueError` ไม่งั้นได้ 400
       และ frontend แยกไม่ออกว่า "ต้องโหลดรายชื่อใหม่" กับ "ข้อมูลไม่ถูกต้อง"
    """
    if isinstance(e, CreditRoundConflictError):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, (RoomNotFoundError, StudentNotFoundError)):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.post(
    "/{target_id}/finance/credits/rounds",
    response_model=CreditRoundResponse,
)
async def create_credit_round(
    req: CreditRoundCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """หักเครดิตของนักเรียนที่เลือกเพื่อปิดบิล — ไม่มีการเคลื่อนไหวของเงิน

    🔁 ยิงซ้ำด้วย `idempotency_key` + ชุดนักเรียนเดิม ⇒ คืนผลเดิม (`reused=true`)
    🔴 ยิงซ้ำด้วยคีย์เดิมแต่ชุดนักเรียนต่าง ⇒ 409 (ไม่สร้าง/แก้ข้อมูลใด ๆ)
    """
    if target.room_id is None:
        raise HTTPException(
            status_code=400,
            detail="รายการนี้ต้องระบุห้องเรียน (target_type=room)",
        )
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_credit_round(
            pool=pool, target_room_id=target.room_id, req=req,
            user_id=user_ctx["user_id"],
            user_name=(req.user_name or "").strip() or "—",
            client_source=client_source, actor_identifier=actor,
        )
    except Exception as e:
        _raise_translated(e)
