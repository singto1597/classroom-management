"""💸 [FIN-V2 / P4.1] ใบสำคัญจ่ายหลายบรรทัด — สร้าง/รายการ/รายละเอียด

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
⚠️ ลำดับ route: static (`/expense-vouchers`) ก่อน dynamic (`/expense-vouchers/{id}`)
⚠️ 409 (คีย์เดิม payload ต่าง) ต้องแยกจาก 400 — หน้าจอจะเปิดใบเดิมแทนการสร้างใหม่
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    ExpenseVoucherCreate, ExpenseVoucherDetailResponse, ExpenseVoucherListResponse,
    ExpenseVoucherResponse, VoidRequest, VoidResponse,
)
from services.finance.expense_vouchers import (
    ExpenseVoucherIdempotencyConflict, ExpenseVoucherNotFoundError,
)
from services.finance.voids import VoidConflictError
from services.finance.pdf import PdfRenderError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP status ตามกติกา routers

    🔴 `ExpenseVoucherIdempotencyConflict` ต้องมาก่อน `ValueError` เสมอ — มันสืบทอด
       มาจาก ValueError ถ้าตรวจแบบ reversed แมทช์เป็น 400 แล้วหน้าจอจะโหลดใบเดิมไม่ได้
    """
    if isinstance(e, (RoomNotFoundError, ExpenseVoucherNotFoundError)):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ExpenseVoucherIdempotencyConflict):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.post("/{target_id}/finance/expense-vouchers", response_model=ExpenseVoucherResponse)
async def create_expense_voucher(
    req: ExpenseVoucherCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """สร้างใบสำคัญจ่าย (MANAGE_FINANCE) — 1 ใบ = N transactions + N journals + 1 PV

    🔁 คีย์เดิม + payload เดิม ⇒ คืนใบเดิม (`reused=true`) · payload ต่าง ⇒ 409
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_expense_voucher(
            pool=pool, req=req, user_id=user_ctx["user_id"],
            # 🖊️ ชื่อผู้จัดทำมาจาก payload ก่อน; ถ้าไม่มี service จะอ่านจากโปรไฟล์ผู้ใช้
            user_name=(req.user_name or "").strip(),
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/expense-vouchers", response_model=ExpenseVoucherListResponse)
async def list_expense_vouchers(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    status: Optional[str] = Query(default=None),
):
    """รายการใบสำคัญจ่ายของห้อง (สมาชิกอ่านได้) — เรียงใหม่สุดก่อน"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_expense_vouchers(
            pool=pool, client_source=client_source, actor_identifier=actor,
            from_date=from_date, to_date=to_date, status=status,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/expense-vouchers/{voucher_id}",
    response_model=ExpenseVoucherDetailResponse,
)
async def get_expense_voucher(
    voucher_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียดใบสำคัญจ่าย — บรรทัด + ลายเซ็น + เลข PV/CERT (สมาชิกอ่านได้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_expense_voucher(
            pool=pool, voucher_id=voucher_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/expense-vouchers/{voucher_id}/pdf")
async def download_expense_voucher_pdf(
    voucher_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ดาวน์โหลด PV ของใบสำคัญจ่ายเป็น PDF (เรนเดอร์ผ่าน Gotenberg)

    ⚠️ ไม่ประกาศ `response_model` โดยเจตนา — response เป็น binary stream
    🔴 ใบที่ถูกยกเลิกพิมพ์ได้ (partial ประทับแบนเนอร์) ⇒ ไม่กรอง status ที่ service
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_expense_voucher_pdf(
            pool=pool, voucher_id=voucher_id, client_source=client_source,
            actor_identifier=actor, user_id=user_ctx["user_id"],
            server_id=target.server_id, room_id=target.room_id,
        )
    except (RoomNotFoundError, ExpenseVoucherNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PdfRenderError as e:
        # 502 = Gotenberg ใช้งานไม่ได้ — ไม่ใช่ 500 (โค้ดเราไม่พัง)
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# 🚫 [FIN-V2 / P6.1] void PV — คืนทุกกระเป๋า + void CERT/PV/journal พร้อมกัน
#    🔴 จับ `VoidConflictError` **ก่อน** `ValueError` — ไม่งั้น 409 จะกลายเป็น 400
@router.post(
    "/{target_id}/finance/expense-vouchers/{voucher_id}/void",
    response_model=VoidResponse,
)
async def void_expense_voucher(
    voucher_id: int,
    req: VoidRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกใบสำคัญจ่าย (MANAGE_FINANCE) — PV และ CERT ต้องถูกยกเลิกด้วยกันเสมอ"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.void_expense_voucher(
            pool=pool, voucher_id=voucher_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except (ExpenseVoucherNotFoundError, RoomNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except VoidConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
