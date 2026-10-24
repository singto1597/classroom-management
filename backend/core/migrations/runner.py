"""Runner ของ migration แบบ additive — ด่านที่บังคับว่า "เปลี่ยนสคีมา = เขียน migration"

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี (ปัญหาจริงที่ `init_db` แก้ไม่ได้)
═══════════════════════════════════════════════════════════════════════════════
`init_db()` ใช้ `CREATE TABLE IF NOT EXISTS` ทั้งไฟล์ ⇒ บน DB ที่ **มีตารางอยู่แล้ว**
บล็อกนั้นเป็น no-op ทุกบรรทัด สิ่งที่เพิ่ม "ข้างใน CREATE TABLE" จึงไม่ถูกสร้างเลย
(เจอมาแล้วกับ `finance_receipts.batch_id` — ดู `tests/test_init_db_upgrade_path.py`)

ทางแก้ระยะยาวคือแยก "สคีมาใหม่" ออกเป็นไฟล์ migration ที่:
  1. **ไม่แก้ไฟล์เก่า** (checksum ตรึงไว้ ⇒ แก้ย้อนหลัง = บูตไม่ขึ้น ดัง ๆ ไม่ใช่เงียบ)
  2. **idempotent** (`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`) ⇒ รันซ้ำได้เสมอ
  3. **ไม่ทำลายข้อมูล** (`DROP TABLE` / `DROP COLUMN` / `TRUNCATE` ถูกปฏิเสธที่ loader)
  4. รันใน **transaction ต่อไฟล์** ⇒ ไฟล์ที่ล้มกลางทางไม่ทิ้งสภาพครึ่ง ๆ ไว้

═══════════════════════════════════════════════════════════════════════════════
🔒 หลาย replica บูตพร้อมกัน
═══════════════════════════════════════════════════════════════════════════════
stack นี้รัน backend 3 replica และทุกตัวเรียก `init_db()` + `apply_migrations()` ตอนบูต
⇒ ต้องมี **advisory lock ระดับ session** ครอบการ apply ทั้งรอบ ไม่งั้นสองตัวจะรันไฟล์
เดียวกันพร้อมกันแล้วตายด้วย unique violation ที่ `schema_migrations` (ทั้งที่สคีมาเรียบร้อยดี)
ใช้ `pg_try_advisory_lock` ในลูปแทนการบล็อกค้าง เพราะถ้าตัวที่ถือ lock ค้างอยู่
การบูตที่เหลือควร **ล้มดัง ๆ ภายใน 60 วิ** ให้ Swarm restart ใหม่ ไม่ใช่แขวนตลอดกาล

═══════════════════════════════════════════════════════════════════════════════
📄 รูปแบบไฟล์
═══════════════════════════════════════════════════════════════════════════════
    backend/core/migrations/0001_add_notifications.py
        SQL: list[str] = [
            "CREATE TABLE IF NOT EXISTS notifications (...)",
            "CREATE INDEX IF NOT EXISTS ...",
        ]

เลขนำหน้า 4 หลัก = ลำดับ; ชื่อไฟล์ทั้งชื่อคือ `version` ที่เก็บใน DB
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import asyncpg

logger = logging.getLogger("API_MIGRATIONS")

# แพ็กเกจเริ่มต้น — ไฟล์จริงทั้งหมดอยู่ในโฟลเดอร์เดียวกับไฟล์นี้
MIGRATION_PACKAGE = "core.migrations"

# `0001_add_notifications` — เลขนำหน้า **4 หลัก** + ตัวพิมพ์เล็ก/ตัวเลข/ขีดล่างเท่านั้น
# (4 หลักไม่ใช่ 3: ระบบนี้ใช้ `0001` และมีที่ว่างถึง 9999 ไฟล์)
_FILE_RE = re.compile(r"^(\d{4})_[a-z0-9_]+$")

# 🔑 ค่าคงที่ของระบบ (ห้ามเปลี่ยน — ถ้าเปลี่ยน ตัวที่ยังถือ lock เดิมจะไม่ถูกกัน)
APPLY_LOCK_KEY = 824_631_907

# ถ้าตัวที่ถือ lock ไม่ปล่อยภายในเวลานี้ ให้ล้มเพื่อให้ orchestrator restart
LOCK_WAIT_SECONDS = 60.0
LOCK_POLL_SECONDS = 0.5

# 🚫 กฎเหล็ก: migration ต้องไม่ทำลายข้อมูล
#    (ถ้าจำเป็นจริง ๆ ต้องประกาศ `DESTRUCTIVE = True` ในไฟล์นั้น — จะถูก log ระดับ WARNING)
_DESTRUCTIVE_RE = re.compile(
    r"\b(?:DROP\s+(?:TABLE|COLUMN|SCHEMA|DATABASE)|TRUNCATE\b)",
    re.IGNORECASE,
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    checksum   TEXT        NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class MigrationError(RuntimeError):
    """ฐานของข้อผิดพลาดทั้งหมดของระบบ migration (ทำให้บูตไม่ขึ้นโดยเจตนา)"""


class MigrationDriftError(MigrationError):
    """ไฟล์ migration ที่เคย apply ไปแล้วถูกแก้ — checksum ไม่ตรงกับที่บันทึกไว้"""


class DestructiveMigrationError(MigrationError):
    """ไฟล์ migration มีคำสั่งทำลายข้อมูลโดยไม่ได้ประกาศ `DESTRUCTIVE = True`"""


@dataclass(frozen=True)
class Migration:
    """migration หนึ่งไฟล์ — `statements` คือคำสั่ง SQL ตามลำดับ

    `checksum` คำนวณจาก (version + ทุก statement) ⇒ แก้แม้แต่ช่องว่างในไฟล์
    จะทำให้ checksum เปลี่ยนและบูตไม่ขึ้น นั่นคือพฤติกรรมที่ต้องการ:
    ของที่ apply ไปแล้วห้ามแก้ย้อนหลัง ให้เขียนไฟล์ใหม่ต่อท้ายแทน
    """

    version: str
    statements: tuple[str, ...]
    allows_destructive: bool = False

    @property
    def checksum(self) -> str:
        return checksum_of(self.version, self.statements)


def checksum_of(version: str, statements: Iterable[str]) -> str:
    """sha256 ของ version + คำสั่งทุกตัว (คั่นด้วย NUL กันกำกวมจากการต่อสตริง)"""
    digest = hashlib.sha256()
    digest.update(version.encode("utf-8"))
    for statement in statements:
        digest.update(b"\x00")
        digest.update(statement.encode("utf-8"))
    return digest.hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
# Loader
# ═════════════════════════════════════════════════════════════════════════════
def _load_module(path: Path):
    """โหลดไฟล์ migration เป็นโมดูลชั่วคราว (ไม่ใส่ sys.modules ⇒ เรียกซ้ำได้เสมอ)"""
    spec = importlib.util.spec_from_file_location(f"_cls_migration_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover — ไฟล์ .py อ่านได้เสมอ
        raise MigrationError(f"โหลด migration ไม่ได้: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _to_migration(path: Path) -> Migration:
    module = _load_module(path)

    statements = getattr(module, "SQL", None)
    if not isinstance(statements, (list, tuple)) or not statements:
        raise MigrationError(
            f"{path.name}: ต้องประกาศ `SQL: list[str]` ที่ไม่ว่าง "
            "(แต่ละสมาชิกคือหนึ่งคำสั่ง SQL)"
        )

    cleaned: list[str] = []
    for index, statement in enumerate(statements, start=1):
        if not isinstance(statement, str) or not statement.strip():
            raise MigrationError(f"{path.name}: SQL ตัวที่ {index} ต้องเป็นสตริงที่ไม่ว่าง")
        cleaned.append(statement)

    allows_destructive = getattr(module, "DESTRUCTIVE", False) is True
    if not allows_destructive:
        for statement in cleaned:
            if _DESTRUCTIVE_RE.search(statement):
                raise DestructiveMigrationError(
                    f"{path.name}: พบคำสั่งทำลายข้อมูล — migration ต้องเป็น additive เท่านั้น\n"
                    "ถ้าจำเป็นจริง ๆ ให้ประกาศ `DESTRUCTIVE = True` ในไฟล์นั้น "
                    "พร้อมสำรองข้อมูลก่อน deploy"
                )
    else:
        logger.warning("⚠️ %s ประกาศ DESTRUCTIVE = True — มีคำสั่งทำลายข้อมูล", path.name)

    return Migration(
        version=path.stem,
        statements=tuple(cleaned),
        allows_destructive=allows_destructive,
    )


def load_migrations(
    package: str = MIGRATION_PACKAGE,
    path: str | Path | None = None,
) -> list[Migration]:
    """อ่านไฟล์ `NNN_*.py` ทั้งหมด เรียงตามเลขนำหน้า

    `path` ใช้ในเทสต์ (ชี้ไปโฟลเดอร์ชั่วคราว) — ค่าเริ่มต้นคือโฟลเดอร์ของแพ็กเกจนี้
    """
    directory = (
        Path(path)
        if path is not None
        else Path(importlib.import_module(package).__path__[0])
    )

    migrations: list[Migration] = []
    prefixes: dict[str, str] = {}

    for file in sorted(directory.iterdir()):
        if not file.is_file() or file.suffix != ".py":
            continue
        match = _FILE_RE.match(file.stem)
        if match is None:
            continue  # `__init__.py`, helper, ฯลฯ

        prefix = match.group(1)
        if prefix in prefixes:
            raise MigrationError(
                f"เลข migration ซ้ำ: {prefixes[prefix]} และ {file.stem} "
                "— ต้องมีเลขนำหน้าไม่ซ้ำกัน"
            )
        prefixes[prefix] = file.stem

        migrations.append(_to_migration(file))

    migrations.sort(key=lambda m: m.version)
    return migrations


# ═════════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════════
async def _acquire_lock(conn: asyncpg.Connection) -> None:
    """ถือ advisory lock ระดับ session แบบมีเพดานเวลา (ดู docstring หัวไฟล์)"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LOCK_WAIT_SECONDS

    while True:
        if await conn.fetchval("SELECT pg_try_advisory_lock($1)", APPLY_LOCK_KEY):
            return
        if loop.time() >= deadline:
            raise MigrationError(
                f"รอ advisory lock ({APPLY_LOCK_KEY}) ไม่สำเร็จภายใน {LOCK_WAIT_SECONDS:.0f} วิ "
                "— อาจมี replica อื่นค้างอยู่ระหว่าง apply"
            )
        await asyncio.sleep(LOCK_POLL_SECONDS)


async def _release_lock(conn: asyncpg.Connection) -> None:
    try:
        await conn.execute("SELECT pg_advisory_unlock($1)", APPLY_LOCK_KEY)
    except Exception as exc:  # noqa: BLE001 — connection หลุด = lock ถูกปล่อยเองอยู่แล้ว
        logger.warning("ปล่อย advisory lock ไม่สำเร็จ (%s) — connection จะปล่อยให้เอง", exc)


async def apply_migrations(
    pool: asyncpg.Pool,
    migrations: Sequence[Migration] | None = None,
) -> int:
    """apply migration ที่ยังไม่เคยรัน คืน **จำนวนไฟล์ที่รันรอบนี้**

    - `0` = สคีมาทันสมัยแล้ว (ไม่ใช่ "โค้ดไม่เคยรัน") ⇒ assert ค่านี้ได้
    - ไฟล์ที่เคย apply แล้ว checksum ต่างจากในโค้ด ⇒ `MigrationDriftError`
    - ไฟล์ที่ล้มกลางทาง ⇒ rollback ทั้งไฟล์ ไม่มีแถวใน `schema_migrations`
    """
    pending_source = list(migrations) if migrations is not None else load_migrations()
    if not pending_source:
        logger.info("ไม่พบไฟล์ migration — ไม่มีอะไรต้อง apply")
        return 0

    async with pool.acquire() as conn:
        await _acquire_lock(conn)
        try:
            await conn.execute(_CREATE_TABLE_SQL)

            rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
            applied = {row["version"]: row["checksum"] for row in rows}

            ran = 0
            for migration in pending_source:
                stored = applied.get(migration.version)

                if stored is not None:
                    if stored != migration.checksum:
                        raise MigrationDriftError(
                            f"{migration.version}: ไฟล์ถูกแก้หลัง apply ไปแล้ว "
                            f"(DB={stored[:12]}…, ไฟล์={migration.checksum[:12]}…) "
                            "— ห้ามแก้ migration เดิม ให้เขียนไฟล์ใหม่ต่อท้าย"
                        )
                    continue

                # transaction ต่อไฟล์ ⇒ ไฟล์ที่ล้มไม่ทิ้งสภาพครึ่ง ๆ
                async with conn.transaction():
                    for statement in migration.statements:
                        await conn.execute(statement)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                        migration.version,
                        migration.checksum,
                    )

                ran += 1
                logger.info("✅ apply migration %s", migration.version)

            if ran == 0:
                logger.info(
                    "schema ทันสมัยแล้ว (%d migration ในโค้ด, ไม่มีไฟล์ใหม่)",
                    len(pending_source),
                )
            return ran
        finally:
            await _release_lock(conn)
