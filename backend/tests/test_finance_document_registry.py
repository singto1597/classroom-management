"""🗂️ [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — union/filters/detail/links/bundle

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **union จริง** — รายการเดียวมีทั้ง `finance_receipts` (REC/INV/ACK/DEP/PV/CERT/INC)
   และ `finance_monthly_reports` (RPT); ถ้าใครถอด RPT ออกจาก CTE ทีหลัง test จับได้
2. **ตัวกรอง 7 มิติ** — ชนิด/ช่วงวันไทย (ครึ่งเปิด)/นักเรียน/ผู้รับ/ช่องทาง/สถานะ/ค้นหา
   โดยช่องทางต้องอ่าน `document_meta->>'channel_id'` (ตารางไม่มีคอลัมน์นี้)
3. **ใบ void ยังอยู่** — ค่าปริยายซ่อน, `include_voided` เห็น, และแถวใน DB ยังมี
   `deleted_at IS NOT NULL` (soft delete ไม่ใช่ลบจริง) + detail เปิดได้เสมอ
4. **pagination** — `total` คือจำนวนทั้งหมด ไม่ใช่ขนาดหน้า
5. **links สองทิศ** — PV→CERT เปิดจากฝั่งไหนก็เห็นอีกฝั่ง (`out`/`in`) + `doc_no` เติมครบ
6. **bundle ผสม layout** — v1+v2 ในไฟล์เดียวด้วย `<style>` ชุดเดียว, เพดาน 100,
   dedupe, ขาดใบ = 404 พร้อมเลขที่
7. **สมาชิกเท่านั้น** — คนนอกห้อง 403 และยืนยันว่า `require_member` ถูกเรียกจริง

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import json
import re
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from services.finance.constants import THAI_TZ

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FAKE_PDF = b"%PDF-1.4 fake"
_DOCURL = re.compile(r'<div class="doc(?: doc-break)?">')
# ⚠️ ห้ามนับ `html.count("<style")` ตรง ๆ — CSS ของ shell มีคอมเมนต์ที่เขียนคำว่า
#    "`<style>`" อยู่ด้วย (กันคนย้ายแท็กเข้าไปในลูป) ⇒ ต้องนับแท็กจริงที่มีขึ้นบรรทัดใหม่
_STYLE_TAG = re.compile(r"<style>\s*\n")


# ═══════════════════════════════════════════════════════════════════ helpers
def _list_url(room_id: int, query: str = "") -> str:
    base = f"{API_PREFIX}/{room_id}/finance/documents?target_type=room"
    return f"{base}&{query}" if query else base


def _detail_url(room_id: int, doc_type: str, doc_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/documents/{doc_type}/{doc_id}"
        "?target_type=room"
    )


def _by_no_url(room_id: int, doc_no: str) -> str:
    return f"{API_PREFIX}/{room_id}/finance/documents/by-no/{doc_no}?target_type=room"


def _pdf_url(room_id: int, doc_type: str, doc_id: int) -> str:
    return (
        f"{API_PREFIX}/{room_id}/finance/documents/{doc_type}/{doc_id}/pdf"
        "?target_type=room"
    )


def _bundle_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/documents/print-bundle?target_type=room"


def _at(y: int, m: int, d: int, hour: int = 10, minute: int = 0) -> datetime:
    """เวลาหนึ่งจุดในเขตเวลาไทย (aware) — ใช้เป็น `event_at` ของเอกสารทุกใบ"""
    return datetime(y, m, d, hour, minute, tzinfo=THAI_TZ)


_DEFAULT_AT = _at(2026, 11, 20)


def _v2_meta(**over) -> dict:
    """`document_meta` v2 ขั้นต่ำที่ตัวเรนเดอร์ v2 อ่าน (เหมือนใบที่ออกจริง)"""
    meta = {
        "payer_name": "เด็กชายทดสอบ",
        "receiver_name": "ครูทดสอบ",
        "amount_received": "1000.00",
        "credit_used": "0.00",
        "credit_added": "0.00",
        "amounts_in_words": "หนึ่งพันบาทถ้วน",
        "event_at": _DEFAULT_AT.isoformat(),
        "channel": {"name": "เงินสด", "channel_type": "cash"},
    }
    meta.update(over)
    return meta


async def _insert_receipt(
    pool,
    room_id: int,
    receipt_no: str,
    *,
    doc_type: str = "receipt",
    student_id=None,
    collection_id=None,
    amount: float = 1000.0,
    layout_version: int = 1,
    event_at=None,
    status: str = "active",
    deleted_at=None,
    document_meta=None,
    line_items=None,
    receiver_person_id=None,
    related_receipt_id=None,
) -> int:
    """แถว `finance_receipts` ตรง ๆ — seq = ท้ายเลขเอกสาร (REC-2569-0001 → 1)"""
    seq = int(receipt_no.rsplit("-", 1)[1])
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, student_id,
                    collection_id, amount, paid_total_after, issued_to_name,
                    issued_by_name, event_at, status, deleted_at, layout_version,
                    line_items, document_meta, receiver_person_id, related_receipt_id)
               VALUES ($1, $2, $3, 2569, $4, $5, $6, $7, $7, 'เด็กชายทดสอบ',
                       'ครูทดสอบ', $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14, $15)
               RETURNING id""",
            room_id, receipt_no, doc_type, seq, student_id, collection_id,
            amount, event_at or _DEFAULT_AT, status, deleted_at, layout_version,
            None if line_items is None else json.dumps(line_items, ensure_ascii=False),
            json.dumps(document_meta or {}, ensure_ascii=False),
            receiver_person_id, related_receipt_id,
        )


async def _insert_report(
    pool,
    room_id: int,
    *,
    report_no: str = "RPT-2569-0011",
    year_be: int = 2569,
    month: int = 11,
    version: int = 1,
    status: str = "final",
    total_income: float = 5000.0,
    total_expense: float = 2000.0,
    finalized_at=None,
) -> int:
    """แถว `finance_monthly_reports` ตรง ๆ — `snapshot` ต้องไม่ NULL"""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_monthly_reports
                   (room_id, year_be, month, version, report_no, status, snapshot,
                    total_income, total_expense, opening_cash, closing_cash,
                    counted_cash, variance, finalized_at)
               VALUES ($1, $2, $3, $4, $5, $6, '{}'::jsonb,
                       $7, $8, 1000.00, 4000.00, 4000.00, 0.00, $9)
               RETURNING id""",
            room_id, year_be, month, version, report_no, status,
            total_income, total_expense, finalized_at or _at(2026, 11, 30, 18),
        )


async def _insert_person(pool, room_id: int, display_name: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people (room_id, person_type, display_name)
               VALUES ($1, 'teacher', $2) RETURNING id""",
            room_id, display_name,
        )


async def _insert_link(
    pool, room_id: int, from_type: str, from_id: int,
    to_type: str, to_id: int, link_type: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_document_links
                   (room_id, from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            room_id, from_type, from_id, to_type, to_id, link_type,
        )


async def _insert_signature(
    pool, room_id: int, doc_type: str, doc_id: int, role: str,
    signer_name: str, sort_order: int = 0,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_document_signatures
                   (room_id, doc_type, doc_id, role, signer_name, signed_at, sort_order)
               VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, $6)""",
            room_id, doc_type, doc_id, role, signer_name, sort_order,
        )


async def _bulk_insert_receipts(pool, room_id: int, count: int) -> None:
    """สร้าง REC จำนวน `count` ใบ — เลข 0001..NNNN และ event_at ไล่ถอยหลังทีละวัน"""
    rows = [
        (
            room_id, f"REC-2569-{i:04d}", "receipt", 2569, i, 100.0,
            _at(2026, 10, 1) + timedelta(hours=i),
        )
        for i in range(1, count + 1)
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, amount,
                    paid_total_after, event_at)
               VALUES ($1, $2, $3, $4, $5, $6, $6, $7)""",
            rows,
        )


# ═══════════════════════════════════════════════ 1. union receipt + RPT
async def test_registry_union_lists_receipt_and_monthly_report(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    await _insert_receipt(db_pool, room_id, "REC-2569-0001", layout_version=2)
    await _insert_report(db_pool, room_id)

    res = client.get(_list_url(room_id), headers=admin_headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    assert {it["doc_type"] for it in body["items"]} == {"receipt", "monthly_report"}

    by_type = {it["doc_type"]: it for it in body["items"]}
    assert by_type["receipt"]["doc_no"] == "REC-2569-0001"
    assert by_type["monthly_report"]["doc_no"] == "RPT-2569-0011"
    # RPT ไม่มีนักเรียน/ช่องทาง — literal NULL ใน CTE ต้องไม่กลายเป็น 0/สตริงว่าง
    assert by_type["monthly_report"]["student_id"] is None
    assert by_type["monthly_report"]["channel_id"] is None
    # ยอดของ RPT = รายได้ − รายจ่าย (ไม่ใช่รายได้ก้อนเดียว)
    assert by_type["monthly_report"]["amount"] == "3000.00"


# ═══════════════════════════════════════════════ 2. กรองด้วย doc_types array
async def test_registry_filters_by_doc_types_array(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _insert_receipt(db_pool, room_id, "REC-2569-0001")
    await _insert_receipt(db_pool, room_id, "PV-2569-0001", doc_type="payment_voucher")

    res = client.get(_list_url(room_id, "doc_types=receipt,invoice"), headers=admin_headers)

    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [it["doc_type"] for it in items] == ["receipt"]
    assert res.json()["total"] == 1


# ═══════════════════════════════════════════════ 3. ขอบวันไทยแบบครึ่งเปิด
async def test_registry_date_filter_thai_boundary_half_open(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    # 23:59:59 ของวันที่ 30 พ.ย. (เวลาไทย) — ยังต้องอยู่ใน `to=2026-11-30`
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0001",
        event_at=datetime(2026, 11, 30, 23, 59, 59, tzinfo=THAI_TZ),
    )

    inside = client.get(_list_url(room_id, "to=2026-11-30"), headers=admin_headers)
    assert inside.status_code == 200, inside.text
    assert inside.json()["total"] == 1

    outside = client.get(_list_url(room_id, "from=2026-12-01"), headers=admin_headers)
    assert outside.status_code == 200, outside.text
    assert outside.json()["total"] == 0, "ขอบเขตล่างต้องเป็นครึ่งเปิด (วันที่ 1 ไม่รวมใบเมื่อวาน)"


# ═══════════════════════════════════════════════ 4. กรองช่องทางจาก document_meta
async def test_registry_channel_filter_reads_document_meta(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", layout_version=2,
        document_meta=_v2_meta(channel_id=4),
    )

    hit = client.get(_list_url(room_id, "channel_id=4"), headers=admin_headers)
    assert hit.status_code == 200, hit.text
    assert hit.json()["total"] == 1
    assert hit.json()["items"][0]["channel_id"] == 4

    miss = client.get(_list_url(room_id, "channel_id=5"), headers=admin_headers)
    assert miss.status_code == 200, miss.text
    assert miss.json()["total"] == 0


# ═══════════════════════════════════════════════ 5. void ถูกซ่อนตามปริยาย
async def test_registry_excludes_voided_by_default_and_includes_with_flag(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    await _insert_receipt(db_pool, room_id, "REC-2569-0001")
    # ⚠️ `finance_receipts.deleted_at` เป็น TIMESTAMP (naive) — ส่ง aware เข้าไป asyncpg
    #    จะ TypeError ("can't subtract offset-naive and offset-aware datetimes")
    voided_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0002",
        status="voided", deleted_at=datetime.now(),
        layout_version=2,
    )

    default = client.get(_list_url(room_id), headers=admin_headers)
    assert default.status_code == 200, default.text
    assert default.json()["total"] == 1
    assert [it["doc_id"] for it in default.json()["items"]] != [voided_id]

    with_flag = client.get(_list_url(room_id, "include_voided=true"), headers=admin_headers)
    assert with_flag.status_code == 200, with_flag.text
    assert with_flag.json()["total"] == 2
    assert any(it["status"] == "voided" for it in with_flag.json()["items"])

    # 🔒 soft delete ไม่ใช่ลบจริง — แถวยังอยู่และ `deleted_at` ถูกตั้ง
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, deleted_at FROM finance_receipts WHERE id = $1", voided_id,
        )
    assert row is not None
    assert row["status"] == "voided"
    assert row["deleted_at"] is not None


# ═══════════════════════════════════════════════ 6. กรองนักเรียนตัด RPT
async def test_registry_student_filter_drops_monthly_report(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", student_id=admin_headers.student_id,
    )
    await _insert_report(db_pool, room_id)

    res = client.get(
        _list_url(room_id, f"student_id={admin_headers.student_id}"),
        headers=admin_headers,
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["doc_type"] == "receipt"


# ═══════════════════════════════════════════════ 7. pagination: total ≠ page size
async def test_registry_pagination_reports_total_not_page_size(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    await _bulk_insert_receipts(db_pool, room_id, 60)

    page1 = client.get(_list_url(room_id, "limit=50"), headers=admin_headers)
    assert page1.status_code == 200, page1.text
    body = page1.json()
    assert len(body["items"]) == 50
    assert body["total"] == 60
    assert body["limit"] == 50
    assert body["offset"] == 0

    page2 = client.get(_list_url(room_id, "limit=50&offset=50"), headers=admin_headers)
    assert page2.status_code == 200, page2.text
    assert len(page2.json()["items"]) == 10
    assert page2.json()["total"] == 60
    # ไม่มีหน้าซ้ำ/หน้าหาย
    ids = [it["doc_id"] for it in body["items"]] + [
        it["doc_id"] for it in page2.json()["items"]
    ]
    assert len(ids) == len(set(ids)) == 60


# ═══════════════════════════════════════════════ 8. detail dispatch v1/v2
async def test_registry_detail_dispatch_by_layout_version(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    person_id = await _insert_person(db_pool, room_id, "ครูทดสอบ")
    legacy_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", layout_version=1, amount=500.0,
    )
    v2_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0002", layout_version=2, amount=1000.0,
        document_meta=_v2_meta(channel_id=4, receiver_person_id=person_id),
        line_items=[{"title": "ค่าโครงการ", "amount_applied": "1000.00"}],
    )
    await _insert_signature(
        db_pool, room_id, "receipt", v2_id, "prepared", "ครูทดสอบ",
    )

    legacy = client.get(_detail_url(room_id, "receipt", legacy_id), headers=admin_headers)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["layout_version"] == 1
    assert legacy.json()["amount"] == "500.00"
    assert legacy.json()["document_meta"] == {}

    v2 = client.get(_detail_url(room_id, "receipt", v2_id), headers=admin_headers)
    assert v2.status_code == 200, v2.text
    body = v2.json()
    assert body["layout_version"] == 2
    assert body["document_meta"]["channel_id"] == 4
    assert body["channel_id"] == 4
    assert body["receiver_person_id"] == person_id
    assert body["receiver_name"] == "ครูทดสอบ"
    assert body["line_item_count"] == 1
    assert body["amounts_in_words"] == "หนึ่งพันบาทถ้วน"
    # 🔗 คีย์ลิงก์/ลายเซ็นต้องมีเสมอ (frontend พึ่ง `[]` ไม่ใช่ `null`)
    assert body["links"] == []
    assert [s["role"] for s in body["signatures"]] == ["prepared"]
    assert body["signatures"][0]["signer_name"] == "ครูทดสอบ"


# ═══════════════════════════════════════════════ 9. detail ของใบ void อ่านได้
async def test_registry_detail_of_voided_document_is_readable(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    doc_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", layout_version=2,
        status="voided", deleted_at=datetime.now(),
    )
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE finance_receipts
               SET voided_at = CURRENT_TIMESTAMP, void_reason = 'ออกซ้ำ'
               WHERE id = $1""",
            doc_id,
        )

    res = client.get(_detail_url(room_id, "receipt", doc_id), headers=admin_headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "voided"
    assert body["void_reason"] == "ออกซ้ำ"
    assert body["voided_at"] is not None


# ═══════════════════════════════════════════════ 10. links สองทิศ + related
async def test_registry_cross_links_bidirectional(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    pv_id = await _insert_receipt(
        db_pool, room_id, "PV-2569-0001", doc_type="payment_voucher",
        layout_version=2, amount=800.0,
    )
    cert_id = await _insert_receipt(
        db_pool, room_id, "CERT-2569-0001", doc_type="certificate",
        layout_version=2, amount=800.0,
    )
    rec_id = await _insert_receipt(db_pool, room_id, "REC-2569-0001", layout_version=2)
    merged_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0002", layout_version=2, related_receipt_id=rec_id,
    )
    await _insert_link(
        db_pool, room_id, "payment_voucher", pv_id, "certificate", cert_id,
        "cert_for_voucher",
    )

    pv = client.get(_detail_url(room_id, "payment_voucher", pv_id), headers=admin_headers)
    assert pv.status_code == 200, pv.text
    pv_links = pv.json()["links"]
    assert len(pv_links) == 1
    assert pv_links[0]["direction"] == "out"
    assert pv_links[0]["link_type"] == "cert_for_voucher"
    assert (pv_links[0]["doc_type"], pv_links[0]["doc_no"]) == (
        "certificate", "CERT-2569-0001",
    )

    cert = client.get(
        _detail_url(room_id, "certificate", cert_id), headers=admin_headers,
    )
    assert cert.status_code == 200, cert.text
    cert_links = cert.json()["links"]
    assert len(cert_links) == 1
    assert cert_links[0]["direction"] == "in"
    assert (cert_links[0]["doc_type"], cert_links[0]["doc_no"]) == (
        "payment_voucher", "PV-2569-0001",
    )

    # ใบเสร็จยุบรวม — `related_receipt_id` ต้องถูก synthesise เป็น link `event_document`
    merged = client.get(
        _detail_url(room_id, "receipt", merged_id), headers=admin_headers,
    )
    assert merged.status_code == 200, merged.text
    assert {
        (l["link_type"], l["direction"], l["doc_no"]) for l in merged.json()["links"]
    } == {("event_document", "out", "REC-2569-0001")}


# ═══════════════════════════════════════════════ 11. by-no resolver
async def test_registry_by_no_resolves_and_404s(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _insert_receipt(db_pool, room_id, "REC-2569-0001", layout_version=2)
    await _insert_report(db_pool, room_id, report_no="RPT-2569-0011")

    rec = client.get(_by_no_url(room_id, "REC-2569-0001"), headers=admin_headers)
    assert rec.status_code == 200, rec.text
    assert rec.json()["doc_type"] == "receipt"
    assert rec.json()["doc_no"] == "REC-2569-0001"

    rpt = client.get(_by_no_url(room_id, "RPT-2569-0011"), headers=admin_headers)
    assert rpt.status_code == 200, rpt.text
    assert rpt.json()["doc_type"] == "monthly_report"
    assert rpt.json()["year_be"] == 2569

    missing = client.get(_by_no_url(room_id, "REC-2569-9999"), headers=admin_headers)
    assert missing.status_code == 404, missing.text

    malformed = client.get(_by_no_url(room_id, "ไม่ใช่เลขเอกสาร"), headers=admin_headers)
    assert malformed.status_code == 400, malformed.text


# ═══════════════════════════════════════════════ 12. bundle ผสม layout
async def test_registry_print_bundle_mixed_layout_single_style(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    legacy_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", layout_version=1, amount=500.0,
    )
    v2_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0002", layout_version=2, amount=1000.0,
        document_meta=_v2_meta(),
        line_items=[{"title": "ค่าโครงการ", "amount_applied": "1000.00"}],
    )

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.post(
            _bundle_url(room_id),
            json={"items": [
                {"doc_type": "receipt", "doc_id": legacy_id},
                {"doc_type": "receipt", "doc_id": v2_id},
                # 🔁 ใบซ้ำต้องถูก dedupe — ไม่ใช่พิมพ์หน้าซ้ำ
                {"doc_type": "receipt", "doc_id": v2_id},
            ]},
            headers=admin_headers,
        )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == FAKE_PDF

    html = mock_render.await_args.args[0]
    assert len(_STYLE_TAG.findall(html)) == 1, "shell ต้องถือ <style> ชุดเดียวทั้งไฟล์"
    assert len(_DOCURL.findall(html)) == 2, "dedupe ต้องเหลือ 2 ใบ"
    assert "REC-2569-0001" in html and "REC-2569-0002" in html


# ═══════════════════════════════════════════════ 13. bundle เกิน 100 = 400
async def test_registry_print_bundle_over_limit_returns_400(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    items = [{"doc_type": "receipt", "doc_id": i} for i in range(1, 102)]

    res = client.post(
        _bundle_url(room_id), json={"items": items}, headers=admin_headers,
    )

    assert res.status_code == 400, res.text
    assert "100" in res.json()["detail"]


# ═══════════════════════════════════════════════ 14. bundle ขาดใบ = 404 + เลขที่
async def test_registry_print_bundle_missing_doc_returns_404_with_numbers(
    client, db_pool, admin_headers,
):
    room_id = admin_headers.room_id
    existing_id = await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", layout_version=2,
    )

    res = client.post(
        _bundle_url(room_id),
        json={"items": [
            {"doc_type": "receipt", "doc_id": existing_id},
            {"doc_type": "receipt", "doc_id": 999999},
        ]},
        headers=admin_headers,
    )

    assert res.status_code == 404, res.text
    detail = res.json()["detail"]
    assert "999999" in detail
    assert "receipt #999999" in detail


# ═══════════════════════════════════════════════ 15. สมาชิกเท่านั้น + เรียกจริง
async def test_registry_requires_member(
    client, db_pool, admin_headers, member_headers,
):
    room_id = admin_headers.room_id
    await _insert_receipt(db_pool, room_id, "REC-2569-0001")

    # `member_headers` เป็นสมาชิกของห้องตัวเอง — ยิงเข้าห้องของ admin ต้อง 403
    denied = client.get(_list_url(room_id), headers=member_headers)
    assert denied.status_code == 403, denied.text

    # 🔍 โครงสร้าง: ต้องเรียก `require_member` จริง (ไม่ได้ผ่านเพราะ is_admin/bypass อื่น)
    with patch(
        "services.finance.document_registry.require_member", new=AsyncMock(),
    ) as mock_member:
        allowed = client.get(_list_url(room_id), headers=member_headers)

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["total"] == 1
    assert mock_member.await_count >= 1
    assert mock_member.await_args.args[1] == room_id
    assert mock_member.await_args.args[2] == member_headers.user_id


# ══════════════════════════════════ 8. void_target — ปลายทางยกเลิกต่อชนิด
async def test_registry_void_target_per_doc_type(client, db_pool, admin_headers):
    """🎯 list/detail ต้องบอก "ยกเลิกด้วย endpoint ไหน id อะไร" ตรงกันทุกชนิด

    - INV → invoice(id)
    - PV  → expense_voucher จาก `document_meta.voucher_id`
    - INC → income_batch จาก `document_meta.batch_id`
    - ACK → acknowledgement(receipt_no) — endpoint รับเลขเอกสาร ไม่ใช่ id
    - RPT → monthly_report(id)
    """
    room_id = admin_headers.room_id
    inv_id = await _insert_receipt(db_pool, room_id, "INV-2569-0001", doc_type="invoice")
    pv_id = await _insert_receipt(
        db_pool, room_id, "PV-2569-0001", doc_type="payment_voucher",
        document_meta={"voucher_id": 42},
    )
    inc_id = await _insert_receipt(
        db_pool, room_id, "INC-2569-0001", doc_type="income",
        document_meta={"batch_id": 7},
    )
    ack_id = await _insert_receipt(
        db_pool, room_id, "ACK-2569-0001", doc_type="acknowledgement",
    )
    rpt_id = await _insert_report(db_pool, room_id)

    res = client.get(_list_url(room_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    by_type = {it["doc_type"]: it for it in res.json()["items"]}

    assert by_type["invoice"]["void_target"] == {
        "method": "invoice", "id": inv_id, "receipt_no": None,
    }
    assert by_type["payment_voucher"]["void_target"] == {
        "method": "expense_voucher", "id": 42, "receipt_no": None,
    }
    assert by_type["income"]["void_target"] == {
        "method": "income_batch", "id": 7, "receipt_no": None,
    }
    assert by_type["acknowledgement"]["void_target"] == {
        "method": "acknowledgement", "id": None, "receipt_no": "ACK-2569-0001",
    }
    assert by_type["monthly_report"]["void_target"] == {
        "method": "monthly_report", "id": rpt_id, "receipt_no": None,
    }

    # detail ใช้ตัวตัดสินเดียวกัน — ห้าม list กับ detail ไม่ตรงกัน
    for doc_type, doc_id, expected in (
        ("invoice", inv_id, {"method": "invoice", "id": inv_id, "receipt_no": None}),
        ("payment_voucher", pv_id, {"method": "expense_voucher", "id": 42, "receipt_no": None}),
        ("income", inc_id, {"method": "income_batch", "id": 7, "receipt_no": None}),
        ("acknowledgement", ack_id, {"method": "acknowledgement", "id": None,
                                     "receipt_no": "ACK-2569-0001"}),
        ("monthly_report", rpt_id, {"method": "monthly_report", "id": rpt_id,
                                    "receipt_no": None}),
    ):
        detail = client.get(_detail_url(room_id, doc_type, doc_id), headers=admin_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["void_target"] == expected, doc_type


async def test_registry_void_target_is_none_when_not_cancellable(
    client, db_pool, admin_headers,
):
    """ใบที่ยกเลิกแล้ว/ถูกลบ ต้องไม่มี void_target — ยกเลิกซ้ำไม่ได้

    RPT ที่ voided ก็ต้องไม่มี แม้ life cycle จะไม่ใช้ `active`
    """
    room_id = admin_headers.room_id
    # ⚠️ `finance_receipts.deleted_at` เป็น TIMESTAMP (naive) — ใส่นาฬิกาไทยไม่ได้
    voided = datetime(2026, 11, 21, 9)
    voided_id = await _insert_receipt(
        db_pool, room_id, "INV-2569-0001", doc_type="invoice",
        status="voided", deleted_at=voided,
    )
    deleted_id = await _insert_receipt(
        db_pool, room_id, "INV-2569-0002", doc_type="invoice", deleted_at=voided,
    )
    rpt_id = await _insert_report(db_pool, room_id, status="voided")

    res = client.get(_list_url(room_id, "include_voided=true"), headers=admin_headers)
    assert res.status_code == 200, res.text
    by_id = {(it["doc_type"], it["doc_id"]): it for it in res.json()["items"]}
    assert by_id[("invoice", voided_id)]["void_target"] is None
    assert by_id[("invoice", deleted_id)]["void_target"] is None
    assert by_id[("monthly_report", rpt_id)]["void_target"] is None

    detail = client.get(_detail_url(room_id, "invoice", voided_id), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["void_target"] is None
