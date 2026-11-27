"""📎 ต่อท้ายไฟล์หลักฐาน (รูป + PDF) เข้าไปใน PDF ของเอกสารการเงิน

เหตุผล: ครู/เหรัญญิกพิมพ์เอกสารแล้วต้องแนบหลักฐานมาด้วยในกระดาษชุดเดียวกัน
⇒ เอกสารหลัก (REC/PV/INC/…) อยู่หน้าแรก ตามด้วยไฟล์แนบของ record ต้นทาง

🔗 **จุดเดียวที่ครอบทุกชนิดเอกสาร:** `FinanceService.render_receipt_pdf` เพราะ
   PV/INC/CERT/เอกสารเดี่ยวทุกใบเรียกผ่านเมธอดนั้น (ดู expense_vouchers.py /
   income_batches.py) · `_render_documents_pdf` (พิมพ์รวมหลายใบ) ต่อท้ายเพิ่มอีกชั้น

🧾 การหา "ไฟล์แนบของเอกสารใบนี้":
   - `legacy_transaction_id` → owner transaction
   - `student_payment_id`    → owner student_payment
   - `payment_event_id`      → owner payment_event
   - เป็น PV: `finance_expense_vouchers.pv_receipt_id` → ทุกบรรทัด (`finance_transaction_id`)
   - เป็น INC: `finance_income_batches.inc_receipt_id` → ทุกบรรทัด (`finance_transaction_id`)
   - CERT → PV: ตาม `related_receipt_id` หนึ่ง hop
   ⇒ dedupe ด้วย attachment id (หลักฐานเดียวกันอาจถูกอ้างหลายทาง)

⚠️ ทั้งหมดเป็น **best-effort**: ถ้าไฟล์ใดเสีย/หาย ให้ข้ามไฟล์นั้นพร้อม log —
   ห้ามทำให้พิมพ์เอกสารไม่ได้เลย
"""
import io
import logging
from typing import Iterable, List, Sequence, Tuple

import asyncpg
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from core.media import MediaStorageError, get_media_storage

logger = logging.getLogger("API_FINANCE_DOC_ATTACHMENTS")

# A4 ที่ 150 dpi (8.27 × 11.69 นิ้ว) — ตรงกับกระดาษที่ Gotenberg เรนเดอร์เอกสารหลัก
_A4_DPI = 150
_A4_W = int(8.27 * _A4_DPI)
_A4_H = int(11.69 * _A4_DPI)
_A4_MARGIN = int(0.35 * _A4_DPI)


async def _refs_for_receipt(
    conn: asyncpg.Connection, receipt_id: int, seen: set[int]
) -> set[Tuple[str, int]]:
    """owner refs ของเอกสาร 1 ใบ (ไล่ `related_receipt_id` หนึ่ง hop, กันวนซ้ำ)"""
    if receipt_id in seen:
        return set()
    seen.add(receipt_id)

    r = await conn.fetchrow(
        """SELECT id, legacy_transaction_id, student_payment_id,
                  payment_event_id, related_receipt_id
           FROM finance_receipts WHERE id = $1""",
        receipt_id,
    )
    if r is None:
        return set()

    refs: set[Tuple[str, int]] = set()
    # 📎 ไฟล์ที่แนบเข้ากับ "เอกสาร" โดยตรง (เพิ่มภายหลังได้จากหน้ารายละเอียดเอกสาร)
    refs.add(("receipt", int(receipt_id)))
    if r["legacy_transaction_id"] is not None:
        refs.add(("transaction", int(r["legacy_transaction_id"])))
    if r["student_payment_id"] is not None:
        refs.add(("student_payment", int(r["student_payment_id"])))
    if r["payment_event_id"] is not None:
        refs.add(("payment_event", int(r["payment_event_id"])))

    # PV — หลักฐานอาจผูกกับรายการของแต่ละบรรทัด ไม่ใช่แค่บรรทัดแรก
    txn_rows = await conn.fetch(
        """SELECT L.finance_transaction_id AS txn_id
           FROM finance_expense_vouchers V
           JOIN finance_expense_lines L ON L.voucher_id = V.id
           WHERE V.pv_receipt_id = $1 AND L.finance_transaction_id IS NOT NULL""",
        receipt_id,
    )
    for row in txn_rows:
        refs.add(("transaction", int(row["txn_id"])))

    # INC — เช่นกัน
    inc_rows = await conn.fetch(
        """SELECT L.finance_transaction_id AS txn_id
           FROM finance_income_batches B
           JOIN finance_income_lines L ON L.batch_id = B.id
           WHERE B.inc_receipt_id = $1 AND L.finance_transaction_id IS NOT NULL""",
        receipt_id,
    )
    for row in inc_rows:
        refs.add(("transaction", int(row["txn_id"])))

    if r["related_receipt_id"] is not None:
        refs |= await _refs_for_receipt(conn, int(r["related_receipt_id"]), seen)

    return refs


async def _fetch_attachments(
    conn: asyncpg.Connection, refs: Iterable[Tuple[str, int]]
) -> List[asyncpg.Record]:
    txn_ids, payment_ids, event_ids, receipt_ids = [], [], [], []
    for owner_type, owner_id in refs:
        if owner_type == "transaction":
            txn_ids.append(owner_id)
        elif owner_type == "student_payment":
            payment_ids.append(owner_id)
        elif owner_type == "payment_event":
            event_ids.append(owner_id)
        elif owner_type == "receipt":
            receipt_ids.append(owner_id)

    if not (txn_ids or payment_ids or event_ids or receipt_ids):
        return []

    return await conn.fetch(
        """SELECT * FROM finance_attachments
           WHERE deleted_at IS NULL
             AND ((owner_type = 'transaction' AND owner_id = ANY($1::int[]))
               OR (owner_type = 'student_payment' AND owner_id = ANY($2::int[]))
               OR (owner_type = 'payment_event' AND owner_id = ANY($3::int[]))
               OR (owner_type = 'receipt' AND owner_id = ANY($4::int[])))
           ORDER BY created_at, id""",
        txn_ids, payment_ids, event_ids, receipt_ids,
    )


def _image_to_a4_pdf(data: bytes) -> bytes:
    """รูป 1 ไฟล์ → หน้า A4 (วางกึ่งกลาง พื้นขาว ไม่เกินขอบ)"""
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        max_w = _A4_W - 2 * _A4_MARGIN
        max_h = _A4_H - 2 * _A4_MARGIN
        im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        page = Image.new("RGB", (_A4_W, _A4_H), (255, 255, 255))
        page.paste(im, ((_A4_W - im.width) // 2, (_A4_H - im.height) // 2))
        buf = io.BytesIO()
        page.save(buf, format="PDF", resolution=_A4_DPI, quality=85)
        return buf.getvalue()


def _merge_sync(base_pdf: bytes, files: Sequence[Tuple[dict, bytes]]) -> bytes:
    """ต่อท้ายไฟล์เข้า base PDF (เอกสารหลักก่อนเสมอ) — ทำงานแบบ blocking ใน threadpool"""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    base_reader = PdfReader(io.BytesIO(base_pdf))
    for page in base_reader.pages:
        writer.add_page(page)

    for row, data in files:
        try:
            if row["mime"] == "application/pdf":
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    logger.warning("skip encrypted attachment %s", row["id"])
                    continue
                for page in reader.pages:
                    writer.add_page(page)
            else:
                image_pdf = _image_to_a4_pdf(data)
                reader = PdfReader(io.BytesIO(image_pdf))
                for page in reader.pages:
                    writer.add_page(page)
        except Exception:
            logger.warning("skip unreadable attachment %s", row["id"], exc_info=True)
            continue

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def list_attachments_for_receipt(
    conn: asyncpg.Connection,
    receipt_id: int,
    viewer_id: int,
) -> list[dict]:
    """ไฟล์แนบของเอกสาร 1 ใบ (สำหรับหน้าจอ) — signed URL ผูก viewer

    ใช้ resolver ชุดเดียวกับ PDF merge ⇒ สิ่งที่เห็นบนจอ = สิ่งที่ต่อท้ายในกระดาษ
    """
    from services.finance_attachments import _attachment_to_dict

    seen: set[int] = set()
    refs = await _refs_for_receipt(conn, int(receipt_id), seen)
    rows = await _fetch_attachments(conn, refs)
    return [_attachment_to_dict(row, int(viewer_id)) for row in rows]


async def append_attachments_to_receipts(
    pool: asyncpg.Pool,
    receipts: Sequence[dict],
    base_pdf: bytes,
) -> bytes:
    """คืน PDF ที่ต่อท้ายไฟล์แนบของเอกสารที่ให้มา (best-effort — ไม่มีไฟล์แนบ = คืนเดิม)

    `receipts` เป็น dict ที่มีคีย์ `id` (ของ `finance_receipts`) — เรียงตามลำดับที่ต้องพิมพ์
    """
    receipt_ids = []
    for d in receipts:
        rid = d.get("id") if isinstance(d, dict) else None
        if isinstance(rid, int):
            receipt_ids.append(rid)
    if not receipt_ids:
        return base_pdf

    async with pool.acquire() as conn:
        seen: set[int] = set()
        refs: set[Tuple[str, int]] = set()
        for rid in receipt_ids:
            refs |= await _refs_for_receipt(conn, rid, seen)
        rows = await _fetch_attachments(conn, refs)

    if not rows:
        return base_pdf

    storage = get_media_storage()
    files: List[Tuple[dict, bytes]] = []
    for row in rows:
        try:
            chunks = []
            async for chunk in storage.read_stream(row["storage_path"]):
                chunks.append(chunk)
            files.append((dict(row), b"".join(chunks)))
        except MediaStorageError:
            logger.warning("missing attachment file %s (%r)", row["id"], row["storage_path"])
            continue

    if not files:
        return base_pdf

    return await run_in_threadpool(_merge_sync, base_pdf, files)
