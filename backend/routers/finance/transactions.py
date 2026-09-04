"""รายการรับ-จ่าย / โอนเงิน / revert"""
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

@router.post("/{target_id}/finance/transactions", response_model=SuccessResponse)
async def add_transaction(
    req: TransactionCreate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.add_transaction(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/transactions", response_model=TransactionListResponse)
async def get_transactions(
    request: Request,
    filters: TransactionFilter = Depends(), 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_transactions(
            pool=pool,
            limit=filters.limit,
            offset=filters.offset,
            start_date=filters.start_date,
            end_date=filters.end_date,
            account_id=filters.account_id,
            category_id=filters.category_id,
            transaction_type=filters.transaction_type,
            server_id=target.server_id,
            room_id=target.room_id,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{target_id}/finance/transactions/{transaction_id}", response_model=SuccessResponse)
async def revert_transaction(
    transaction_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.revert_transaction(
            pool=pool,
            transaction_id=transaction_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except (RoomNotFoundError, TransactionNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/transfer", response_model=SuccessResponse)
async def transfer_money(
    req: TransferCreate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.transfer_money(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e: 
        raise HTTPException(status_code=400, detail=str(e))
