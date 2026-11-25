"""📊 [FIN-V2 / P6.4] แดชบอร์ดการเงิน — เงินของห้องตอนนี้ (อ่านอย่างเดียว)

`GET /{target_id}/finance/dashboard/ownership`

⚠️ path ขึ้นต้นด้วย segment literal `dashboard/` ⇒ ไม่ชนกับ `/finance/summary`
   (คนละพาธ) และไม่ชนกับ route `{doc_type}/{doc_id}` ใด ๆ ของทะเบียนเอกสาร
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import MoneyOwnershipResponse
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_audit_context, get_target

router = APIRouter()


@router.get(
    "/{target_id}/finance/dashboard/ownership",
    response_model=MoneyOwnershipResponse,
)
async def get_money_ownership(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_money_ownership(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
