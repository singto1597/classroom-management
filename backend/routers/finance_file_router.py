"""📎 เสิร์ฟไฟล์หลักฐานการเงินด้วย signed URL — **ไม่มี auth dependency**

⭐ ทำไมไม่มี `get_current_user`: `<img src>`/แท็บ PDF ใหม่ส่ง Authorization header ไม่ได้
   ⇒ ฝังลายเซ็นใน URL (ดู `core/media_signing.py`) แล้ว **ตรวจสิทธิ์ซ้ำทุก GET** ใน
   `resolve_attachment_for_serving` ด้วย viewer_id ที่ลายเซ็นผูกไว้

🔒 headers: `Cache-Control: private` (ห้าม CDN/edge แคชไฟล์ส่วนตัว) ·
   PDF ได้ `Content-Security-Policy: sandbox` เพิ่มเพื่อกันสคริปต์ในไฟล์
"""
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.dependencies import get_db_pool
from core.exceptions import (
    FinanceAttachmentNotFoundError,
    ForbiddenError,
)
from core.media import MediaStorageError
from services import finance_attachments as attachment_service

router = APIRouter(tags=["Finance Files"])


@router.get("/finance-files/{attachment_id}")
async def serve_finance_attachment(
    attachment_id: str,
    variant: Optional[str] = None,
    viewer: Optional[str] = None,
    exp: Optional[str] = None,
    sig: Optional[str] = None,
    download: Optional[str] = None,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    # ⚠️ query param เป็น Optional[str] โดยเจตนา: ค่าเสียรูปต้องได้ 403 เหมือนลายเซ็นผิด
    #    (ไม่ใช่ 422 ที่แยกรูปแบบฟิลด์ให้ผู้โจมตีเห็น)
    try:
        row, path = await attachment_service.resolve_attachment_for_serving(
            pool, attachment_id, variant, viewer, exp, sig
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FinanceAttachmentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MediaStorageError:
        raise HTTPException(status_code=500, detail="ระบบจัดเก็บไฟล์ขัดข้อง")

    return FileResponse(
        path,
        media_type=row["mime"] or "application/octet-stream",
        headers=attachment_service.attachment_headers(
            row, download=download in ("1", "true")
        ),
    )
