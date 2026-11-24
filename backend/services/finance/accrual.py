"""เกณฑ์คงค้าง (accrual): ออกบิล → ลงผู้ค้างชำระ, รับเงิน → ตัดผู้ค้างชำระ

═══════════════════════════════════════════════════════════════════════════════
🎯 Matrix ที่ไฟล์นี้รับผิดชอบ (ส่วน "เกิดหนี้/กลับหนี้/ปรับยอด")
═══════════════════════════════════════════════════════════════════════════════
  ออกบิลโปรเจกต์     Dr 11001 ผู้ค้างชำระค่าโครงการ / Cr รายได้เริ่มต้นของห้อง
  ออกบิลค่าปรับ      Dr 11002 ผู้ค้างชำระค่าปรับ   / Cr 49001 รายได้ค่าปรับ
  ยอดยกมา (opening)  Dr 11001/11002               / Cr 31002 ยอดยกมาบัญชีเปิด
  ลบบิล/ยกเลิกบิล     กลับตาม "แหล่งที่มาของ AR":
                     - issue   → Dr รายได้ / Cr AR
                     - opening → Dr 31002 (equity) / Cr AR   [ห้ามแตะรายได้งวดนี้]
                     - none    → ยังไม่มี AR ⇒ ไม่ลง journal
  แก้ยอดบิล          ส่วนต่าง (increase/decrease) ตามแหล่งที่มาเดียวกัน

⚠️ การรับเงิน (`student_payment`) / ใช้เครดิต (`student_credit_apply`) ถูกแก้ใน
   Phase 2 (collections.py / credits.py) ให้ **Cr AR** แทน Cr รายได้ — ไม่ทำในไฟล์นี้

═══════════════════════════════════════════════════════════════════════════════
🔒 ข้อตกลงการล็อก
═══════════════════════════════════════════════════════════════════════════════
เมธอดทั้งหมดในไฟล์นี้ **ไม่ยึด advisory lock เอง** — ผู้เรียกต้องถือ `_lock_room_money`
อยู่ใน transaction เดียวกันแล้ว (เหมือน `_insert_journal_entry`) เพราะ:
  • เรียกซ้ำใน transaction เดียวกันไม่บล็อก แต่ถ้า helper ไป "เปิด transaction เอง"
    จะหลุด atomicity ของงานหลัก
  • การยึดล็อกซ้ำจาก layer ล่างทำให้อ่านโค้ดไม่รู้อีกว่าล็อกเริ่มที่ไหน (Protocol
    ต้องมีจุดเดียว: ขาเข้าของ service)

═══════════════════════════════════════════════════════════════════════════════
📌 "บิลเปิด" (open bill) มีคำจำกัดความเดียว
═══════════════════════════════════════════════════════════════════════════════
`SP.deleted_at IS NULL AND SP.status = 'pending' AND FC.deleted_at IS NULL`
**ไม่กรอง `FC.status`** — ปิดโปรเจกต์ = หยุดเพิ่มคน ไม่ใช่ลบหนี้เดิม
ถ้าต้องการล้างหนี้ ต้องยกเว้นหรือลบรายชื่อ (ซึ่งจะกลับ journal ให้เอง)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import asyncpg

from .constants import (
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    REFERENCE_TYPE_BILL_ISSUE,
    REFERENCE_TYPE_BILL_REVERSAL,
    REFERENCE_TYPE_COLLECTION_ADJUSTMENT,
    REFERENCE_TYPE_OPENING_RECEIVABLE,
)

# คำจำกัดความเดียวของบิลเปิด — ใช้ต่อ string นี้ในทุก query (ดู docstring หัวไฟล์)
OPEN_BILL_PREDICATE = (
    "SP.deleted_at IS NULL AND SP.status = 'pending' AND FC.deleted_at IS NULL"
)

# แหล่งที่มาของ AR ที่ลงไปแล้ว — ใช้ตัดสินว่าจะกลับ/ปรับกับบัญชีไหน
AR_SOURCE_ISSUE = "issue"      # มี journal student_payment_issue
AR_SOURCE_OPENING = "opening"  # มี journal opening_receivable
AR_SOURCE_NONE = "none"        # ยังไม่มี AR (บิลยุคก่อน deploy ที่ยังไม่รัน opening)


def _normalize_kind(value: Optional[str]) -> str:
    """ค่าที่ไม่รู้จักถือเป็นโปรเจกต์ (ค่าเริ่มต้นของคอลัมน์) — ไม่ปล่อยผ่านเป็นค่าอื่น"""
    return COLLECTION_KIND_FINE if value == COLLECTION_KIND_FINE else COLLECTION_KIND_PROJECT


class AccrualMixin:
    # ═════════════════════════════════════════════════════════════════
    # อ่าน (ไม่เขียน)
    # ═════════════════════════════════════════════════════════════════
    @staticmethod
    def _open_bill_predicate() -> str:
        """คืน SQL fragment ของ predicate กลาง (ใช้ต่อใน WHERE …)"""
        return OPEN_BILL_PREDICATE

    @staticmethod
    def _normalize_collection_kind(value: Optional[str]) -> str:
        """ค่าที่ไม่รู้จัก (หรือ NULL) ถือเป็นโปรเจกต์ — ใช้ให้ทั้งระบบตัดสินบัญชีตรงกัน"""
        return _normalize_kind(value)

    @classmethod
    async def _collection_kind_for_payment(
        cls, conn: asyncpg.Connection, payment_id: int
    ) -> str:
        kind = await conn.fetchval(
            """SELECT FC.collection_kind
               FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE SP.id = $1""",
            payment_id,
        )
        return _normalize_kind(kind)

    @classmethod
    async def _bill_ar_source(cls, conn: asyncpg.Connection, payment_id: int) -> str:
        """AR ของบิลนี้มาจากไหน: `issue` | `opening` | `none`

        🔴 ใช้ตัดสินทิศการกลับรายการ/ปรับยอด — ห้าม hardcode ว่าเป็นรายได้เสมอ:
           บิลที่ AR มาจาก opening ต้องกลับกับ equity 31002 ไม่ใช่รายได้งวดนี้
           (ไม่งั้นงบกำไรขาดทุนงวดปัจจุบันจะติดลบปลอมเมื่อลบบิลเก่า)
        """
        ref_type = await conn.fetchval(
            """SELECT reference_type
               FROM journal_entries
               WHERE reference_id = $1
                 AND reference_type IN ($2, $3)
                 AND deleted_at IS NULL
                 AND status <> 'voided'
               ORDER BY CASE reference_type WHEN $2 THEN 0 ELSE 1 END
               LIMIT 1""",
            str(payment_id), REFERENCE_TYPE_BILL_ISSUE, REFERENCE_TYPE_OPENING_RECEIVABLE,
        )
        if ref_type == REFERENCE_TYPE_BILL_ISSUE:
            return AR_SOURCE_ISSUE
        if ref_type == REFERENCE_TYPE_OPENING_RECEIVABLE:
            return AR_SOURCE_OPENING
        return AR_SOURCE_NONE

    # ═════════════════════════════════════════════════════════════════
    # Ledger resolvers (เรียกผ่าน LedgerMixin เพื่อให้ guard อยู่ที่เดียว)
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def _resolve_ar_ledger(
        cls, conn: asyncpg.Connection, *, room_id: int, collection_kind: Optional[str]
    ) -> int:
        if _normalize_kind(collection_kind) == COLLECTION_KIND_FINE:
            return await cls._resolve_ar_fine_ledger(conn, room_id)
        return await cls._resolve_ar_project_ledger(conn, room_id)

    @classmethod
    async def _resolve_revenue_ledger_for_kind(
        cls, conn: asyncpg.Connection, *, room_id: int, collection_kind: Optional[str]
    ) -> int:
        """ขารายได้ตอนออกบิล — โปรเจกต์ใช้รายได้เริ่มต้นเดิม, ค่าปรับใช้ 49001"""
        if _normalize_kind(collection_kind) == COLLECTION_KIND_FINE:
            return await cls._resolve_fine_revenue_ledger(conn, room_id)
        return await cls._resolve_default_income_ledger(conn, room_id)

    @classmethod
    async def _resolve_contra_ledger(
        cls,
        conn: asyncpg.Connection,
        *,
        room_id: int,
        collection_kind: Optional[str],
        source: str,
    ) -> Optional[int]:
        """บัญชีฝั่งตรงข้าม AR ตามแหล่งที่มา — คืน None เมื่อไม่มี AR ให้กลับ"""
        if source == AR_SOURCE_ISSUE:
            return await cls._resolve_revenue_ledger_for_kind(
                conn, room_id=room_id, collection_kind=collection_kind
            )
        if source == AR_SOURCE_OPENING:
            return await cls._resolve_opening_ar_equity_ledger(conn, room_id)
        return None

    # ═════════════════════════════════════════════════════════════════
    # เขียน journal
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def _post_bill_accrual(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        payment_id: int,
        *,
        amount: float,
        collection_kind: Optional[str] = COLLECTION_KIND_PROJECT,
        description: Optional[str] = None,
        recorded_by: Optional[str] = None,
        metadata: Optional[dict] = None,
        transaction_date: Optional[datetime] = None,
    ) -> Optional[str]:
        """ลง accrual ตอนออกบิล: Dr AR / Cr รายได้

        Idempotent ในระดับบิล — ถ้ามี journal `student_payment_issue` หรือ
        `opening_receivable` ของบิลนี้อยู่แล้ว จะ **ไม่ลงซ้ำ** และคืน None
        (unique index `uq_journal_bill_issue` เป็นด่านสุดท้ายที่ DB)
        """
        amount = round(float(amount), 2)
        if amount <= 0:
            return None

        existing = await cls._bill_ar_source(conn, payment_id)
        if existing != AR_SOURCE_NONE:
            return None

        kind = _normalize_kind(collection_kind)
        ar_ledger_id = await cls._resolve_ar_ledger(
            conn, room_id=room_id, collection_kind=kind
        )
        revenue_ledger_id = await cls._resolve_revenue_ledger_for_kind(
            conn, room_id=room_id, collection_kind=kind
        )

        if description is None:
            title = await conn.fetchval(
                """SELECT FC.title FROM student_payments SP
                   JOIN fee_collections FC ON FC.id = SP.collection_id
                   WHERE SP.id = $1""",
                payment_id,
            )
            description = f"ออกบิล: {title or f'student_payment #{payment_id}'}"

        entry_metadata = {
            "student_payment_id": payment_id,
            "collection_kind": kind,
            "accrual": "bill_issue",
        }
        if metadata:
            entry_metadata.update(metadata)

        return await cls._insert_journal_entry(
            conn, room_id,
            reference_type=REFERENCE_TYPE_BILL_ISSUE,
            reference_id=str(payment_id),
            description=description,
            recorded_by=recorded_by,
            metadata=entry_metadata,
            transaction_date=transaction_date,
            lines=[
                {"ledger_id": ar_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"ผู้ค้างชำระจากบิล #{payment_id}"},
                {"ledger_id": revenue_ledger_id, "debit": 0, "credit": amount,
                 "line_description": "รับรู้รายได้ตอนออกบิล (เกณฑ์คงค้าง)"},
            ],
        )

    @classmethod
    async def _post_bill_reversal(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        payment_id: int,
        *,
        amount: float,
        collection_kind: Optional[str] = COLLECTION_KIND_PROJECT,
        source: Optional[str] = None,
        description: Optional[str] = None,
        recorded_by: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """กลับ accrual ของบิล (ลบรายชื่อ/ยกเลิกบิล) — Dr contra / Cr AR

        `source` ไม่ระบุ = อ่านจาก journal (`issue`/`opening`); ถ้า `none` ⇒ ไม่มี AR
        ให้กลับ จึงไม่ลง journal (คืน None) — opening script จะใช้ยอดล่าสุดเอง
        """
        amount = round(float(amount), 2)
        if amount <= 0:
            return None

        resolved_source = source or await cls._bill_ar_source(conn, payment_id)
        kind = _normalize_kind(collection_kind)
        contra_ledger_id = await cls._resolve_contra_ledger(
            conn, room_id=room_id, collection_kind=kind, source=resolved_source
        )
        if contra_ledger_id is None:
            return None

        ar_ledger_id = await cls._resolve_ar_ledger(
            conn, room_id=room_id, collection_kind=kind
        )

        entry_metadata = {
            "student_payment_id": payment_id,
            "collection_kind": kind,
            "ar_source": resolved_source,
            "accrual": "bill_reversal",
        }
        if metadata:
            entry_metadata.update(metadata)

        return await cls._insert_journal_entry(
            conn, room_id,
            reference_type=REFERENCE_TYPE_BILL_REVERSAL,
            reference_id=str(payment_id),
            description=description or f"กลับรายการออกบิล #{payment_id}",
            recorded_by=recorded_by,
            metadata=entry_metadata,
            lines=[
                {"ledger_id": contra_ledger_id, "debit": amount, "credit": 0,
                 "line_description": "กลับรายได้/ยอดยกมาที่รับรู้ไว้ตอนออกบิล"},
                {"ledger_id": ar_ledger_id, "debit": 0, "credit": amount,
                 "line_description": f"ตัดผู้ค้างชำระบิล #{payment_id}"},
            ],
        )

    @classmethod
    async def _post_bill_adjustment(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        payment_id: int,
        *,
        delta: float,
        collection_kind: Optional[str] = COLLECTION_KIND_PROJECT,
        source: Optional[str] = None,
        description: Optional[str] = None,
        recorded_by: Optional[str] = None,
        metadata: Optional[dict] = None,
        reference_type: str = REFERENCE_TYPE_COLLECTION_ADJUSTMENT,
    ) -> Optional[str]:
        """ปรับยอดบิล (เพิ่ม/ลด) — `delta` บวก = เพิ่มหนี้, ลบ = ลดหนี้

        ขาตรงข้ามเป็นรายได้หรือ equity ตามแหล่งที่มาของ AR (source-aware)
        `reference_type` เปลี่ยนได้ เช่นค่าปรับใช้ `REFERENCE_TYPE_FINE_ADJUSTMENT`
        (unique index ต่อบิลมีเฉพาะ `student_payment_issue`/`opening_receivable`
        ⇒ ปรับหลายครั้งต่อบิลได้)
        """
        delta = round(float(delta), 2)
        if abs(delta) < 0.005:
            return None

        resolved_source = source or await cls._bill_ar_source(conn, payment_id)
        kind = _normalize_kind(collection_kind)
        contra_ledger_id = await cls._resolve_contra_ledger(
            conn, room_id=room_id, collection_kind=kind, source=resolved_source
        )
        if contra_ledger_id is None:
            # ยังไม่มี AR ของบิลนี้ ⇒ ไม่มีอะไรให้ปรับ (opening จะใช้ยอดล่าสุดเอง)
            return None

        ar_ledger_id = await cls._resolve_ar_ledger(
            conn, room_id=room_id, collection_kind=kind
        )
        amount = round(abs(delta), 2)

        if delta > 0:
            lines = [
                {"ledger_id": ar_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"เพิ่มผู้ค้างชำระบิล #{payment_id}"},
                {"ledger_id": contra_ledger_id, "debit": 0, "credit": amount,
                 "line_description": "ปรับเพิ่มรายได้/ยอดยกมา"},
            ]
        else:
            lines = [
                {"ledger_id": contra_ledger_id, "debit": amount, "credit": 0,
                 "line_description": "ปรับลดรายได้/ยอดยกมา"},
                {"ledger_id": ar_ledger_id, "debit": 0, "credit": amount,
                 "line_description": f"ลดผู้ค้างชำระบิล #{payment_id}"},
            ]

        entry_metadata = {
            "student_payment_id": payment_id,
            "collection_kind": kind,
            "ar_source": resolved_source,
            "delta": delta,
            "accrual": "bill_adjustment",
        }
        if metadata:
            entry_metadata.update(metadata)

        return await cls._insert_journal_entry(
            conn, room_id,
            reference_type=reference_type,
            reference_id=str(payment_id),
            description=description or f"ปรับยอดบิล #{payment_id} ({delta:+.2f} บาท)",
            recorded_by=recorded_by,
            metadata=entry_metadata,
            lines=lines,
        )

    # ═════════════════════════════════════════════════════════════════
    # สร้างบิล + ลง accrual (ผู้เรียกถือ lock แล้ว)
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def _create_bills_with_accrual(
        cls,
        conn: asyncpg.Connection,
        *,
        room_id: int,
        collection_id: int,
        student_ids: List[int],
        amount: float,
        collection_kind: Optional[str] = COLLECTION_KIND_PROJECT,
        recorded_by: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> List[int]:
        """สร้าง `student_payments` ทีละใบ (**RETURNING id**) + ลง accrual ต่อใบทันที

        - ใช้ `INSERT` ทีละใบแทน `executemany` เพราะต้องได้ id ไปออก journal
          (ขนาดห้อง 40–50 คน ต้นทุน round-trip ยอมรับได้)
        - id ซ้ำถูกตัดทิ้งก่อน (unique `(collection_id, student_id)` ของ DB ยังเป็นด่านจริง)
        - ต้องอยู่ใน transaction ของผู้เรียก (all-or-nothing ทั้งชุด)
        """
        amount = round(float(amount), 2)
        if amount <= 0:
            raise ValueError("จำนวนเงินของบิลต้องมากกว่า 0 บาท")

        kind = _normalize_kind(collection_kind)
        title = await conn.fetchval(
            "SELECT title FROM fee_collections WHERE id = $1 AND room_id = $2",
            collection_id, room_id,
        )
        if title is None:
            raise ValueError("ไม่พบรายการเรียกเก็บเงินนี้ในห้อง")

        payment_ids: List[int] = []
        for student_id in dict.fromkeys(int(s) for s in student_ids):
            payment_id = await conn.fetchval(
                """INSERT INTO student_payments (collection_id, student_id, status)
                   VALUES ($1, $2, 'pending')
                   RETURNING id""",
                collection_id, student_id,
            )
            await cls._post_bill_accrual(
                conn, room_id, payment_id,
                amount=amount,
                collection_kind=kind,
                description=f"ออกบิล: {title}",
                recorded_by=recorded_by,
                metadata=metadata,
            )
            payment_ids.append(payment_id)

        return payment_ids
