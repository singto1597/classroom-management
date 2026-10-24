"""🧱 พิสูจน์สัญญาของระบบ migration (`core/migrations/runner.py`)

เทสต์เหล่านี้สร้าง **DB ของตัวเองแยกต่างหาก** (เหมือน `test_init_db_upgrade_path.py`)
เพราะบางข้อต้องรัน migration ที่ล้มกลางทาง/แก้ checksum — ห้ามทำบน DB ที่เทสต์อื่นใช้ร่วม

สิ่งที่ล็อกไว้:
  1. รันซ้ำได้ ไม่สร้างแถวซ้ำ และคืน `0` เมื่อไม่มีอะไรต้องทำ
  2. ไฟล์ที่ล้มกลางทาง **rollback ทั้งไฟล์** (ไม่มีตารางค้าง ไม่มีแถวใน `schema_migrations`)
  3. แก้ migration เดิมหลัง apply = `MigrationDriftError` (บูตไม่ขึ้น ไม่ใช่เงียบ ๆ)
  4. สอง replica บูตพร้อมกัน → migration รันครั้งเดียว (advisory lock ทำงานจริง)
  5. loader ปฏิเสธคำสั่งทำลายข้อมูล / เลขซ้ำ / `SQL` ว่าง
"""

import asyncio
import uuid
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio

from core.config import settings
from core.migrations import (
    DestructiveMigrationError,
    Migration,
    MigrationDriftError,
    MigrationError,
    apply_migrations,
    load_migrations,
)

# ⚠️ ไม่ใช้ `pytestmark = pytest.mark.asyncio` ทั้งไฟล์ เพราะครึ่งล่าง (loader) เป็น
#    เทสต์ sync — mark asyncio ให้ sync function จะตกด้วย "not an async function"


# ═════════════════════════════════════════════════════════════════════════════
# Scratch DB — แยกจาก session DB โดยเจตนา
# ═════════════════════════════════════════════════════════════════════════════
async def _create_scratch_db() -> tuple[str, str]:
    db_name = f"test_migrations_{uuid.uuid4().hex}"
    parsed = urlparse(settings.DATABASE_URL)
    base = (
        f"{parsed.scheme}://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port}"
    )
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


@pytest_asyncio.fixture
async def scratch():
    """คืน (pool, db_url) ของ DB ใหม่ แล้วเก็บกวาดให้เอง"""
    db_url, sys_db_url = await _create_scratch_db()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    try:
        yield pool, db_url
    finally:
        await pool.close()
        await _drop_scratch_db(sys_db_url, db_url)


# ═════════════════════════════════════════════════════════════════════════════
# 1. idempotent
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_apply_is_idempotent_and_records_one_row(scratch):
    pool, _ = scratch
    migration = Migration(
        "0001_make_table",
        ("CREATE TABLE IF NOT EXISTS mig_probe (id INT PRIMARY KEY)",),
    )

    assert await apply_migrations(pool, [migration]) == 1

    # 🔑 รันซ้ำต้องได้ 0 — "0" คือค่าที่ assert ได้ ไม่ใช่สัญญาณว่าโค้ดไม่เคยรัน
    assert await apply_migrations(pool, [migration]) == 0

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
        assert len(rows) == 1, "ต้องมีแถวเดียวต่อ migration หนึ่งไฟล์"
        assert rows[0]["version"] == "0001_make_table"
        assert rows[0]["checksum"] == migration.checksum
        assert await conn.fetchval(
            "SELECT to_regclass('public.mig_probe') IS NOT NULL"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 2. rollback ต่อไฟล์
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_failing_migration_rolls_back_whole_file(scratch):
    pool, _ = scratch
    good = Migration("0001_good", ("CREATE TABLE IF NOT EXISTS mig_good (id INT)",))
    bad = Migration(
        "0002_bad",
        (
            # สร้างตารางก่อนแล้วค่อยพัง ⇒ ถ้าไม่มี transaction ครึ่งแรกจะค้างอยู่
            "CREATE TABLE IF NOT EXISTS mig_bad (id INT)",
            "SELECT 1 / 0",
        ),
    )

    with pytest.raises(asyncpg.PostgresError):
        await apply_migrations(pool, [good, bad])

    async with pool.acquire() as conn:
        # ไฟล์แรกสำเร็จและถูกบันทึก — ไม่ใช่ทั้งหมดหรือไม่เลย
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '0001_good'"
        ) == 1
        # ไฟล์ที่ล้ม: ไม่มีทั้งตารางและแถว
        assert await conn.fetchval(
            "SELECT to_regclass('public.mig_bad') IS NULL"
        ), "ตารางของ migration ที่ล้มต้องถูก rollback"
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '0002_bad'"
        ) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3. drift
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_editing_an_applied_migration_fails_loudly(scratch):
    pool, _ = scratch
    original = Migration("0001_fixed", ("CREATE TABLE IF NOT EXISTS mig_drift (id INT)",))
    await apply_migrations(pool, [original])

    edited = Migration(
        "0001_fixed",
        (
            "CREATE TABLE IF NOT EXISTS mig_drift (id INT)",
            "ALTER TABLE mig_drift ADD COLUMN IF NOT EXISTS extra TEXT",
        ),
    )

    with pytest.raises(MigrationDriftError):
        await apply_migrations(pool, [edited])


# ═════════════════════════════════════════════════════════════════════════════
# 4. advisory lock — 3 replica บูตพร้อมกัน
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_concurrent_runners_apply_a_migration_exactly_once(scratch):
    _, db_url = scratch
    slow = Migration(
        "0001_slow",
        (
            "SELECT pg_sleep(0.4)",
            "CREATE TABLE IF NOT EXISTS mig_lock (id INT)",
        ),
    )

    pool_a = await asyncpg.create_pool(db_url, min_size=1, max_size=1)
    pool_b = await asyncpg.create_pool(db_url, min_size=1, max_size=1)
    try:
        results = await asyncio.gather(
            apply_migrations(pool_a, [slow]),
            apply_migrations(pool_b, [slow]),
        )
        assert sorted(results) == [0, 1], (
            "ต้องมีตัวเดียวที่รันจริง อีกตัวรอ lock แล้วเห็นว่าถูก apply ไปแล้ว"
        )

        async with pool_a.acquire() as conn:
            assert await conn.fetchval("SELECT COUNT(*) FROM schema_migrations") == 1
    finally:
        await pool_a.close()
        await pool_b.close()


# ═════════════════════════════════════════════════════════════════════════════
# 5. loader — ด่านหน้า (ไม่แตะ DB)
# ═════════════════════════════════════════════════════════════════════════════
def test_loader_orders_by_prefix_and_ignores_other_files(tmp_path):
    (tmp_path / "0002_second.py").write_text('SQL = ["SELECT 2"]\n', encoding="utf-8")
    (tmp_path / "0001_first.py").write_text('SQL = ["SELECT 1"]\n', encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "helper.py").write_text('SQL = ["SELECT 9"]\n', encoding="utf-8")

    versions = [m.version for m in load_migrations(path=tmp_path)]
    assert versions == ["0001_first", "0002_second"]


def test_loader_rejects_duplicate_number(tmp_path):
    (tmp_path / "0001_a.py").write_text('SQL = ["SELECT 1"]\n', encoding="utf-8")
    (tmp_path / "0001_b.py").write_text('SQL = ["SELECT 2"]\n', encoding="utf-8")

    with pytest.raises(MigrationError):
        load_migrations(path=tmp_path)


def test_loader_rejects_empty_sql_list(tmp_path):
    (tmp_path / "0001_empty.py").write_text("SQL = []\n", encoding="utf-8")

    with pytest.raises(MigrationError):
        load_migrations(path=tmp_path)


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TABLE users",
        "drop table if exists users",
        "ALTER TABLE users DROP COLUMN phone_number",
        "TRUNCATE users",
        "DROP SCHEMA public CASCADE",
    ],
)
def test_loader_rejects_destructive_statements(tmp_path, statement):
    (tmp_path / "0001_danger.py").write_text(
        f"SQL = [{statement!r}]\n", encoding="utf-8"
    )

    with pytest.raises(DestructiveMigrationError):
        load_migrations(path=tmp_path)


def test_loader_allows_destructive_only_with_explicit_flag(tmp_path):
    (tmp_path / "0001_cleanup.py").write_text(
        'DESTRUCTIVE = True\nSQL = ["DROP TABLE IF EXISTS tmp_scratch"]\n',
        encoding="utf-8",
    )

    migrations = load_migrations(path=tmp_path)
    assert migrations[0].allows_destructive is True


def test_real_package_loads_and_is_sorted():
    """ไฟล์จริงใน `core/migrations/` ต้องโหลดได้และเรียงถูกเสมอ"""
    migrations = load_migrations()
    assert [m.version for m in migrations] == sorted(m.version for m in migrations)
