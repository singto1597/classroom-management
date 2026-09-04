"""กระเป๋าเงิน / บัญชี (finance_accounts)"""
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

@router.post("/{target_id}/finance/accounts", response_model=SuccessResponse)
async def create_account(
    req: AccountCreate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_account(
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


@router.get("/{target_id}/finance/accounts", response_model=List[AccountResponse])
async def get_accounts(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_accounts(
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


@router.patch("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def update_account(
    account_id: int,
    req: AccountUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_account(
            pool=pool,
            account_id=account_id,
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


@router.delete("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def delete_account(
    account_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.delete_account(
            pool=pool,
            account_id=account_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
