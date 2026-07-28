"""Audit log helper — บันทึกลง `audit_logs` ภายใน transaction เดียวกับ mutation."""

import asyncpg


async def log_action(
    conn: asyncpg.Connection,
    room_id: int,
    user_name: str,
    action: str,
    detail: str,
) -> None:
    await conn.execute(
        "INSERT INTO audit_logs (room_id, user_name, action, detail) VALUES ($1, $2, $3, $4)",
        room_id,
        user_name,
        action,
        detail,
    )
