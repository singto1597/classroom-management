"""✂️ [FIN-V2 / P6.2] ตัดจำหน่าย / ให้ส่วนลดบิลโครงการ + fund_type + เตือนชื่อซ้ำ

═══════════════════════════════════════════════════════════════════════════════
หลักการที่ห้ามพลาด
═══════════════════════════════════════════════════════════════════════════════
1. `student_payments.written_off_amount` = **แหล่งความจริงเดียว** ของ "ยอดที่ถูกตัด"
   ของบิลโครงการ ⇒ ไม่แตะ `paid_amount` (เงินที่รับจริง) และไม่ลด `fee_collections.amount`
   (ซึ่งเป็นยอดบิลต้นฉบับที่ใช้บนใบแจ้งหนี้/สัญญา)
2. สูตรยอดค้างทั้งระบบ = `FC.amount - paid_amount - written_off_amount`
   (จุดที่ลืม = ยอดค้างเกินจริง — ความเสี่ยง #8 ของแผน)
3. **เฉพาะบิลโครงการ** — บิลค่าปรับมีเส้นทางคำขอยกเว้น (`waivers.py`) ที่ลง 49002/59001,
   sync `fines.amount` + `fee_collections.amount` + `waived_amount` ครบแล้ว
   ⇒ เปิดทางที่สองจะทำให้ "ยอดที่ถูกตัด" ของค่าปรับมีสองแหล่งและนับซ้ำ (409 ชี้ทาง)
4. ตัดจนไม่เหลืออะไร ⇒ `status='waived'` (ค่าเดียวกับเส้นทาง waiver ของค่าปรับ)
   เพื่อให้หลุดจาก `_open_bill_predicate` (predicate ไม่มีเงื่อนไขยอด)
5. `collections.py` เป็นhot file ของ P2.1 — **ห้ามแก้จาก package นี้** (ดู Gotchas)

⚠️ `constants.py` เป็น hot file ของ P1.1/P2.4 ⇒ ไฟล์นี้ **ไม่แก้**; `REFERENCE_TYPE_*`
   ที่ยังขาดประกาศเป็นค่าท้องถิ่นพร้อมหมายเหตุ (ไม่ถูกตรวจโดย label registry —
   `REFERENCE_TYPE_LABELS.get()` fallback เป็นค่าดิบได้)
"""
import time
from typing import List, Optional

import asyncpg

from core.exceptions import PaymentNotFoundError, RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
from .constants import (
    COLLECTION_KIND_FINE,
    PROJECT_BAD_DEBT_CODE,
    PROJECT_BAD_DEBT_NAME,
)

# 🧮 epsilon ของระบบ (ทศนิยม 2 ตำแหน่ง) — ใช้ค่าเดียวกันทุกไฟล์
_EPS = 0.005

ADJUSTMENT_TYPE_WRITE_OFF = "write_off"
ADJUSTMENT_TYPE_DISCOUNT = "discount"
_ADJUSTMENT_TYPES = (ADJUSTMENT_TYPE_WRITE_OFF, ADJUSTMENT_TYPE_DISCOUNT)

FUND_TYPE_ROOM = "room_fund"
FUND_TYPE_PASS_THROUGH = "pass_through"
_FUND_TYPES = (FUND_TYPE_ROOM, FUND_TYPE_PASS_THROUGH)

# ⚠️ ช่องว่างของ P1.1: `constants.py` ยังไม่มี `REFERENCE_TYPE_BILL_ADJUSTMENT`
#    (owned by P1.1/P2.4 ⇒ package นี้ไม่แก้) ⇒ ประกาศที่ไฟล์ผู้ใช้ตัวเดียว
REFERENCE_TYPE_BILL_ADJUSTMENT = "bill_adjustment"


class BillAdjustmentConflictError(ValueError):
    """409 — บิลค่าปรับใช้หน้าค่าปรับ / idempotency key ซ้ำแต่ payload ต่าง

    🔴 สืบทอดจาก `ValueError` ⇒ router **ต้องจับตัวนี้ก่อน** `ValueError` ไม่งั้น 409
       จะกลายเป็น 400 แล้วหน้าจอไม่รู้ว่าต้องไปจัดการอะไรก่อน
    """


def _money(value) -> float:
    """NUMERIC → float แล้วปัด 2 ตำแหน่ง (กฎ CLAUDE.md)"""
    return round(float(value or 0), 2)


def _money_str(value) -> str:
    return f"{_money(value):.2f}"


def _require_reason(value: Optional[str]) -> str:
    """เหตุผลบังคับ — ตรวจที่ service เพื่อให้ว่าง/ช่องว่างล้วนได้ **400** ไม่ใช่ 422"""
    reason = (value or "").strip()
    if not reason:
        raise ValueError("กรุณาระบุเหตุผลการตัดจำหน่าย/ให้ส่วนลด")
    if len(reason) > 500:
        raise ValueError("เหตุผลต้องไม่เกิน 500 ตัวอักษร")
    return reason


class BillAdjustmentsMixin:
    """ตัดจำหน่าย/ให้ส่วนลดบิลโครงการ + ตั้ง fund_type + เตือนชื่อโครงการซ้ำ"""

    # ═════════════════════════════════════════════════════════════════
    # public API — wrapper บาง ๆ; ตรรกะเงินอยู่ใน `_adjust_bill`
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def write_off_bill(
        cls, pool: asyncpg.Pool, *, payment_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ตัดจำหน่ายหนี้บิลโครงการ (MANAGE_FINANCE) — Dr 59002 / Cr 11001"""
        return await cls._adjust_bill(
            pool, payment_id=payment_id, req=req, user_id=user_id,
            client_source=client_source, actor_identifier=actor_identifier,
            server_id=server_id, room_id=room_id,
            adjustment_type=ADJUSTMENT_TYPE_WRITE_OFF,
            endpoint="POST /finance/payments/{payment_id}/write-off",
        )

    @classmethod
    async def discount_bill(
        cls, pool: asyncpg.Pool, *, payment_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ให้ส่วนลดบิลโครงการ (MANAGE_FINANCE) — Dr 49002 / Cr 11001"""
        return await cls._adjust_bill(
            pool, payment_id=payment_id, req=req, user_id=user_id,
            client_source=client_source, actor_identifier=actor_identifier,
            server_id=server_id, room_id=room_id,
            adjustment_type=ADJUSTMENT_TYPE_DISCOUNT,
            endpoint="POST /finance/payments/{payment_id}/discount",
        )

    # ═════════════════════════════════════════════════════════════════
    # เนื้อใน (transaction + ล็อก + guard + journal + audit) — ตัวเดียวทั้งสองชนิด
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def _adjust_bill(
        cls, pool: asyncpg.Pool, *, payment_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int], room_id: Optional[int],
        adjustment_type: str, endpoint: str,
    ) -> dict:
        """ลำดับ: resolve → RBAC → reason → 🔒lock → FOR UPDATE → guard → amount →
        idempotency → INSERT → journal → written_off → status → audit → void INV"""
        if adjustment_type not in _ADJUSTMENT_TYPES:
            raise ValueError(f"ไม่รองรับชนิดการปรับบิล '{adjustment_type}'")

        start_time = time.time()
        target_room_id = room_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                reason = _require_reason(getattr(req, "reason", None))
                amount = round(float(getattr(req, "amount", 0) or 0), 2)
                key = (getattr(req, "idempotency_key", None) or "").strip()
                if not key:
                    raise ValueError("ต้องมี idempotency_key")

                # 🔒 ต้องเป็น statement แรกที่แตะเงิน (หลัง RBAC + validation ที่ไม่แตะ DB)
                await _lock_room_money(conn, target_room_id)

                # 🔎 โหลดบิล + ล็อกแถว (FOR UPDATE OF SP — ไม่ล็อกแถว fee_collections
                #    ซึ่งเส้นทางอื่นอาจถืออยู่ก่อนหน้า; ยอดบิลเป็น snapshot ที่เราแค่อ่าน)
                bill = await conn.fetchrow(
                    """SELECT SP.id, SP.student_id, SP.paid_amount,
                              SP.written_off_amount, SP.status,
                              FC.amount AS bill_amount, FC.collection_kind,
                              FC.fund_type, FC.title
                       FROM student_payments SP
                       JOIN fee_collections FC ON FC.id = SP.collection_id
                       WHERE SP.id = $1 AND FC.room_id = $2
                         AND SP.deleted_at IS NULL AND FC.deleted_at IS NULL
                       FOR UPDATE OF SP""",
                    payment_id, target_room_id,
                )
                if bill is None:
                    raise PaymentNotFoundError("ไม่พบบิลนี้")

                # ⚖️ บิลค่าปรับมีเส้นทางของตัวเอง (waiver) — 409 ชี้ทาง
                if bill["collection_kind"] == COLLECTION_KIND_FINE:
                    raise BillAdjustmentConflictError(
                        "บิลค่าปรับใช้หน้าค่าปรับ (คำขอยกเว้น) — "
                        "ซึ่งลง 49002/59001 ให้แล้ว"
                    )

                # 🔁 idempotency ตรวจ **ก่อน** guard ยอดคงเหลือ: คำขอซ้ำด้วยคีย์เดิม
                #    ต้องคืนผลเดิมได้ แม้ยอดคงเหลือหลังครั้งแรกจะลดลงจนไม่ถึง `amount` อีก
                existing = await conn.fetchrow(
                    """SELECT * FROM finance_bill_adjustments
                       WHERE room_id = $1 AND idempotency_key = $2""",
                    target_room_id, key,
                )
                if existing is not None:
                    same = (
                        int(existing["student_payment_id"]) == int(payment_id)
                        and existing["adjustment_type"] == adjustment_type
                        and abs(_money(existing["amount"]) - amount) <= _EPS
                    )
                    if not same:
                        raise BillAdjustmentConflictError(
                            "คีย์นี้ถูกใช้กับรายการตัดบิลอื่นแล้ว — "
                            "ใช้คีย์ใหม่สำหรับรายการใหม่"
                        )
                    return cls._shape_adjustment(
                        existing, bill, reason=reason, reused=True,
                    )

                if amount <= _EPS:
                    raise ValueError("ยอดที่ตัดต้องมากกว่า 0 บาท")

                paid = _money(bill["paid_amount"])
                written_before = _money(bill["written_off_amount"])
                outstanding = round(
                    _money(bill["bill_amount"]) - paid - written_before, 2
                )
                if amount > outstanding + _EPS:
                    raise ValueError(
                        f"ตัดได้ไม่เกินยอดคงเหลือ {outstanding:,.2f} บาท "
                        f"(ขอ {amount:,.2f} บาท)"
                    )

                # 🧾 INSERT แถวปรับบิลก่อน (ต้องการ id เป็น reference ของ journal)
                adjustment_id = await conn.fetchval(
                    """INSERT INTO finance_bill_adjustments
                           (room_id, student_payment_id, adjustment_type,
                            amount, reason, idempotency_key, created_by)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       RETURNING id""",
                    target_room_id, payment_id, adjustment_type,
                    amount, reason, key, user_id,
                )

                # ⚖️ journal: write_off → Dr 59002 / discount → Dr 49002 · Cr AR โครงการ 11001
                if adjustment_type == ADJUSTMENT_TYPE_WRITE_OFF:
                    debit_ledger_id = await cls._resolve_system_ledger(
                        conn, target_room_id,
                        code=PROJECT_BAD_DEBT_CODE, name=PROJECT_BAD_DEBT_NAME,
                        account_type="expense",
                    )
                    journal_label = "ตัดจำหน่ายหนี้สูญ (โครงการ)"
                else:
                    debit_ledger_id = await cls._resolve_fine_discount_ledger(
                        conn, target_room_id,
                    )
                    journal_label = "ให้ส่วนลดบิล (โครงการ)"
                ar_ledger_id = await cls._resolve_ar_project_ledger(
                    conn, target_room_id,
                )

                journal_id = await cls._insert_journal_entry(
                    conn, target_room_id,
                    reference_type=REFERENCE_TYPE_BILL_ADJUSTMENT,
                    reference_id=str(adjustment_id),
                    description=f"{journal_label} — {bill['title']} #{payment_id}",
                    recorded_by=actor_identifier,
                    metadata={
                        "idempotency_key": key,
                        "student_payment_id": payment_id,
                        "adjustment_type": adjustment_type,
                        "collection_kind": "project",
                    },
                    lines=[
                        {"ledger_id": debit_ledger_id, "debit": amount, "credit": 0,
                         "line_description": journal_label},
                        {"ledger_id": ar_ledger_id, "debit": 0, "credit": amount,
                         "line_description": f"ลดผู้ค้างชำระบิล #{payment_id}"},
                    ],
                )
                await conn.execute(
                    "UPDATE finance_bill_adjustments SET journal_entry_id = $1 WHERE id = $2",
                    journal_id, adjustment_id,
                )

                # 💰 written_off_amount += amount — **ไม่แตะ paid_amount**
                written_after = round(written_before + amount, 2)
                remaining = round(
                    _money(bill["bill_amount"]) - paid - written_after, 2
                )
                # บิลที่ไม่มีอะไรค้างแล้วต้องหลุดจาก predicate "บิลเปิด" (ไม่มีเงื่อนไขยอด)
                new_status = "waived" if remaining <= _EPS else "pending"
                await conn.execute(
                    """UPDATE student_payments
                       SET written_off_amount = written_off_amount + $1, status = $2
                       WHERE id = $3""",
                    amount, new_status, payment_id,
                )

                # 🧾 snapshot ยอดค้างใน INV เก่าไม่จริงแล้ว ⇒ void ใบรวมยอดของนักเรียนคนนี้
                #    (ใช้ helper ของ collections ผ่าน MRO — ห้าม UPDATE เอง)
                voided_invoices = await cls._void_aggregate_invoices_for_students(
                    conn, room_id=target_room_id,
                    student_ids=[int(bill["student_id"])],
                    reason=(
                        f"ยอดค้างเปลี่ยนจากการ{'ตัดจำหน่าย' if adjustment_type == ADJUSTMENT_TYPE_WRITE_OFF else 'ให้ส่วนลด'}"
                        f"บิล #{payment_id}"
                    ),
                    voided_by=user_id,
                )

                await service_logger.log(
                    conn=conn, action="INSERT",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_BILL_ADJUSTMENT",
                    entity_id=str(adjustment_id), status="success",
                    old_values={
                        "paid_amount": paid,
                        "written_off_amount": written_before,
                        "status": bill["status"],
                    },
                    new_values={
                        "adjustment_type": adjustment_type,
                        "amount": amount,
                        "reason": reason,
                        "written_off_amount": written_after,
                        "remaining": remaining,
                        "status": new_status,
                        "journal_entry_id": str(journal_id),
                        "idempotency_key": key,
                        "voided_invoices": voided_invoices,
                    },
                    endpoint_or_command=endpoint,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

                return cls._shape_adjustment(
                    {
                        "id": adjustment_id,
                        "adjustment_type": adjustment_type,
                        "amount": amount,
                        "status": "active",
                        "journal_entry_id": journal_id,
                    },
                    bill,
                    reason=reason,
                    reused=False,
                    written_off_total=written_after,
                    remaining=remaining,
                    bill_status=new_status,
                    voided_invoices=voided_invoices,
                )

    @staticmethod
    def _shape_adjustment(
        row, bill, *, reason: str, reused: bool,
        written_off_total: Optional[float] = None,
        remaining: Optional[float] = None,
        bill_status: Optional[str] = None,
        voided_invoices: int = 0,
    ) -> dict:
        """รูปร่างคำตอบเดียวทั้งครั้งแรกและครั้งที่ซ้ำ (ตัวเลขเงินเป็น string 2 ตำแหน่ง)"""
        paid = _money(bill["paid_amount"])
        written = (
            _money(written_off_total) if written_off_total is not None
            else _money(bill["written_off_amount"])
        )
        left = (
            _money(remaining) if remaining is not None
            else round(_money(bill["bill_amount"]) - paid - written, 2)
        )
        status = bill_status or bill["status"]
        return {
            "status": "success",
            "message": "รายการนี้ถูกบันทึกไว้แล้ว (คีย์เดิม)" if reused else None,
            "reused": reused,
            "adjustment": {
                "id": int(row["id"]),
                "adjustment_type": row["adjustment_type"],
                "amount": _money_str(row["amount"]),
                "status": row["status"],
                "written_off_total": _money_str(written),
                "remaining": _money_str(left),
                "bill_status": status,
                "journal_entry_id": (
                    str(row["journal_entry_id"]) if row["journal_entry_id"] else None
                ),
                "created_at": row.get("created_at") if hasattr(row, "get") else None,
                "reason": reason,
            },
            "voided_invoices": voided_invoices,
        }

    # ═════════════════════════════════════════════════════════════════
    # อ่านรายการปรับบิลของบิลหนึ่ง (สมาชิกอ่านได้)
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def list_bill_adjustments(
        cls, pool: asyncpg.Pool, *, payment_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: int,
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            exists = await conn.fetchval(
                """SELECT 1 FROM student_payments SP
                   JOIN fee_collections FC ON FC.id = SP.collection_id
                   WHERE SP.id = $1 AND FC.room_id = $2 AND SP.deleted_at IS NULL""",
                payment_id, target_room_id,
            )
            if not exists:
                raise PaymentNotFoundError("ไม่พบบิลนี้")

            rows = await conn.fetch(
                """SELECT id, student_payment_id, adjustment_type, amount,
                          reason, status, voided_at, void_reason,
                          journal_entry_id, created_by, created_at
                   FROM finance_bill_adjustments
                   WHERE room_id = $1 AND student_payment_id = $2
                   ORDER BY id DESC""",
                target_room_id, payment_id,
            )
        items = [
            {
                "id": int(r["id"]),
                "student_payment_id": int(r["student_payment_id"]),
                "adjustment_type": r["adjustment_type"],
                "amount": _money_str(r["amount"]),
                "reason": r["reason"],
                "status": r["status"],
                "voided_at": r["voided_at"],
                "void_reason": r["void_reason"],
                "journal_entry_id": str(r["journal_entry_id"]) if r["journal_entry_id"] else None,
                "created_by": r["created_by"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"items": items, "total": len(items)}

    # ═════════════════════════════════════════════════════════════════
    # มิติรายงาน: fund_type (ไม่แตะเงิน/ยอด/journal)
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def set_collection_fund_type(
        cls, pool: asyncpg.Pool, *, collection_id: int, fund_type: str,
        user_id: int, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ตั้ง `fee_collections.fund_type` — มิติรายงานเท่านั้น (ไม่ใช่การแก้เงิน)

        🔒 ยังยึด `_lock_room_money` เพราะรายงานที่ SUM ตาม fund_type ต้องเห็นค่าที่
           commit แล้วเท่านั้น (กันอ่านค่ากลางทางระหว่างรายงานกับ UPDATE)
        """
        start_time = time.time()
        target_room_id = room_id
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                value = (fund_type or "").strip()
                if value not in _FUND_TYPES:
                    raise ValueError("fund_type ต้องเป็น room_fund หรือ pass_through")
                await _lock_room_money(conn, target_room_id)

                row = await conn.fetchrow(
                    """SELECT id, title, fund_type FROM fee_collections
                       WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                       FOR UPDATE""",
                    collection_id, target_room_id,
                )
                if row is None:
                    raise RoomNotFoundError("ไม่พบโครงการนี้")

                old_value = row["fund_type"]
                if old_value != value:
                    await conn.execute(
                        "UPDATE fee_collections SET fund_type = $1 WHERE id = $2",
                        value, collection_id,
                    )
                    await service_logger.log(
                        conn=conn, action="UPDATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source,
                        room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_FEE_COLLECTION",
                        entity_id=str(collection_id), status="success",
                        old_values={"fund_type": old_value},
                        new_values={"fund_type": value},
                        endpoint_or_command="PATCH /finance/fee-collections/{id}/fund-type",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return {
                    "status": "success",
                    "message": None,
                    "id": int(collection_id),
                    "title": row["title"],
                    "fund_type": value,
                }
    # ═════════════════════════════════════════════════════════════════
    # เตือนชื่อโครงการซ้ำ — อ่านล้วน (non-blocking)
    # ═════════════════════════════════════════════════════════════════
    @classmethod
    async def check_duplicate_collection_title(
        cls, pool: asyncpg.Pool, *, title: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: int,
    ) -> dict:
        needle = (title or "").strip()
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            if not needle:
                raise ValueError("ต้องระบุชื่อโครงการที่ต้องการตรวจ")

            # ⚠️ `fee_collections` ไม่มีคอลัมน์ `created_at` (ดู `core/init_db.py`) ⇒
            #    เรียงด้วย `id` แทน (id = ลำดับการสร้างจริง) และไม่ส่ง `created_at` กลับ
            rows = await conn.fetch(
                """SELECT id, title, status FROM fee_collections
                   WHERE room_id = $1 AND deleted_at IS NULL
                     AND lower(btrim(title)) = lower(btrim($2))
                   ORDER BY id DESC LIMIT 5""",
                target_room_id, needle,
            )
        items: List[dict] = [
            {"id": int(r["id"]), "title": r["title"], "status": r["status"]}
            for r in rows
        ]
        warning = None
        if items:
            warning = f"มีโครงการชื่อเดียวกันอยู่แล้ว {len(items)} รายการ (สร้างซ้ำได้)"
        return {"duplicates": items, "warning": warning}
