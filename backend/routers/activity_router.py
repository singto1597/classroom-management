"""Re-export shim — โค้ดจริงถูกแยกไปที่ routers/activity/ ตาม resource

เก็บไฟล์นี้ไว้เพื่อให้ ``from routers import activity_router`` + ``activity_router.router``
ใน main.py ยังทำงานได้โดยไม่ต้องแก้ไข.
"""
from routers.activity import router

__all__ = ["router"]
