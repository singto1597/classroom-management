"""🗂️ [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — union `finance_receipts` + `finance_monthly_reports`

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
ทะเบียนเดิม (`get_receipts`) อ่าน **ตารางเดียว** `finance_receipts`, กรอง `doc_type`
ได้ครั้งละชนิด, `LIMIT 500` แข็ง, ไม่มี RPT และไม่มี cross-link ⇒ หน้าเดียวบอกไม่ได้ว่า
"เดือนนี้ห้องออกเอกสารอะไรไปบ้าง" เพราะใบเสร็จ ใบสำคัญจ่าย และรายงานปิดงบอยู่คนละที่

ที่นี่คือ **ทางอ่านเดียว**: รายการเดียวที่รวมทุกชนิด + pagination + ตัวกรอง 7 มิติ +
รายละเอียดที่เห็นเอกสารที่ลิงก์กัน + พิมพ์ชุด ≤100 ใบ (mixed layout ในไฟล์เดียว)

🔴 กติกาข้อสำคัญ
- **ไม่แตะ** `get_receipts`/`get_receipt` เดิม — legacy list ยังกรอง `layout_version=1`
  ตาม P2.2 (หน้าจอเดิมพึ่งพฤติกรรมนั้น)
- **ไม่เรียก `get_receipt`** ใน detail: มันตัดใบที่ถูก void ออก แต่ทะเบียนคือมุมมอง
  ตรวจสอบย้อนหลัง ⇒ ใบ void ต้องเปิดได้เสมอ
- `deleted_at` ของ receipts กรอง **ใน subquery ก่อน UNION** เพราะ `finance_monthly_reports`
  ไม่มีคอลัมน์นี้ (กรองหลัง union จะ error)
- `finance_receipts` **ไม่มีคอลัมน์ `channel_id`** ⇒ กรอง/แสดงผ่าน
  `document_meta->>'channel_id'` (สัญญาการเขียนคีย์นี้เป็นของ P2.2/P4.1/P4.4/P5.4)
- `RECEIPT_LIKE_DOC_TYPES`/`DOC_TYPE_LABELS` มาจาก constants — ห้ามประกาศซ้ำที่นี่
"""
import json
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member

from .base import service_logger
from .document_void_target import resolve_void_target
from .helpers import _full_name
from .baht_text import baht_text
from .constants import (
    DOC_STATUS_VOIDED,
    DOC_TYPE_MONTHLY_REPORT,
    DOC_TYPE_RECEIPT,
    PDF_BATCH_TIMEOUT,
    RECEIPTS_PER_PDF_MAX,
    RECEIPT_NO_PATTERN,
    REGISTRY_DOC_TYPES,
    REGISTRY_PAGE_DEFAULT,
    REGISTRY_PAGE_MAX,
)
# ⚠️ ไม่ import `pdf` ที่หัวไฟล์ — เดินตามแบบ `receipts.py`: ผู้เรียก `from .pdf import …`
#    ในฟังก์ชัน ทำให้ `patch("services.finance.pdf.html_to_pdf")` ของเทสต์มีผลจริง


# ===================================================================== helpers
def _money_text(value) -> Optional[str]:
    """`Decimal`/`float`/`None` → ข้อความเงิน 2 ตำแหน่ง (สัญญา response ของ registry)

    ⚠️ เก็บเป็น **สตริง** ไม่ใช่ float: ตัวเลขเงินที่ผ่าน float แล้ว round ตำแหน่งทศนิยม
       อาจเพี้ยน (0.1 + 0.2) และ frontend มี `formatMoney` ที่อ่านสตริงอยู่แล้ว
    """
    if value is None:
        return None
    return f"{float(value):.2f}"


def _int_or_none(value) -> Optional[int]:
    """ค่า jsonb ที่อาจเป็นสตริง/None → int (หรือ None) — ไม่ raise กับค่าขยะ"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _student_name(row) -> Optional[str]:
    """ชื่อ-นามสกุลเต็มของนักเรียนจากแถวที่ JOIN `users` — ไม่ต่อชื่อเล่น

    `students` ไม่มีคอลัมน์ชื่อ (ชื่ออยู่ที่ `users` ผ่าน `students.user_id`)
    ⇒ นักเรียนที่ยังไม่ผูกบัญชีผู้ใช้จะได้ `None` ไม่ใช่ "Unknown" ปลอม ๆ
    """
    return _full_name(row) or None


def _jsonb_dict(raw) -> dict:
    """jsonb จาก asyncpg (มักเป็น str) → dict — เฉพาะค่าที่เป็น object"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _escape_like(value: str) -> str:
    """escape `%`/`_`/`\\` ของค่าที่ผู้ใช้พิมพ์ก่อนทำ `ILIKE ... ESCAPE '\\'`

    ถ้าไม่ทำ: พิมพ์ `%` แล้วได้ทุกแถว และพิมพ์ `_` แล้ว match ตัวอักษรใดก็ได้
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DocumentRegistryMixin:
    """ทะเบียนเอกสารรวม (ใช้ผ่าน MRO ของ `FinanceService`)

    ⚠️ ไม่ประกาศชื่อฟังก์ชันซ้ำกับ mixin ใด — เป็นการ **อ่าน** ล้วน
       (ยกเว้น audit log ที่เขียนตาราง log ตามกติกาเดิม)
    """

    # ---------------------------------------------------------------- รายการ
    @classmethod
    async def list_documents(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        doc_types: Optional[Sequence[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        student_id: Optional[int] = None,
        receiver_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        include_voided: bool = False,
        limit: int = REGISTRY_PAGE_DEFAULT,
        offset: int = 0,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายการเอกสารทุกชนิดของห้อง — เรียงใหม่สุดก่อน + pagination แบบ offset

        🔓 อ่านได้โดยสมาชิก (`require_member`) — ทะเบียนไม่ใช่ข้อมูลที่ต้องมีสิทธิ์เขียน

        🚫 ค่าปริยายตัดใบที่ถูก void (ทั้ง receipts และ monthly_reports);
           `include_voided=True` หรือ `status='voided'` เปิดมุมมองตรวจสอบ
        """
        start_time = time.time()
        target_room_id = room_id

        wanted_types = cls._normalise_doc_types(doc_types)
        if status is not None and status not in ("active", DOC_STATUS_VOIDED):
            raise ValueError("สถานะที่กรองได้มีแค่ active หรือ voided")
        if limit < 1:
            raise ValueError("จำนวนรายการต่อหน้าต้องมากกว่า 0")
        limit = min(int(limit), REGISTRY_PAGE_MAX)
        offset = max(int(offset), 0)

        # 🔎 มุมมองตรวจสอบต้องเห็นใบที่ถูกลบ/ยกเลิก ⇒ ตัด `deleted_at` ออกทั้งก้อน
        include_hidden = include_voided or status == DOC_STATUS_VOIDED
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                where: List[str] = []
                params: List[Any] = [target_room_id]
                idx = 2

                if wanted_types:
                    where.append(f"doc_type = ANY(${idx}::text[])")
                    params.append(wanted_types)
                    idx += 1

                if status is not None:
                    where.append(f"status = ${idx}")
                    params.append(status)
                    idx += 1
                elif not include_voided:
                    # 🚫 ค่าปริยาย: ไม่คืนใบที่ถูกยกเลิก
                    where.append(f"status <> ${idx}")
                    params.append(DOC_STATUS_VOIDED)
                    idx += 1

                if start_date is not None:
                    # ขอบเขตวันไทยแบบ half-open — ตรงกับ `get_receipts` เป๊ะ
                    where.append(
                        f"doc_at >= ((${idx}::date)::timestamp AT TIME ZONE 'Asia/Bangkok')"
                    )
                    params.append(start_date)
                    idx += 1
                if end_date is not None:
                    where.append(
                        f"doc_at < (((${idx}::date) + 1)::timestamp AT TIME ZONE 'Asia/Bangkok')"
                    )
                    params.append(end_date)
                    idx += 1

                if student_id is not None:
                    where.append(f"student_id = ${idx}")
                    params.append(student_id)
                    idx += 1
                if receiver_id is not None:
                    where.append(f"receiver_person_id = ${idx}")
                    params.append(receiver_id)
                    idx += 1
                if channel_id is not None:
                    where.append(f"channel_id = ${idx}")
                    params.append(channel_id)
                    idx += 1

                if q and q.strip():
                    needle = f"%{_escape_like(q.strip())}%"
                    where.append(
                        "(doc_no ILIKE ${i} ESCAPE '\\'"
                        " OR student_name ILIKE ${i} ESCAPE '\\'"
                        " OR receiver_name ILIKE ${i} ESCAPE '\\')".replace(
                            "${i}", f"${idx}"
                        )
                    )
                    params.append(needle)
                    idx += 1

                where_sql = ("WHERE " + " AND ".join(where)) if where else ""

                # 🔴 `deleted_at` อยู่ใน subquery ก่อน UNION — ไม่ใช่หลัง UNION
                #    (monthly_reports ไม่มีคอลัมน์นี้ ⇒ ใส่หลัง union จะ error ทั้งหน้า)
                receipt_hidden = "" if include_hidden else " AND R.deleted_at IS NULL"

                sql = f"""
                    WITH docs AS (
                        SELECT
                            R.doc_type                                   AS doc_type,
                            R.id                                         AS doc_id,
                            R.receipt_no                                 AS doc_no,
                            COALESCE(R.event_at, R.issued_at)            AS doc_at,
                            R.issued_at                                  AS issued_at,
                            R.amount                                     AS amount,
                            R.status                                     AS status,
                            R.layout_version                             AS layout_version,
                            R.student_id                                 AS student_id,
                            S.student_no                                 AS student_no,
                            COALESCE(
                                NULLIF(BTRIM(CONCAT_WS(' ', U.prefix, U.first_name,
                                                       U.last_name)), ''),
                                NULLIF(BTRIM(U.first_name), ''),
                                NULLIF(BTRIM(U.username), ''))           AS student_name,
                            COALESCE(R.receiver_person_id,
                                     NULLIF(R.document_meta->>'receiver_person_id', '')::bigint)
                                                                         AS receiver_person_id,
                            FP.display_name                              AS receiver_name,
                            NULLIF(R.document_meta->>'channel_id', '')::bigint
                                                                         AS channel_id,
                            R.payment_event_id                           AS payment_event_id,
                            CASE WHEN jsonb_typeof(R.line_items) = 'array'
                                 THEN jsonb_array_length(R.line_items) END
                                                                         AS line_item_count,
                            -- 🎯 วัตถุดิบสำหรับ `resolve_void_target()` — record ต้นทาง
                            --    ที่จะต้องไปเรียก void (ดู document_void_target.py)
                            R.legacy_transaction_id                      AS legacy_transaction_id,
                            R.document_meta->>'voucher_id'               AS voucher_id_raw,
                            R.document_meta->>'batch_id'                 AS batch_id_raw,
                            R.deleted_at                                 AS deleted_at
                        FROM finance_receipts R
                        LEFT JOIN students S ON S.id = R.student_id
                        LEFT JOIN users U ON U.id = S.user_id
                        LEFT JOIN finance_people FP
                               ON FP.id = COALESCE(R.receiver_person_id,
                                       NULLIF(R.document_meta->>'receiver_person_id', '')::bigint)
                        WHERE R.room_id = $1{receipt_hidden}

                        UNION ALL

                        SELECT
                            'monthly_report'::text,
                            M.id,
                            M.report_no,
                            COALESCE(M.finalized_at, M.created_at),
                            M.finalized_at,
                            (M.total_income - M.total_expense)::numeric,
                            M.status,
                            2::smallint,
                            NULL::integer,
                            NULL::integer,
                            NULL::text,
                            NULL::bigint,
                            NULL::text,
                            NULL::bigint,
                            NULL::bigint,
                            NULL::integer,
                            -- 4 คอลัมน์ void_target — RPT ไม่มี record ต้นทางแบบ receipt
                            NULL::integer,
                            NULL::text,
                            NULL::text,
                            NULL::timestamp with time zone
                        FROM finance_monthly_reports M
                        WHERE M.room_id = $1
                    )
                    SELECT *, COUNT(*) OVER () AS total_count
                    FROM docs
                    {where_sql}
                    ORDER BY doc_at DESC NULLS LAST, doc_id DESC
                    LIMIT ${idx} OFFSET ${idx + 1}
                """
                params.extend([limit, offset])

                rows = await conn.fetch(sql, *params)
                total = int(rows[0]["total_count"]) if rows else 0

                items = [
                    {
                        "doc_type": r["doc_type"],
                        "doc_id": int(r["doc_id"]),
                        "doc_no": r["doc_no"],
                        "doc_at": r["doc_at"],
                        "amount": _money_text(r["amount"]),
                        "status": r["status"],
                        "layout_version": int(r["layout_version"] or 1),
                        "student_id": r["student_id"],
                        "student_no": r["student_no"],
                        "student_name": r["student_name"],
                        "receiver_person_id": _int_or_none(r["receiver_person_id"]),
                        "receiver_name": r["receiver_name"],
                        "channel_id": _int_or_none(r["channel_id"]),
                        "line_item_count": r["line_item_count"],
                        "void_target": resolve_void_target(
                            doc_type=r["doc_type"],
                            doc_id=int(r["doc_id"]),
                            doc_no=r["doc_no"],
                            status=r["status"],
                            deleted=r["deleted_at"] is not None,
                            payment_event_id=_int_or_none(r["payment_event_id"]),
                            legacy_transaction_id=_int_or_none(
                                r["legacy_transaction_id"]
                            ),
                            voucher_id=_int_or_none(r["voucher_id_raw"]),
                            batch_id=_int_or_none(r["batch_id_raw"]),
                        ),
                    }
                    for r in rows
                ]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_DOCUMENT", status="success",
                    endpoint_or_command="FinanceService.list_documents",
                    execution_time_ms=exec_time,
                )
                return {"items": items, "total": total, "limit": limit, "offset": offset}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_DOCUMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.list_documents",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # -------------------------------------------------------------- ละเอียด
    @classmethod
    async def get_document_detail(
        cls,
        pool: asyncpg.Pool,
        doc_type: str,
        doc_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายละเอียดเอกสาร 1 ใบ (dispatch ตามชนิด) — ใบ void อ่านได้เสมอ

        🔴 **ไม่เรียก `get_receipt(receipt_no)`**: เส้นทางนั้นตัดใบ void ออก และระบุด้วย
           เลขเอกสาร (str) ไม่ใช่ `(doc_type, id)` ⇒ ใช้ไม่ได้กับ ACK/PV/CERT/INC/RPT
        """
        if doc_type not in REGISTRY_DOC_TYPES:
            raise ValueError(f"ไม่รู้จักชนิดเอกสาร '{doc_type}'")

        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if doc_type == DOC_TYPE_MONTHLY_REPORT:
                    d = await cls._monthly_report_detail(conn, target_room_id, int(doc_id))
                else:
                    row = await cls._fetch_receipt_row(conn, target_room_id, doc_type, int(doc_id))
                    d = cls._registry_detail_from_row(row)
                    d["signatures"] = await cls._load_signatures(
                        conn, target_room_id, doc_type, int(doc_id)
                    )
                    d["links"] = await cls._load_links(
                        conn, target_room_id, doc_type, int(doc_id),
                        related_receipt_id=_int_or_none(row["related_receipt_id"]),
                    )
                    # 📎 ไฟล์หลักฐานของ record ต้นทาง — ชุดเดียวกับที่ต่อท้ายใน PDF
                    from .document_attachments import list_attachments_for_receipt

                    d["attachments"] = await list_attachments_for_receipt(
                        conn, int(row["id"]), int(user_id)
                    )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_DOCUMENT", entity_id=f"{doc_type}:{doc_id}",
                    status="success",
                    endpoint_or_command="FinanceService.get_document_detail",
                    execution_time_ms=exec_time,
                )
                return d
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_DOCUMENT", entity_id=f"{doc_type}:{doc_id}",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_document_detail",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    @classmethod
    async def get_document_detail_by_no(
        cls,
        pool: asyncpg.Pool,
        doc_no: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """resolver สำหรับ redirect จากเลขเอกสารเดิม — คืนรายละเอียดเหมือน detail

        P6.5 ต้องพา `/finance/receipts/:receiptNo` มาที่หน้าใหม่โดยไม่รู้ `doc_type`/`id`
        ⇒ ที่นี่ค้นทั้งสองตารางแล้วส่งต่อ `get_document_detail`
        """
        if not re.fullmatch(RECEIPT_NO_PATTERN, (doc_no or "").strip()):
            raise ValueError(
                "เลขเอกสารไม่ถูกต้อง — ต้องอยู่ในรูป REC-2569-0001 (หรือคำนำหน้าของชนิดนั้น)"
            )
        doc_no = doc_no.strip()

        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                hit = await conn.fetchrow(
                    "SELECT doc_type, id FROM finance_receipts WHERE room_id = $1 AND receipt_no = $2",
                    target_room_id, doc_no,
                )
                if hit is None:
                    hit = await conn.fetchrow(
                        "SELECT $3::text AS doc_type, id FROM finance_monthly_reports"
                        " WHERE room_id = $1 AND report_no = $2",
                        target_room_id, doc_no, DOC_TYPE_MONTHLY_REPORT,
                    )
                if hit is None:
                    raise RoomNotFoundError(f"ไม่พบเอกสารเลขที่ {doc_no} ในห้องนี้")

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_DOCUMENT", entity_id=doc_no, status="success",
                    endpoint_or_command="FinanceService.get_document_detail_by_no",
                    execution_time_ms=exec_time,
                )
            # ⬅️ ปล่อย connection ก่อนเรียก detail (detail acquire เอง + เขียน audit ของตัวเอง)
            return await cls.get_document_detail(
                pool=pool, doc_type=hit["doc_type"], doc_id=int(hit["id"]),
                client_source=client_source, actor_identifier=actor_identifier,
                server_id=None, room_id=target_room_id, user_id=user_id,
            )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_DOCUMENT", entity_id=doc_no, status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.get_document_detail_by_no",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------ PDF
    @classmethod
    async def render_document_pdf(
        cls,
        pool: asyncpg.Pool,
        doc_type: str,
        doc_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[bytes, str]:
        """PDF ของเอกสาร 1 ใบ — legacy ต้องได้ไบต์เดิมของ `render_receipt_pdf`

        🚫 RPT ยังไม่มี renderer (P5.4) ⇒ 404 พร้อมบอกทาง **ห้ามให้ 500**
        """
        if doc_type == DOC_TYPE_MONTHLY_REPORT:
            raise RoomNotFoundError("รายงานปิดงบพิมพ์ได้จากหน้ารายงานปิดงบ")
        if doc_type not in REGISTRY_DOC_TYPES:
            raise ValueError(f"ไม่รู้จักชนิดเอกสาร '{doc_type}'")

        from .pdf import html_to_pdf, pdf_filename, render_receipt_html

        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                head = await conn.fetchrow(
                    "SELECT receipt_no, layout_version FROM finance_receipts"
                    " WHERE room_id = $1 AND id = $2 AND doc_type = $3",
                    target_room_id, int(doc_id), doc_type,
                )
                if head is None:
                    raise RoomNotFoundError(f"ไม่พบเอกสาร {doc_type} #{doc_id} ในห้องนี้")

                # 🧾 legacy (layout 1) → เรียกเส้นทางเดิมทั้งดุ้น ⇒ ไบต์เท่าเดิมแน่นอน
                if int(head["layout_version"] or 1) < 2:
                    return await cls.render_receipt_pdf(
                        pool=pool, receipt_no=head["receipt_no"],
                        client_source=client_source, actor_identifier=actor_identifier,
                        server_id=None, room_id=target_room_id, user_id=user_id,
                    )

                row = await cls._fetch_receipt_row(conn, target_room_id, doc_type, int(doc_id))
                d = cls._shape_receipt_detail(row)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="PRINT", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_DOCUMENT", entity_id=f"{doc_type}:{doc_id}",
                    status="success",
                    endpoint_or_command="FinanceService.render_document_pdf",
                    execution_time_ms=exec_time,
                )
            # ⬅️ คืน connection ก่อนเรนเดอร์ (Chromium ใช้เวลาเป็นวินาที)
            html = render_receipt_html(cls._document_context(d))
            pdf_bytes = await html_to_pdf(html)

            # 📎 ต่อท้ายไฟล์หลักฐาน — layout v2 เรนเดอร์เอง (ไม่ผ่าน render_receipt_pdf)
            #    ⇒ ต้อง hook ที่นี่ด้วย ไม่งั้นปุ่มดาวน์โหลดในหน้ารายละเอียดเอกสารจะไม่มีไฟล์แนบ
            try:
                from .document_attachments import append_attachments_to_receipts

                pdf_bytes = await append_attachments_to_receipts(pool, [d], pdf_bytes)
            except Exception:
                import logging

                logging.getLogger("API_FINANCE_RECEIPTS").warning(
                    "แนบไฟล์หลักฐานเข้า PDF เอกสารเดี่ยวไม่สำเร็จ", exc_info=True
                )

            return pdf_bytes, pdf_filename(d["receipt_no"], d["doc_type"])
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="PRINT", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_DOCUMENT", entity_id=f"{doc_type}:{doc_id}",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.render_document_pdf",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    @classmethod
    async def render_document_bundle(
        cls,
        pool: asyncpg.Pool,
        items: Sequence[dict],
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[bytes, str]:
        """พิมพ์เอกสารหลายใบเป็น PDF ไฟล์เดียว — mixed layout (v1+v2) ใน `<style>` ชุดเดียว

        🔴 dedupe รักษาลำดับ — เลขซ้ำ = หน้าซ้ำในไฟล์เดียว ทำให้ "หน้าละใบ" เป็นเท็จ
        🔴 ขาดใบใด = 404 ทั้งคำขอ **ห้ามข้ามเงียบ ๆ** (ไฟล์ที่ขาดหน้าดูเหมือนไฟล์ที่ครบ)
           และต้องบอกเลขที่/ID ที่ขาดให้ผู้ใช้ตรวจได้
        """
        wanted: List[Tuple[str, int]] = list(
            dict.fromkeys(
                (str(it.get("doc_type")), int(it.get("doc_id"))) for it in (items or [])
            )
        )
        if not wanted:
            raise ValueError("ต้องเลือกเอกสารอย่างน้อย 1 ฉบับ")
        over = [t for t, _ in wanted if t not in REGISTRY_DOC_TYPES]
        if over:
            raise ValueError(f"ไม่รู้จักชนิดเอกสาร '{over[0]}'")
        if any(t == DOC_TYPE_MONTHLY_REPORT for t, _ in wanted):
            raise RoomNotFoundError("รายงานปิดงบพิมพ์ได้จากหน้ารายงานปิดงบ")
        if len(wanted) > RECEIPTS_PER_PDF_MAX:
            raise ValueError(
                f"รวมไฟล์ได้ครั้งละไม่เกิน {RECEIPTS_PER_PDF_MAX} ฉบับ "
                f"(เลือกมา {len(wanted)} ฉบับ) — กรุณาแบ่งดาวน์โหลดเป็นรอบละไม่เกิน "
                f"{RECEIPTS_PER_PDF_MAX} ฉบับ"
            )

        from .pdf import html_to_pdf, pdf_filename_batch, render_receipts_html

        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                ids = [doc_id for _, doc_id in wanted]
                rows = await conn.fetch(
                    cls._receipt_row_query("R.room_id = $1 AND R.id = ANY($2::bigint[])"),
                    target_room_id, ids,
                )
                by_id = {int(r["id"]): r for r in rows}

                missing = [
                    f"{t} #{i}" for t, i in wanted
                    if int(i) not in by_id or by_id[int(i)]["doc_type"] != t
                ]
                if missing:
                    raise RoomNotFoundError(
                        "ไม่พบเอกสาร " + ", ".join(missing) + " ในห้องนี้"
                    )

                docs = [cls._shape_receipt_detail(by_id[i]) for _, i in wanted]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="PRINT_BATCH", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_DOCUMENT", status="success",
                    new_values={
                        "items": [{"doc_type": t, "doc_id": i} for t, i in wanted],
                        "count": len(wanted),
                    },
                    endpoint_or_command="FinanceService.render_document_bundle",
                    execution_time_ms=exec_time,
                )
            # ⬅️ คืน connection ก่อนเรนเดอร์ (เหมือน `_render_documents_pdf`)
            html = render_receipts_html(cls._document_contexts(docs))
            pdf_bytes = await html_to_pdf(html, timeout=PDF_BATCH_TIMEOUT)

            # 📎 ต่อท้ายไฟล์แนบของทุกใบ (ตามลำดับเอกสาร) — best-effort
            try:
                from .document_attachments import append_attachments_to_receipts

                pdf_bytes = await append_attachments_to_receipts(pool, docs, pdf_bytes)
            except Exception:
                import logging

                logging.getLogger("API_FINANCE_RECEIPTS").warning(
                    "แนบไฟล์หลักฐานเข้า PDF ชุดเอกสารไม่สำเร็จ", exc_info=True
                )

            doc_types = {d["doc_type"] for d in docs}
            return pdf_bytes, pdf_filename_batch(
                [d["receipt_no"] for d in docs],
                docs[0]["doc_type"] if len(doc_types) == 1 else "documents",
            )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="PRINT_BATCH", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_DOCUMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.render_document_bundle",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ------------------------------------------------------- ตัวช่วยภายใน
    @staticmethod
    def _normalise_doc_types(doc_types: Optional[Sequence[str]]) -> Optional[List[str]]:
        """ตรวจ/ล้างรายการ `doc_types` — ค่าที่ไม่รู้จัก = 400 ไม่ใช่ผลลัพธ์ว่างเงียบ ๆ"""
        if not doc_types:
            return None
        cleaned = [t.strip() for t in doc_types if t and t.strip()]
        if not cleaned:
            return None
        unknown = [t for t in cleaned if t not in REGISTRY_DOC_TYPES]
        if unknown:
            raise ValueError(
                f"ไม่รู้จักชนิดเอกสาร '{unknown[0]}' — ใช้ได้: " + ", ".join(REGISTRY_DOC_TYPES)
            )
        return cleaned

    @staticmethod
    def _receipt_row_query(where_sql: str) -> str:
        """คิวรีแถว receipt แบบเต็ม (คอลัมน์ครบตาม `_shape_receipt_detail`)"""
        return f"""
            SELECT R.*,
                   FC.title AS collection_title,
                   FC.amount AS collection_amount,
                   FC.due_date AS collection_due_date,
                   S.student_no,
                   U.prefix, U.first_name, U.last_name, U.first_name_en, U.last_name_en,
                   FP.display_name AS receiver_name,
                   R2.room_name, R2.room_code
            FROM finance_receipts R
            LEFT JOIN fee_collections FC ON FC.id = R.collection_id
            LEFT JOIN students S ON S.id = R.student_id
            LEFT JOIN users U ON U.id = S.user_id
            LEFT JOIN finance_people FP
                   ON FP.id = COALESCE(R.receiver_person_id,
                           NULLIF(R.document_meta->>'receiver_person_id', '')::bigint)
            JOIN rooms R2 ON R2.id = R.room_id
            WHERE {where_sql}
        """

    @classmethod
    async def _fetch_receipt_row(
        cls, conn: asyncpg.Connection, room_id: int, doc_type: str, doc_id: int
    ):
        row = await conn.fetchrow(
            cls._receipt_row_query("R.room_id = $1 AND R.id = $2 AND R.doc_type = $3"),
            room_id, doc_id, doc_type,
        )
        if row is None:
            raise RoomNotFoundError(f"ไม่พบเอกสาร {doc_type} #{doc_id} ในห้องนี้")
        return row

    @classmethod
    def _registry_detail_from_row(cls, row) -> dict:
        """แถว receipt (พร้อม JOIN) → dict รายละเอียดของ registry + links/signatures

        ⚠️ `links`/`signatures` ถูกเติมโดยผู้เรียก (`get_document_detail`) เพราะต้อง
           เปิด cursor เพิ่ม — ตัวนี้จึงประกอบเฉพาะเนื้อเอกสาร
        """
        d = cls._shape_receipt_detail(row)
        meta = d.get("document_meta") or {}
        receiver_person_id = _int_or_none(row["receiver_person_id"]) or _int_or_none(
            meta.get("receiver_person_id")
        )
        amount_value = float(d["amount"]) if d.get("amount") is not None else None

        d["doc_type"] = row["doc_type"]
        d["doc_id"] = int(row["id"])
        d["doc_no"] = row["receipt_no"]
        d["doc_at"] = row["event_at"] or row["issued_at"]
        d["status"] = row["status"]
        d["layout_version"] = int(row["layout_version"] or 1)
        d["student_name"] = _student_name(row)
        d["receiver_person_id"] = receiver_person_id
        d["receiver_name"] = row["receiver_name"]
        d["channel_id"] = _int_or_none(meta.get("channel_id"))
        d["payment_event_id"] = _int_or_none(row["payment_event_id"])
        d["line_item_count"] = len(d["line_items"]) if d.get("line_items") else None
        # 🎯 ปลายทางของการยกเลิก (ตรงกับรายการใน list — ใช้ตัวตัดสินเดียวกัน)
        d["void_target"] = resolve_void_target(
            doc_type=row["doc_type"],
            doc_id=int(row["id"]),
            doc_no=row["receipt_no"],
            status=row["status"],
            deleted=row["deleted_at"] is not None,
            payment_event_id=_int_or_none(row["payment_event_id"]),
            legacy_transaction_id=_int_or_none(row["legacy_transaction_id"]),
            voucher_id=_int_or_none(meta.get("voucher_id")),
            batch_id=_int_or_none(meta.get("batch_id")),
        )
        # 💰 สัญญา response: เงินเป็นสตริง 2 ตำแหน่ง + คำอ่านภาษาไทย
        d["amount"] = _money_text(amount_value)
        d["amounts_in_words"] = baht_text(amount_value) if amount_value is not None else None
        d["signatures"] = []
        d["links"] = []
        return d

    @classmethod
    async def _monthly_report_detail(
        cls, conn: asyncpg.Connection, room_id: int, report_id: int
    ) -> dict:
        """รายละเอียดขั้นต่ำของ RPT — อ่านตารางตรง (lifecycle/PDF เป็นของ P5.4)"""
        row = await conn.fetchrow(
            "SELECT * FROM finance_monthly_reports WHERE room_id = $1 AND id = $2",
            room_id, report_id,
        )
        if row is None:
            raise RoomNotFoundError(f"ไม่พบรายงานปิดงบ #{report_id} ในห้องนี้")

        net = float(row["total_income"]) - float(row["total_expense"])
        signatures = await cls._load_signatures(
            conn, room_id, DOC_TYPE_MONTHLY_REPORT, report_id
        )
        links = await cls._load_links(
            conn, room_id, DOC_TYPE_MONTHLY_REPORT, report_id, related_receipt_id=None
        )
        return {
            "doc_type": DOC_TYPE_MONTHLY_REPORT,
            "doc_id": int(row["id"]),
            "doc_no": row["report_no"],
            "doc_type_label": "รายงานปิดงบ",
            "doc_at": row["finalized_at"] or row["created_at"],
            "issued_at": row["finalized_at"],
            "amount": _money_text(net),
            "amounts_in_words": baht_text(net),
            "status": row["status"],
            "layout_version": 2,
            "student_id": None,
            "student_no": None,
            "student_name": None,
            "receiver_person_id": None,
            "receiver_name": None,
            "channel_id": None,
            "payment_event_id": None,
            "line_item_count": None,
            "void_target": resolve_void_target(
                doc_type=DOC_TYPE_MONTHLY_REPORT,
                doc_id=int(row["id"]),
                status=row["status"],
            ),
            "issued_to_name": None,
            "issued_by_name": None,
            "note": None,
            "void_reason": row["void_reason"],
            "voided_at": row["voided_at"],
            "document_meta": {},
            "line_items": None,
            "year_be": row["year_be"],
            "month": row["month"],
            "version": row["version"],
            "total_income": float(row["total_income"]),
            "total_expense": float(row["total_expense"]),
            "opening_cash": float(row["opening_cash"]),
            "closing_cash": float(row["closing_cash"]),
            "counted_cash": (
                float(row["counted_cash"]) if row["counted_cash"] is not None else None
            ),
            "variance": float(row["variance"]) if row["variance"] is not None else None,
            "finalized_at": row["finalized_at"],
            "snapshot": _jsonb_dict(row["snapshot"]),
            "signatures": signatures,
            "links": links,
        }

    @classmethod
    async def _load_signatures(
        cls, conn: asyncpg.Connection, room_id: int, doc_type: str, doc_id: int
    ) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT role, person_id, signer_name, signed_at
            FROM finance_document_signatures
            WHERE room_id = $1 AND doc_type = $2 AND doc_id = $3
            ORDER BY sort_order, id
            """,
            room_id, doc_type, doc_id,
        )
        return [
            {
                "role": r["role"],
                "person_id": _int_or_none(r["person_id"]),
                "signer_name": r["signer_name"],
                "signed_at": r["signed_at"],
            }
            for r in rows
        ]

    @classmethod
    async def _load_links(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        doc_type: str,
        doc_id: int,
        related_receipt_id: Optional[int] = None,
    ) -> List[dict]:
        """ลิงก์สองทิศ + เติม `doc_no` ด้วยคำสั่งเดียวต่อชนิด (ห้าม N+1)"""
        rows = await conn.fetch(
            """
            SELECT link_type, from_doc_type, from_doc_id, to_doc_type, to_doc_id
            FROM finance_document_links
            WHERE room_id = $1
              AND ((from_doc_type = $2 AND from_doc_id = $3)
                OR (to_doc_type = $2 AND to_doc_id = $3))
            ORDER BY id
            """,
            room_id, doc_type, doc_id,
        )

        links: List[dict] = []
        seen = set()

        def _add(link_type: str, direction: str, other_type: str, other_id: int) -> None:
            key = (link_type, direction, other_type, int(other_id))
            if key in seen:
                return
            seen.add(key)
            links.append({
                "link_type": link_type,
                "direction": direction,
                "doc_type": other_type,
                "doc_id": int(other_id),
                "doc_no": None,
            })

        for r in rows:
            is_out = r["from_doc_type"] == doc_type and int(r["from_doc_id"]) == doc_id
            if is_out:
                _add(r["link_type"], "out", r["to_doc_type"], r["to_doc_id"])
            else:
                _add(r["link_type"], "in", r["from_doc_type"], r["from_doc_id"])

        # 🧾 REC ยุบรวมใช้ `related_receipt_id` — synthesise เป็น link `event_document`
        if doc_type == DOC_TYPE_RECEIPT and related_receipt_id:
            _add("event_document", "out", DOC_TYPE_RECEIPT, related_receipt_id)

        # 🏷️ เติมเลขเอกสารของปลายทาง — จัดกลุ่มตามชนิดแล้วยิงคำสั่งเดียวต่อชนิด
        ids_by_type: Dict[str, List[int]] = {}
        for link in links:
            ids_by_type.setdefault(link["doc_type"], []).append(link["doc_id"])

        no_map: Dict[Tuple[str, int], Optional[str]] = {}
        for other_type, ids in ids_by_type.items():
            if other_type == DOC_TYPE_MONTHLY_REPORT:
                found = await conn.fetch(
                    "SELECT id, report_no AS doc_no FROM finance_monthly_reports"
                    " WHERE room_id = $1 AND id = ANY($2::bigint[])",
                    room_id, ids,
                )
            else:
                found = await conn.fetch(
                    "SELECT id, receipt_no AS doc_no FROM finance_receipts"
                    " WHERE room_id = $1 AND id = ANY($2::bigint[])",
                    room_id, ids,
                )
            for f in found:
                no_map[(other_type, int(f["id"]))] = f["doc_no"]

        for link in links:
            link["doc_no"] = no_map.get((link["doc_type"], link["doc_id"]))
        return links
