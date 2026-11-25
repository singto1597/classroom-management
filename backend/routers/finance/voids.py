"""🚫 [FIN-V2 / P6.1] void endpoint กลาง — `/finance/documents/{doc_type}/{doc_id}/void`

รับผิดชอบเฉพาะชนิดที่ไม่มี resource router ของตัวเอง (INV/CERT) + กันไม่ให้ไคลเอนต์
เรียกยกเลิกเอกสารที่แตะเงินผ่านทางนี้ — เอกสารเหล่านั้นต้องยกเลิกผ่าน endpoint ของมันเอง:

- payment event → `POST /finance/payment-events/{id}/void`
- PV           → `POST /finance/expense-vouchers/{id}/void`
- INC          → `POST /finance/income-batches/{id}/void`
- ACK          → `POST /finance/acknowledgements/{receipt_no}/void`
- RPT          → `POST /finance/monthly-reports/{id}/void`

🔴 ลำดับ except: `VoidConflictError` **ก่อน** `ValueError` — ไม่งั้น 409 จะกลายเป็น 400
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, PaymentNotFoundError, RoomNotFoundError
from models.finance_schemas import VoidRequest, VoidResponse
from services.finance.expense_vouchers import ExpenseVoucherNotFoundError
from services.finance.income_batches import IncomeBatchNotFoundError
from services.finance.voids import VoidConflictError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


@router.post(
    "/{target_id}/finance/documents/{doc_type}/{doc_id}/void",
    response_model=VoidResponse,
)
async def void_document(
    doc_type: str,
    doc_id: int,
    req: VoidRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกเอกสาร INV (ไม่แตะเงิน) — ชนิดอื่นถูกปฏิเสธพร้อมชี้ endpoint ที่ถูกต้อง"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.void_document(
            pool=pool, doc_type=doc_type, doc_id=doc_id, req=req,
            user_id=user_ctx["user_id"], client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
        )
    except (
        RoomNotFoundError, PaymentNotFoundError,
        ExpenseVoucherNotFoundError, IncomeBatchNotFoundError,
    ) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except VoidConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
