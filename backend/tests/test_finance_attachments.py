"""📎 ไฟล์หลักฐานการเงิน — service layer (รูป + PDF, สิทธิ์, โควตา, serve, soft delete)"""
import io
import uuid

import pytest
from PIL import Image
from pypdf import PdfWriter

from core.config import settings
from core.exceptions import (
    FinanceAttachmentNotFoundError,
    ForbiddenError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
)
from core.media import get_media_storage
from core.media_signing import sign_url
from services import finance_attachments as svc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _png_bytes(width=800, height=600) -> bytes:
    im = Image.new("RGB", (width, height), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _pdf_bytes(pages=2, encrypted=False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if encrypted:
        writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def _make_transaction(pool, room_id, user_id, txn_type="expense") -> int:
    account_id = await pool.fetchval(
        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'cash', 1000) RETURNING id",
        room_id,
    )
    category_id = await pool.fetchval(
        """INSERT INTO finance_categories (room_id, category_name, category_type)
           VALUES ($1, 'อาหาร', $2) RETURNING id""",
        room_id, txn_type,
    )
    return await pool.fetchval(
        """INSERT INTO finance_transactions
               (room_id, account_id, category_id, amount, description,
                transaction_type, recorded_by)
           VALUES ($1, $2, $3, 100, 'test', $4, 'tester')
           RETURNING id""",
        room_id, account_id, category_id, txn_type,
    )


async def _make_student_payment(pool, room_id, student_id) -> int:
    collection_id = await pool.fetchval(
        """INSERT INTO fee_collections (room_id, title, amount)
           VALUES ($1, 'ค่าอาหาร', 100) RETURNING id""",
        room_id,
    )
    return await pool.fetchval(
        """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
           VALUES ($1, $2, 'pending', 0) RETURNING id""",
        collection_id, student_id,
    )


async def _make_payment_event(pool, room_id, student_id, user_id) -> int:
    account_id = await pool.fetchval(
        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'cash', 1000) RETURNING id",
        room_id,
    )
    return await pool.fetchval(
        """INSERT INTO finance_payment_events
               (room_id, student_id, payer_name, receiver_name, wallet_account_id,
                amount_received, total_applied, idempotency_key)
           VALUES ($1, $2, 'payer', 'receiver', $3, 10, 10, $4)
           RETURNING id""",
        room_id, student_id, account_id, f"evt-{uuid.uuid4().hex}",
    )


# ---------------------------------------------------------------------------
# upload — รูป + PDF
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_image_stores_webp_and_thumb(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)

    result = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("slip.png", _png_bytes())],
    )

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["file_kind"] == "image"
    assert item["mime"] == "image/webp"
    assert item["thumb_url"] is not None
    assert item["kind"] == "expense_evidence"
    assert item["width"] == 800 and item["height"] == 600

    row = await db_pool.fetchrow(
        "SELECT * FROM finance_attachments WHERE id = $1", uuid.UUID(item["id"])
    )
    assert row["deleted_at"] is None
    assert row["page_count"] is None

    storage = get_media_storage()
    assert await storage.exists(row["storage_path"])
    assert await storage.exists(row["thumb_path"])

    # audit ถูกเขียนใน transaction เดียวกัน
    audit = await db_pool.fetchval(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'CREATE_FINANCE_ATTACHMENT'"
    )
    assert audit == 1


@pytest.mark.asyncio
async def test_upload_pdf_is_sanitized_and_counts_pages(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id, "income")

    result = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("receipt.pdf", _pdf_bytes(pages=3))],
    )

    item = result["items"][0]
    assert item["file_kind"] == "pdf"
    assert item["mime"] == "application/pdf"
    assert item["page_count"] == 3
    assert item["thumb_url"] is None
    assert item["kind"] == "payment_proof"

    row = await db_pool.fetchrow(
        "SELECT * FROM finance_attachments WHERE id = $1", uuid.UUID(item["id"])
    )
    assert row["thumb_path"] is None
    assert row["width"] is None and row["height"] is None


@pytest.mark.asyncio
async def test_filename_path_is_stripped(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    result = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("../../etc/passwd.png", _png_bytes())],
    )
    assert result["items"][0]["original_name"] == "passwd.png"


# ---------------------------------------------------------------------------
# owner types
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_to_student_payment(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    payment_id = await _make_student_payment(db_pool, ctx.room_id, ctx.student_id)
    result = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "student_payment", payment_id,
        [("slip.png", _png_bytes())],
    )
    assert result["items"][0]["kind"] == "payment_proof"


@pytest.mark.asyncio
async def test_upload_to_payment_event(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    event_id = await _make_payment_event(db_pool, ctx.room_id, ctx.student_id, ctx.user_id)
    result = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "payment_event", event_id,
        [("slip.pdf", _pdf_bytes(pages=1))],
    )
    assert result["items"][0]["kind"] == "payment_proof"


# ---------------------------------------------------------------------------
# permissions / isolation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_member_cannot_upload(db_pool, member_headers):
    ctx = member_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    with pytest.raises(ForbiddenError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("slip.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_cross_room_transaction_is_not_found(db_pool, finance_manager_headers, member_headers):
    """ผู้จัดการห้อง A ต้องแนบกับรายการของห้อง B ไม่ได้ (404 ไม่ใช่ 403 — ไม่ยืนยันว่ามีอยู่)"""
    a, b = finance_manager_headers, member_headers
    txn_in_b = await _make_transaction(db_pool, b.room_id, b.user_id)
    with pytest.raises(FinanceAttachmentNotFoundError):
        await svc.upload_attachments(
            db_pool, a.user_id, a.room_id, "transaction", txn_in_b,
            [("slip.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_missing_owner_is_not_found(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    with pytest.raises(FinanceAttachmentNotFoundError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", 999_999_999,
            [("slip.png", _png_bytes())],
        )


# ---------------------------------------------------------------------------
# validation / quotas
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rejects_non_image_non_pdf(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    with pytest.raises(ValidationError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("evil.gif", b"GIF89a" + b"x" * 100)],
        )


@pytest.mark.asyncio
async def test_rejects_encrypted_pdf(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    with pytest.raises(ValidationError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("secret.pdf", _pdf_bytes(pages=1, encrypted=True))],
        )


@pytest.mark.asyncio
async def test_rejects_too_many_pdf_pages(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_MAX_PDF_PAGES", 1)
    with pytest.raises(ValidationError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("many.pdf", _pdf_bytes(pages=2))],
        )


@pytest.mark.asyncio
async def test_rejects_too_many_files_per_request(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_MAX_UPLOAD_PER_REQUEST", 1)
    with pytest.raises(ValidationError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("a.png", _png_bytes()), ("b.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_enforces_per_owner_limit(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_MAX_FINANCE_ATTACHMENTS", 1)
    await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    with pytest.raises(ValidationError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("b.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_enforces_hourly_limit(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_MAX_UPLOAD_PER_HOUR", 0)
    with pytest.raises(RateLimitError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("a.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_enforces_total_bytes(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_MAX_ATTACHMENT_BYTES_TOTAL_MB", 0)
    with pytest.raises(PayloadTooLargeError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("a.png", _png_bytes())],
        )


@pytest.mark.asyncio
async def test_rejects_oversized_file(db_pool, finance_manager_headers, monkeypatch):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_IMAGE_SIZE_LIMIT_MB", 0)
    with pytest.raises(PayloadTooLargeError):
        await svc.upload_attachments(
            db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
            [("big.png", _png_bytes())],
        )


# ---------------------------------------------------------------------------
# list / delete / serve
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_and_soft_delete(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    uploaded = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    item = uploaded["items"][0]

    listed = await svc.list_attachments(db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id)
    assert len(listed["items"]) == 1
    assert listed["items"][0]["url"].startswith("/api/finance-files/")

    row_before = await db_pool.fetchrow(
        "SELECT * FROM finance_attachments WHERE id = $1", uuid.UUID(item["id"])
    )
    storage = get_media_storage()
    assert await storage.exists(row_before["storage_path"])

    await svc.delete_attachment(db_pool, ctx.user_id, ctx.room_id, item["id"])

    row_after = await db_pool.fetchrow(
        "SELECT * FROM finance_attachments WHERE id = $1", uuid.UUID(item["id"])
    )
    assert row_after["deleted_at"] is not None
    # ไฟล์ยังอยู่จนกว่า purge (กู้คืนได้ภายใน 30 วัน)
    assert await storage.exists(row_after["storage_path"])

    listed2 = await svc.list_attachments(db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id)
    assert listed2["items"] == []


@pytest.mark.asyncio
async def test_member_can_list_but_cannot_delete(db_pool, finance_manager_headers, member_headers):
    mgr, mem = finance_manager_headers, member_headers
    # same room: ให้ member อยู่ในห้องของ manager
    await db_pool.execute(
        """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
           VALUES ($1, $2, 2, 'student', 'active', FALSE, '[]'::jsonb)""",
        mgr.room_id, mem.user_id,
    )
    txn_id = await _make_transaction(db_pool, mgr.room_id, mgr.user_id)
    uploaded = await svc.upload_attachments(
        db_pool, mgr.user_id, mgr.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )

    listed = await svc.list_attachments(db_pool, mem.user_id, mgr.room_id, "transaction", txn_id)
    assert len(listed["items"]) == 1

    with pytest.raises(ForbiddenError):
        await svc.delete_attachment(db_pool, mem.user_id, mgr.room_id, uploaded["items"][0]["id"])


@pytest.mark.asyncio
async def test_serve_signed_url_and_rejects_tampering(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    uploaded = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    item = uploaded["items"][0]
    url = item["url"]
    # ใช้ sign_url ตรง ๆ เพื่อดึงค่า exp/sig
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(url).query)

    row, path = await svc.resolve_attachment_for_serving(
        db_pool, item["id"], q["variant"][0], q["viewer"][0], q["exp"][0], q["sig"][0]
    )
    assert path.is_file()
    assert row["file_kind"] == "image"

    with pytest.raises(ForbiddenError):
        await svc.resolve_attachment_for_serving(
            db_pool, item["id"], "full", str(ctx.user_id + 1), q["exp"][0], q["sig"][0]
        )
    with pytest.raises(ForbiddenError):
        await svc.resolve_attachment_for_serving(
            db_pool, item["id"], "full", q["viewer"][0], q["exp"][0], "AAAA"
        )


@pytest.mark.asyncio
async def test_serve_missing_file_is_not_found(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    uploaded = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    item = uploaded["items"][0]
    row = await db_pool.fetchrow(
        "SELECT * FROM finance_attachments WHERE id = $1", uuid.UUID(item["id"])
    )
    get_media_storage().local_path(row["storage_path"]).unlink()

    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(item["url"]).query)
    with pytest.raises(FinanceAttachmentNotFoundError):
        await svc.resolve_attachment_for_serving(
            db_pool, item["id"], q["variant"][0], q["viewer"][0], q["exp"][0], q["sig"][0]
        )


@pytest.mark.asyncio
async def test_serve_path_traversal_is_not_found(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    uploaded = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    item = uploaded["items"][0]
    await db_pool.execute(
        "UPDATE finance_attachments SET storage_path = '../../etc/passwd' WHERE id = $1",
        uuid.UUID(item["id"]),
    )
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(item["url"]).query)
    with pytest.raises(FinanceAttachmentNotFoundError):
        await svc.resolve_attachment_for_serving(
            db_pool, item["id"], q["variant"][0], q["viewer"][0], q["exp"][0], q["sig"][0]
        )
