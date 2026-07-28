import json
import time
import uuid
import asyncpg
from typing import Optional, Dict, Any

class AuditLogger:
    def __init__(self, service_name: str):
        self.service_name = service_name

    async def log(
        self,
        conn: asyncpg.Connection,
        action: str,
        actor_identifier: str,
        client_source: str,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        status: str = 'success',
        error_detail: Optional[str] = None,
        old_values: Optional[Dict] = None,
        new_values: Optional[Dict] = None,
        endpoint_or_command: Optional[str] = None,
        ip_address: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
        trace_id: Optional[str] = None
    ):
        # ถ้าไม่มี Trace ID ให้สร้างใหม่
        current_trace_id = trace_id or str(uuid.uuid4())
        
        await conn.execute("""
            INSERT INTO audit_logs (
                trace_id, room_id, user_id, actor_identifier, client_source, 
                service_name, action, entity_type, entity_id, status, 
                error_detail, old_values, new_values, endpoint_or_command, 
                ip_address, execution_time_ms
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14, $15, $16)
        """, 
            current_trace_id, room_id, user_id, actor_identifier, client_source,
            self.service_name, action, entity_type, str(entity_id) if entity_id else None,
            status, error_detail, 
            json.dumps(old_values, default=str) if old_values else None,
            json.dumps(new_values, default=str) if new_values else None,
            endpoint_or_command, ip_address, execution_time_ms
        )