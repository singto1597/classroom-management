"""Excel export (transactions + journal)"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header, Path, Request
from fastapi.responses import StreamingResponse
import asyncpg
from typing import List, Optional, Literal

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()

@router.post("/{target_id}/finance/export")
async def export_transactions(
    req: FinanceExportRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        excel_file = await FinanceService.export_transactions_excel(
            pool=pool,
            req=req,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
        ref_id = target.server_id or target.room_id
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=finance_export_{ref_id}.xlsx"}
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/export/journal")
async def export_journal_excel(
    request: Request,
    month: Optional[int] = Query(None, ge=1, le=12, description="เดือนที่ต้องการ (ให้พร้อม year เสมอ)"),
    year: Optional[int] = Query(None, ge=2000, le=2200, description="ปี ค.ศ. ที่ต้องการ"),
    start_date: Optional[date] = Query(None, description="วันที่เริ่มต้น"),
    end_date: Optional[date] = Query(None, description="วันที่สิ้นสุด"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        excel_file = await FinanceService.export_journal_excel(
            pool=pool,
            month=month,
            year=year,
            start_date=start_date,
            end_date=end_date,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
        ref_id = target.server_id or target.room_id
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=finance_journal_{ref_id}.xlsx"}
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
