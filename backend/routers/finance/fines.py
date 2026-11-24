"""ค่าปรับ — ประเภทความผิด / ออกค่าปรับ / รายการ / แก้ / ยกเลิก

⚠️ ลำดับ route: **path แบบ fix ต้องมาก่อน path ที่มี `{fine_id}`** ในตำแหน่งเดียวกัน
   (เช่น `/finance/fines/summary` ต้องอยู่เหนือ `/finance/fines/{fine_id}`)
   ถ้าจัดสลับ FastAPI จะ match ชื่อเข้า `{fine_id}` แล้วได้ 422

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from core.dependencies import get_current_user, get_db_pool
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_fines import (
    AgingResponse,
    FineCancelRequest,
    FineDetailResponse,
    FineIssueRequest,
    FineIssueResponse,
    FineListResponse,
    FineSummaryResponse,
    FineRefundCreate,
    FineRefundCreatedResponse,
    FineRefundDecision,
    FineRefundDecisionResponse,
    FineRefundListResponse,
    FineTypeCreate,
    FineTypeCreatedResponse,
    FineTypeResponse,
    FineTypeUpdate,
    FineUpdateRequest,
    FineWaiverCreate,
    FineWaiverCreatedResponse,
    FineWaiverDecision,
    FineWaiverDecisionResponse,
    FineWaiverListResponse,
)
from models.finance_schemas import SuccessResponse
from routers._common import TargetResolution, get_audit_context, get_target
from services.finance_service import FinanceService

router = APIRouter()


# ═════════════════════════════════════════════════════ ประเภทความผิด
@router.get("/{target_id}/finance/fine-types", response_model=list[FineTypeResponse])
async def list_fine_types(
    request: Request,
    active_only: bool = Query(False),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_fine_types(
            pool=pool, client_source=client_source, actor_identifier=actor,
            active_only=active_only,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{target_id}/finance/fine-types", response_model=FineTypeCreatedResponse)
async def create_fine_type(
    req: FineTypeCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_fine_type(
            pool=pool, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{target_id}/finance/fine-types/{fine_type_id}", response_model=SuccessResponse)
async def update_fine_type(
    fine_type_id: int,
    req: FineTypeUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_fine_type(
            pool=pool, fine_type_id=fine_type_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{target_id}/finance/fine-types/{fine_type_id}", response_model=SuccessResponse)
async def delete_fine_type(
    fine_type_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.delete_fine_type(
            pool=pool, fine_type_id=fine_type_id, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ═════════════════════════════════════════════════════════ ค่าปรับ
@router.post("/{target_id}/finance/fines", response_model=FineIssueResponse)
async def issue_fines(
    req: FineIssueRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ออกค่าปรับ 1 รอบ (หลายคน ความผิดเดียวกัน) — idempotency key บังคับ"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_fines(
            pool=pool, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════ คำขอยกเว้น / ลดค่าปรับ
@router.post(
    "/{target_id}/finance/fines/{fine_id}/waivers",
    response_model=FineWaiverCreatedResponse,
)
async def request_waiver(
    fine_id: int,
    req: FineWaiverCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.request_waiver(
            pool=pool, fine_id=fine_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/fine-waivers", response_model=FineWaiverListResponse)
async def list_fine_waivers(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
    fine_id: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_fine_waivers(
            pool=pool, client_source=client_source, actor_identifier=actor,
            status=status, fine_id=fine_id, limit=limit, offset=offset,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-waivers/{waiver_id}/approve",
    response_model=FineWaiverDecisionResponse,
)
async def approve_waiver(
    waiver_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineWaiverDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.approve_waiver(
            pool=pool, waiver_id=waiver_id, req=req or FineWaiverDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-waivers/{waiver_id}/reject",
    response_model=FineWaiverDecisionResponse,
)
async def reject_waiver(
    waiver_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineWaiverDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.reject_waiver(
            pool=pool, waiver_id=waiver_id, req=req or FineWaiverDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-waivers/{waiver_id}/cancel",
    response_model=FineWaiverDecisionResponse,
)
async def cancel_waiver(
    waiver_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineWaiverDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.cancel_waiver(
            pool=pool, waiver_id=waiver_id, req=req or FineWaiverDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════ คืนเงินค่าปรับ
@router.post(
    "/{target_id}/finance/fines/{fine_id}/refunds",
    response_model=FineRefundCreatedResponse,
)
async def request_refund(
    fine_id: int,
    req: FineRefundCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.request_refund(
            pool=pool, fine_id=fine_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/fine-refunds", response_model=FineRefundListResponse)
async def list_fine_refunds(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
    fine_id: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_fine_refunds(
            pool=pool, client_source=client_source, actor_identifier=actor,
            status=status, fine_id=fine_id, limit=limit, offset=offset,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-refunds/{refund_id}/approve",
    response_model=FineRefundDecisionResponse,
)
async def approve_refund(
    refund_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineRefundDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.approve_refund(
            pool=pool, refund_id=refund_id, req=req or FineRefundDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-refunds/{refund_id}/reject",
    response_model=FineRefundDecisionResponse,
)
async def reject_refund(
    refund_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineRefundDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.reject_refund(
            pool=pool, refund_id=refund_id, req=req or FineRefundDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/fine-refunds/{refund_id}/cancel",
    response_model=FineRefundDecisionResponse,
)
async def cancel_refund(
    refund_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineRefundDecision] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.cancel_refund(
            pool=pool, refund_id=refund_id, req=req or FineRefundDecision(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═════════════════════════════════════════════════════ รายงาน
# ⚠️ `/finance/fines/summary` **ต้องอยู่ก่อน** `/finance/fines/{fine_id}` ด้านล่าง
@router.get("/{target_id}/finance/fines/summary", response_model=FineSummaryResponse)
async def get_fine_summary(
    request: Request,
    as_of: Optional[date] = Query(None, description="ณ วันที่ (default = วันนี้)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ภาพรวมค่าปรับ — นักเรียนเห็นเฉพาะของตัวเอง (backend กรองให้)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_fine_summary(
            pool=pool, client_source=client_source, actor_identifier=actor,
            as_of=as_of,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/receivables/aging", response_model=AgingResponse)
async def get_receivables_aging(
    request: Request,
    as_of: Optional[date] = Query(None, description="ณ วันที่ (default = วันนี้)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายงานอายุหนี้ — บิลเปิดทุกใบ (โปรเจกต์ + ค่าปรับ) แยกถังตามจำนวนวันเลยกำหนด"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_receivables_aging(
            pool=pool, client_source=client_source, actor_identifier=actor,
            as_of=as_of,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/fines", response_model=FineListResponse)
async def list_fines(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(issued|partially_paid|paid|waived|cancelled|refunded)$"),
    student_id: Optional[int] = Query(None),
    fine_type_id: Optional[int] = Query(None),
    batch_id: Optional[int] = Query(None),
    from_date: Optional[date] = Query(None, description="วันที่เกิดเหตุ (เริ่ม)"),
    to_date: Optional[date] = Query(None, description="วันที่เกิดเหตุ (สิ้นสุด)"),
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_fines(
            pool=pool, client_source=client_source, actor_identifier=actor,
            status=status, student_id=student_id, fine_type_id=fine_type_id,
            batch_id=batch_id, from_date=from_date, to_date=to_date, search=search,
            limit=limit, offset=offset,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/fines/{fine_id}", response_model=FineDetailResponse)
async def get_fine(
    fine_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_fine(
            pool=pool, fine_id=fine_id, client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{target_id}/finance/fines/{fine_id}", response_model=SuccessResponse)
async def update_fine(
    fine_id: int,
    req: FineUpdateRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """แก้ค่าปรับ **ก่อนมีคนจ่าย** — เปลี่ยนยอดได้ (journal ปรับส่วนต่าง)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_fine(
            pool=pool, fine_id=fine_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/fines/{fine_id}/cancel", response_model=SuccessResponse)
async def cancel_fine(
    fine_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[FineCancelRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    """ยกเลิกค่าปรับ **ก่อนมีคนจ่าย** — กลับรายได้ + soft delete บิล/โปรเจกต์ซ่อน + void INV"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.cancel_fine(
            pool=pool, fine_id=fine_id, req=req or FineCancelRequest(),
            user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
