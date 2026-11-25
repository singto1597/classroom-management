"""🖨️ [FIN-V2 / P4.6] PDF หลายใบต่อไฟล์ + route ดาวน์โหลด PV/INC

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ไฟล์รวม N ใบ = N กรอบ `.doc`** และมี `.doc-break` คั่นทุกหน้า ยกเว้นหน้าสุดท้าย
   — padding อยู่ที่ `.doc` (บทเรียน skills: ถ้าย้ายไป `body` หน้าถัดไปจะกินขอบซ้ำ)
2. **`<style>` เดียว ฟอนต์ 2 ไฟล์** ไม่ว่าจะกี่ใบ (data URI ฝังครั้งเดียว ไม่บวมตาม N)
3. **แต่ละ partial ถูกเรนเดอร์ครั้งเดียวต่อใบ** — ไม่มีใบไหนได้เนื้อหาของอีกชนิด
4. **แบนเนอร์ VOID เฉพาะใบที่ยกเลิก** — ใบข้างเคียงในไฟล์เดียวกันต้องไม่ติดไปด้วย
5. **bundle ผสม legacy + v2 ได้** — ใบเก่าใช้ partial เดิม ใบใหม่ใช้ partial ของชนิด
6. **route PDF ของ PV/INC เปิดให้สมาชิกของห้อง** แต่ **ข้ามห้อง = 404** (ไม่ใช่ 403
   เพราะไม่ควรยืนยันด้วยซ้ำว่า id นั้นมีอยู่จริงในระบบ)
7. **ไม่พบเอกสาร = 404 · Gotenberg ล่ม = 502** (ผู้เรียกแยก "ขอผิด" กับ "ลองใหม่ได้" ออก)

⚠️ ยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md) — เอกสารถูกสร้าง
   ผ่าน API จริง (P4.1/P4.4) ไม่ได้ใส่แถวปลอม ⇒ snapshot มีรูปเดียวกับของจริง
"""
import random
import re
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from services.finance.pdf import PdfRenderError, render_receipts_html
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FAKE_PDF = b"%PDF-1.4 fake-pdf-bytes"
_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════ helpers
def _money(value) -> str:
    return f"{float(value):.2f}"


def _new_key() -> str:
    return uuid.uuid4().hex


def _base_doc(doc_type: str, receipt_no: str, **over) -> dict:
    base = {
        "doc_type": doc_type,
        "doc_type_label": None,
        "receipt_no": receipt_no,
        "amount": 350.0,
        "paid_total_after": 0.0,
        "issued_to_name": "ร้านวัสดุทดสอบ",
        "issued_by_name": "ครูผู้จัดทำ",
        "event_at": _FIXED_AT,
        "issued_at": _FIXED_AT,
        "status": "active",
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "student_no": None,
        "note": None,
        "layout_version": 2,
        "document_meta": {},
        "line_items": None,
        "voucher_snapshot": None,
    }
    base.update(over)
    return base


def _pv_doc(**over) -> dict:
    snapshot = {
        "layout_version": 2,
        "payee_name": "ร้านวัสดุทดสอบ",
        "voucher_date": "2026-11-20",
        "total_amount": 350.0,
        "default_wallet": {"id": 11, "name": "เงินสดห้อง"},
        "lines": [
            {"line_no": 1, "description": "กระดาษ A4", "amount": 250.0,
             "category_name": "วัสดุสำนักงาน", "budget_label": None,
             "wallet_name": "เงินสดห้อง", "receipt_status": "none",
             "paper_bill_count": 0, "funding_source": "room_fund"},
            {"line_no": 2, "description": "ค่าขนส่ง", "amount": 100.0,
             "category_name": "ค่าขนส่ง", "budget_label": None,
             "wallet_name": "เงินสดห้อง", "receipt_status": "none",
             "paper_bill_count": 0, "funding_source": "room_fund"},
        ],
        "signatures": [
            {"role": "prepared", "signer_name": "ครูผู้จัดทำ"},
            {"role": "approved", "signer_name": "ครูอนุมัติ"},
            {"role": "receiver", "signer_name": "ร้านวัสดุทดสอบ"},
        ],
        "total_paper_bill_count": 0,
    }
    doc = _base_doc(
        "payment_voucher", "PV-2569-0001",
        document_meta={"voucher_id": 1, "signatures": snapshot["signatures"]},
        voucher_snapshot=snapshot,
    )
    doc.update(over)
    return doc


def _cert_doc(**over) -> dict:
    doc = _base_doc(
        "certificate", "CERT-2569-0001",
        document_meta={
            "voucher_no": "PV-2569-0001",
            "source_line_nos": [1, 2],
            "signatures": [
                {"role": "prepared", "signer_name": "ครูผู้จัดทำ"},
                {"role": "approved", "signer_name": "ครูอนุมัติ"},
            ],
        },
        line_items=[
            {"title": "กระดาษ A4", "amount_applied": "250.00"},
            {"title": "ค่าขนส่ง", "amount_applied": "100.00"},
        ],
    )
    doc.update(over)
    return doc


def _inc_doc(**over) -> dict:
    channel = {"channel_type": "cash", "label": "เงินสดหน้าร้าน"}
    signatures = [
        {"role": "prepared", "signer_name": "ครูผู้บันทึก"},
        {"role": "receiver", "signer_name": "ครูสมหญิง"},
    ]
    doc = _base_doc(
        "income", "INC-2569-0001",
        amount=2500.0,
        issued_to_name="ผู้ปกครองนักเรียน ม.2",
        issued_by_name="ครูผู้บันทึก",
        document_meta={"receiver_name": "ครูสมหญิง", "channel": channel,
                       "signatures": signatures},
        voucher_snapshot={"wallet": {"id": 11, "name": "เงินสดหน้าร้าน"},
                          "channel": channel, "signatures": signatures},
        line_items=[
            {"title": "เงินสนับสนุนกิจกรรม", "amount_applied": "2000.00"},
            {"title": "ขายของที่ระลึก", "amount_applied": "500.00"},
        ],
    )
    doc.update(over)
    return doc


def _legacy_doc(**over) -> dict:
    base = {
        "doc_type": "receipt",
        "doc_type_label": "ใบเสร็จรับเงิน",
        "receipt_no": "REC-2569-0099",
        "amount": 500.0,
        "paid_total_after": 500.0,
        "issued_to_name": "เด็กชายเก่า",
        "issued_by_name": "ครูเก่า",
        "event_at": _FIXED_AT,
        "issued_at": _FIXED_AT,
        "status": "active",
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "student_no": 3,
        "note": None,
        "layout_version": 1,
        "collection_title": "ค่าเทอม",
        "collection_due_date": None,
        "collection_amount": None,
        "line_items": None,
        "approver_name": None,
        "attachment_count": 0,
        "account_name": None,
        "category_name": None,
        "budgets": [],
    }
    base.update(over)
    return base


def _bundle_html(docs: list) -> str:
    return render_receipts_html([FinanceService._document_context(d) for d in docs])


async def _insert_category(pool, room_id: int, name: str, cat_type: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, cat_type,
        )


async def _insert_account(
    pool, room_id: int, name: str, balance: float = 0.0,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, balance,
        )


async def _add_member(pool, room_id: int, api_key: str) -> dict:
    """ผู้ใช้ใหม่ + students row ในห้องเดิม (ไม่ใช่ admin, ไม่มีสิทธิ์) — คืน headers

    🔑 ใช้เส้นทาง API key เหมือน `conftest._provision_auth_context` แต่ผูกกับห้องที่
       มีอยู่แล้ว (fixture มาตรฐานสร้างห้องใหม่ให้ทุกตัว ⇒ ยิงเข้าเอกสารของ admin ไม่ได้)
    """
    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (email, first_name, last_name, username, discord_id)
               VALUES (NULL, 'Member', 'User', $1, $2) RETURNING id""",
            f"m{uuid.uuid4().hex[:12]}", discord_id,
        )
        await conn.execute(
            """INSERT INTO students
                   (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 2, 'student', 'active', FALSE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return {"X-API-Key": api_key, "X-Discord-Id": str(discord_id)}


async def _seed_voucher(client, db_pool, headers) -> dict:
    """สร้างใบสำคัญจ่าย 2 บรรทัดผ่าน API จริง — คืน response body"""
    room = headers.room_id
    cat_a = await _insert_category(db_pool, room, "วัสดุสำนักงาน", "expense")
    cat_b = await _insert_category(db_pool, room, "ค่าขนส่ง", "expense")
    wallet = await _insert_account(db_pool, room, "เงินสดห้อง", 1000.0)
    payload = {
        "idempotency_key": _new_key(),
        "default_wallet_account_id": wallet,
        "payee_name": "ร้านวัสดุทดสอบ",
        "approved_by_name": "ครูอนุมัติ",
        "note": "ทดสอบพิมพ์ PV",
        "lines": [
            {"description": "กระดาษ A4", "amount": _money(250.0),
             "category_id": cat_a, "wallet_account_id": wallet,
             "receipt_status": "attached", "paper_bill_count": 1,
             "funding_source": "room_fund"},
            {"description": "ค่าขนส่ง", "amount": _money(100.0),
             "category_id": cat_b, "wallet_account_id": wallet,
             "receipt_status": "none", "paper_bill_count": 0,
             "funding_source": "room_fund"},
        ],
    }
    res = client.post(
        f"{API_PREFIX}/{room}/finance/expense-vouchers?target_type=room",
        json=payload, headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _seed_batch(client, db_pool, headers) -> dict:
    """สร้างใบรับเงิน 2 บรรทัดผ่าน API จริง — คืน response body"""
    room = headers.room_id
    cat_a = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม", "income")
    cat_b = await _insert_category(db_pool, room, "ขายของที่ระลึก", "income")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)
    payload = {
        "idempotency_key": _new_key(),
        "payer_name": "ผู้ปกครองนักเรียน ม.2",
        "receiver_name": "ครูสมหญิง",
        "wallet_account_id": wallet,
        "note": "ทดสอบพิมพ์ INC",
        "lines": [
            {"description": "เงินสนับสนุนกิจกรรม", "amount": _money(2000.0),
             "category_id": cat_a},
            {"description": "ขายของที่ระลึก", "amount": _money(500.0),
             "category_id": cat_b},
        ],
    }
    res = client.post(
        f"{API_PREFIX}/{room}/finance/income-batches?target_type=room",
        json=payload, headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _voucher_pdf_url(room_id: int, voucher_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/expense-vouchers/"
        f"{voucher_id}/pdf?target_type=room"
    )


def _batch_pdf_url(room_id: int, batch_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/income-batches/"
        f"{batch_id}/pdf?target_type=room"
    )


# ═══════════ 14. N ใบ = N กรอบ `.doc` + `.doc-break` ระหว่างหน้า
async def test_multi_doc_renders_one_page_wrapper_per_document():
    html = _bundle_html([_pv_doc(), _cert_doc(), _inc_doc()])
    pages = re_find_pages(html)
    assert len(pages) == 3
    assert pages.count("doc-break") == 2, "ทุกหน้า ยกเว้นหน้าสุดท้าย ต้องมีตัวแบ่งหน้า"
    # padding ของระยะขอบอยู่ที่ `.doc` (ไม่ใช่ body)
    # 🖨️ [A4] shell v2 ใช้ระยะขอบมาตรฐาน 13/15/11 (legacy-only ยังได้ 14/14/10)
    #    กฎ `.doc` ของ shell v2 เขียนหลายบรรทัด ⇒ จับด้วย regex ไม่ใช่ substring ตรง ๆ
    assert re.search(r"\.doc\s*\{[^}]*padding:\s*13mm 15mm 11mm", html)


def re_find_pages(html: str) -> list:
    """กรอบหน้าของ shell — `<div class="doc">` หรือ `<div class="doc doc-break">`"""
    import re
    return [
        "doc-break" if "doc-break" in m.group(0) else "doc"
        for m in re.finditer(r'<div class="doc(?: doc-break)?">', html)
    ]


# ═══════════ 15. `<style>` เดียว + ฟอนต์ 2 ไฟล์ ไม่ว่าจะกี่ใบ
async def test_multi_doc_has_single_style_and_two_font_faces():
    html = _bundle_html([_pv_doc(), _cert_doc(), _inc_doc()])
    # 🔴 นับแท็กปิด — คอมเมนต์ใน <style> ของ shell อ้างคำว่า `<style>` (นับแท็กเปิดจะได้ 2)
    assert html.count("</style>") == 1
    assert html.count("data:font/ttf;base64,") == 2


# ═══════════ 16. เนื้อหาของแต่ละชนิดถูกเรนเดอร์ครั้งเดียว
async def test_each_document_body_rendered_exactly_once():
    html = _bundle_html([_pv_doc(), _cert_doc(), _inc_doc()])
    assert html.count("รายละเอียดการเบิก") == 1
    assert html.count("รายละเอียดที่รับรอง") == 1
    assert html.count("รายการรับเงิน") == 1


# ═══════════ 17. แบนเนอร์ VOID เฉพาะใบที่ยกเลิก
async def test_void_banner_only_on_voided_document():
    html = _bundle_html([
        _pv_doc(),
        _cert_doc(status="voided", void_reason="ออกซ้ำ"),
        _inc_doc(),
    ])
    # 🔴 นับ `class="void-banner"` — ชื่อคลาสปรากฏใน <style> ของ shell ด้วย
    assert html.count('class="void-banner"') == 1
    assert "ออกซ้ำ" in html


# ═══════════ 18. bundle ผสม legacy + v2 — ต่างคนต่าง partial
async def test_bundle_dispatches_legacy_and_v2_partials():
    legacy, pv = _legacy_doc(), _pv_doc()
    assert FinanceService._document_context(legacy)["body_template"] == "_receipt_body.html"
    assert FinanceService._document_context(pv)["body_template"] == "_voucher_body_v2.html"

    html = _bundle_html([legacy, pv])
    assert "ผู้ชำระเงิน" in html          # ถ้อยคำของ partial legacy
    assert "รายละเอียดการเบิก" in html     # ตารางของ partial PV v2
    # ⚠️ ห้ามนับ `class="doc` (จะโดน `class="doc-title"`) — ใช้ regex กรอบหน้าตรง ๆ
    assert len(re_find_pages(html)) == 2


# ═══════════ 19. route PV: สมาชิกของห้องดาวน์โหลดได้
async def test_expense_voucher_pdf_route_serves_room_member(
    client, db_pool, admin_headers,
):
    body = await _seed_voucher(client, db_pool, admin_headers)
    member = await _add_member(
        db_pool, admin_headers.room_id, dict(admin_headers)["X-API-Key"],
    )

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(
            _voucher_pdf_url(admin_headers.room_id, body["id"]), headers=member,
        )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == FAKE_PDF
    assert f"{body['pv_receipt_no']}.pdf" in res.headers["content-disposition"]

    html = mock_render.await_args.args[0]
    assert body["pv_receipt_no"] in html
    assert "กระดาษ A4" in html
    assert "รายละเอียดการเบิก" in html


# ═══════════ 20. route PV: ข้ามห้อง = 404 (ไม่ยืนยันการมีอยู่ของ id)
async def test_expense_voucher_pdf_route_is_room_scoped(
    client, db_pool, admin_headers, member_headers,
):
    body = await _seed_voucher(client, db_pool, admin_headers)

    # `member_headers` อยู่ในห้องของตัวเอง (ไม่ใช่ห้องที่ใบนี้อยู่)
    res = client.get(
        _voucher_pdf_url(member_headers.room_id, body["id"]), headers=member_headers,
    )
    assert res.status_code == 404, res.text


# ═══════════ 21. route INC: สมาชิกของห้องดาวน์โหลดได้
async def test_income_batch_pdf_route_serves_room_member(
    client, db_pool, admin_headers,
):
    body = await _seed_batch(client, db_pool, admin_headers)
    member = await _add_member(
        db_pool, admin_headers.room_id, dict(admin_headers)["X-API-Key"],
    )

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(
            _batch_pdf_url(admin_headers.room_id, body["id"]), headers=member,
        )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == FAKE_PDF
    assert f"{body['inc_receipt_no']}.pdf" in res.headers["content-disposition"]

    html = mock_render.await_args.args[0]
    assert body["inc_receipt_no"] in html
    assert "เงินสนับสนุนกิจกรรม" in html
    assert "รายการรับเงิน" in html


# ═══════════ 22. route INC: ข้ามห้อง = 404
async def test_income_batch_pdf_route_is_room_scoped(
    client, db_pool, admin_headers, member_headers,
):
    body = await _seed_batch(client, db_pool, admin_headers)

    res = client.get(
        _batch_pdf_url(member_headers.room_id, body["id"]), headers=member_headers,
    )
    assert res.status_code == 404, res.text


# ═══════════ 23. ไม่พบเอกสาร = 404 ทั้งสอง route
async def test_pdf_routes_return_404_for_missing_document(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    assert client.get(
        _voucher_pdf_url(room, 999_999), headers=admin_headers,
    ).status_code == 404
    assert client.get(
        _batch_pdf_url(room, 999_999), headers=admin_headers,
    ).status_code == 404


# ═══════════ 24. Gotenberg ล่ม = 502 (ไม่ใช่ 500)
async def test_pdf_routes_map_gotenberg_failure_to_502(
    client, db_pool, admin_headers,
):
    voucher = await _seed_voucher(client, db_pool, admin_headers)
    batch = await _seed_batch(client, db_pool, admin_headers)

    async def boom(*_args, **_kwargs):
        raise PdfRenderError("Gotenberg ไม่ตอบ")

    with patch("services.finance.pdf.html_to_pdf", new=boom):
        res_v = client.get(
            _voucher_pdf_url(admin_headers.room_id, voucher["id"]),
            headers=admin_headers,
        )
        res_i = client.get(
            _batch_pdf_url(admin_headers.room_id, batch["id"]),
            headers=admin_headers,
        )

    assert res_v.status_code == 502, res_v.text
    assert res_i.status_code == 502, res_i.text
    assert "Gotenberg" in res_v.json()["detail"]
    assert "Gotenberg" in res_i.json()["detail"]
