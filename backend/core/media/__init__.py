"""🗂️ Storage layer ของไฟล์หลักฐานการเงิน — แยก interface จาก implementation

⭐ **ทำไมต้องมี interface ตั้งแต่เฟสแรก ทั้งที่วันนี้มีแค่ local disk**

   ตัวที่ราคาแพงของการย้าย storage ไม่ใช่การเขียน `write()` ใหม่ — แต่คือ **ทุก service
   ที่เรียกมันอยู่** (finance_attachments รู้เส้นทางไฟล์, purge script เดินบนดิสก์,
   backup tar volume ตรง ๆ) ⇒ ถ้า service เรียก `open(path, "rb")` ตรง ๆ วันที่จะย้าย
   ไป S3/R2 จะต้องแก้ทุกจุดพร้อมกันและเทสต์ใหม่ทั้งหมด

   ⇒ service เรียกผ่าน `MediaStorage` เท่านั้น · `local_path()` คือ **ทางลัดที่ระบุชัดว่า
     "ถ้าเป็น local จะได้ path ไปเสิร์ฟได้ไว"** — backend ที่ไม่ใช่ local คืน `None`
     แล้วผู้เรียกต้อง fall back ไป `read_stream()`

⚠️ **key ไม่ใช่ path** — `media/finance/{owner_type}/{owner_id}/{uuid}.webp|.pdf`
   ใช้ร่วมได้ทุก backend (S3 ใช้ key นี้เป็น object key ตรง ๆ) ห้ามใส่ `/` นำหน้า ห้าม `..`
   — LocalMediaStorage ตรวจ pattern + containment ก่อนแตะดิสก์ทุกครั้ง
"""
from core.config import settings
from core.media.base import MediaStorage, MediaStorageError
from core.media.local import LocalMediaStorage

__all__ = ["MediaStorage", "MediaStorageError", "LocalMediaStorage", "get_media_storage"]

# 🏭 cache ต่อ (backend, dir) — ไม่ใช่ singleton ตัวเดียว เพราะเทสต์สลับ
# `settings.MEDIA_STORAGE_DIR` ไป temp dir ต่อ session แล้วต้องได้ instance ใหม่
_storage_cache: dict[tuple[str, str], MediaStorage] = {}


def get_media_storage() -> MediaStorage:
    """คืน storage ตาม `MEDIA_STORAGE_BACKEND` (default: local)

    ⚠️ backend อื่น (s3/r2) **ยังไม่ implement** — raise ตั้งแต่ต้นแทนที่จะเงียบ ๆ
       ตกลงมาใช้ local ผิด ๆ (จะได้รู้ตอนบูต ไม่ใช่ตอนผู้ใช้อัปไฟล์แล้วหาไฟล์ไม่เจอ)
    """
    backend = (settings.MEDIA_STORAGE_BACKEND or "local").strip().lower()
    key = (backend, settings.MEDIA_STORAGE_DIR)
    cached = _storage_cache.get(key)
    if cached is not None:
        return cached
    if backend == "local":
        storage: MediaStorage = LocalMediaStorage(settings.MEDIA_STORAGE_DIR)
    else:
        raise MediaStorageError(
            f"MEDIA_STORAGE_BACKEND='{backend}' ยังไม่รองรับ "
            "(ตอนนี้มีเฉพาะ 'local' — เพิ่ม adapter ใน core/media/ ก่อน)"
        )
    _storage_cache[key] = storage
    return storage
