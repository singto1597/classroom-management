"""📎 ไฟล์หลักฐานการเงิน — อัปโหลด/รายการ/ลบ (รูปภาพ + PDF)

path อยู่ใต้ `/finance/attachments/...` (segment ใหม่ ไม่ทับกลุ่มเดิม)
บริการจริงอยู่ใน `services/finance_attachments.py` — router ทำแค่ DI + map exception
"""
from typing import List, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from core.config import settings
from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import (
    FinanceAttachmentNotFoundError,
    ForbiddenError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
)
from models.finance_attachment_schemas import FinanceAttachmentListOut
from models.finance_schemas import SuccessResponse
from routers._common import get_audit_context
from services import finance_attachments as attachment_service

router = APIRouter()

OwnerType = Literal["transaction", "student_payment", "payment_event", "receipt"]


async def _read_upload_capped(upload: UploadFile) -> bytes:
    """อ่านไฟล์แบบจำกัดขนาด — ไม่ buffer ทั้งก้อนก่อนเช็ค (กันอัปไฟล์ยักษ์กินแรม replica)

    cap ที่เพดานกว้างสุด (PDF) ก่อน แล้ว service ตรวจเพดานจริงตามชนิดไฟล์อีกชั้น
    """
    limit = max(
        int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB),
        int(settings.MEDIA_DOCUMENT_SIZE_LIMIT_MB),
    ) * 1024 * 1024
    buf = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        if len(buf) + len(chunk) > limit:
            raise PayloadTooLargeError(
                f"ไฟล์ใหญ่เกิน {limit // (1024 * 1024)} MB"
            )
        buf.extend(chunk)
    return bytes(buf)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, FinanceAttachmentNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValidationError):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, PayloadTooLargeError):
        return HTTPException(status_code=413, detail=str(e))
    if isinstance(e, RateLimitError):
        return HTTPException(status_code=429, detail=str(e))
    return HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")


@router.post(
    "/{target_id}/finance/attachments/{owner_type}/{owner_id}",
    response_model=FinanceAttachmentListOut,
)
async def upload_finance_attachments(
    request: Request,
    owner_type: OwnerType,
    owner_id: int,
    files: List[UploadFile] = File(...),
    kind: Optional[str] = Form(None),
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        payload = []
        for upload in files:
            payload.append((upload.filename, await _read_upload_capped(upload)))
        return await attachment_service.upload_attachments(
            pool=pool,
            user_id=user_ctx["user_id"],
            room_id=room_id,
            owner_type=owner_type,
            owner_id=owner_id,
            files=payload,
            requested_kind=kind,
            client_source=client_source,
            actor_identifier=actor,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/{target_id}/finance/attachments/{owner_type}/{owner_id}",
    response_model=FinanceAttachmentListOut,
)
async def list_finance_attachments(
    owner_type: OwnerType,
    owner_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        return await attachment_service.list_attachments(
            pool=pool,
            user_id=user_ctx["user_id"],
            room_id=room_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
    except Exception as e:
        raise _err(e)


@router.delete(
    "/{target_id}/finance/attachments/{attachment_id}",
    response_model=SuccessResponse,
)
async def delete_finance_attachment(
    request: Request,
    attachment_id: str,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await attachment_service.delete_attachment(
            pool=pool,
            user_id=user_ctx["user_id"],
            room_id=room_id,
            attachment_id=attachment_id,
            client_source=client_source,
            actor_identifier=actor,
        )
    except Exception as e:
        raise _err(e)
