"""🏗️ พิสูจน์ว่า `init_db` **อัปเกรด DB เดิมได้จริง** ไม่ใช่แค่สร้าง DB ใหม่ได้

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมีไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
เทสต์ทั้ง suite รันบน DB ที่ `conftest.py` สร้าง **ใหม่เอี่ยม** จาก `init_db` เสมอ
⇒ บล็อก `CREATE TABLE IF NOT EXISTS` ทุกบล็อกรันจริง และ **ผ่านหมด**

แต่ DB จริงในโปรดักชัน **มีตารางอยู่แล้ว** ⇒ `CREATE TABLE IF NOT EXISTS` เป็น **no-op**
⇒ ทุกอย่างที่เพิ่มไว้ "ในบล็อก CREATE TABLE" ของตารางที่มีอยู่แล้ว **ไม่ถูกสร้างเลย**
   และงาน F5 เพิ่ม `finance_receipts.batch_id` + index + FK คู่ เข้าไปในตารางนั้นพอดี

⇒ ถ้าพลาด จะไม่พังในเทสต์ **แต่จะพังตอน deploy** ด้วย `column "batch_id" does not exist`
   = ทุก replica บูตไม่ขึ้น ระบบล่มทั้งระบบ (และเป็นความล้มเหลวที่เทสต์ 900 ตัวจับไม่ได้)

ไฟล์นี้จึงจำลอง "DB ที่รัน F3 มาก่อน" ด้วยการ **ถอดสิ่งที่ F5 เพิ่มออก** แล้วรัน `init_db`
ซ้ำ — เส้นทางเดียวกับที่โปรดักชันจะเดินจริงตอน deploy

⚠️ **สร้าง DB ของตัวเองแยกต่างหาก** — ห้ามใช้ `db_pool` ร่วม: เทสต์นี้ `DROP COLUMN`
   บน DB ที่เทสต์อื่นใช้อยู่ = พังทั้ง session (เหตุผลเดียวกับที่ `conftest.test_db_url`
   สร้าง DB ใหม่ต่อ session)
"""
import uuid
from urllib.parse import urlparse

import asyncpg
import pytest

from core.config import settings
from core.init_db import init_db

pytestmark = pytest.mark.asyncio


# 🏷️ สิ่งที่งาน F5 เพิ่มเข้าไปในตาราง **ที่มีอยู่แล้ว** (`finance_receipts`)
F5_COLUMN = "batch_id"
F5_INDEX = "idx_finance_receipts_batch"
F5_FK = "fk_receipts_batch_same_room"
# 🆕 ตารางใหม่ของ F5 — ตัวนี้ `CREATE TABLE IF NOT EXISTS` สร้างให้ได้เองทุกสภาพ
F5_TABLE = "finance_receipt_batches"


async def _create_scratch_db() -> tuple[str, str]:
    """สร้าง DB ใหม่แบบสุ่มชื่อ คืน (db_url, sys_db_url)"""
    db_name = f"test_upgrade_{uuid.uuid4().hex}"
    parsed = urlparse(settings.DATABASE_URL)
    base = (f"{parsed.scheme}://{parsed.username}:{parsed.password}"
            f"@{parsed.hostname}:{parsed.port}")
    sys_db_url = f"{base}/postgres"
    conn = await asyncpg.connect(sys_db_url)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()
    return f"{base}/{db_name}", sys_db_url


async def _drop_scratch_db(sys_db_url: str, db_url: str) -> None:
    db_name = urlparse(db_url).path.lstrip("/")
    conn = await asyncpg.connect(sys_db_url)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# Helper อ่าน schema — ใช้ `information_schema`/`pg_catalog` ไม่ใช่การเดา
# ═════════════════════════════════════════════════════════════════════════════
async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2",
        table, column,
    ))


async def _has_index(conn, index_name: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_indexes WHERE indexname = $1", index_name
    ))


async def _has_constraint(conn, table: str, constraint: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_constraint C JOIN pg_class T ON T.oid = C.conrelid"
        " WHERE T.relname = $1 AND C.conname = $2",
        table, constraint,
    ))


async def _has_table(conn, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.tables WHERE table_name = $1", table
    ))


async def test_init_db_recreates_f5_schema_on_a_database_that_predates_it():
    """🔑 จำลอง DB ที่รัน F3 มาก่อน → ถอดสิ่งที่ F5 เพิ่ม → รัน `init_db` ซ้ำ → ต้องได้ครบ

    ขั้นตอน:
      1. สร้าง DB เปล่า + `init_db` ครั้งแรก (ได้ schema ปัจจุบันครบ)
      2. ใส่ข้อมูลจริง 1 แถว (พิสูจน์ว่า ADD COLUMN/ADD CONSTRAINT ไม่ล้มเพราะ **ข้อมูลเดิม**)
      3. **ถอด** คอลัมน์/index/FK/ตาราง ของ F5 ออก = สภาพ "DB ยุค F3"
      4. ยืนยันว่าถอดจริง (ไม่งั้นเทสต์นี้จะเขียวหลอก)
      5. รัน `init_db` ซ้ำ = **จังหวะ deploy** → ต้องได้ทุกอย่างคืน และข้อมูลเดิมต้องอยู่ครบ
    """
    db_url, sys_db_url = await _create_scratch_db()
    try:
        pool = await asyncpg.create_pool(db_url)
        try:
            # ── 1. schema ปัจจุบัน ────────────────────────────────────────────
            await init_db(pool)
            async with pool.acquire() as conn:
                assert await _has_column(conn, "finance_receipts", F5_COLUMN)
                assert await _has_table(conn, F5_TABLE)

                # ── 2. ข้อมูลเดิมของ "DB เก่า" ────────────────────────────────
                # 🔴 จำเป็น: ถ้า DB ว่างเปล่า `ADD CONSTRAINT` จะผ่านเสมอไม่ว่าจะเขียนถูก
                #    หรือผิด ⇒ เทสต์จะไม่พิสูจน์อะไรเลยเกี่ยวกับข้อมูลที่มีอยู่จริง
                room_id = await conn.fetchval(
                    "INSERT INTO rooms (room_name, room_code, owner_id)"
                    " VALUES ($1, $2, NULL) RETURNING id",
                    "ห้องยุคก่อน F5", f"OLD{uuid.uuid4().hex[:6].upper()}",
                )
                receipt_id = await conn.fetchval(
                    "INSERT INTO finance_receipts"
                    " (room_id, receipt_no, doc_type, year_be, seq, amount, paid_total_after)"
                    " VALUES ($1, $2, 'receipt', 2569, 1, 100.00, 100.00) RETURNING id",
                    room_id, f"REC-2569-{uuid.uuid4().hex[:4].upper()}",
                )

                # ── 3. ถอดกลับไปเป็นสภาพ "ก่อน F5" ────────────────────────────
                #    DROP TABLE ... CASCADE พา FK คู่ที่ชี้มาที่ตารางนั้นหายไปด้วย
                #    (เหมือน DB ที่ไม่เคยรู้จัก F5 มาก่อน)
                await conn.execute("ALTER TABLE finance_receipts DROP COLUMN batch_id;")
                await conn.execute(f"DROP TABLE IF EXISTS {F5_TABLE} CASCADE;")

                # ── 4. ยืนยันว่าจำลองสำเร็จ (กันเทสต์เขียวหลอก) ───────────────
                assert not await _has_column(conn, "finance_receipts", F5_COLUMN), \
                    "จำลอง DB เก่าไม่สำเร็จ — คอลัมน์ยังอยู่ ⇒ เทสต์นี้พิสูจน์อะไรไม่ได้"
                assert not await _has_index(conn, F5_INDEX)
                assert not await _has_constraint(conn, "finance_receipts", F5_FK)
                assert not await _has_table(conn, F5_TABLE)

            # ── 5. จังหวะ deploy: รัน `init_db` ซ้ำบน DB ที่มีข้อมูลอยู่แล้ว ────
            await init_db(pool)

            async with pool.acquire() as conn:
                # (ก) คอลัมน์ — ต้องมาจากบล็อก ALTER (CREATE TABLE เป็น no-op ไปแล้ว)
                assert await _has_column(conn, "finance_receipts", F5_COLUMN), \
                    "`batch_id` ไม่ถูกเพิ่ม ⇒ deploy บน DB จริงจะพังด้วย column does not exist"
                # (ข) index — ต้องถูกสร้าง "หลัง" คอลัมน์มีอยู่
                assert await _has_index(conn, F5_INDEX), \
                    "index ของ batch_id หาย ⇒ เทสต์นี้คือด่านที่จับการย้าย index ไป CREATE TABLE"
                # (ค) FK คู่ — ต้องกลับมาพร้อม unique constraint ที่เป็นเป้าของมัน
                assert await _has_constraint(conn, "finance_receipts", F5_FK)
                assert await _has_constraint(conn, F5_TABLE, "uq_receipt_batch_id_room")
                # (ง) ตารางใหม่
                assert await _has_table(conn, F5_TABLE)

                # (จ) 🔑 ข้อมูลเดิมต้องรอด — แถวเดิมได้ `batch_id = NULL` (ยังไม่ถูกจัดกลุ่ม)
                #     และต้องไม่ถูกแตะเลย
                row = await conn.fetchrow(
                    "SELECT id, room_id, amount, status, batch_id FROM finance_receipts"
                    " WHERE id = $1",
                    receipt_id,
                )
                assert row is not None, "ข้อมูลเดิมหายไปหลังรัน init_db ซ้ำ"
                assert row["room_id"] == room_id
                assert float(row["amount"]) == 100.00
                assert row["status"] == "active"
                assert row["batch_id"] is None, \
                    "ใบเดิมต้องได้ batch_id = NULL (ยังไม่จัดกลุ่ม) ไม่ใช่ค่าอื่น"

                # (ฉ) composite FK **ทำงานจริง** หลังอัปเกรด — ใบของห้อง A เข้าชุดของห้อง B ไม่ได้
                #     ⚠️ ขั้นนี้สำคัญกว่าการเช็คว่า constraint "มีอยู่": constraint ที่มีแต่ใช้
                #        ไม่ได้ (เช่นชี้ผิดคอลัมน์) จะผ่านข้อ (ค) แต่ตกข้อนี้
                other_room_id = await conn.fetchval(
                    "INSERT INTO rooms (room_name, room_code, owner_id)"
                    " VALUES ($1, $2, NULL) RETURNING id",
                    "ห้องอื่น", f"OTH{uuid.uuid4().hex[:6].upper()}",
                )
                other_batch_id = await conn.fetchval(
                    "INSERT INTO finance_receipt_batches (room_id, source)"
                    " VALUES ($1, 'manual') RETURNING id",
                    other_room_id,
                )
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await conn.execute(
                        "UPDATE finance_receipts SET batch_id = $1 WHERE id = $2",
                        other_batch_id, receipt_id,
                    )
        finally:
            await pool.close()
    finally:
        await _drop_scratch_db(sys_db_url, db_url)
