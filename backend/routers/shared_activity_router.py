"""🔗 หน้าสาธารณะของกิจกรรม (P4.3) — อ่านด้วยโทเคนเท่านั้น ไม่ต้องล็อกอิน

**ทำไมแยก router:** ทุก route ใต้ `/api/classroom` บังคับ `get_current_user` และต้องมี
`target_id` ของห้อง — หน้าลิงก์แชร์ไม่รู้ทั้งสองอย่าง (คนเปิดลิงก์คือผู้ปกครองที่ไม่มีบัญชี)
จึงต้องมี namespace ของตัวเองที่ **ไม่มี auth dependency** และถูกประกาศใน
`tests/test_route_auth_audit.py::PUBLIC_ROUTES` พร้อมเหตุผล

**มาตรการความปลอดภัยที่ยึดไว้:**
- ไม่คืนข้อมูลส่วนบุคคลใด ๆ (ไม่มีรายชื่อ/เบอร์/โปรไฟล์) — ดู `services/activity/share.py`
- โทเคนสั้นกว่า 128 ตัวอักษรและมาจาก `secrets.token_urlsafe(32)` ⇒ เดาไม่ได้
- กิจกรรม/ห้องที่ถูกลบ = 404 ทันที (ลิงก์เก่าไม่ค้างข้อมูลที่ถูกถอด)
- ไม่เปิด CORS เพิ่ม: หน้าเว็บฝั่งเราอ่านผ่าน proxy เดียวกัน
"""
from fastapi import APIRouter, Depends, HTTPException, Response
import asyncpg

from core.dependencies import get_db_pool
from core.exceptions import ActivityNotFoundError
from core.rate_limit import rate_limit
from models.activity_schemas import SharedActivityResponse
from services.activity_service import ActivityService

router = APIRouter()


# 🚦 [P6.3] 60 ครั้ง/นาที/IP — endpoint เดียวในระบบที่ไม่มี auth เลย (ดู core/rate_limit.py)
@router.get(
    "/activity/{token}",
    response_model=SharedActivityResponse,
    summary="ดูกิจกรรมด้วยลิงก์แชร์ (อ่านอย่างเดียว ไม่ต้องล็อกอิน)",
    dependencies=[rate_limit("shared_activity")],
)
async def get_shared_activity(
    token: str,
    response: Response,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    try:
        data = await ActivityService.get_shared_activity(pool=pool, token=token)
    except ActivityNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # ข้อมูลอาจถูกแก้/เพิกถอนได้ทุกเมื่อ ⇒ ห้ามแคชที่ CDN (Cloudflare อยู่หน้าเว็บเรา)
    response.headers["Cache-Control"] = "no-store"
    return data
