"""Re-export shim — โค้ดจริงถูกแยกไปที่ services/student/ ตามความรับผิดชอบ

เก็บไฟล์นี้ไว้เพื่อให้ import path เดิม (``from services.student_service import StudentService``)
ของ routers / tests ยังทำงานได้โดยไม่ต้องแก้ไข.

หมายเหตุ: re-export ``ActionService`` ไว้ด้วย เพราะ tests บางตัว patch
``services.student_service.ActionService.notify_*`` ผ่าน string path.
"""
from services.student import StudentService
from services.action_service import ActionService

__all__ = ["StudentService", "ActionService"]
