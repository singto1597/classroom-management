"""สัญญาของ storage layer สำหรับไฟล์หลักฐานการเงิน — ใช้ `Protocol` ไม่ใช่ abstract class

⭐ **ทำไม Protocol:** service ไม่ต้อง import คลาสจริงเลย (แค่ print type) ⇒ เทสต์สามารถ
   ส่ง fake storage เข้า `finance_attachments` ได้โดยไม่ต้องสืบทอดอะไร และการย้ายไป S3/R2
   ต้องแก้แค่ adapter ไม่แตะ service

⚠️ **ทุก method ที่แตะ I/O เป็น async** (แม้ local จะเรียก blocking I/O ข้างในผ่าน
   `asyncio.to_thread`) — เพราะ storage ปลายทางในอนาคตเป็น network call ซึ่ง **ห้าม**
   ถูกเรียกแบบ blocking ใน event loop ของ FastAPI

📦 **สองชนิดไฟล์ที่รับ:**
   - รูป → `{uuid}.webp` (ไฟล์เต็ม) + `{uuid}_thumb.webp` (thumbnail)
   - PDF → `{uuid}.pdf` (ไม่มี thumbnail)
"""
import re
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol, runtime_checkable

# 🔑 รูปแบบ key ที่ทั้งระบบยอมรับ — ตรวจ **ก่อน** แตะดิสก์ทุกครั้ง
#   media/finance/{owner_type}/{owner_id}/{uuid}.webp        → รูปหลักฐาน
#   media/finance/{owner_type}/{owner_id}/{uuid}_thumb.webp  → thumbnail ของรูป
#   media/finance/{owner_type}/{owner_id}/{uuid}.pdf         → ไฟล์ PDF หลักฐาน
#
# ⚠️ ไม่รับ subfolder อื่น (เช่น tmp/) — tmp ใช้ภายใน LocalMediaStorage เท่านั้น
#    และไม่เคยถูกอ้างจาก DB ⇒ ถ้า storage_path ใน DB หลุดมาเป็น `../../etc/passwd`
#    (หรือแถวถูกแก้โดยใครก็ตาม) pattern นี้จะปฏิเสธก่อนเปิดไฟล์
# ⚠️ owner_type **เขียนเป็น alternation ของค่าที่รู้จัก** ไม่ใช่ `[a-z_]+` —
#    ชนิดเจ้าของที่ไม่มี policy ต้องสร้าง key ไม่ได้ตั้งแต่ต้น (fail-closed)
_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
FINANCE_OWNER_TYPES = ("transaction", "student_payment", "payment_event", "receipt")
_OWNERS = rf"(?:{'|'.join(FINANCE_OWNER_TYPES)})"
KEY_PATTERN = re.compile(
    rf"^(?:media/finance/{_OWNERS}/\d+/{_UUID_RE}(?:_thumb)?\.webp"
    rf"|media/finance/{_OWNERS}/\d+/{_UUID_RE}\.pdf)$"
)

MAX_KEY_LENGTH = 200


class MediaStorageError(Exception):
    """storage ล้มเหลว (เขียน/อ่าน/ลบ) หรือ key/backend ไม่ถูกต้อง — กลายเป็น 500 ที่ router"""


def is_valid_key(key: str) -> bool:
    return (
        isinstance(key, str)
        and 0 < len(key) <= MAX_KEY_LENGTH
        and KEY_PATTERN.match(key) is not None
    )


@runtime_checkable
class MediaStorage(Protocol):
    async def write(self, key: str, data: bytes) -> None:
        """เขียนไฟล์ทั้งก้อน — ต้อง **atomic** (ผู้อ่านเห็นไฟล์เก่าหรือครบทั้งไฟล์ ไม่เห็นครึ่ง ๆ)"""
        ...

    def read_stream(self, key: str) -> AsyncIterator[bytes]:
        """อ่านเป็น chunk — ใช้กับ backend ที่ไม่ใช่ local / กรณีไม่ต้องการ buffer ทั้งไฟล์"""
        ...

    def local_path(self, key: str) -> Optional[Path]:
        """path บนดิสก์ถ้า backend นี้เป็น local (สำหรับ FileResponse ที่ส่งแบบ zero-copy)

        คืน `None` = ต้องใช้ `read_stream()` แทน · ⚠️ **path ที่คืนต้องอยู่ใต้ root เสมอ**
        (ตรวจ containment แล้ว) และอาจเป็นไฟล์ที่ไม่มีอยู่จริง — ผู้เรียกต้องเช็ค `exists()`
        """
        ...

    async def delete(self, key: str) -> None:
        """ลบไฟล์ — **idempotent**: ไฟล์ไม่มีอยู่แล้วต้องไม่ error"""
        ...

    async def exists(self, key: str) -> bool:
        ...
