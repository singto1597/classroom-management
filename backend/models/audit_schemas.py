"""Pydantic schemas ของหน้าดูบันทึกกิจกรรม (P6.2)

🎯 หน้าดูนี้มีไว้ให้ **ประธาน/รอง/เลขา** ตรวจย้อนว่าใครทำอะไรกับข้อมูลห้อง
⇒ คืนค่า "ดิบ" ที่อยู่ใน `audit_logs` (ไม่แปลงเป็นข้อความไทย) เพราะผู้ใช้กลุ่มนี้
สืบเหตุ ต้องเห็น `action`/`entity_type` ตรง ๆ ว่าตารางไหนถูกแตะ

⚠️ `old_values`/`new_values` เป็น JSONB ที่อาจเป็นได้ทั้ง object และ array
⇒ ใช้ `Any` ไม่ใช่ `dict` (ถ้าใครสักคน log เป็น list Pydantic จะตอบ 500 ทั้งหน้า)

⚠️ `cursor` เป็นสตริงทึบ (base64 ของ `created_at|id`) ไม่ใช่ offset — ดู
`services/audit_service.py` ว่าทำไม offset ใช้กับตารางที่เพิ่มแถวตลอดเวลาไม่ได้
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AuditLogOut(BaseModel):
    id: UUID
    trace_id: Optional[str] = None
    user_id: Optional[int] = None
    actor_identifier: str
    actor_name: Optional[str] = Field(
        None, description="ชื่อ-นามสกุลจาก users (None ถ้า user ถูกลบหรือไม่มีแถว)"
    )
    client_source: str
    service_name: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    status: Optional[str] = None
    error_detail: Optional[str] = None
    old_values: Optional[Any] = None
    new_values: Optional[Any] = None
    endpoint_or_command: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    execution_time_ms: Optional[int] = None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut] = Field(default_factory=list)
    next_cursor: Optional[str] = Field(
        None, description="ส่งกลับมาเป็น `cursor` เพื่อขอหน้าถัดไป — None = หมดแล้ว"
    )
    has_more: bool = False


class AuditLogOptions(BaseModel):
    """ค่าที่มีอยู่จริงในข้อมูล ใช้เติมตัวเลือกในตัวกรอง (ไม่เดาจากโค้ด)"""

    service_names: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
