"""รายงานการเงิน (summary / trial-balance / income-statement / students / debtors / student-debts)"""
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

@router.get("/{target_id}/finance/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    request: Request,
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_summary(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            month=month,
            year=year,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/trial-balance")
async def get_trial_balance(
    request: Request,
    as_of_date: Optional[date] = Query(None, description="งบ ณ วันที่ (ไม่ระบุ = ทั้งหมดจนถึงตอนนี้)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_trial_balance(
            pool=pool,
            room_id=target.room_id,
            server_id=target.server_id,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"],
            as_of_date=as_of_date
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/income-statement")
async def get_income_statement(
    request: Request,
    start_date: date = Query(..., description="วันที่เริ่มต้น"),
    end_date: date = Query(..., description="วันที่สิ้นสุด"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_income_statement(
            pool=pool,
            room_id=target.room_id,
            server_id=target.server_id,
            start_date=start_date,
            end_date=end_date,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/students", response_model=List[StudentBasicInfo])
async def get_active_students(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_active_students(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/debtors", response_model=List[DebtorItem])
async def get_all_debtors(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_all_debtors(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/students/{student_id}/debts", response_model=StudentDebtProfileResponse)
async def get_student_debts(
    student_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_student_debts(
            pool=pool,
            student_id=student_id,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
