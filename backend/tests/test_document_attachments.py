"""📎 ต่อท้ายไฟล์แนบ (รูป + PDF) เข้าเอกสาร PDF — จำนวนหน้า/ลำดับ/A4/ไม่มีไฟล์แนบ"""
import io
import uuid

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from services import finance_attachments as svc
from services.finance.document_attachments import append_attachments_to_receipts


def _png_bytes(width=800, height=600) -> bytes:
    im = Image.new("RGB", (width, height), (10, 180, 60))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _pdf_bytes(pages=2) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


async def _make_transaction(pool, room_id) -> int:
    account_id = await pool.fetchval(
        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'cash', 1000) RETURNING id",
        room_id,
    )
    category_id = await pool.fetchval(
        """INSERT INTO finance_categories (room_id, category_name, category_type)
           VALUES ($1, 'อาหาร', 'expense') RETURNING id""",
        room_id,
    )
    return await pool.fetchval(
        """INSERT INTO finance_transactions
               (room_id, account_id, category_id, amount, description,
                transaction_type, recorded_by)
           VALUES ($1, $2, $3, 100, 'test', 'expense', 'tester')
           RETURNING id""",
        room_id, account_id, category_id,
    )


async def _make_receipt(pool, room_id, *, txn_id=None, payment_id=None) -> int:
    return await pool.fetchval(
        """INSERT INTO finance_receipts
               (room_id, receipt_no, doc_type, year_be, seq, amount, paid_total_after,
                legacy_transaction_id, student_payment_id)
           VALUES ($1, $2, 'receipt', 2569, 1, 100, 100, $3, $4)
           RETURNING id""",
        room_id, f"REC-TEST-{uuid.uuid4().hex[:8]}", txn_id, payment_id,
    )


@pytest.mark.asyncio
async def test_appends_images_and_pdf_after_document(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id)
    await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [
            ("a.png", _png_bytes()),
            ("b.png", _png_bytes(400, 300)),
            ("c.pdf", _pdf_bytes(pages=2)),
        ],
    )
    receipt_id = await _make_receipt(db_pool, ctx.room_id, txn_id=txn_id)

    base = _pdf_bytes(pages=2)
    merged = await append_attachments_to_receipts(db_pool, [{"id": receipt_id}], base)

    # 2 หน้าเอกสาร + 2 รูป (รูปละ 1 หน้า) + PDF 2 หน้า
    assert _page_count(merged) == 6

    reader = PdfReader(io.BytesIO(merged))
    # หน้าแรก ๆ ต้องเป็นเอกสารหลัก (A4 จาก base 595×842)
    for i in range(2):
        assert abs(float(reader.pages[i].mediabox.width) - 595) < 2
    # หน้ารูปถูกจัดเป็น A4 ที่ 150dpi (1240px/150*72 = 595.2 pt)
    for i in range(2, 4):
        assert abs(float(reader.pages[i].mediabox.width) - 595.2) < 2
        assert abs(float(reader.pages[i].mediabox.height) - 841.0) < 3


@pytest.mark.asyncio
async def test_no_attachments_returns_original_bytes(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id)
    receipt_id = await _make_receipt(db_pool, ctx.room_id, txn_id=txn_id)
    base = _pdf_bytes(pages=1)
    merged = await append_attachments_to_receipts(db_pool, [{"id": receipt_id}], base)
    assert merged == base


@pytest.mark.asyncio
async def test_student_payment_owner_is_resolved(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    collection_id = await db_pool.fetchval(
        "INSERT INTO fee_collections (room_id, title, amount) VALUES ($1, 'ค่าอาหาร', 100) RETURNING id",
        ctx.room_id,
    )
    payment_id = await db_pool.fetchval(
        """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
           VALUES ($1, $2, 'paid', 100) RETURNING id""",
        collection_id, ctx.student_id,
    )
    await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "student_payment", payment_id,
        [("slip.png", _png_bytes())],
    )
    receipt_id = await _make_receipt(db_pool, ctx.room_id, payment_id=payment_id)

    merged = await append_attachments_to_receipts(
        db_pool, [{"id": receipt_id}], _pdf_bytes(pages=1)
    )
    assert _page_count(merged) == 2


@pytest.mark.asyncio
async def test_batch_appends_each_receipt_once(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_a = await _make_transaction(db_pool, ctx.room_id)
    txn_b = await _make_transaction(db_pool, ctx.room_id)
    await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_a,
        [("a.png", _png_bytes())],
    )
    await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_b,
        [("b.png", _png_bytes())],
    )
    rec_a = await _make_receipt(db_pool, ctx.room_id, txn_id=txn_a)
    rec_b = await _make_receipt(db_pool, ctx.room_id, txn_id=txn_b)

    merged = await append_attachments_to_receipts(
        db_pool, [{"id": rec_a}, {"id": rec_b}], _pdf_bytes(pages=2)
    )
    assert _page_count(merged) == 4  # 2 หน้าเอกสาร + รูปของ A + รูปของ B


@pytest.mark.asyncio
async def test_missing_attachment_file_is_skipped(db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id)
    uploaded = await svc.upload_attachments(
        db_pool, ctx.user_id, ctx.room_id, "transaction", txn_id,
        [("a.png", _png_bytes())],
    )
    receipt_id = await _make_receipt(db_pool, ctx.room_id, txn_id=txn_id)

    from core.media import get_media_storage
    row = await db_pool.fetchrow(
        "SELECT storage_path FROM finance_attachments WHERE id = $1",
        uuid.UUID(uploaded["items"][0]["id"]),
    )
    get_media_storage().local_path(row["storage_path"]).unlink()

    base = _pdf_bytes(pages=1)
    merged = await append_attachments_to_receipts(db_pool, [{"id": receipt_id}], base)
    assert _page_count(merged) == 1  # ไฟล์หาย → ข้าม แล้วพิมพ์เอกสารหลักต่อ
