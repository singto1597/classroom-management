"""HTTP layer ของหน้าดูบันทึกกิจกรรม (P6.2)

- `GET /{target_id}/audit-logs`          — รายการแบบเลื่อนหน้า (keyset) + ตัวกรอง
- `GET /{target_id}/audit-logs/options`  — ค่าที่มีจริงสำหรับเติม dropdown

🔒 ทั้งคู่ต้องมี `VIEW_AUDIT_LOGS` (ตรวจใน service ในทรานแซกชันเดียวกับการอ่าน)
ไม่ใช่แค่ `require_member` — ในบันทึกมี IP/User-Agent/ค่าก่อน-หลังของข้อมูล

⚠️ ห้ามส่ง `ip_address=` เอง — middleware ตั้งบริบทให้แล้ว (P6.1)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import ForbiddenError, ValidationError
from models.audit_schemas import AuditLogOptions, AuditLogPage
from routers._common import get_audit_context
from services import audit_service

router = APIRouter()


@router.get("/{target_id}/audit-logs", response_model=AuditLogPage)
async def list_audit_logs(
    request: Request,
    # ⚠️ ตัวกรองต้องเป็น `date` ไม่ใช่ `str` (กติกาทั้งระบบ) — FastAPI แปลงให้เอง
    #    และตอบ 422 อ่านรู้เรื่องถ้าส่งวันที่ที่ไม่มีจริง เช่น 2026-02-30
    date_from: Optional[date] = Query(None, description="เริ่มต้น (ตามเวลาไทย, รวมวันนั้น)"),
    date_to: Optional[date] = Query(None, description="สิ้นสุด (ตามเวลาไทย, รวมวันนั้น)"),
    service_name: Optional[str] = Query(None, max_length=50),
    action: Optional[str] = Query(None, max_length=50),
    status: Optional[str] = Query(None, max_length=20),
    q: Optional[str] = Query(None, max_length=100, description="ค้นในผู้ทำ/endpoint/entity/ข้อผิดพลาด"),
    limit: int = Query(audit_service.DEFAULT_LIMIT, ge=1, le=audit_service.MAX_LIMIT),
    cursor: Optional[str] = Query(None, max_length=200),
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        return await audit_service.list_logs(
            pool,
            room_id=room_id,
            user_id=int(user_ctx.get("user_id")),
            client_source=client_source,
            actor_identifier=actor,
            service_name=service_name,
            action=action,
            status=status,
            search=q,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            cursor=cursor,
        )
    except ValidationError as exc:
        # cursor ที่พิมพ์มือ/ถูกตัดขาด — 400 ไม่ใช่ 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{target_id}/audit-logs/options", response_model=AuditLogOptions)
async def list_audit_log_options(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        return await audit_service.get_options(
            pool, room_id=room_id, user_id=int(user_ctx.get("user_id"))
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
