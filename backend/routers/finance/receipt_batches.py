"""📚 ชุดเอกสาร (Document Batch) — F5

⚠️ ลำดับการประกาศ route: `GET /finance/receipt-batches` (ไม่มี path param) **ต้องมาก่อน**
   `GET /finance/receipt-batches/{batch_id}` — มิฉะนั้น FastAPI จะพยายามแปลง path ที่ไม่มี
   ตัวแปรเป็น `batch_id` (กับดักเดียวกับ `routers/finance/receipts.py` และ `credits.py`)
   ⚠️ ไฟล์นี้ **ไม่มี** route ที่รับ `receipt_nos` ทาง query string โดยเจตนา — เลขที่เอกสาร
      ไปใน body ของ POST/PUT เท่านั้น ⇒ เลี่ยงกับดัก axios ที่ serialize array เป็น
      `receipt_nos[]=` ซึ่ง FastAPI มองไม่เห็นแล้วกลายเป็น 422 ที่อ่านไม่ออก

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`

🔒 สิทธิ์: อ่าน = `require_member` (service) · เขียน = `MANAGE_FINANCE` (service)
   ⚠️ **ไม่มีการเช็คสิทธิ์ในไฟล์นี้เลย** ตามกฎ "RBAC อยู่ใน service เท่านั้น"
"""
from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from typing import List

from models.finance_schemas import (
    ReceiptBatchResponse, ReceiptBatchDetailResponse, ReceiptBatchCreate,
    ReceiptBatchSetReceipts, ReceiptBatchUpdate, ReceiptBatchMutationResponse,
    ReceiptBatchDissolveResponse,
)
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


# 🔴 ต้องประกาศ **ก่อน** `/{batch_id}` — ดูคำเตือนบนหัวไฟล์
@router.get(
    "/{target_id}/finance/receipt-batches", response_model=List[ReceiptBatchResponse]
)
async def list_receipt_batches(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ชุดเอกสารทั้งหมดของห้อง (ใหม่สุดก่อน)

    ⚠️ ชุดที่สมาชิกทุกใบถูกยกเลิก/ลบไปแล้วจะ **ไม่** ถูกคืน — ชุดที่กดเข้าไปแล้วว่าง
       ทำให้ผู้ใช้อ่านไม่ออกว่าเกิดอะไรขึ้น (เหตุผลอยู่ใน service)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_receipt_batches(
            pool=pool, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{target_id}/finance/receipt-batches/{batch_id}",
    response_model=ReceiptBatchDetailResponse,
)
async def get_receipt_batch(
    batch_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """รายละเอียดชุด + เอกสารทุกใบในชุด (**รวมใบที่ถูกยกเลิก** โดยเจตนา)

    ใบที่ถูกยกเลิกต้องอยู่ในลิสต์: ถ้ากรองออก จำนวนที่กางดูจะไม่ตรงกับ `voided_count`
    ที่ทะเบียนบอก ⇒ ผู้ใช้เห็น "ยกเลิก 3" แต่ในชุดมีแค่ 17 ใบ
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_receipt_batch_detail(
            pool=pool, batch_id=batch_id, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{target_id}/finance/receipt-batches",
    response_model=ReceiptBatchMutationResponse,
)
async def create_receipt_batch(
    req: ReceiptBatchCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """จัดกลุ่มเอกสารที่ติ๊กเลือกเป็นชุดใหม่ (MANAGE_FINANCE)

    🔁 **กดซ้ำปลอดภัย**: ถ้ามีชุดที่สมาชิกชุดเดียวกันเป๊ะอยู่แล้ว จะคืนชุดนั้นพร้อม
       `created=false` โดยไม่สร้างใหม่ ⇒ ไม่ต้องมี idempotency key จาก client
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_receipt_batch(
            pool=pool, req=req, client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/{target_id}/finance/receipt-batches/{batch_id}/receipts",
    response_model=ReceiptBatchMutationResponse,
)
async def set_batch_receipts(
    batch_id: int,
    req: ReceiptBatchSetReceipts,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """**ตั้งสมาชิกทั้งชุด** (ไม่ใช่ "เพิ่มเข้า") — ใบที่หายจากลิสต์จะถูกถอดออก (MANAGE_FINANCE)

    ⚠️ ใบที่ถูกย้ายมาจากชุดอื่นจะหลุดจากชุดเดิม (1 ใบอยู่ได้ชุดเดียว) — ตั้งใจ
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.set_batch_receipts(
            pool=pool, batch_id=batch_id, req=req, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch(
    "/{target_id}/finance/receipt-batches/{batch_id}",
    response_model=ReceiptBatchMutationResponse,
)
async def update_receipt_batch(
    batch_id: int,
    req: ReceiptBatchUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """เปลี่ยนชื่อ/โน้ตของชุด (MANAGE_FINANCE) — ส่งมาแค่ฟิลด์ที่จะแก้"""
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_receipt_batch(
            pool=pool, batch_id=batch_id, req=req, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{target_id}/finance/receipt-batches/{batch_id}",
    response_model=ReceiptBatchDissolveResponse,
)
async def delete_receipt_batch(
    batch_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ยุบชุด (MANAGE_FINANCE) — **เอกสารไม่ถูกแตะเลย** แค่หลุดออกจากชุด

    ⚠️ ไม่ใช่ "ลบเอกสาร": ใบเสร็จทุกใบยัง `status='active'` และยอด/เลขที่เดิมครบ
       (เทสต์ตรวจข้อนี้กับ DB ตรง ๆ)
    """
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.delete_receipt_batch(
            pool=pool, batch_id=batch_id, client_source=client_source,
            actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
