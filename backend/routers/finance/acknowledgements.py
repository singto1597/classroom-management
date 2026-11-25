"""ใบรับทราบยอดค้าง (ACK) — [FIN-V2 / P2.6]

⭐ ไฟล์นี้เป็น **จุดต่อท้ายของ P5.4** (ACK status/void + RPT): P5.4 จะ append
   `GET`/`void` ของ ACK ต่อท้ายไฟล์นี้ ⇒ ห้ามย้าย router นี้ไปรวมกับ `receipts.py`
   (path ขึ้นต้น `/finance/acknowledgements` ไม่ซ้ำกับกลุ่มใด ⇒ ลำดับ include ไม่มีผล)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg

from models.finance_schemas import AckIssueRequest, AckIssueResponse
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


@router.post(
    "/{target_id}/finance/acknowledgements", response_model=AckIssueResponse
)
async def issue_acknowledgements(
    req: AckIssueRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ออก **ใบรับทราบยอดค้าง 1 ใบต่อรอบ** (ทั้งห้อง หรือคนที่เลือก) — ไม่มีการรับเงิน

    🧾 เอกสารนี้คือ "รับทราบหนี้" ไม่ใช่หลักฐานชำระเงิน: ไม่มี QR/ช่องทาง และไม่มี
       การขยับกระเป๋า/บัญชี/เครดิต (service ไม่แตะตารางเงินเลย)
    """
    # 🚧 ตรวจรูปแบบคำขอก่อนแตะ DB — ตอบ 400 ที่บอกทางแก้ ไม่ใช่ 422 ดิบของ Pydantic
    #    (`scope='room'` ต้องไม่ส่งรายชื่อ: ถ้ารับ จะกลายเป็น "ห้องที่กรองรายชื่อ"
    #     ซึ่งเป็นความหมายที่ผู้เรียกไม่ได้ตั้งใจ)
    if req.scope == "selected" and not req.student_ids:
        raise HTTPException(status_code=400, detail="กรุณาเลือกนักเรียนอย่างน้อย 1 คน")
    if req.scope == "room" and req.student_ids:
        raise HTTPException(
            status_code=400,
            detail="การแจ้งทั้งห้องไม่ต้องระบุรายชื่อนักเรียน — เลือก 'เฉพาะคนที่เลือก' แทน",
        )
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_acknowledgements(
            pool=pool, req=req,
            user_id=user_ctx["user_id"], client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
