"""📊 [FIN-V2 / P5.4] รายงานปิดงบเดือน (RPT) — HTTP layer เท่านั้น

- `/finance/monthly-reports` — list / create
- `/finance/monthly-reports/{report_id}` — detail
- `/finance/monthly-reports/{report_id}/finalize` · `/void` — เปลี่ยนสถานะ
- `/finance/monthly-reports/{report_id}/pdf` — binary stream (ไม่มี `response_model`)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
⚠️ ลำดับ route: `/{report_id}` กับ `/{report_id}/pdf` ไม่ชนกัน แต่ถ้าเพิ่ม
   `/monthly-reports/latest` ในอนาคตต้องประกาศ **ก่อน** `{report_id}`
   (บทเรียนเดียวกับ `routers/finance/budgets.py`)
"""
import io
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    MonthlyReportCreate,
    MonthlyReportDetailResponse,
    MonthlyReportFinalize,
    MonthlyReportListResponse,
    MonthlyReportVoid,
    SuccessResponse,
)
from services.finance.pdf import PdfRenderError
from services.finance.monthly_reports import MonthlyReportConflictError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """service exception → HTTP (ข้อความไทยมาจาก service · conflict ก่อน ValueError)"""
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, MonthlyReportConflictError):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


def _pdf_response(pdf_bytes: bytes, filename: str) -> StreamingResponse:
    """เหมือน `routers/finance/documents.py` — ไม่มี `response_model` โดยเจตนา"""
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get(
    "/{target_id}/finance/monthly-reports", response_model=MonthlyReportListResponse
)
async def list_monthly_reports(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    year_be: Optional[int] = Query(default=None, alias="year", description="ปี พ.ศ."),
    status: Optional[str] = Query(default=None, description="draft | final | voided"),
):
    """รายงานปิดงบของห้อง — ทุกสถานะแสดงเสมอ (กรองได้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_monthly_reports(
            pool=pool, client_source=client_source, actor_identifier=actor,
            year_be=year_be, status=status,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/monthly-reports", response_model=MonthlyReportDetailResponse
)
async def create_monthly_report(
    req: MonthlyReportCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """สร้างฉบับร่าง — snapshot จาก journal ณ ขณะนี้ (ไม่แตะเงิน)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_monthly_report(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get(
    "/{target_id}/finance/monthly-reports/{report_id}",
    response_model=MonthlyReportDetailResponse,
)
async def get_monthly_report(
    report_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายงาน 1 ใบ + ลายเซ็น — ใบที่ void แล้วอ่านได้เสมอ"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_monthly_report(
            pool=pool, report_id=report_id, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/monthly-reports/{report_id}/finalize",
    response_model=MonthlyReportDetailResponse,
)
async def finalize_monthly_report(
    report_id: int,
    req: MonthlyReportFinalize,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ปิดงบ — เงินสดนับจริงต้องตรงกับยอดบัญชี (ต่าง ≥ 0.005 → 400 พร้อมสามตัวเลข)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.finalize_monthly_report(
            pool=pool, report_id=report_id, req=req, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post(
    "/{target_id}/finance/monthly-reports/{report_id}/void",
    response_model=SuccessResponse,
)
async def void_monthly_report(
    report_id: int,
    req: MonthlyReportVoid,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกรายงาน — เฉพาะฉบับล่าสุดของเดือน (409 ถ้าไม่ใช่)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.void_monthly_report(
            pool=pool, report_id=report_id, req=req, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/monthly-reports/{report_id}/pdf")
async def render_monthly_report_pdf(
    report_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """PDF ของรายงาน — `application/pdf` (ไม่มี `response_model` โดยเจตนา)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_monthly_report_pdf(
            pool=pool, report_id=report_id, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except PdfRenderError as e:
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")
    except Exception as e:
        _raise_translated(e)
    return _pdf_response(pdf_bytes, filename)
