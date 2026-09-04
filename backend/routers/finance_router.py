"""Re-export shim — โค้ดจริงถูกแยกไปที่ routers/finance/ ตาม resource

เก็บไฟล์นี้ไว้เพื่อให้ ``from routers import finance_router`` + ``finance_router.router``
ใน main.py ยังทำงานได้โดยไม่ต้องแก้ไข.
"""
from routers.finance import router

__all__ = ["router"]
