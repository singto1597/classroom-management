"""🧾 [FIN-V2 / P4.2] ใบรับรองแทนใบเสร็จ (CERT)

═══════════════════════════════════════════════════════════════════════════════
🎯 CERT คือ "เอกสารรับรอง" ไม่ใช่ "รายการเงิน"
═══════════════════════════════════════════════════════════════════════════════
ออกให้ใบสำคัญจ่าย (PV) ที่มีบรรทัด **ไม่มีหลักฐานใบเสร็จ** (`receipt_status='none'`)
โดย CERT 1 ใบต่อ voucher และยอดบน CERT = ผลรวม **เฉพาะบรรทัด none** เท่านั้น

🔴 กฎที่ห้ามพลาด
   1. **ไม่ลง journal / ไม่แตะ `finance_transactions` / ไม่ขยับ `finance_accounts`**
      — เงินจ่ายถูกบันทึกโดย P4.1 (PV) แล้ว; CERT ลงบัญชีซ้ำ = ค่าใช้จ่ายนับสองเท่า
   2. `paid_total_after = 0` — CERT ไม่ได้ "เก็บเงินมา" ถ้าใส่ `cert_amount`
      รายงานที่ SUM คอลัมน์นี้จะเข้าใจผิดว่ามีเงินเข้า
   3. `legacy_transaction_id` = txn ของ **บรรทัด none แรก** (ไม่ใช่บรรทัดแรกของ voucher)
   4. `event_at` = เวลาเดียวกับ PV — ปี พ.ศ. ของเลข CERT ต้องไม่ข้ามปีเพราะออกตอนกด
   5. seq จองจาก `receipt_sequences` ด้วย `doc_type='certificate'` (แยกจาก PV)
   6. SAVEPOINT ครอบ INSERT เอกสาร — ห้ามอ่าน `conn` ต่อหลัง `UniqueViolationError`
      ใน transaction ที่ abort (`25P02`)
   7. snapshot ของ CERT ต้องเป็น **สำเนา** ของ PV ที่เติม `cert_mode=true`
      — ห้ามแก้ object เดียวกับ PV ที่ insert ไปแล้ว

ℹ️ CERT ถูกเรียกจาก `create_expense_voucher` **ภายในล็อกห้องของ P4.1** — ไม่ใช่
   เส้นทางเงินใหม่ จึงไม่ต้องขึ้นทะเบียนใน `_MONEY_PATHS`
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

import asyncpg

from .base import _lock_room_money
from .constants import (
    BUDDHIST_ERA_OFFSET, DOC_TYPE_CERTIFICATE, DOC_TYPE_PREFIXES,
    RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_MAX, RECEIPT_SEQ_OVERFLOW_MSG, THAI_TZ,
)


def _cert_hash(voucher_id: int, none_lines: list) -> str:
    """ลายนิ้วมือของชุดบรรทัดที่ CERT รับรอง — ตรวจภายหลังได้ว่าครอบบรรทัดใด

    ⚠️ ต้องเรียงก่อน hash: client/DB คืนบรรทัดตามลำดับ line_no อยู่แล้ว แต่การเรียง
       เองทำให้ hash ไม่ขึ้นกับลำดับที่ caller ส่งมา (idempotent ต่อ representation)
    """
    payload = [
        [int(l["line_no"]), round(float(l["amount"]), 2), l.get("category_id")]
        for l in sorted(none_lines, key=lambda x: int(x["line_no"]))
    ]
    raw = json.dumps([voucher_id, payload], ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _snapshot_with_cert_mode(snapshot) -> str:
    """คัดลอก snapshot ของ PV แล้วเติม `cert_mode=True` (คืน **สตริง JSON**)"""
    if isinstance(snapshot, str):
        try:
            data = json.loads(snapshot)
        except (TypeError, ValueError):
            data = {}
    else:
        data = dict(snapshot or {})
    data["cert_mode"] = True
    return json.dumps(data, ensure_ascii=False)


async def issue_certificate_locked(
    conn: asyncpg.Connection, *, room_id: int, voucher_id: int,
    pv_receipt_id: int, pv_receipt_no: str, payee_name: str,
    payee_person_id: Optional[int], user_id: int, user_name: str,
    event_at_db: datetime, issued_at_db: datetime,
    none_lines: list, snapshot, signatures: list,
) -> dict:
    """ออก CERT ของ voucher (caller ถือ `_lock_room_money` + transaction อยู่แล้ว)

    คืน `{"receipt": row | None, "reused": bool}` — `receipt=None` เมื่อไม่มี
    บรรทัด `receipt_status='none'` (หรือผลรวมเป็น 0) ซึ่ง **ไม่ใช่ error**
    """
    none_lines = list(none_lines or [])
    if not none_lines:
        return {"receipt": None, "reused": False}

    cert_amount = round(sum(float(l["amount"]) for l in none_lines), 2)
    if cert_amount <= 0:
        return {"receipt": None, "reused": False}

    # 🔒 re-entrant กับล็อกของ P4.1 — เรียกซ้ำใน transaction เดียวไม่บล็อก
    await _lock_room_money(conn, room_id)

    idem = f"cert:{voucher_id}"

    # 🔁 idempotency ชั้นที่ 1 — อ่านก่อนเขียน
    existing = await conn.fetchrow(
        """SELECT * FROM finance_receipts
           WHERE room_id = $1 AND doc_type = $2 AND idempotency_key = $3
             AND deleted_at IS NULL AND status = 'active'""",
        room_id, DOC_TYPE_CERTIFICATE, idem,
    )
    if existing:
        return {"receipt": existing, "reused": True}

    # 🗓️ ปี พ.ศ. จากเวลาที่จ่ายจริง (เดียวกันกับ PV)
    year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

    seq = await conn.fetchval(
        """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
           VALUES ($1, $2, $3, 1)
           ON CONFLICT (room_id, year_be, doc_type)
           DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                         updated_at = CURRENT_TIMESTAMP
           RETURNING last_seq""",
        room_id, year_be, DOC_TYPE_CERTIFICATE,
    )
    if seq > RECEIPT_SEQ_MAX:
        raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
    receipt_no = RECEIPT_NO_TEMPLATE.format(
        prefix=DOC_TYPE_PREFIXES[DOC_TYPE_CERTIFICATE], year_be=year_be, seq=seq,
    )

    line_items = [
        {"title": l["description"], "amount_applied": float(l["amount"])}
        for l in sorted(none_lines, key=lambda x: int(x["line_no"]))
    ]
    source_line_nos = [int(l["line_no"]) for l in sorted(none_lines, key=lambda x: int(x["line_no"]))]
    first_none_txn = next(
        (l.get("finance_transaction_id") for l in none_lines
         if l.get("finance_transaction_id") is not None),
        None,
    )

    signature_payload = [
        {"role": s.get("role"), "signer_name": s.get("signer_name")}
        for s in (signatures or [])
        if s.get("role") in ("prepared", "approved")
    ]
    document_meta = json.dumps({
        "voucher_id": voucher_id,
        "pv_receipt_id": pv_receipt_id,
        "cert_amount": cert_amount,
        "source_line_nos": source_line_nos,
        "voucher_no": pv_receipt_no,
        "cert_hash": _cert_hash(voucher_id, none_lines),
        "signatures": signature_payload,
    }, ensure_ascii=False)

    try:
        # 🔁 SAVEPOINT — รูปเดียวกับ `_issue_one`/`_issue_income_doc`
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO finance_receipts
                       (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                        legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                        issued_to_name, issued_by, issued_by_name, note, event_at, issued_at,
                        line_items, voucher_snapshot, layout_version, idempotency_key,
                        document_meta, receiver_person_id, related_receipt_id)
                   VALUES ($1,$2,$3,$4,$5,NULL,$6,NULL,NULL,$7,0,$8,$9,$10,NULL,$11,$12,
                           $13::jsonb,$14,2,$15,$16::jsonb,$17,$18)
                   RETURNING *""",
                room_id, receipt_no, DOC_TYPE_CERTIFICATE, year_be, seq,
                first_none_txn, cert_amount, payee_name, user_id, user_name,
                event_at_db, issued_at_db,
                json.dumps(line_items, ensure_ascii=False),
                _snapshot_with_cert_mode(snapshot),
                idem, document_meta, payee_person_id, pv_receipt_id,
            )
    except asyncpg.UniqueViolationError:
        raced = await conn.fetchrow(
            """SELECT * FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 AND idempotency_key = $3
                 AND deleted_at IS NULL AND status = 'active'""",
            room_id, DOC_TYPE_CERTIFICATE, idem,
        )
        if raced:
            return {"receipt": raced, "reused": True}
        raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

    cert_id = row["id"]

    # 🔗 ผูก voucher → CERT (race ไม่ควรเกิดเพราะถือล็อกห้องอยู่แล้ว)
    updated = await conn.fetchval(
        """UPDATE finance_expense_vouchers SET cert_receipt_id = $1
           WHERE id = $2 AND cert_receipt_id IS NULL
           RETURNING cert_receipt_id""",
        cert_id, voucher_id,
    )
    if updated is None:
        current = await conn.fetchval(
            "SELECT cert_receipt_id FROM finance_expense_vouchers WHERE id = $1",
            voucher_id,
        )
        if current != cert_id:
            raise ValueError("ใบสำคัญจ่ายนี้ผูกกับใบรับรองอีกใบแล้ว — กรุณาโหลดใหม่")

    # 🔗 ลิงก์ทิศ certificate → payment_voucher (ทิศเดียวตาม decision log)
    await conn.execute(
        """INSERT INTO finance_document_links
               (room_id, from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type)
           VALUES ($1, $2, $3, $4, $5, 'cert_for_voucher')""",
        room_id, DOC_TYPE_CERTIFICATE, cert_id, "payment_voucher", pv_receipt_id,
    )

    # ✍️ 2 ลายเซ็น (prepared / approved) — ไม่มี receiver (ผู้รับเซ็นบน PV)
    prepared_name = user_name
    approved_name = next(
        (s.get("signer_name") for s in (signatures or []) if s.get("role") == "approved"),
        None,
    ) or user_name
    approved_person_id = next(
        (s.get("person_id") for s in (signatures or []) if s.get("role") == "approved"),
        None,
    )
    for sort_order, (role, person_id, signer_name) in enumerate([
        ("prepared", None, prepared_name),
        ("approved", approved_person_id, approved_name),
    ]):
        await conn.execute(
            """INSERT INTO finance_document_signatures
                   (room_id, doc_type, doc_id, role, person_id, signer_name, signed_at, sort_order)
               VALUES ($1, $2, $3, $4, $5, $6, NULL, $7)""",
            room_id, DOC_TYPE_CERTIFICATE, cert_id, role, person_id, signer_name,
            sort_order,
        )

    return {"receipt": row, "reused": False}
