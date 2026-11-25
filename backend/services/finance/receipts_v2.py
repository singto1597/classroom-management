"""🧾 [FIN-V2 / P2.1] เอกสารของ "รายการรับเงิน" (payment event) — REC/DEP ผูก event

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้ แยกจาก `receipts.py`
═══════════════════════════════════════════════════════════════════════════════
`_issue_one` ถูกสร้างรอบ **บิล** (`student_payment_id` ไม่ NULL) และ
`_issue_deposit` ผูก idempotency ที่ `legacy_transaction_id` เดี่ยว ๆ
⇒ ทั้งคู่ไม่รู้จัก `payment_event_id` / `layout_version` / `document_meta`
   และ P2.1 **ห้ามแก้ `receipts.py`** (P2.2 เป็นเจ้าของ filter layout_version)

ไฟล์นี้จึงมี **ตัวเขียนเอกสารของ event โดยเฉพาะ** — โครงเดียวกับ `_issue_one`
(จองเลขแบบ upsert, savepoint กันแข่ง, อ่านใบที่ชนะคืน) แต่:

    🔑 idempotency = `payment_event_id` + `doc_type`
       ⇒ ตรงกับ `idx_finance_receipts_event_active` (P1.1/0013)
    🗓️ ปี พ.ศ. = ปีของ `event_at` ที่ผู้เรียกส่งมา (เวลาของ "การรับเงิน")
       ไม่ใช่เวลาที่กดพิมพ์/ออกเอกสาร
    📄 เก็บ snapshot ที่ P2.2 จะเรนเดอร์: `line_items` + `document_meta`
       (P2.2 ห้าม JOIN บิลสด — snapshot ต้องพอให้พิมพ์ได้เอง)

⚠️ caller เป็นเจ้าของ transaction และถือ `_lock_room_money` มาแล้ว
   (ในเส้นทาง P2.1 คือ `create_payment_event`) ⇒ ไฟล์นี้ไม่ล็อกซ้ำ
"""
import json
from datetime import datetime
from typing import List, Optional

import asyncpg

from .constants import (
    DOC_STATUS_ACTIVE, DOC_TYPE_DEPOSIT, DOC_TYPE_PREFIXES, DOC_TYPE_RECEIPT,
    RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_MAX, RECEIPT_SEQ_OVERFLOW_MSG,
)

# คอลัมน์ที่ต้องอ่านกลับ/คืนให้ caller — ครบพอให้ response ของ P2.1 ประกอบได้
#   (ไม่รวม v2 column ที่ไม่ใช้ตอบ เช่น related_receipt_id)
_EVENT_DOC_COLUMNS = """
    R.id, R.room_id, R.receipt_no, R.doc_type, R.year_be, R.seq,
    R.student_payment_id, R.legacy_transaction_id, R.student_id, R.collection_id,
    R.amount, R.paid_total_after, R.issued_to_name, R.issued_by_name, R.note,
    R.event_at, R.issued_at, R.status, R.layout_version, R.payment_event_id
"""
# ⚠️ `RETURNING` ไม่มี alias `R` — คอลัมน์เป็นของแถวที่เพิ่ง insert ตรง ๆ
#    (ถ้าใช้ชุดที่มี `R.` จะได้ `UndefinedTableError: missing FROM-clause entry`)
_EVENT_DOC_RETURNING = _EVENT_DOC_COLUMNS.replace("R.", "")


class ReceiptsV2Mixin:
    # ================================================================ helpers
    @classmethod
    async def _find_event_document(
        cls, conn: asyncpg.Connection, event_id: int, doc_type: str,
    ):
        """เอกสารที่ยัง active ของ event นี้ (idempotency ชั้นที่ 1)"""
        return await conn.fetchrow(
            f"""SELECT {_EVENT_DOC_COLUMNS} FROM finance_receipts R
                WHERE R.payment_event_id = $1 AND R.doc_type = $2
                  AND R.deleted_at IS NULL AND R.status = '{DOC_STATUS_ACTIVE}'
                ORDER BY R.id LIMIT 1""",
            event_id, doc_type,
        )

    @classmethod
    async def _reserve_document_no(
        cls, conn: asyncpg.Connection, *, target_room_id: int, year_be: int,
        doc_type: str,
    ) -> tuple[str, int]:
        """จองเลขเอกสารแบบ atomic — **ห้าม MAX(seq)+1**

        `ON CONFLICT ... DO UPDATE ... RETURNING` ล็อกแถว sequence ให้เอง
        ⇒ สองคำขอพร้อมกันได้เลขต่างกันเสมอ (ตรงกับ `_issue_one`/`_issue_deposit`)
        """
        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, doc_type,
        )
        # 🚧 เกิน 4 หลักแล้ว GET /finance/receipts/{receipt_no} จะเปิดใบไม่ได้อีก
        #    raise ใน transaction ⇒ เลขที่จองไปถูก rollback (ไม่มีเลขถูกเผา)
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[doc_type], year_be=year_be, seq=seq,
        )
        return receipt_no, int(seq)

    @classmethod
    def _shape_event_document(cls, row) -> dict:
        """แถวดิบ → dict ที่ response ใช้ (เงินเป็นสตริง 2 ตำแหน่ง)"""
        return {
            "id": row["id"],
            "doc_type": row["doc_type"],
            "receipt_no": row["receipt_no"],
            "amount": f"{float(row['amount']):.2f}",
            "layout_version": int(row["layout_version"]),
            "event_at": row["event_at"],
            "issued_at": row["issued_at"],
            "status": row["status"],
        }

    # ================================================================ REC
    @classmethod
    async def _issue_event_receipt(
        cls,
        conn: asyncpg.Connection,
        *,
        target_room_id: int,
        event_id: int,
        student_id: int,
        issued_to_name: str,
        user_id: int,
        user_name: str,
        note: Optional[str],
        amount: float,
        total_applied: float,
        event_at: datetime,
        issued_at: datetime,
        line_items: List[dict],
        document_meta: dict,
        idempotency_key: str,
        receiver_person_id: Optional[int],
    ) -> dict:
        """ออก **ใบเสร็จ 1 ใบของ event** (`layout_version=2`, หลาย `line_items`)

        คืน `{"receipt": dict, "reused": bool}` — `receipt` เป็น dict สั้นที่ response ใช้
        (ไม่ใช่ `_shape_receipt` ของใบ legacy เพราะคอลัมน์ v2 ไม่อยู่ใน `_RECEIPT_COLUMNS`)

        🔒 caller ถือ transaction + `_lock_room_money` แล้ว (ห้ามล็อกซ้ำ)
        """
        # 💰 ยอดต้อง > 0 หลังปัดเป็นสตางค์ — `chk_receipt_amount_positive` ใน DB
        #    ถ้าปล่อยผ่านไปจะได้ CheckViolationError (500) แทน 400 ที่อ่านรู้เรื่อง
        document_amount = round(float(amount), 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดรับเงินน้อยกว่า 0.01 บาท จึงออกใบเสร็จไม่ได้"
            )

        # 🔁 อ่านก่อนเขียน — กดซ้ำแบบไม่ชนกันเจอตรงนี้ ไม่กินเลข
        existing = await cls._find_event_document(conn, event_id, DOC_TYPE_RECEIPT)
        if existing:
            return {"receipt": cls._shape_event_document(existing), "reused": True}

        # 🗓️ ปี พ.ศ. ของ **เหตุการณ์รับเงิน** — ตัวเดียวกับที่พิมพ์บนกระดาษ
        year_be = cls._thai_year_be(event_at)
        receipt_no, seq = await cls._reserve_document_no(
            conn, target_room_id=target_room_id, year_be=year_be,
            doc_type=DOC_TYPE_RECEIPT,
        )

        try:
            # 💾 savepoint จำเป็น: หลัง UniqueViolation transaction หลักถูก mark aborted
            #    ⇒ ต้องดัก **นอก** savepoint แล้วอ่านใบที่ชนะใน transaction ที่ยังดี
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount,
                            paid_total_after, issued_to_name, issued_by, issued_by_name,
                            note, event_at, issued_at, line_items,
                            layout_version, payment_event_id, document_meta,
                            idempotency_key, receiver_person_id)
                       VALUES ($1,$2,$3,$4,$5,NULL,NULL,$6,NULL,$7,$8,$9,$10,$11,$12,$13,$14,
                               $15::jsonb, 2, $16, $17::jsonb, $18, $19)
                       RETURNING {_EVENT_DOC_RETURNING}""",
                    target_room_id, receipt_no, DOC_TYPE_RECEIPT, year_be, seq,
                    student_id,
                    document_amount, round(float(total_applied), 2),
                    issued_to_name, user_id, user_name, note,
                    event_at, issued_at,
                    json.dumps(line_items or [], ensure_ascii=False),
                    event_id,
                    json.dumps(document_meta or {}, ensure_ascii=False),
                    idempotency_key, receiver_person_id,
                )
        except asyncpg.UniqueViolationError:
            # 🔁 idempotency ชั้นที่ 2 — แพ้การแข่งขันของ event เดียวกัน ⇒ คืนใบที่ชนะ
            raced = await cls._find_event_document(conn, event_id, DOC_TYPE_RECEIPT)
            if raced:
                return {"receipt": cls._shape_event_document(raced), "reused": True}
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_event_document(row), "reused": False}

    # ================================================================ DEP
    @classmethod
    async def _issue_event_deposit(
        cls,
        conn: asyncpg.Connection,
        *,
        target_room_id: int,
        event_id: int,
        student_id: int,
        transaction_id: int,
        issued_to_name: str,
        user_id: int,
        user_name: str,
        note: Optional[str],
        amount: float,
        event_at: datetime,
        issued_at: datetime,
        document_meta: dict,
        idempotency_key: str,
        receiver_person_id: Optional[int],
    ) -> dict:
        """ออก **ใบรับเงินล่วงหน้า 1 ใบของ event** (DEP) — `layout_version=2`

        🔑 idempotency = `payment_event_id` + `doc_type`
           ⇒ ใช้ `idx_finance_receipts_event_active` (ไม่ใช่
              `idx_finance_receipts_deposit_active` ของ `legacy_transaction_id`
              เพราะใบ event ไม่ได้ผูกกับธุรกรรมเพียงแถวเดียว — ธุรกรรม top-up
              เป็นของ event นี้ และ replay ต้องคืนใบเดิมของ event)

        `legacy_transaction_id` = ธุรกรรมเงินรับล่วงหน้าที่ `_create_excess_credit_locked`
        เพิ่งสร้าง ⇒ ค้นย้อนจากหน้าธุรกรรมยังเจอเอกสาร (เหมือน DEP เดิม)

        `line_items` = NULL โดยเจตนา: ใบนี้ไม่มีรายการย่อยรายบิล
        `paid_total_after` = ยอดพัก (ไม่ใช่ยอดสะสมของบิลแบบใบเสร็จ)
        """
        document_amount = round(float(amount), 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดเงินรับล่วงหน้าน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้"
            )

        existing = await cls._find_event_document(conn, event_id, DOC_TYPE_DEPOSIT)
        if existing:
            return {"receipt": cls._shape_event_document(existing), "reused": True}

        year_be = cls._thai_year_be(event_at)
        receipt_no, seq = await cls._reserve_document_no(
            conn, target_room_id=target_room_id, year_be=year_be,
            doc_type=DOC_TYPE_DEPOSIT,
        )

        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount,
                            paid_total_after, issued_to_name, issued_by, issued_by_name,
                            note, event_at, issued_at, line_items,
                            layout_version, payment_event_id, document_meta,
                            idempotency_key, receiver_person_id)
                       VALUES ($1,$2,$3,$4,$5,NULL,$6,$7,NULL,$8,$9,$10,$11,$12,$13,$14,$15,
                               NULL, 2, $16, $17::jsonb, $18, $19)
                       RETURNING {_EVENT_DOC_RETURNING}""",
                    target_room_id, receipt_no, DOC_TYPE_DEPOSIT, year_be, seq,
                    transaction_id, student_id,
                    document_amount, document_amount,
                    issued_to_name, user_id, user_name, note,
                    event_at, issued_at,
                    event_id,
                    json.dumps(document_meta or {}, ensure_ascii=False),
                    idempotency_key, receiver_person_id,
                )
        except asyncpg.UniqueViolationError:
            raced = await cls._find_event_document(conn, event_id, DOC_TYPE_DEPOSIT)
            if raced:
                return {"receipt": cls._shape_event_document(raced), "reused": True}
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_event_document(row), "reused": False}
