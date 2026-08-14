import json
import asyncpg
from core.exceptions import ForbiddenError
from core.config import settings

# 💡 กำหนดรายการสิทธิ์ทั้งหมดที่มีในระบบ (เก็บเป็น List ไว้ดูอ้างอิง)
# เวลามีการมอบหมายสิทธิ์ให้ใคร ระบบจะเก็บค่าพวกนี้ลงในช่อง permissions (JSONB)
AVAILABLE_PERMISSIONS = [
    "VIEW_ALL_STUDENTS",
    "MANAGE_STUDENTS",
    "EXPORT_STUDENTS",
    "HARD_DELETE_STUDENTS",
    "MANAGE_FINANCE",
    "MANAGE_CLASSROOM_SETTINGS",
    "MANAGE_CLASSROOM_TASKS",
    "MANAGE_ACTIVITIES"
]

async def require_member(conn: asyncpg.Connection, room_id: int, user_id: int):
    """
    🔍 Membership check (ใช้สำหรับข้อมูลที่ต้องการความโปร่งใส เช่น Finance GET)
    - เช็คว่า user เป็นสมาชิก active ของห้องนี้หรือไม่
    - กันการอ่านข้อมูลข้ามห้อง (cross-room data leak) โดยไม่ต้องมี permission เฉพาะ
    - Super Admin ผ่านฉลุย
    """
    if settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID):
        return True

    row = await conn.fetchval(
        "SELECT 1 FROM students WHERE room_id = $1 AND user_id = $2 AND status = 'active' AND deleted_at IS NULL",
        room_id, int(user_id)
    )
    if not row:
        raise ForbiddenError("คุณไม่ได้เป็นสมาชิกที่ใช้งานอยู่ในห้องเรียนนี้")

    return True

async def require_permission(conn: asyncpg.Connection, room_id: int, user_id: int, required_permission: str):
    """
    ระบบเช็คสิทธิ์ (Granular RBAC) รูปแบบใหม่
    - ไม่สนใจ class_role (ป้ายชื่อ) อีกต่อไป
    - เช็คจาก is_admin (ผ่านฉลุย) และฟิลด์ permissions (แบบรายตัว)
    """
    
    # 1. เช็ค Super Admin (God Mode ระดับ Server - คนถือ Config)
    if settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID):
        return True

    # 2. Query ดึงค่า is_admin และ permissions ออกมาจากตาราง students
    query = """
        SELECT is_admin, permissions, status
        FROM students 
        WHERE room_id = $1 
          AND user_id = $2 
          AND deleted_at IS NULL
    """
    row = await conn.fetchrow(query, room_id, int(user_id))
    
    if not row:
        raise ForbiddenError("Access Denied: ไม่พบข้อมูลของคุณในห้องเรียนนี้")
        
    if row['status'] != 'active':
        raise ForbiddenError("Access Denied: บัญชีของคุณในห้องนี้ยังไม่ได้รับการอนุมัติ หรือถูกระงับ")

    is_admin = row['is_admin']
    
    # 3. 🛡️ เช็คระดับ 1 (God Mode ของห้อง): ถ้าเป็น Admin คือข้ามการเช็คสิทธิ์ย่อยไปเลย ทำได้ทุกอย่าง!
    if is_admin:
        return True

    # 4. 🛡️ เช็คระดับ 2 (Custom Mode): ถ้าไม่ใช่ Admin ให้เช็คจาก Array สิทธิ์ย่อย (permissions)
    user_permissions = []
    raw_perms = row['permissions']
    
    if raw_perms:
        if isinstance(raw_perms, str):
            try:
                user_permissions = json.loads(raw_perms)
            except json.JSONDecodeError:
                user_permissions = []
        else:
            # กรณีที่ asyncpg แปลง JSONB กลับมาเป็น List Python ให้อัตโนมัติ
            user_permissions = raw_perms
    
    # ถ้าสิทธิ์ที่ต้องการ (required_permission) ไม่มีใน Array ของ User คนนี้ ให้ดีดออกทันที
    if required_permission not in user_permissions:
        raise ForbiddenError(f"Access Denied: คุณไม่มีสิทธิ์ '{required_permission}'")
    
    return True