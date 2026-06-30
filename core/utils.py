import asyncpg
from fastapi import HTTPException

async def resolve_room_id(conn: asyncpg.Connection, server_id: int = None, room_id: int = None) -> int:
    """
    Helper function สำหรับดึง room_id ที่ถูกต้อง
    - ถ้าระบบเว็บส่ง room_id มาโดยตรง -> ใช้งานได้เลย
    - ถ้า Discord Bot ส่ง server_id มา -> ควานหา room_id จาก Database
    """
    if room_id:
        return room_id
        
    if server_id:
        r_id = await conn.fetchval(
            "SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", 
            server_id
        )
        if not r_id:
            raise HTTPException(status_code=404, detail="Room not found for this Discord server")
        return r_id
        
    raise HTTPException(status_code=400, detail="Must provide either room_id or server_id")