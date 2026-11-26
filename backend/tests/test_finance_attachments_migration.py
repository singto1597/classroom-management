"""🧱 migration 0014_finance_attachments — ตาราง/ข้อจำกัด/apply ซ้ำต้อง no-op"""
import uuid

import asyncpg
import pytest

from core.migrations import apply_migrations


@pytest.mark.asyncio
async def test_migration_registered_and_idempotent(db_pool):
    stored = await db_pool.fetchval(
        "SELECT checksum FROM schema_migrations WHERE version = '0014_finance_attachments'"
    )
    assert stored, "migration 0014 ต้องถูก apply ใน DB ของเทสต์"

    # apply ซ้ำต้องไม่รันอะไรใหม่ (0 = สคีมาทันสมัยแล้ว)
    assert await apply_migrations(db_pool) == 0


@pytest.mark.asyncio
async def test_table_and_indexes_exist(db_pool):
    table = await db_pool.fetchval(
        "SELECT to_regclass('public.finance_attachments')"
    )
    assert table == "finance_attachments"

    indexes = {
        row["indexname"]
        for row in await db_pool.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'finance_attachments'"
        )
    }
    assert "idx_finance_attachments_owner" in indexes
    assert "idx_finance_attachments_uploader" in indexes
    assert "uq_finance_attachments_storage_path" in indexes


@pytest.mark.asyncio
async def test_constraints_reject_invalid_rows(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    account_id = await db_pool.fetchval(
        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'cash', 0) RETURNING id",
        ctx.room_id,
    )
    category_id = await db_pool.fetchval(
        """INSERT INTO finance_categories (room_id, category_name, category_type)
           VALUES ($1, 'อาหาร', 'expense') RETURNING id""",
        ctx.room_id,
    )
    txn_id = await db_pool.fetchval(
        """INSERT INTO finance_transactions
               (room_id, account_id, category_id, amount, description, transaction_type, recorded_by)
           VALUES ($1, $2, $3, 1, 't', 'expense', 't') RETURNING id""",
        ctx.room_id, account_id, category_id,
    )

    base = dict(
        owner_type="transaction",
        owner_id=txn_id,
        file_kind="image",
        kind="expense_evidence",
        uploaded_by=ctx.user_id,
        storage_path=f"media/finance/transaction/{txn_id}/{uuid.uuid4()}.webp",
        thumb_path=f"media/finance/transaction/{txn_id}/{uuid.uuid4()}_thumb.webp",
        sha256="a" * 64,
        thumb_sha256="b" * 64,
        mime="image/webp",
        bytes=10,
        width=10,
        height=10,
    )

    # แถวปกติผ่าน
    await db_pool.execute(
        """INSERT INTO finance_attachments
               (owner_type, owner_id, file_kind, kind, uploaded_by,
                storage_path, thumb_path, sha256, thumb_sha256, mime, bytes, width, height)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
        *[base[k] for k in (
            "owner_type", "owner_id", "file_kind", "kind", "uploaded_by",
            "storage_path", "thumb_path", "sha256", "thumb_sha256",
            "mime", "bytes", "width", "height",
        )],
    )

    # owner_type นอกรายการ → CHECK violation
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await db_pool.execute(
            """INSERT INTO finance_attachments
                   (owner_type, owner_id, file_kind, kind, storage_path, sha256, mime, bytes,
                    thumb_path, width, height)
               VALUES ('board', 1, 'image', 'other', $1, $2, 'image/webp', 10, $3, 1, 1)""",
            f"media/finance/transaction/{txn_id}/{uuid.uuid4()}.webp",
            "a" * 64,
            f"media/finance/transaction/{txn_id}/{uuid.uuid4()}_thumb.webp",
        )

    # image ต้องมี thumb + width/height → CHECK violation
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await db_pool.execute(
            """INSERT INTO finance_attachments
                   (owner_type, owner_id, file_kind, kind, storage_path, sha256, mime, bytes)
               VALUES ('transaction', $1, 'image', 'other', $2, $3, 'image/webp', 10)""",
            txn_id,
            f"media/finance/transaction/{txn_id}/{uuid.uuid4()}.webp",
            "a" * 64,
        )

    # storage_path ซ้ำ → unique violation
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await db_pool.execute(
            """INSERT INTO finance_attachments
                   (owner_type, owner_id, file_kind, kind, storage_path, sha256, mime, bytes,
                    thumb_path, width, height)
               VALUES ('transaction', $1, 'image', 'other', $2, $3, 'image/webp', 10, $4, 1, 1)""",
            txn_id,
            base["storage_path"],
            "a" * 64,
            f"media/finance/transaction/{txn_id}/{uuid.uuid4()}_thumb.webp",
        )
