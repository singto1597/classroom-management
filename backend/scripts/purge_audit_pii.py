"""
ล้างข้อมูลส่วนบุคคลออกจาก audit_logs ที่คัดลอกไว้ก่อนหน้านี้ (ครั้งเดียว)

**ที่มา:** `auth_service.process_user_login` ใช้ `SELECT *` แล้วส่งทั้งแถว `users`
เข้า `old_values` ของ audit_logs ⇒ ข้อมูลสุขภาพ เบอร์โทร ที่อยู่ และวันเกิด
ถูกคัดลอกไปอยู่ในตาราง audit_logs ซึ่งมีคนอ่านได้กว้างกว่าตาราง users มาก

โค้ดต้นทางแก้แล้ว (`core/logger.py::redact_sensitive`) แต่แถวที่เขียนไปแล้ว
ยังมีค่าเต็มอยู่ — สคริปต์นี้ตามไปแทนที่ด้วย ``[REDACTED]``

**หัวใจ:** สคริปต์นี้เรียก `redact_sensitive()` ตัวเดียวกับที่ logger ใช้
จึงรับประกันได้ว่าสิ่งที่ล้างย้อนหลัง = สิ่งที่ logger จะเขียนต่อจากนี้
(ถ้าเขียนกฎซ้ำเป็น SQL เอง กฎสองที่จะเพี้ยนออกจากกันในอนาคต)

**รัน:**
    # dry-run (ค่าเริ่มต้น) — บน staging
    docker compose -f docker-compose.test.yml run --rm test_runner \\
        python /app/scripts/purge_audit_pii.py
    # ลงมือแก้จริง
    ... python /app/scripts/purge_audit_pii.py --apply

**ปลอดภัย:** แทนค่าด้วย ``[REDACTED]`` ไม่ได้ลบแถว — audit ยังอยู่ครบ
ตอบได้ว่าใครแก้อะไร เมื่อไร แค่ไม่รู้ค่า และรันซ้ำได้ไม่มีผลข้างเคียง
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402

from core.config import settings  # noqa: E402
from core.logger import _SENSITIVE_KEYS, redact_sensitive  # noqa: E402

COLUMNS = ("old_values", "new_values")
WATCHED_KEYS = sorted(_SENSITIVE_KEYS)


def _as_dict(raw):
    """asyncpg คืน jsonb เป็น str (ไม่มี codec) — เผื่ออนาคตมี codec ก็รองรับทั้งคู่"""
    if raw is None:
        return None
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def _affected_ids(conn, column: str):
    """แถวที่มีคีย์อ่อนไหวอย่างน้อยหนึ่งคีย์ — ใช้ตัวดำเนินการ `?|` ของ jsonb"""
    return await conn.fetch(
        f"SELECT id FROM audit_logs WHERE {column} ?| $1::text[]", WATCHED_KEYS
    )


async def _show_sample(conn, column: str, limit: int = 5):
    """นับว่าคีย์ไหนถูกใช้บ้าง — แสดงแค่ *ชื่อคีย์* ไม่แสดงค่า (ไม่ให้ค่าลับลงจอ/log)"""
    rows = await conn.fetch(
        f"""
        SELECT action, service_name, created_at, k AS key, COUNT(*) OVER (PARTITION BY k) AS n
        FROM audit_logs, LATERAL jsonb_object_keys({column}) AS k
        WHERE {column} ?| $1::text[] AND k = ANY($1::text[])
        ORDER BY created_at DESC
        LIMIT $2
        """,
        WATCHED_KEYS, limit,
    )
    for row in rows:
        print(f"    {row['key']:<32} ×{row['n']:<5} "
              f"{row['created_at']:%Y-%m-%d} {row['service_name']}/{row['action']}")


async def _purge(conn, column: str) -> int:
    ids = [r["id"] for r in await _affected_ids(conn, column)]
    if not ids:
        return 0

    fixed = 0
    for batch_start in range(0, len(ids), 500):
        batch = ids[batch_start:batch_start + 500]
        rows = await conn.fetch(
            f"SELECT id, {column} AS payload FROM audit_logs WHERE id = ANY($1::uuid[])",
            batch,
        )
        for row in rows:
            payload = _as_dict(row["payload"])
            redacted = redact_sensitive(payload)
            if redacted == payload:
                continue  # ไม่มีอะไรต้องแก้ (เช่นค่าถูกปกปิดไว้แล้ว)
            await conn.execute(
                f"UPDATE audit_logs SET {column} = $1::jsonb WHERE id = $2",
                json.dumps(redacted, default=str, ensure_ascii=False), row["id"],
            )
            fixed += 1
    return fixed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="ลงมือแก้จริง (ไม่ใส่ = dry-run แค่รายงาน)")
    args = parser.parse_args()

    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        total_rows = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
        print(f"audit_logs ทั้งหมด {total_rows} แถว — กำลังหาแถวที่มีข้อมูลอ่อนไหว...\n")

        counts = {c: len(await _affected_ids(conn, c)) for c in COLUMNS}
        total = sum(counts.values())
        for column, n in counts.items():
            print(f"  {column}: {n} แถว")

        if total == 0:
            print("\n✅ ไม่มีอะไรต้องล้าง — สะอาดแล้ว")
            return 0

        print("\nคีย์ที่พบ (แสดงชื่อคีย์เท่านั้น ไม่แสดงค่า):")
        for column in COLUMNS:
            if counts[column]:
                print(f"  [{column}]")
                await _show_sample(conn, column)

        if not args.apply:
            print(f"\n(dry-run) จะแก้ไม่เกิน {total} แถว — ใส่ --apply เพื่อลงมือจริง")
            return 0

        print()
        async with conn.transaction():
            for column in COLUMNS:
                n = await _purge(conn, column)
                print(f"  แก้ {column} ไป {n} แถว")

        print("\nผลหลังล้าง:")
        remaining = sum(len(await _affected_ids(conn, c)) for c in COLUMNS)
        print(f"  เหลือแถวที่มีคีย์อ่อนไหว: {remaining}")
        print("✅ ล้างเสร็จ" if remaining == 0 else f"⚠️ ยังเหลือ {remaining} แถว")
        return 0 if remaining == 0 else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
