"""🗂️ [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — รายการ/รายละเอียด/by-no/PDF/พิมพ์ชุด

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — service เป็นผู้ resolve
⚠️ ลำดับ route: `by-no/{doc_no}` (static segment แรก) ต้องประกาศ **ก่อน**
   `{doc_type}/{doc_id}` (dynamic สอง segment) ไม่งั้น `by-no` จะถูกตีความเป็น doc_type
   แล้วตอบ 400 "ไม่รู้จักชนิดเอกสาร" ทุกครั้ง
⚠️ ไม่ประกาศ `response_model` บนเส้นทาง PDF โดยเจตนา — response เป็น binary stream
"""
import io
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentPrintBundleRequest,
)
from services.finance.constants import REGISTRY_PAGE_DEFAULT, REGISTRY_PAGE_MAX
from services.finance.pdf import PdfRenderError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception ของ service → HTTP ตามกติกา routers (ข้อความไทยจาก service)"""
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


def _split_doc_types(raw: Optional[str]) -> Optional[list]:
    """`doc_types=receipt,invoice` → `['receipt', 'invoice']` (ค่าว่าง = ไม่กรอง)"""
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or None


def _pdf_response(pdf_bytes: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get("/{target_id}/finance/documents", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    doc_types: Optional[str] = Query(
        default=None, description="ชนิดเอกสารคั่นด้วยจุลภาค เช่น receipt,invoice"
    ),
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    student_id: Optional[int] = Query(default=None),
    receiver_id: Optional[int] = Query(default=None),
    channel_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None, description="active | voided"),
    q: Optional[str] = Query(default=None, description="ค้นเลขเอกสาร/ชื่อนักเรียน/ชื่อผู้รับ"),
    include_voided: bool = Query(default=False),
    limit: int = Query(default=REGISTRY_PAGE_DEFAULT, ge=1, le=REGISTRY_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
):
    """รายการเอกสารทุกชนิดของห้อง (สมาชิกอ่านได้) — เรียงใหม่สุดก่อน + total"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.list_documents(
            pool=pool, client_source=client_source, actor_identifier=actor,
            doc_types=_split_doc_types(doc_types),
            start_date=from_date, end_date=to_date,
            student_id=student_id, receiver_id=receiver_id, channel_id=channel_id,
            status=status, q=q, include_voided=include_voided,
            limit=limit, offset=offset,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


# 🔴 static ก่อน dynamic — `/documents/by-no/{doc_no}` vs `/documents/{doc_type}/{doc_id}`
@router.get(
    "/{target_id}/finance/documents/by-no/{doc_no}",
    response_model=DocumentDetailResponse,
)
async def get_document_by_no(
    doc_no: str,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ค้นด้วยเลขเอกสาร (resolver สำหรับ redirect จากลิงก์เก่า)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_document_detail_by_no(
            pool=pool, doc_no=doc_no, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.post("/{target_id}/finance/documents/print-bundle")
async def print_document_bundle(
    req: DocumentPrintBundleRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """พิมพ์ชุด ≤100 ใบ (mixed layout v1+v2 ได้) — 404 ถ้ามีใบใดขาด"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_document_bundle(
            pool=pool, items=[it.model_dump() for it in req.items],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except (RoomNotFoundError, ForbiddenError, ValueError, PdfRenderError) as e:
        if isinstance(e, PdfRenderError):
            raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")
        _raise_translated(e)
    return _pdf_response(pdf_bytes, filename)


@router.get("/{target_id}/finance/documents/{doc_type}/{doc_id}", response_model=DocumentDetailResponse)
async def get_document_detail(
    doc_type: str,
    doc_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียดเอกสาร 1 ใบ — ใบที่ถูกยกเลิกอ่านได้เสมอ (มุมมองตรวจสอบ)"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_document_detail(
            pool=pool, doc_type=doc_type, doc_id=doc_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except Exception as e:
        _raise_translated(e)


@router.get("/{target_id}/finance/documents/{doc_type}/{doc_id}/pdf")
async def download_document_pdf(
    doc_type: str,
    doc_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """PDF ของเอกสาร 1 ใบ — legacy ใช้เส้นทางเดิม (ไบต์เท่าเดิม), RPT ยัง 404"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_document_pdf(
            pool=pool, doc_type=doc_type, doc_id=doc_id,
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except PdfRenderError as e:
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")
    except Exception as e:
        _raise_translated(e)
    return _pdf_response(pdf_bytes, filename)
