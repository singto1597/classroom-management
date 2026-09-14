"""ใบเสร็จ / ใบแจ้งหนี้ (finance_receipts) — F3

⚠️ ลำดับการประกาศ route: `/finance/receipts/batch` ประกาศ **ก่อน** route ที่มี path param
   ในตำแหน่งเดียวกัน (ตอนนี้ยังไม่มี `POST /finance/receipts/{...}` จึงยังไม่ชนกัน
   แต่กันไว้เพราะเป็นกับดักเดียวกับที่เตือนไว้ใน budgets.py — แก้ยากตอนเจอ)

   ⇒ `invoices`, `invoices/room`, `pdf` (สามเส้นทางใหม่) ถูกประกาศ **ก่อน** `POST /finance/receipts`
     ด้วยเหตุผลเดียวกัน: วันหนึ่งถ้ามีคนเพิ่ม `POST /finance/receipts/{receipt_no}` การประกาศ
     เส้นทาง static ไว้ก่อนคือสิ่งเดียวที่กันไม่ให้คำว่า "invoices" ถูกตีความเป็นเลขที่เอกสาร

⚠️ `receipt_no` เป็น **`str`** ไม่ใช่ `int` — เลขที่เอกสารมีรูปเป็น `REC-2569-0042`
   และถ้าประกาศเป็น int ตัว path จะ match ไม่ได้เลย (ได้ 422 ทุกครั้ง)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
import asyncpg
from datetime import date
from typing import List, Optional

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, ForbiddenError
from services.finance_service import FinanceService
from services.finance.constants import RECEIPT_NO_PATTERN
from services.finance.pdf import PdfRenderError

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()

# 🔒 path param ของเลขเอกสาร — pattern มาจาก constants ที่เดียวกับที่ใช้สร้างเลข
ReceiptNoPath = Path(..., pattern=RECEIPT_NO_PATTERN, description="เลขที่เอกสาร เช่น REC-2569-0042")


@router.post("/{target_id}/finance/receipts/batch", response_model=ReceiptBatchIssueResponse)
async def issue_receipts_batch(
    req: ReceiptBatchIssueRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_receipts_batch(
            pool=pool, payment_ids=req.payment_ids, doc_type=req.doc_type,
            note=req.note, user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/receipts/invoices", response_model=InvoiceBatchIssueResponse)
async def issue_invoices(
    req: ReceiptInvoiceIssueRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ออกใบแจ้งหนี้ **ยอดค้างรวมต่อคน** ให้กลุ่มนักเรียนที่เลือก (1 คน = 1 ใบ)

    🎯 ต่างจาก `POST /finance/receipts` (ใบเสร็จ): ที่นี่เลือก **"คน"** ไม่ใช่ "บิล"
       ⇒ ไม่รับ `payment_id` เลย (ดูเหตุผลใน `ReceiptInvoiceIssueRequest`)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_invoices(
            pool=pool, student_ids=req.student_ids, note=req.note,
            user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/receipts/invoices/room", response_model=InvoiceBatchIssueResponse
)
async def issue_room_invoices(
    req: ReceiptRoomInvoiceRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ออกใบแจ้งหนี้ **ทุกคนที่มียอดค้าง** ในห้อง — 1 คน = 1 ใบ

    ⚠️ เป็น **การเขียนจริงทุกคน** ไม่ใช่การแสดงตัวอย่าง: กดซ้ำ = กินเลข INV ชุดใหม่
       (ใบแจ้งหนี้เป็น point-in-time ⇒ พฤติกรรมนี้ถูกต้อง แต่ frontend ต้องเตือนก่อนยิง)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_invoices_for_room(
            pool=pool, note=req.note, user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{target_id}/finance/receipts/pdf")
async def download_combined_pdf(
    req: ReceiptCombinedPdfRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ดาวน์โหลดเอกสารหลายใบเป็น PDF **ไฟล์เดียว หน้าละใบ**

    ⚠️ `POST` ไม่ใช่ `GET` โดยเจตนา: เลขเอกสาร 100 ใบใส่ใน query string ไม่ได้ (URL ยาวเกิน)
       และการเลือกเอกสารเป็นการกระทำที่ผู้ใช้ประกอบขึ้น ไม่ใช่การอ่าน resource เดียว
    ⚠️ ไม่ประกาศ `response_model` — response เป็น binary stream (ดูหมายเหตุใน
       `download_receipt_pdf` ด้านล่าง)
    ⚠️ ใช้ `require_member` ไม่ใช่ `MANAGE_FINANCE` (เหมือน PDF ใบเดียว): การพิมพ์เอกสาร
       ที่มีอยู่แล้วคือการอ่าน — คนที่เปิดดูในหน้าจอได้ ก็พิมพ์ออกกระดาษได้
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_documents_pdf(
            pool=pool, receipt_nos=req.receipt_nos, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        # 400 = คำขอที่ผู้ใช้แก้เองได้ (เกินเพดาน 100 ฉบับ / ไม่ได้เลือกอะไรเลย)
        raise HTTPException(status_code=400, detail=str(e))
    except PdfRenderError as e:
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.post("/{target_id}/finance/receipts", response_model=ReceiptIssueResponse)
async def issue_receipt(
    req: ReceiptIssueRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.issue_receipt(
            pool=pool, payment_id=req.payment_id, doc_type=req.doc_type,
            transaction_id=req.transaction_id, note=req.note,
            user_name=req.user_name or "—",
            user_id=user_ctx["user_id"], client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/receipts", response_model=List[ReceiptListItem])
async def get_receipts(
    request: Request,
    start_date: Optional[date] = Query(None, description="วันเริ่ม (ค.ศ.) — กรองตามเวลาไทย"),
    end_date: Optional[date] = Query(None, description="วันสิ้นสุด (ค.ศ.) — กรองตามเวลาไทย"),
    # ⚠️ ต้องมี 'deposit' ด้วย ไม่งั้น chip "ใบรับเงินล่วงหน้า" บนหน้าทะเบียนได้ 422
    #    จาก router ก่อนถึง service — ตัว service (`get_receipts`) **ไม่มี whitelist**
    #    จึงมีด่านนี้ด่านเดียวที่บล็อก (ข่าวดี: ล้มดัง ไม่เงียบ)
    doc_type: Optional[str] = Query(None, pattern="^(receipt|invoice|deposit)$"),
    student_id: Optional[int] = Query(None, gt=0),
    include_voided: bool = Query(
        False, description="รวมเอกสารที่ถูกยกเลิก/ลบแล้ว (มุมมองตรวจสอบย้อนหลัง)"
    ),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_receipts(
            pool=pool, client_source=client_source, actor_identifier=actor,
            start_date=start_date, end_date=end_date, doc_type=doc_type, student_id=student_id,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], include_voided=include_voided,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/receipts/{receipt_no}", response_model=ReceiptDetailResponse)
async def get_receipt(
    request: Request,
    receipt_no: str = ReceiptNoPath,
    include_voided: bool = Query(
        False, description="ยอมอ่านเอกสารที่ถูกยกเลิกแล้ว (ใช้เมื่อต้องการตรวจสอบย้อนหลัง)"
    ),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_receipt(
            pool=pool, receipt_no=receipt_no, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"], include_voided=include_voided,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/receipts/{receipt_no}/pdf")
async def download_receipt_pdf(
    request: Request,
    receipt_no: str = ReceiptNoPath,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ดาวน์โหลดเอกสารเป็น PDF (เรนเดอร์ผ่าน Gotenberg)

    ⚠️ ไม่ประกาศ `response_model` โดยเจตนา — response เป็น binary stream ไม่ใช่ JSON
       (การใส่ response_model ที่นี่จะทำให้ FastAPI พยายาม serialize bytes เป็น JSON)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        pdf_bytes, filename = await FinanceService.render_receipt_pdf(
            pool=pool, receipt_no=receipt_no, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PdfRenderError as e:
        # 502 = "ผู้ให้บริการปลายทาง (Gotenberg) ใช้งานไม่ได้" — ไม่ใช่ความผิดของผู้ใช้
        # และไม่ใช่ 500 ที่แปลว่าโค้ดเราพัง ⇒ แยกให้ชัดเพื่อให้ debug ได้ตรงจุด
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")

    # filename* แบบ RFC 5987 รองรับชื่อไฟล์ที่มีอักขระนอก ASCII
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
