"""ตัวช่วยร่วมของ routers — TargetResolution / get_target / get_audit_context.

ย้ายมาจาก finance_router / student_router / ... ที่เคย copy กันไว้ (7 ไฟล์)
เพื่อให้มี source of truth ไฟล์เดียว.
"""
from typing import Literal, Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel

from core.config import settings
from core.request_context import (
    current_request_audit_context,
    resolve_client_ip,
)


class TargetResolution(BaseModel):
    server_id: Optional[int] = None
    room_id: Optional[int] = None


def get_target(
    target_id: int = Path(...),
    target_type: Literal["server", "room"] = Query("room", description="ระบุประเภทไอดีว่าเป็น server หรือ room (default=room สำหรับ web)"),
) -> TargetResolution:
    return TargetResolution(
        server_id=target_id if target_type == "server" else None,
        room_id=target_id if target_type == "room" else None,
    )


def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    """คืน `(client_source, actor_identifier)` สำหรับส่งเข้า service

    🌐 [P6.1] `ip` ใช้ตัวแก้ค่าเดียวกับ middleware (`resolve_client_ip`) เพื่อไม่ให้
    `actor_identifier` ของคำขอที่ไม่มีล็อกอินบันทึก IP ของ **Traefik** ทับทุกคน
    — เดิม `request.client.host` คือ IP ของ proxy ⇒ `ip:172.20.0.5` เหมือนกันหมด
    และไม่มีประโยชน์ในการสืบเหตุ

    ใช้ค่าที่ middleware คำนวณไว้ก่อน (กันการคำนวณซ้ำและกันสองทางตีกันเอง)
    แล้วค่อยคำนวณสดเมื่อถูกเรียกนอก middleware (เช่น unit test)
    """
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ctx = current_request_audit_context()
    if ctx is not None and ctx.ip_address:
        ip = ctx.ip_address
    else:
        ip = resolve_client_ip(
            request.client.host if request.client else None,
            request.headers,
            settings.TRUSTED_PROXY_HOPS,
        ) or "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier
