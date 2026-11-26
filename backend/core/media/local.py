"""LocalMediaStorage — เก็บไฟล์หลักฐานบน named volume (`/data/media`) ของเครื่องเดียว

⭐ **เขียนแบบ atomic: tmp → `os.replace()`**
   `os.replace` เป็น rename ภายใน filesystem เดียว ⇒ ผู้อ่านเห็นได้แค่ "ไม่มีไฟล์"
   หรือ "ไฟล์ครบ" ไม่มีทางเห็นไฟล์ครึ่งเดียว
   ⚠️ นี่คือเหตุผลที่ `tmp/` ต้องอยู่ **ใต้ root เดียวกัน** — ข้าม filesystem แล้ว
     `os.replace` จะกลายเป็น copy+delete ซึ่งไม่ atomic

⚠️ **local driver ผูกกับ node เดียว** — single-node Swarm ปัจจุบันโอเค
   ถ้าขยาย multi-node ต้องเปลี่ยน `MEDIA_STORAGE_BACKEND` ไป S3/R2 (service ไม่ต้องแก้)

🔒 ทุก method เรียก `_safe_path()` ก่อนแตะดิสก์: ตรวจ pattern + containment
   (`resolve()` แล้วต้องอยู่ใต้ root) ⇒ แถว DB ที่ถูกแก้เป็น `../../etc/passwd`
   เปิดไฟล์ไม่ได้แม้แต่ครั้งเดียว
"""
import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from core.media.base import MediaStorageError, is_valid_key

logger = logging.getLogger("API_MEDIA")

# ขนาด chunk ตอน stream — 64KB พอดีกับ read-ahead ของ kernel และไม่กิน memory ต่อ request
READ_CHUNK = 64 * 1024


class LocalMediaStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.tmp_dir = self.root / "tmp"

    # ---------- ภายใน ----------
    def _safe_path(self, key: str) -> Path:
        """key → path ที่อยู่ใต้ root แน่นอน (raise ถ้าไม่ผ่าน)"""
        if not is_valid_key(key):
            raise MediaStorageError("path ของไฟล์ไม่ถูกต้อง")
        path = (self.root / key).resolve()
        # ⚠️ ใช้ commonpath ไม่ใช่ startswith: `/data/media2` ขึ้นต้นด้วย `/data/media`
        #    เหมือนกัน ⇒ startswith จะปล่อยให้หลุดออกไปนอก root
        if os.path.commonpath([str(self.root), str(path)]) != str(self.root):
            raise MediaStorageError("path ของไฟล์ออกนอกโฟลเดอร์จัดเก็บ")
        return path

    @staticmethod
    def _write_sync(path: Path, tmp: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            # ลบ .part ที่ค้าง — ไม่งั้นดิสก์จะ accumulate ขยะทุกครั้งที่เขียนล้ม
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ---------- MediaStorage ----------
    async def write(self, key: str, data: bytes) -> None:
        path = self._safe_path(key)
        tmp = self.tmp_dir / f"{uuid.uuid4().hex}.part"
        try:
            await asyncio.to_thread(self._write_sync, path, tmp, data)
        except MediaStorageError:
            raise
        except Exception as e:
            raise MediaStorageError(f"เขียนไฟล์ไม่สำเร็จ: {e}") from e

    async def read_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._safe_path(key)
        try:
            f = await asyncio.to_thread(open, path, "rb")
        except FileNotFoundError:
            raise MediaStorageError("ไม่พบไฟล์ในที่จัดเก็บ")
        except OSError as e:
            raise MediaStorageError(f"เปิดไฟล์ไม่สำเร็จ: {e}") from e
        try:
            while True:
                chunk = await asyncio.to_thread(f.read, READ_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(f.close)

    def local_path(self, key: str) -> Optional[Path]:
        return self._safe_path(key)

    async def delete(self, key: str) -> None:
        path = self._safe_path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as e:
            raise MediaStorageError(f"ลบไฟล์ไม่สำเร็จ: {e}") from e

    async def exists(self, key: str) -> bool:
        path = self._safe_path(key)
        return await asyncio.to_thread(path.is_file)
