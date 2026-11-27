"""📎 ไฟล์หลักฐานการเงิน — HTTP layer (upload/list/delete/serve) + API contract"""
import io
import uuid
from urllib.parse import urlsplit

import pytest
from PIL import Image
from pypdf import PdfWriter


def _png_bytes(width=800, height=600) -> bytes:
    im = Image.new("RGB", (width, height), (30, 120, 200))
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


async def _make_receipt(pool, room_id) -> int:
    return await pool.fetchval(
        """INSERT INTO finance_receipts
               (room_id, receipt_no, doc_type, year_be, seq, amount, paid_total_after)
           VALUES ($1, $2, 'receipt', 2569, 1, 100, 100)
           RETURNING id""",
        room_id, f"REC-TEST-{uuid.uuid4().hex[:8]}",
    )


def _upload_url(ctx, owner_type, owner_id):
    return f"/api/classroom/{ctx.room_id}/finance/attachments/{owner_type}/{owner_id}?target_type=room"


@pytest.mark.asyncio
async def test_upload_list_delete_and_serve(client, db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)

    res = client.post(
        _upload_url(ctx, "transaction", txn_id),
        headers=ctx,
        files=[("files", ("slip.png", _png_bytes(), "image/png"))],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["file_kind"] == "image"
    assert item["url"].startswith("/api/finance-files/")

    listed = client.get(_upload_url(ctx, "transaction", txn_id), headers=ctx)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    # เสิร์ฟด้วย signed URL — **ไม่มี auth header**
    img = client.get(item["url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/webp"
    assert "private" in img.headers["cache-control"]
    assert img.headers["x-content-type-options"] == "nosniff"

    # ?download=1 → บังคับดาวน์โหลด (ลายเซ็นเดิม)
    dl = client.get(item["url"] + "&download=1")
    assert dl.status_code == 200
    assert dl.headers["content-disposition"].startswith("attachment;")

    # URL ที่ถูกแก้ (viewer) ต้อง 403
    parts = urlsplit(item["url"])
    tampered = parts.path + "?variant=full&viewer=999999&exp=1&sig=AAAA"
    assert client.get(tampered).status_code == 403

    deleted = client.delete(
        f"/api/classroom/{ctx.room_id}/finance/attachments/{item['id']}?target_type=room",
        headers=ctx,
    )
    assert deleted.status_code == 200, deleted.text

    assert client.get(_upload_url(ctx, "transaction", txn_id), headers=ctx).json()["items"] == []
    # ไฟล์ถูกลบแบบ soft ⇒ เปิดด้วย URL เดิมไม่ได้แล้ว
    assert client.get(item["url"]).status_code == 404


@pytest.mark.asyncio
async def test_upload_pdf_served_inline_with_sandbox(client, db_pool, finance_manager_headers):
    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id, "income")
    res = client.post(
        _upload_url(ctx, "transaction", txn_id),
        headers=ctx,
        files=[("files", ("bill.pdf", _pdf_bytes(pages=3), "application/pdf"))],
    )
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["file_kind"] == "pdf"
    assert item["page_count"] == 3
    assert item["thumb_url"] is None

    pdf = client.get(item["url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-security-policy"] == "sandbox"


@pytest.mark.asyncio
async def test_upload_to_receipt_owner(client, db_pool, finance_manager_headers):
    """แนบไฟล์เข้ากับใบเสร็จ/เอกสารโดยตรง (เพิ่มเติมภายหลัง)"""
    ctx = finance_manager_headers
    receipt_id = await _make_receipt(db_pool, ctx.room_id)
    res = client.post(
        _upload_url(ctx, "receipt", receipt_id),
        headers=ctx,
        files=[("files", ("evidence.pdf", _pdf_bytes(pages=1), "application/pdf"))],
    )
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["owner_type"] == "receipt"
    assert item["owner_id"] == receipt_id


@pytest.mark.asyncio
async def test_member_upload_forbidden(client, db_pool, member_headers):
    ctx = member_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    res = client.post(
        _upload_url(ctx, "transaction", txn_id),
        headers=ctx,
        files=[("files", ("slip.png", _png_bytes(), "image/png"))],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_invalid_owner_type_is_422(client, finance_manager_headers):
    ctx = finance_manager_headers
    res = client.get(
        f"/api/classroom/{ctx.room_id}/finance/attachments/not_a_type/1?target_type=room",
        headers=ctx,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_oversized_upload_413(client, db_pool, finance_manager_headers, monkeypatch):
    from core.config import settings

    ctx = finance_manager_headers
    txn_id = await _make_transaction(db_pool, ctx.room_id, ctx.user_id)
    monkeypatch.setattr(settings, "MEDIA_IMAGE_SIZE_LIMIT_MB", 0)
    monkeypatch.setattr(settings, "MEDIA_DOCUMENT_SIZE_LIMIT_MB", 0)
    res = client.post(
        _upload_url(ctx, "transaction", txn_id),
        headers=ctx,
        files=[("files", ("slip.png", _png_bytes(), "image/png"))],
    )
    assert res.status_code == 413


@pytest.mark.asyncio
async def test_create_transaction_returns_transaction_id_and_history_count(
    client, db_pool, finance_manager_headers
):
    ctx = finance_manager_headers
    account_id = await db_pool.fetchval(
        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'cash', 1000) RETURNING id",
        ctx.room_id,
    )
    category_id = await db_pool.fetchval(
        """INSERT INTO finance_categories (room_id, category_name, category_type)
           VALUES ($1, 'อาหาร', 'expense') RETURNING id""",
        ctx.room_id,
    )
    created = client.post(
        f"/api/classroom/{ctx.room_id}/finance/transactions?target_type=room",
        headers=ctx,
        json={
            "account_id": account_id,
            "category_id": category_id,
            "amount": 50,
            "description": "ซื้อของ",
            "transaction_type": "expense",
            "user_name": "tester",
            "payee_name": "ร้านค้า",
        },
    )
    assert created.status_code == 200, created.text
    txn_id = created.json()["transaction_id"]
    assert isinstance(txn_id, int) and txn_id > 0

    up = client.post(
        _upload_url(ctx, "transaction", txn_id),
        headers=ctx,
        files=[("files", ("slip.png", _png_bytes(), "image/png"))],
    )
    assert up.status_code == 200, up.text

    history = client.get(
        f"/api/classroom/{ctx.room_id}/finance/transactions?target_type=room&limit=50",
        headers=ctx,
    )
    assert history.status_code == 200, history.text
    match = [it for it in history.json()["items"] if it["id"] == txn_id]
    assert match and match[0]["attachment_file_count"] == 1
