"""Re-export shim — โค้ดจริงถูกแยกไปที่ services/classroom_sync/ ตามความรับผิดชอบ

เก็บไฟล์นี้ไว้เพื่อให้ import path เดิม (``from services.classroom_sync_service import ClassroomService``)
ของ routers / tests ยังทำงานได้โดยไม่ต้องแก้ไข.

หมายเหตุ: re-export ``THAI_TZ`` (tests import โดยตรง) และ ``ActionService``
(tests บางตัว patch ``services.classroom_sync_service.ActionService.notify_*``) ไว้ด้วย.
"""
from services.classroom_sync import ClassroomService, THAI_TZ
from services.action_service import ActionService

__all__ = ["ClassroomService", "THAI_TZ", "ActionService"]
