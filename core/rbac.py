import json
import os
from typing import Dict, List
import asyncpg
from core.exceptions import ForbiddenError
from core.config import settings

class RBACManager:
    _roles_config: Dict[str, List[str]] = {}

    @classmethod
    def load_roles(cls):
        """โหลดไฟล์ roles.json ครั้งเดียวและ Cache ไว้"""
        if not cls._roles_config:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "roles.json")
            
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cls._roles_config = json.load(f)
            except FileNotFoundError:
                cls._roles_config = {}
        return cls._roles_config

    @classmethod
    def has_permission(cls, role: str, permission: str) -> bool:
        roles_with_permission = cls.load_roles().get(permission, [])
        return role in roles_with_permission

async def require_permission(conn: asyncpg.Connection, room_id: int, user_id: int, required_permission: str):
    """
    ฟังก์ชันเช็คสิทธิ์แบบ Async
    - 🚨 เปลี่ยนจากรับ discord_id มาใช้ user_id แบบ 100%
    """
    
    # 1. เช็ค Super Admin (God Mode)
    if settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID):
        return True

    # 2. Query ดึงค่า class_role จากตาราง students
    query = """
        SELECT class_role 
        FROM students 
        WHERE room_id = $1 
          AND user_id = $2 
          AND status = 'active' 
          AND deleted_at IS NULL
    """
    row = await conn.fetchrow(query, room_id, int(user_id))
    
    if not row:
        raise ForbiddenError("Access Denied: ไม่พบข้อมูลนักเรียน หรือบัญชีของคุณถูกระงับ")
    
    user_role = row['class_role']
    
    # 3. ตรวจสอบสิทธิ์ใน RBAC Engine
    if not user_role or not RBACManager.has_permission(user_role, required_permission):
        raise ForbiddenError(f"Access Denied: สิทธิ์ของคุณ ({user_role or 'student'}) ไม่เพียงพอสำหรับทำรายการนี้")
    
    return True