"""Re-export shim — โค้ดจริงถูกแยกไปที่ services/activity/ ตามความรับผิดชอบ

เก็บไฟล์นี้ไว้เพื่อให้ import path เดิม (``from services.activity_service import ActivityService``)
ของ routers / tests ยังทำงานได้โดยไม่ต้องแก้ไข.
"""
from services.activity import ActivityService

__all__ = ["ActivityService"]
