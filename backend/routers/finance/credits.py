"""เงินรับล่วงหน้า / เครดิตคงเหลือรายนักเรียน — F4

⚠️ ลำดับการประกาศ route: `GET /finance/credits/plan` **ต้องมาก่อน**
   `GET /finance/credits/{student_id}` — มิฉะนั้นคำว่า "plan" จะถูกตีความเป็น
   `student_id` แล้วได้ 422 ทุกครั้ง (กับดักเดียวกับที่ `routers/finance/receipts.py`
   และ `budgets.py` เตือนไว้ — และเป็นชนิดที่ "ล้มดัง" แต่หาสาเหตุยากเพราะข้อความ
   error จะบอกแค่ "ค่าที่ส่งมาไม่ใช่จำนวนเต็ม")

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`

⚠️ ชื่อ route ใช้ `/finance/credits` (พหูพจน์) ให้ตรงกับตาราง `student_credits`
   และไม่ชนกับ `/{target_id}/finance/transactions`
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
import asyncpg
from typing import List, Optional

from models.finance_schemas import (
    StudentCreditBalanceResponse, StudentCreditDetailResponse,
    CreditTopUpRequest, CreditTopUpResponse, CreditApplyRequest, CreditUndoRequest,
    CreditApplyPlanResponse, CreditUndoResponse,
)
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, StudentNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()

# 🔁 ยิงได้สูงสุด 100 คนต่อครั้ง — เพดานเดียวกับ `ReceiptInvoiceIssueRequest`
#    ("หนึ่ง HTTP request" ของระบบนี้มีขนาดเท่ากันไม่ว่าจะเป็นเส้นทางไหน)
_MAX_APPLY_STUDENTS = 100


@router.get("/{target_id}/finance/credits", response_model=List[StudentCreditBalanceResponse])
async def get_credit_balances(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """นักเรียนทุกคนของห้อง + ยอดเครดิตคงเหลือ (คนไม่มีเครดิตก็อยู่ ยอด 0)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_credit_balances(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# 🔴 ต้องประกาศ **ก่อน** `/{student_id}` — ดูคำเตือนบนหัวไฟล์
@router.get("/{target_id}/finance/credits/plan", response_model=CreditApplyPlanResponse)
async def get_credit_plan(
    request: Request,
    student_ids: List[int] = Query(..., description="นักเรียนที่ต้องการดูข้อเสนอการหัก"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """**อ่านล้วน** — ข้อเสนอว่าจะหักบิลไหน เท่าไร เหลือเท่าไร (ยังไม่เขียนอะไรเลย)

    ⚠️ เพดาน 100 คนบังคับที่นี่ (ไม่ใช่ `max_length` ของ Pydantic) เพราะเป็น
       query param ที่ผู้ใช้อาจส่งมาเกินได้จาก URL ที่ประกอบเอง — ตอบเป็นข้อความไทย
       ที่บอกทางออก ดีกว่า 422 ที่แปลว่า "ข้อมูลไม่ถูกต้อง"
    """
    if not student_ids:
        raise HTTPException(status_code=400, detail="กรุณาเลือกนักเรียนอย่างน้อย 1 คน")
    if len(student_ids) > _MAX_APPLY_STUDENTS:
        raise HTTPException(
            status_code=400,
            detail=f"ดูข้อเสนอได้ครั้งละไม่เกิน {_MAX_APPLY_STUDENTS} คน (ส่งมา {len(student_ids)} คน)",
        )
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.plan_credit_application(
            pool=pool, student_ids=student_ids, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{target_id}/finance/credits/{student_id}", response_model=StudentCreditDetailResponse
)
async def get_student_credit(
    request: Request,
    student_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียดเครดิตของนักเรียน 1 คน: ยอดคงเหลือ + ประวัติ + บิลค้าง + ข้อเสนอการหัก"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_student_credit(
            pool=pool, student_id=student_id, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/credits/apply", response_model=CreditApplyPlanResponse)
async def apply_credit(
    req: CreditApplyRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """หักเครดิตไปปิดบิลของนักเรียนที่เลือก — **ทั้งชุด all-or-nothing**

    🎯 ระบบวางแผนใหม่ **ใต้ล็อก** ก่อนลงมือ ⇒ ไม่ใช้ตัวเลขที่ client เห็นมาก่อนหน้านี้
       (ระหว่างที่ครูกดยืนยัน อาจมีคนรับเงินบิลเดียวกันไปแล้ว)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.apply_credit(
            pool=pool, student_ids=req.student_ids, user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/credits/undo", response_model=CreditUndoResponse)
async def undo_credit_application(
    req: CreditUndoRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิก 'การหักเครดิต' 1 รายการ → คืนเครดิต + คืนสถานะบิล + void journal

    ⚠️ ยกเลิกได้เฉพาะ `entry_type='apply'` — การ **เติม** เงินล่วงหน้าต้องยกเลิกผ่าน
       `DELETE /finance/transactions/{id}` (ซึ่งจะยกเลิกใบ DEP ให้ด้วย)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.undo_credit_application(
            pool=pool, credit_entry_id=req.credit_entry_id, reason=req.reason,
            user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/credits", response_model=CreditTopUpResponse)
async def top_up_credit(
    req: CreditTopUpRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """เติมเงินล่วงหน้าให้นักเรียน 1 คน → ออกใบรับเงินล่วงหน้า (DEP)

    🔑 `idempotency_key` บังคับ — กดซ้ำด้วยคีย์เดิม = ได้ผลลัพธ์เดิม (`reused: true`)
       ไม่ใช่การรับเงินรอบที่สอง
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        # ⚠️ ไม่ส่ง `user_name` แยก — service อ่านจาก `req.user_name` เอง (ที่เดียว)
        #    การส่งสองทางเปิดโอกาสให้สองค่าไม่ตรงกันโดยไม่มีใครรู้
        return await FinanceService.top_up_credit(
            pool=pool, req=req,
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StudentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
