"""ระบบ migration แบบ additive ของระบบนี้ — ดูรายละเอียดที่ `runner.py`

การใช้งานจริงมีที่เดียว: `main.py` lifespan เรียก `apply_migrations(pool)` หลัง `init_db(pool)`
(ทุก replica เรียก — runner จัดการ lock ให้เอง)
"""

from core.migrations.runner import (
    APPLY_LOCK_KEY,
    DestructiveMigrationError,
    Migration,
    MigrationDriftError,
    MigrationError,
    apply_migrations,
    checksum_of,
    load_migrations,
)

__all__ = [
    "APPLY_LOCK_KEY",
    "DestructiveMigrationError",
    "Migration",
    "MigrationDriftError",
    "MigrationError",
    "apply_migrations",
    "checksum_of",
    "load_migrations",
]
