"""ตัวช่วยร่วมของ routers — TargetResolution / get_target / get_audit_context.

ย้ายมาจาก finance_router / student_router / ... ที่เคย copy กันไว้ (7 ไฟล์)
เพื่อให้มี source of truth ไฟล์เดียว.
"""
from typing import Literal, Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel


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
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier
