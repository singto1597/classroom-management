"""
purge_media — เก็บกวาดไฟล์หลักฐานการเงินที่ไม่มีใครใช้แล้ว
==========================================================
สองงาน:
1. **แถวที่ soft-delete เกิน `MEDIA_PURGE_AFTER_DAYS`** → ลบแถว + ไฟล์ (full + thumb)
2. **ไฟล์ orphan** (ไม่มีแถวใดอ้างถึง) ที่เก่ากว่า `--orphan-age-hours` → ลบไฟล์

⭐ ลบ **แถวก่อน แล้วค่อยลบไฟล์** — ถ้าลบไฟล์ก่อนแล้วลบแถวไม่สำเร็จ
   จะเหลือแถวที่ชี้ไฟล์ซึ่งไม่มีอยู่ (ผู้ใช้เห็นไฟล์เสีย) ซึ่งแย่กว่า orphan ที่ไม่มีใครอ้าง
   ⇒ crash กลางทางกลายเป็น "ไฟล์ค้าง" ที่รอบถัดไป/ขั้น orphan เก็บให้

⚠️ **default = dry-run** ต้องใส่ `--apply` จึงจะลบจริง
   cron รายวันใช้ `--apply` (ดู ops/finance-media/README.md)

รัน:
    DATABASE_URL=... MEDIA_STORAGE_DIR=... python scripts/purge_media.py
    DATABASE_URL=... MEDIA_STORAGE_DIR=... python scripts/purge_media.py --apply

exit: 0 = จบ (ไม่ว่าจะลบหรือไม่) · 2 = ใช้ผิด/เชื่อมต่อไม่ได้/ION ล้ม
"""
import argparse
import asyncio
import os
import sys
import time

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.media.base import MediaStorageError  # noqa: E402
from core.media.local import LocalMediaStorage  # noqa: E402


# (ตาราง, prefix ของ key) — ครอบครัวเดียว: ไฟล์หลักฐานการเงิน
FAMILIES: tuple[tuple[str, str], ...] = (
    ("finance_attachments", "media/finance"),
)


def _scan_files(storage: LocalMediaStorage) -> list[tuple[str, float]]:
    """(relative path, mtime) ของทุกไฟล์ใต้ prefix ของทุกครอบครัว"""
    out: list[tuple[str, float]] = []
    for _table, prefix in FAMILIES:
        base = storage.root / prefix
        if not base.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    out.append((os.path.relpath(full, storage.root).replace(os.sep, "/"), os.path.getmtime(full)))
                except OSError:
                    continue
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description="ลบไฟล์ที่ soft-delete เกินกำหนด + ไฟล์ orphan")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--root", default=os.environ.get("MEDIA_STORAGE_DIR"))
    ap.add_argument("--days", type=int, default=None, help="เก็บแถวที่ลบไว้กี่วัน (default: MEDIA_PURGE_AFTER_DAYS)")
    ap.add_argument("--orphan-age-hours", type=int, default=24, help="ไฟล์ orphan ต้องเก่ากี่ชั่วโมงจึงลบ (กันชนกับ upload ที่ยังไม่ commit)")
    ap.add_argument("--apply", action="store_true", help="ลบจริง (ไม่ใส่ = dry-run)")
    args = ap.parse_args()

    if not args.database_url:
        print("❌ ต้องระบุ --database-url หรือตั้ง DATABASE_URL", file=sys.stderr)
        return 2
    if not args.root or not os.path.isdir(args.root):
        print(f"❌ ไม่พบโฟลเดอร์ media: {args.root}", file=sys.stderr)
        return 2

    days = args.days
    if days is None:
        from core.config import settings
        days = settings.MEDIA_PURGE_AFTER_DAYS
    if days < 0:
        print("❌ --days ต้องไม่ติดลบ", file=sys.stderr)
        return 2

    storage = LocalMediaStorage(args.root)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"🧹 purge_media [{mode}] root={args.root} · แถวที่ลบเกิน {days} วัน · orphan เกิน {args.orphan_age_hours} ชม.")

    try:
        pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=2)
    except Exception as e:  # noqa: BLE001
        print(f"❌ เชื่อมต่อ DB ไม่ได้: {e}", file=sys.stderr)
        return 2

    # ⚠️ ชื่อตารางมาจาก `FAMILIES` (ค่าคงที่ในโค้ด) ไม่ใช่ input ของผู้ใช้ — ใช้ f-string ได้
    paths: list[str] = []
    expired_total = 0
    async with pool.acquire() as conn:
        for table, _prefix in FAMILIES:
            async with conn.transaction():
                expired = await conn.fetch(
                    f"""
                    SELECT id, storage_path, thumb_path
                    FROM {table}
                    WHERE deleted_at IS NOT NULL
                      AND deleted_at < NOW() - ($1::int * INTERVAL '1 day')
                    ORDER BY deleted_at
                    FOR UPDATE
                    """,
                    days,
                )
                for row in expired:
                    for key in (row["storage_path"], row["thumb_path"]):
                        if key:
                            paths.append(key)

                ids = [row["id"] for row in expired]
                if args.apply and ids:
                    await conn.execute(
                        f"DELETE FROM {table} WHERE id = ANY($1::uuid[])",
                        ids,
                    )
                expired_total += len(expired)
                print(f"   {table}: {len(expired)} แถวครบกำหนด")

    # ไฟล์ของแถวที่ลบไปแล้ว → ลบ (idempotent)
    file_errors = 0
    for key in paths:
        if not args.apply:
            print(f"   would delete file: {key}")
            continue
        try:
            await storage.delete(key)
        except MediaStorageError as e:
            file_errors += 1
            print(f"   ⚠️ ลบไฟล์ไม่สำเร็จ {key}: {e}", file=sys.stderr)

    # ---------- orphan ----------
    # อ่านแถวที่ "ยังอยู่ใน DB ตอนนี้" — ใน dry-run แถวที่ครบกำหนดยังอยู่ จึงไม่ถูก
    # ตีความเป็น orphan (มันจะถูกลบพร้อมแถวในรอบ apply) ส่วนใน apply แถวนั้นถูกลบแล้ว
    # ⇒ ไฟล์ที่ค้างเพราะลบไม่สำเร็จจะถูกเก็บในรอบถัดไป
    referenced_set: set[str] = set()
    async with pool.acquire() as conn:
        for table, _prefix in FAMILIES:
            referenced = await conn.fetch(
                f"SELECT storage_path, thumb_path FROM {table}"
            )
            for r in referenced:
                if r["storage_path"]:
                    referenced_set.add(r["storage_path"])
                if r["thumb_path"]:
                    referenced_set.add(r["thumb_path"])

    cutoff = time.time() - args.orphan_age_hours * 3600
    orphans = [(p, m) for p, m in _scan_files(storage) if p not in referenced_set and m < cutoff]

    orphan_errors = 0
    for key, _mtime in orphans:
        if not args.apply:
            print(f"   would delete orphan: {key}")
            continue
        try:
            await storage.delete(key)
        except MediaStorageError as e:
            orphan_errors += 1
            print(f"   ⚠️ ลบ orphan ไม่สำเร็จ {key}: {e}", file=sys.stderr)

    await pool.close()

    verb = "ลบ" if args.apply else "จะลบ"
    print(
        f"🟢 สรุป: {verb}แถวที่เก็บเกินกำหนด {expired_total} แถว ({len(paths)} ไฟล์) · "
        f"orphan {len(orphans)} ไฟล์"
    )
    if file_errors or orphan_errors:
        print(f"🔴 ลบไฟล์ล้ม {file_errors + orphan_errors} รายการ — ตรวจสิทธิ์/ดิสก์", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
