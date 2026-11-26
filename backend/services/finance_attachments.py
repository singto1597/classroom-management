"""📎 ไฟล์หลักฐานการเงิน — รูปภาพ (WebP) + PDF บน named volume + signed URL

ลอกกลไกจาก PRSC `services/image_service.py` (PR #120) ตรง ๆ:
  - ประมวลผลรูปใน threadpool **ก่อน** เปิด transaction (Pillow กิน CPU หลายร้อย ms)
  - ตรวจสิทธิ์/โควตาใน transaction เดียว แล้ว **เขียนไฟล์ก่อน INSERT**
    ⇒ crash กลางทางเหลือ "ไฟล์กำพร้า" (purge เก็บได้) ไม่ใช่ "แถวชี้ไฟล์หาย"
  - เสิร์ฟด้วย signed URL + **ตรวจสิทธิ์ซ้ำทุก GET** (URL อาจถูกแชร์/ผู้ใช้ถูกย้ายห้อง)

🆕 ส่วนที่เพิ่มจาก PRSC:
  - รับ **PDF** ด้วย — ตรวจ magic bytes, ปฏิเสธไฟล์เข้ารหัส, จำกัดจำนวนหน้า และ
    **เขียนใหม่ด้วย `PdfWriter`** (เก็บเฉพาะหน้า) ⇒ ตัด document-level JavaScript /
    embedded file ที่ติดมากับ PDF
  - polymorphic owner: `transaction` | `student_payment` | `payment_event`
"""
import hashlib
import io
import logging
import re
import uuid
from pathlib import Path
from typing import Optional, Sequence, Tuple
from urllib.parse import quote

import asyncpg
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

from core.config import settings
from core.exceptions import (
    FinanceAttachmentNotFoundError,
    ForbiddenError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
)
from core.logger import AuditLogger
from core.media import MediaStorageError, get_media_storage
from core.media_signing import sign_url, verify_signature
from core.rbac import require_member, require_permission

logger = logging.getLogger("API_FINANCE_ATTACHMENTS")
service_logger = AuditLogger("finance_attachment_service")

# ---------------------------------------------------------------------------
# รูปภาพ — ตั้งค่า Pillow/HEIF
# ---------------------------------------------------------------------------
try:  # best-effort: ถ้า lib ไม่มี ให้เหลือ JPEG/PNG/WebP และตอบ 400 สำหรับ HEIC
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover - ขึ้นกับ environment
    _HEIF_OK = False
    logger.warning("pillow-heif ใช้ไม่ได้ — จะไม่รองรับ HEIC")

ALLOWED_IMAGE_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
if _HEIF_OK:
    ALLOWED_IMAGE_FORMATS.add("HEIF")

# เพดานพิกเซลกัน decompression bomb (ตรวจซ้ำด้วย width*height ของตัวเอง)
MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

PDF_MAGIC = b"%PDF-"
MIME_IMAGE = "image/webp"
MIME_PDF = "application/pdf"

OWNER_TYPES = ("transaction", "student_payment", "payment_event")
VALID_KINDS = ("payment_proof", "expense_evidence", "withdrawal_evidence", "other")


# ---------------------------------------------------------------------------
# ประมวลผลไฟล์ (sync — ต้องเรียกผ่าน run_in_threadpool เท่านั้น)
# ---------------------------------------------------------------------------
def _to_rgb(im: Image.Image) -> Image.Image:
    """แปลงเป็น RGB — ถ้ามี alpha ให้วางพื้นขาว (WebP รองรับ alpha แต่พื้นขาวปลอดภัยทุกเบราว์เซอร์)"""
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        background = Image.new("RGB", im.size, (255, 255, 255))
        background.paste(im, mask=im.split()[-1])
        return background
    return im.convert("RGB")


def _resize_longest(im: Image.Image, max_dim: int) -> Image.Image:
    """ย่อด้านยาวสุดให้ ≤ max_dim (ไม่ขยายรูปเล็ก)"""
    longest = max(im.size)
    if longest <= max_dim:
        return im
    scale = max_dim / float(longest)
    new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    return im.resize(new_size, Image.Resampling.LANCZOS)


def _encode_webp(im: Image.Image) -> bytes:
    """บันทึก WebP **โดยไม่ส่ง exif/icc** ⇒ GPS/ข้อมูลกล้องไม่หลุด"""
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=int(settings.MEDIA_WEBP_QUALITY), method=4)
    return buf.getvalue()


def _process_image_sync(raw: bytes) -> dict:
    if not raw:
        raise ValidationError("ไฟล์รูปว่าง")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError("รับเฉพาะไฟล์ JPEG, PNG, WebP หรือ HEIC")
            width, height = im.size
            if width * height > MAX_PIXELS:
                raise ValidationError("รูปมีขนาดพิกเซลใหญ่เกินไป")
            if min(width, height) < int(settings.MEDIA_MIN_DIMENSION):
                raise ValidationError(
                    f"รูปเล็กเกินไป (ด้านสั้นต้องอย่างน้อย {settings.MEDIA_MIN_DIMENSION}px)"
                )
            im.load()
            im = ImageOps.exif_transpose(im)  # หมุนตาม EXIF แล้วทิ้ง tag
            im = _to_rgb(im)

            full = _resize_longest(im, int(settings.MEDIA_MAX_DIMENSION))
            thumb = full.copy()
            thumb.thumbnail(
                (int(settings.MEDIA_THUMB_DIMENSION), int(settings.MEDIA_THUMB_DIMENSION)),
                Image.Resampling.LANCZOS,
            )
            full_bytes = _encode_webp(full)
            thumb_bytes = _encode_webp(thumb)
            out_w, out_h = full.size
    except ValidationError:
        raise
    except Image.DecompressionBombError:
        raise ValidationError("รูปมีขนาดพิกเซลใหญ่เกินไป")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValidationError("ไฟล์รูปเสียหรือไม่ใช่รูปภาพที่รองรับ") from e

    return {
        "file_kind": "image",
        "data": full_bytes,
        "thumb_data": thumb_bytes,
        "sha256": hashlib.sha256(full_bytes).hexdigest(),
        "thumb_sha256": hashlib.sha256(thumb_bytes).hexdigest(),
        "bytes": len(full_bytes),
        "width": out_w,
        "height": out_h,
        "page_count": None,
        "mime": MIME_IMAGE,
    }


def _sanitize_pdf_sync(raw: bytes) -> dict:
    """ตรวจ + เขียน PDF ใหม่ (เก็บเฉพาะหน้า) ⇒ ตัด JavaScript / embedded files ระดับเอกสาร"""
    if not raw.startswith(PDF_MAGIC):
        raise ValidationError("ไฟล์ PDF ไม่ถูกต้อง")
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as e:  # pragma: no cover
        raise ValidationError("ระบบยังไม่พร้อมรับไฟล์ PDF") from e

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValidationError("ไม่รองรับ PDF ที่มีรหัสผ่าน")
        page_count = len(reader.pages)
        if page_count < 1:
            raise ValidationError("ไฟล์ PDF ไม่มีหน้า")
        if page_count > int(settings.MEDIA_MAX_PDF_PAGES):
            raise ValidationError(
                f"PDF มีเกิน {settings.MEDIA_MAX_PDF_PAGES} หน้า — กรุณาแยกไฟล์"
            )
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError("ไฟล์ PDF เสียหรืออ่านไม่ได้") from e

    if not data.startswith(PDF_MAGIC):
        raise ValidationError("ไฟล์ PDF เสียหรืออ่านไม่ได้")

    return {
        "file_kind": "pdf",
        "data": data,
        "thumb_data": None,
        "sha256": hashlib.sha256(data).hexdigest(),
        "thumb_sha256": None,
        "bytes": len(data),
        "width": None,
        "height": None,
        "page_count": page_count,
        "mime": MIME_PDF,
    }


def _process_file_sync(raw: bytes) -> dict:
    """แยกชนิดด้วย magic bytes (ไม่เชื่อ MIME จาก client) แล้วประมวลผลตามชนิด"""
    if raw.startswith(PDF_MAGIC):
        return _sanitize_pdf_sync(raw)
    return _process_image_sync(raw)


def _sniff_is_pdf(raw: bytes) -> bool:
    return raw.startswith(PDF_MAGIC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _limits() -> dict:
    return {
        "max_per_owner": int(settings.MEDIA_MAX_FINANCE_ATTACHMENTS),
        "max_per_request": int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST),
        "image_size_limit_mb": int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB),
        "document_size_limit_mb": int(settings.MEDIA_DOCUMENT_SIZE_LIMIT_MB),
        "max_total_mb": int(settings.MEDIA_MAX_ATTACHMENT_BYTES_TOTAL_MB),
        "max_pdf_pages": int(settings.MEDIA_MAX_PDF_PAGES),
    }


def _clean_original_name(name: Optional[str]) -> Optional[str]:
    """เก็บแค่ชื่อไฟล์ (ตัด path) และจำกัดความยาว — ห้ามใช้เป็น path ที่ไหนอีก"""
    if not name:
        return None
    base = Path(str(name).replace("\\", "/")).name.strip()
    return base[:120] or None


def _attachment_to_dict(row: asyncpg.Record, viewer_id: int) -> dict:
    attachment_id = str(row["id"])
    return {
        "id": attachment_id,
        "owner_type": row["owner_type"],
        "owner_id": row["owner_id"],
        "file_kind": row["file_kind"],
        "kind": row["kind"],
        "original_name": row["original_name"],
        "url": sign_url(attachment_id, "full", viewer_id),
        "thumb_url": sign_url(attachment_id, "thumb", viewer_id) if row["thumb_path"] else None,
        "mime": row["mime"],
        "width": row["width"],
        "height": row["height"],
        "page_count": row["page_count"],
        "bytes": row["bytes"],
        "uploaded_by": row["uploaded_by"],
        "created_at": row["created_at"],
    }


async def resolve_owner_room(
    conn: asyncpg.Connection,
    owner_type: str,
    owner_id: int,
    *,
    lock: bool = False,
    allow_deleted: bool = False,
) -> Optional[dict]:
    """คืนแถวเจ้าของ (อย่างน้อยมี `room_id`) หรือ `None` ถ้าไม่พบ

    ⚠️ นี่คือ **policy เดียว** ที่ตัดสินว่าไฟล์ของ owner นี้อยู่ในห้องไหน — เรียกทุกครั้ง
       ที่อัป/อ่าน/ลบ เพื่อไม่ต้องเก็บ `room_id` ซ้ำในตารางไฟล์ (และไม่ให้ drift)
    """
    if owner_type == "transaction":
        deleted = "" if allow_deleted else " AND deleted_at IS NULL"
        lock_sql = " FOR UPDATE" if lock else ""
        return await conn.fetchrow(
            f"""SELECT id, room_id, transaction_type, expense_voucher_id
                FROM finance_transactions
                WHERE id = $1{deleted}{lock_sql}""",
            owner_id,
        )

    if owner_type == "student_payment":
        deleted = "" if allow_deleted else " AND sp.deleted_at IS NULL"
        lock_sql = " FOR UPDATE OF sp" if lock else ""
        return await conn.fetchrow(
            f"""SELECT sp.id, fc.room_id
                FROM student_payments sp
                JOIN fee_collections fc ON fc.id = sp.collection_id
                WHERE sp.id = $1{deleted}{lock_sql}""",
            owner_id,
        )

    if owner_type == "payment_event":
        lock_sql = " FOR UPDATE" if lock else ""
        return await conn.fetchrow(
            f"""SELECT id, room_id, status
                FROM finance_payment_events
                WHERE id = $1{lock_sql}""",
            owner_id,
        )

    return None


def _default_kind(owner_type: str, owner_row: asyncpg.Record) -> str:
    if owner_type in ("student_payment", "payment_event"):
        return "payment_proof"
    # transaction
    if owner_row["transaction_type"] == "income":
        return "payment_proof"
    if owner_row["expense_voucher_id"] is not None:
        return "withdrawal_evidence"
    return "expense_evidence"


def _validate_owner_type(owner_type: str) -> None:
    if owner_type not in OWNER_TYPES:
        raise ValidationError("ชนิดของเจ้าของไฟล์ไม่ถูกต้อง")


def _validate_kind(kind: Optional[str]) -> Optional[str]:
    if kind is None:
        return None
    cleaned = str(kind).strip().lower()
    if cleaned not in VALID_KINDS:
        raise ValidationError("ชนิดของหลักฐานไม่ถูกต้อง")
    return cleaned


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------
async def upload_attachments(
    pool: asyncpg.Pool,
    user_id: int,
    room_id: int,
    owner_type: str,
    owner_id: int,
    files: Sequence[Tuple[str, bytes]],
    requested_kind: Optional[str] = None,
    *,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict:
    """อัปโหลดไฟล์หลักฐาน (รูป + PDF) — คืน `{items, limits}`

    ลำดับ: validate → **ประมวลผลนอกร transaction** → BEGIN → สิทธิ์/โควตา →
    เขียนไฟล์ → INSERT + audit → COMMIT
    """
    _validate_owner_type(owner_type)
    kind_override = _validate_kind(requested_kind)

    if not files:
        raise ValidationError("ต้องเลือกไฟล์อย่างน้อย 1 ไฟล์")
    if len(files) > int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST):
        raise ValidationError(
            f"อัปโหลดได้ครั้งละไม่เกิน {settings.MEDIA_MAX_UPLOAD_PER_REQUEST} ไฟล์"
        )

    image_limit = int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB) * 1024 * 1024
    pdf_limit = int(settings.MEDIA_DOCUMENT_SIZE_LIMIT_MB) * 1024 * 1024

    # 1) ตรวจขนาดตามชนิด ( sniff จาก magic bytes ก่อน — ไม่ต้อง decode ฟรี )
    names: list[Optional[str]] = []
    for filename, raw in files:
        is_pdf = _sniff_is_pdf(raw)
        limit = pdf_limit if is_pdf else image_limit
        if len(raw) > limit:
            limit_mb = limit // (1024 * 1024)
            raise PayloadTooLargeError(
                f"{'ไฟล์ PDF' if is_pdf else 'รูป'}ใหญ่เกิน {limit_mb} MB"
            )
        if not raw:
            raise ValidationError("ไฟล์ว่าง")
        names.append(_clean_original_name(filename))

    # 2) ประมวลผลให้เสร็จ **ก่อน** เปิด transaction
    processed = []
    for (_name, raw) in files:
        processed.append(await run_in_threadpool(_process_file_sync, raw))

    storage = get_media_storage()

    async with pool.acquire() as conn:
        async with conn.transaction():
            owner_row = await resolve_owner_room(
                conn, owner_type, owner_id, lock=True
            )
            if owner_row is None or int(owner_row["room_id"]) != int(room_id):
                # ไม่แยกว่า "ไม่มีเจ้าของ" กับ "อยู่ห้องอื่น" — กันการเดาข้อมูลข้ามห้อง
                raise FinanceAttachmentNotFoundError("ไม่พบรายการที่ต้องการแนบหลักฐาน")

            await require_permission(conn, room_id, user_id, "MANAGE_FINANCE")

            kind = kind_override or _default_kind(owner_type, owner_row)

            existing_count = await conn.fetchval(
                """SELECT COUNT(*) FROM finance_attachments
                   WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL""",
                owner_type, owner_id,
            )
            total_bytes = await conn.fetchval(
                """SELECT COALESCE(SUM(bytes), 0) FROM finance_attachments
                   WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL""",
                owner_type, owner_id,
            )
            max_per_owner = int(settings.MEDIA_MAX_FINANCE_ATTACHMENTS)
            if int(existing_count) + len(processed) > max_per_owner:
                raise ValidationError(
                    f"แนบได้ไม่เกิน {max_per_owner} ไฟล์ต่อรายการ "
                    f"(มีอยู่แล้ว {int(existing_count)} ไฟล์)"
                )

            hourly_count = await conn.fetchval(
                """SELECT COUNT(*) FROM finance_attachments
                   WHERE uploaded_by = $1
                     AND created_at > NOW() - INTERVAL '1 hour'
                     AND deleted_at IS NULL""",
                user_id,
            )
            if int(hourly_count) + len(processed) > int(settings.MEDIA_MAX_UPLOAD_PER_HOUR):
                raise RateLimitError("อัปโหลดบ่อยเกินไป — กรุณารอสักครู่แล้วลองใหม่")

            total_limit = int(settings.MEDIA_MAX_ATTACHMENT_BYTES_TOTAL_MB) * 1024 * 1024
            new_bytes = sum(int(item["bytes"]) for item in processed)
            if int(total_bytes) + new_bytes > total_limit:
                raise PayloadTooLargeError(
                    f"ขนาดไฟล์รวมต่อรายการต้องไม่เกิน "
                    f"{settings.MEDIA_MAX_ATTACHMENT_BYTES_TOTAL_MB} MB"
                )

            items = []
            for idx, item in enumerate(processed):
                attachment_id = uuid.uuid4()
                ext = "webp" if item["file_kind"] == "image" else "pdf"
                storage_path = (
                    f"media/finance/{owner_type}/{owner_id}/{attachment_id}.{ext}"
                )
                thumb_path = (
                    f"media/finance/{owner_type}/{owner_id}/{attachment_id}_thumb.webp"
                    if item["file_kind"] == "image"
                    else None
                )

                # ⚠️ เขียนไฟล์ก่อน INSERT — crash แล้วเหลือ orphan (purge เก็บได้)
                #    ตรงกันข้าม = แถวชี้ไฟล์ที่ไม่มี → 404 ตลอดกาล
                await storage.write(storage_path, item["data"])
                if thumb_path is not None:
                    await storage.write(thumb_path, item["thumb_data"])

                row = await conn.fetchrow(
                    """INSERT INTO finance_attachments (
                           id, owner_type, owner_id, file_kind, kind, original_name,
                           uploaded_by, storage_path, thumb_path,
                           sha256, thumb_sha256, mime, bytes, width, height, page_count
                       ) VALUES (
                           $1, $2, $3, $4, $5, $6,
                           $7, $8, $9,
                           $10, $11, $12, $13, $14, $15, $16
                       )
                       RETURNING *""",
                    attachment_id, owner_type, owner_id, item["file_kind"], kind, names[idx],
                    user_id, storage_path, thumb_path,
                    item["sha256"], item["thumb_sha256"], item["mime"],
                    item["bytes"], item["width"], item["height"], item["page_count"],
                )

                await service_logger.log(
                    conn=conn,
                    action="CREATE_FINANCE_ATTACHMENT",
                    actor_identifier=actor_identifier or f"user_id:{user_id}",
                    client_source=client_source,
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="FINANCE_ATTACHMENT",
                    entity_id=str(attachment_id),
                    new_values={
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "file_kind": item["file_kind"],
                        "kind": kind,
                        "original_name": names[idx],
                        "bytes": item["bytes"],
                        "width": item["width"],
                        "height": item["height"],
                        "page_count": item["page_count"],
                        "sha256": item["sha256"],
                        "storage_path": storage_path,
                    },
                    endpoint_or_command="FinanceAttachmentService.upload_attachments",
                )
                items.append(_attachment_to_dict(row, user_id))

    return {"items": items, "limits": _limits()}


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
async def list_attachments(
    pool: asyncpg.Pool,
    user_id: int,
    room_id: int,
    owner_type: str,
    owner_id: int,
) -> dict:
    _validate_owner_type(owner_type)
    async with pool.acquire() as conn:
        owner_row = await resolve_owner_room(conn, owner_type, owner_id, allow_deleted=True)
        if owner_row is None or int(owner_row["room_id"]) != int(room_id):
            raise FinanceAttachmentNotFoundError("ไม่พบรายการที่ต้องการดูหลักฐาน")

        await require_member(conn, room_id, user_id)

        rows = await conn.fetch(
            """SELECT * FROM finance_attachments
               WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL
               ORDER BY created_at, id""",
            owner_type, owner_id,
        )

    return {"items": [_attachment_to_dict(r, user_id) for r in rows], "limits": _limits()}


# ---------------------------------------------------------------------------
# delete (soft)
# ---------------------------------------------------------------------------
async def delete_attachment(
    pool: asyncpg.Pool,
    user_id: int,
    room_id: int,
    attachment_id: str,
    *,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict:
    try:
        attachment_uuid = uuid.UUID(str(attachment_id))
    except (ValueError, TypeError):
        raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """SELECT * FROM finance_attachments
                   WHERE id = $1 AND deleted_at IS NULL
                   FOR UPDATE""",
                attachment_uuid,
            )
            if row is None:
                raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

            owner_row = await resolve_owner_room(
                conn, row["owner_type"], row["owner_id"], allow_deleted=True
            )
            if owner_row is None or int(owner_row["room_id"]) != int(room_id):
                raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

            await require_permission(conn, room_id, user_id, "MANAGE_FINANCE")

            await conn.execute(
                "UPDATE finance_attachments SET deleted_at = NOW() WHERE id = $1",
                attachment_uuid,
            )
            await service_logger.log(
                conn=conn,
                action="DELETE_FINANCE_ATTACHMENT",
                actor_identifier=actor_identifier or f"user_id:{user_id}",
                client_source=client_source,
                room_id=room_id,
                user_id=user_id,
                entity_type="FINANCE_ATTACHMENT",
                entity_id=str(attachment_uuid),
                old_values={
                    "owner_type": row["owner_type"],
                    "owner_id": row["owner_id"],
                    "file_kind": row["file_kind"],
                    "storage_path": row["storage_path"],
                    "sha256": row["sha256"],
                },
                endpoint_or_command="FinanceAttachmentService.delete_attachment",
            )

    return {"status": "success", "message": "ลบไฟล์หลักฐานแล้ว"}


# ---------------------------------------------------------------------------
# serve (signed URL)
# ---------------------------------------------------------------------------
async def resolve_attachment_for_serving(
    pool: asyncpg.Pool,
    attachment_id: str,
    variant: Optional[str],
    viewer: Optional[str],
    exp: Optional[str],
    sig: Optional[str],
) -> Tuple[asyncpg.Record, Path]:
    """ตรวจลายเซ็น → โหลดแถว → **ตรวจสิทธิ์ซ้ำ** → ตรวจไฟล์มีจริง

    ⚠️ คืน path ที่ผ่าน containment เท่านั้น · ไฟล์หาย/แถวเสีย = 404 (ไม่ใช่ 500)
    """
    verified = verify_signature(str(attachment_id), variant, viewer, exp, sig)
    if verified is None:
        raise ForbiddenError("ลิงก์ไฟล์ไม่ถูกต้องหรือหมดอายุ")
    viewer_id, _variant = verified

    try:
        attachment_uuid = uuid.UUID(str(attachment_id))
    except (ValueError, TypeError):
        raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM finance_attachments
               WHERE id = $1 AND deleted_at IS NULL""",
            attachment_uuid,
        )
        if row is None:
            raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

        owner_row = await resolve_owner_room(
            conn, row["owner_type"], row["owner_id"], allow_deleted=True
        )
        if owner_row is None:
            raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานนี้")

        await require_member(conn, int(owner_row["room_id"]), viewer_id)

    # thumb ใช้ได้เฉพาะรูปที่มี thumb_path; PDF (หรือรูปที่ไม่มี thumb) ถอยไปใช้ไฟล์เต็ม
    key = row["thumb_path"] if _variant == "thumb" and row["thumb_path"] else row["storage_path"]

    storage = get_media_storage()
    try:
        path = storage.local_path(key)
        if path is None:
            raise MediaStorageError("storage backend นี้ไม่รองรับ FileResponse")
        exists = await storage.exists(key)
    except MediaStorageError:
        logger.warning(
            "finance attachment file unusable: id=%s key=%r", attachment_uuid, key
        )
        raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานในที่จัดเก็บ")

    if not exists:
        logger.warning("finance attachment file missing: id=%s key=%r", attachment_uuid, key)
        raise FinanceAttachmentNotFoundError("ไม่พบไฟล์หลักฐานในที่จัดเก็บ")

    return row, path


def attachment_headers(row: asyncpg.Record, *, download: bool = False) -> dict:
    """headers ของการเสิร์ฟไฟล์ — PDF ได้ CSP sandbox เพิ่ม (กันสคริปต์ในไฟล์)

    `download=True` (จาก `?download=1`) เปลี่ยน disposition เป็น attachment
    โดยยังใช้ลายเซ็นเดิม — flag นี้ไม่เปลี่ยนสิทธิ์การเข้าถึง
    """
    headers = {
        "Cache-Control": "private, max-age=60, no-transform",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex",
        "Content-Disposition": "inline",
    }
    if download:
        name = row["original_name"] or f"finance-attachment-{row['id']}"
        # กัน header injection และตัดให้สั้น — ชื่อไฟล์มาจากผู้ใช้
        safe = re.sub(r'[\r\n"\\]', "_", str(name))[:120]
        headers["Content-Disposition"] = (
            "attachment; filename=\"download\"; "
            f"filename*=UTF-8''{quote(safe)}"
        )
    if row["mime"] == MIME_PDF:
        headers["Content-Security-Policy"] = "sandbox"
    return headers
