"""🧾 [FIN-V2 / P5.4] ใบรับทราบยอดค้าง (ACK) — อ่าน/ยกเลิก + สัญญา replay

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้แยกจาก `invoice_documents.py`
═══════════════════════════════════════════════════════════════════════════════
P2.6 ออก ACK ได้แล้ว (`issue_acknowledgements` อยู่ใน `invoice_documents.py`)
P5.4 เติม **วงจรชีวิตที่เหลือ** ของเอกสารชนิดเดียวกัน:

- `get_acknowledgements` — รายการเฉพาะ `doc_type='acknowledgement'` ของห้อง
- `get_acknowledgement` — ใบเดียว + รายชื่อผู้ค้าง (อ่านจาก `finance_ack_entries`
  ที่เป็นหลักฐาน ณ วันออก ไม่ใช่ JOIN บิลสด)
- `void_acknowledgement` — ยกเลิกเอกสาร (ไม่แตะเงินและ **ไม่แตะ entries**)

🔴 ACK ไม่แตะเงินเลย — ไม่มี journal/กระเป๋า/เครดิต/บิล ⇒ void จึงไม่ต้อง reverse อะไร
   (`P6.1 void engine` ไม่ครอบเอกสารชนิดนี้) และ `finance_ack_entries` คือประวัติ
   "เคยแจ้งใครไว้ ยอดเท่าไร" ⇒ void บอกว่าเอกสารถูกยกเลิก ไม่ได้บอกว่าไม่เคยแจ้ง

🔁 `AckConflictError`/`assert_ack_replay_matches` อาศัยอยู่ที่นี่และถูกเรียกจาก
   `invoice_documents.issue_acknowledgements` ตอน replay ด้วย `idempotency_key` เดิม
   (คีย์เดิมแต่ payload ต่าง = 409 ไม่ใช่คืนใบเดิมเงียบ ๆ)
"""
import json
import time
from datetime import date
from typing import List, Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
from .constants import DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED, DOC_TYPE_ACKNOWLEDGEMENT
from .receipts import _DOC_DATE, _RECEIPT_COLUMNS


class AckConflictError(Exception):
    """ACK ขัดแย้งกับสถานะที่มีอยู่ (router แปลงเป็น 409)

    ⚠️ นิยามในโมดูล service **ไม่ใช่** `core/exceptions.py` — ไฟล์นั้นอยู่นอก owned
       ของ P5.4 และ exception นี้ไม่มีผู้ใช้นอกโมดูลการเงิน
    """


def _meta_dict(row) -> dict:
    """`document_meta` จาก asyncpg jsonb (str) → dict (ทนข้อมูลผิดรูป)"""
    meta = row["document_meta"] if "document_meta" in row else None
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            return {}
    return meta if isinstance(meta, dict) else {}


def _requested_student_ids(req) -> Optional[List[int]]:
    """รายชื่อที่คำขอระบุ (เรียง+ตัดซ้ำ) — `None` = ทั้งห้อง"""
    if getattr(req, "scope", None) != "selected":
        return None
    return sorted({int(sid) for sid in (getattr(req, "student_ids", None) or [])})


def assert_ack_replay_matches(existing, req) -> None:
    """คำขอ replay ต้องตรงกับใบเดิม — ไม่ตรง = `AckConflictError` (409)

    🎯 กันความเข้าใจผิดที่แพงที่สุดของ idempotency: client กดซ้ำด้วยคีย์เดิมแต่
       **เปลี่ยนชุดนักเรียน** ⇒ ถ้าคืนใบเดิมเงียบ ๆ ผู้ใช้จะคิดว่าได้ใบใหม่ที่ครอบคนใหม่
       ทั้งที่กระดาษที่พิมพ์ออกมามีชื่อชุดเก่า

    🔎 เทียบเฉพาะสิ่งที่คำขอเป็นคนตัดสิน (scope / รายชื่อ / include_invoice) —
       **ไม่เทียบยอดเงิน** เพราะยอดเป็นผลจากการอ่านบิลสด: ระหว่างสองคำขอมีบิลใหม่อาจ
       เกิดขึ้นได้ และการบล็อกด้วยเหตุนั้นจะทำให้ retry ที่ถูกต้องล้มทั้งที่เอกสารเดิมถูกต้อง
       (ยอดของใบเดิมคือ snapshot ที่ผู้ปกครองเห็นและเซ็นไปแล้ว — ไม่เปลี่ยนตามบิลสด)
    """
    meta = _meta_dict(existing)
    stored_scope = meta.get("scope")
    if stored_scope is not None and stored_scope != getattr(req, "scope", None):
        raise AckConflictError(
            "idempotency_key นี้ถูกใช้กับใบรับทราบขอบเขตอื่นแล้ว — "
            "ใช้คีย์ใหม่ถ้าต้องการออกใบใหม่"
        )

    if stored_scope == "selected":
        stored_ids = sorted({
            int(e["student_id"])
            for e in (meta.get("entries") or [])
            if isinstance(e, dict) and e.get("student_id") is not None
        })
        if stored_ids and stored_ids != (_requested_student_ids(req) or []):
            raise AckConflictError(
                "idempotency_key นี้ถูกใช้กับรายชื่อนักเรียนชุดอื่นแล้ว — "
                "ใช้คีย์ใหม่ถ้าต้องการออกใบใหม่"
            )

    # 🔁 ฟิลด์นี้มีตั้งแต่ P5.4 (ใบเก่าไม่มีคีย์ ⇒ ข้ามการเทียบ ไม่ทำให้ replay เก่าพัง)
    if "include_invoice" in meta and bool(meta.get("include_invoice")) != bool(
        getattr(req, "include_invoice", False)
    ):
        raise AckConflictError(
            "idempotency_key นี้ถูกใช้กับการออก/ไม่ออกใบแจ้งหนี้คนละแบบแล้ว — "
            "ใช้คีย์ใหม่ถ้าต้องการออกใบใหม่"
        )


def _entry_count(meta: dict) -> int:
    value = meta.get("entry_count")
    if isinstance(value, int):
        return value
    return len([e for e in (meta.get("entries") or []) if isinstance(e, dict)])


class AcknowledgmentMixin:
    """ACK — รายการ/รายละเอียด/ยกเลิก (ออกใบเป็นของ P2.6 · `invoice_documents.py`)"""

    # ─────────────────────────────────────────────────────────────── รายการ
    @classmethod
    async def get_acknowledgements(
        cls,
        pool: asyncpg.Pool,
        *,
        client_source: str,
        actor_identifier: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_voided: bool = False,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ACK ของห้อง — กรองช่วงด้วย **เวลาไทย** บน "วันที่ของเอกสาร"

        🗓️ ใช้ `_DOC_DATE` = `COALESCE(event_at, issued_at)` ตัวเดียวกับที่พิมพ์บนกระดาษ
           และตัวเดียวกับทะเบียนเอกสาร (`get_receipts`)
        🚫 ค่าปริยายซ่อนใบที่ยกเลิก — `include_voided=True` สำหรับมุมมองตรวจสอบ
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if include_voided:
                    where = "WHERE R.room_id = $1 AND R.doc_type = $2"
                else:
                    where = (
                        "WHERE R.room_id = $1 AND R.doc_type = $2"
                        " AND R.deleted_at IS NULL"
                        f" AND R.status = '{DOC_STATUS_ACTIVE}'"
                    )
                params: List = [target_room_id, DOC_TYPE_ACKNOWLEDGEMENT]
                idx = 3
                if start_date is not None:
                    where += (
                        f" AND {_DOC_DATE} >= ((${idx}::date)::timestamp"
                        " AT TIME ZONE 'Asia/Bangkok')"
                    )
                    params.append(start_date); idx += 1
                if end_date is not None:
                    where += (
                        f" AND {_DOC_DATE} < ((((${idx}::date) + 1)::timestamp)"
                        " AT TIME ZONE 'Asia/Bangkok')"
                    )
                    params.append(end_date); idx += 1

                rows = await conn.fetch(
                    f"""SELECT {_RECEIPT_COLUMNS}
                        FROM finance_receipts R
                        {where}
                        ORDER BY {_DOC_DATE} DESC, R.id DESC
                        LIMIT 500""",
                    *params,
                )

                items = []
                for r in rows:
                    d = cls._shape_receipt(r)
                    meta = d.get("document_meta") or {}
                    items.append({
                        "receipt_no": d["receipt_no"],
                        "doc_type": d["doc_type"],
                        "doc_type_label": d.get("doc_type_label"),
                        "amount": d["amount"],
                        "paid_total_after": d["paid_total_after"],
                        "entry_count": _entry_count(meta),
                        "scope": meta.get("scope"),
                        "note": d.get("note"),
                        "event_at": d.get("event_at"),
                        "issued_at": d.get("issued_at"),
                        "status": d.get("status"),
                        "voided_at": d.get("voided_at"),
                        "void_reason": d.get("void_reason"),
                    })

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT", status="success",
                    endpoint_or_command="FinanceService.get_acknowledgements",
                    execution_time_ms=exec_time,
                )
                return {"status": "success", "items": items, "total": len(items)}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_acknowledgements",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── รายละเอียด
    @classmethod
    async def get_acknowledgement(
        cls,
        pool: asyncpg.Pool,
        *,
        receipt_no: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ACK 1 ใบ (ระบุด้วยเลขที่) + entries

        🚫 **ไม่กรองสถานะ** — ใบที่ยกเลิกแล้วต้องเปิดได้เสมอ (เป็นหลักฐานว่าเคยแจ้ง)
           clip เทมเพลตจะประทับ "ยกเลิก" ให้เองเมื่อพิมพ์
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                row = await conn.fetchrow(
                    f"""SELECT {_RECEIPT_COLUMNS}, R.line_items, R.voucher_snapshot,
                               FC.title AS collection_title,
                               FC.amount AS collection_amount,
                               FC.due_date AS collection_due_date,
                               S.student_no, R2.room_name, R2.room_code
                        FROM finance_receipts R
                        LEFT JOIN fee_collections FC ON R.collection_id = FC.id
                        LEFT JOIN students S ON R.student_id = S.id
                        JOIN rooms R2 ON R.room_id = R2.id
                        WHERE R.room_id = $1 AND R.doc_type = $2 AND R.receipt_no = $3""",
                    target_room_id, DOC_TYPE_ACKNOWLEDGEMENT, receipt_no,
                )
                if row is None:
                    raise RoomNotFoundError("ไม่พบเอกสารเลขที่นี้")

                d = cls._shape_receipt_detail(row)
                entries = await cls._load_ack_entries(conn, row["id"])

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT", entity_id=receipt_no, status="success",
                    endpoint_or_command="FinanceService.get_acknowledgement",
                    execution_time_ms=exec_time,
                )
                return {
                    "status": "success",
                    "message": (
                        f"ใบรับทราบยอดค้าง {receipt_no} — "
                        f"{len(entries)} คน · {d['amount']:,.2f} บาท"
                    ),
                    "receipt": d,
                    "entries": entries,
                    "entry_count": len(entries),
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", entity_id=receipt_no, status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.get_acknowledgement",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ─────────────────────────────────────────────────────────────── ยกเลิก
    @classmethod
    async def void_acknowledgement(
        cls,
        pool: asyncpg.Pool,
        *,
        receipt_no: str,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิก ACK — ต้องมีเหตุผล · ตั้ง `status` + `deleted_at` คู่กันเสมอ

        🔴 `chk_receipt_voided_is_deleted` บังคับให้สองค่านี้ไปด้วยกัน — ลืมตัวใดตัวหนึ่ง
           = CHECK โยน error ดิบกลายเป็น 500
        🔴 **ไม่แตะ `finance_ack_entries`** — ประวัติว่าเคยแจ้งใครไว้คือหลักฐาน
        🔴 ไม่แตะเงิน/journal/credit — ACK ไม่เคยแตะเงินตั้งแต่แรก
        """
        start_time = time.time()
        target_room_id = room_id
        reason = (getattr(req, "reason", None) or "").strip()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    # 🔒 คำสั่งแรกหลัง RBAC — อ่าน/เขียนแถวเอกสารใต้ล็อกห้องเสมอ
                    await _lock_room_money(conn, target_room_id)

                    if not reason:
                        raise ValueError("กรุณาระบุเหตุผลที่ยกเลิกเอกสาร")

                    row = await conn.fetchrow(
                        f"""SELECT {_RECEIPT_COLUMNS}, R.deleted_at
                              FROM finance_receipts R
                             WHERE R.room_id = $1 AND R.doc_type = $2
                               AND R.receipt_no = $3
                             FOR UPDATE""",
                        target_room_id, DOC_TYPE_ACKNOWLEDGEMENT, receipt_no,
                    )
                    if row is None:
                        raise RoomNotFoundError("ไม่พบเอกสารเลขที่นี้")
                    if row["status"] == DOC_STATUS_VOIDED or row["deleted_at"] is not None:
                        raise AckConflictError("เอกสารนี้ถูกยกเลิกแล้ว")

                    await conn.execute(
                        """UPDATE finance_receipts
                              SET status = 'voided',
                                  voided_at = CURRENT_TIMESTAMP,
                                  voided_by = $4,
                                  void_reason = $5,
                                  deleted_at = CURRENT_TIMESTAMP
                            WHERE id = $1 AND room_id = $2 AND doc_type = $3""",
                        row["id"], target_room_id, DOC_TYPE_ACKNOWLEDGEMENT,
                        user_id, reason,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", entity_id=receipt_no, status="success",
                        old_values={"status": row["status"]},
                        new_values={
                            "status": DOC_STATUS_VOIDED,
                            "void_reason": reason,
                            "deleted_at": "CURRENT_TIMESTAMP",
                        },
                        endpoint_or_command="FinanceService.void_acknowledgement",
                        execution_time_ms=exec_time,
                    )

                    return {
                        "status": "success",
                        "message": f"ยกเลิกใบรับทราบยอดค้าง {receipt_no} แล้ว",
                    }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", entity_id=receipt_no,
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.void_acknowledgement",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise
