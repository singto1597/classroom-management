"""🚫 [FIN-V2 / P6.1] void engine — ยกเลิกเหตุการณ์เงิน/เอกสารแบบ atomic จุดเดียวของระบบ

═══════════════════════════════════════════════════════════════════════════════
หลักประกัน 4 ข้อ (เหมือน `revert_transaction` แต่ครอบ event/PV/INC v2)
═══════════════════════════════════════════════════════════════════════════════
1. **transaction เดียว** — พังกลางทาง = ไม่มีอะไรเปลี่ยน (ไม่มี void ครึ่งทาง)
2. **กลับทุกขา** — `finance_accounts.balance`, `student_payments.paid_amount`,
   `student_credits` (append-only `reverse`), journal, เอกสาร
3. **guard ก่อนแตะเงินเสมอ** — เครดิตถูกใช้ต่อ / เงินในกระเป๋าไม่พอ / เอกสารถูกอ้าง / void ซ้ำ
4. **เหตุผลบังคับ** + audit log ใน transaction เดียวกัน

═══════════════════════════════════════════════════════════════════════════════
🔴 กฎที่ห้ามพลาด
═══════════════════════════════════════════════════════════════════════════════
- `_lock_room_money` ต้องเป็น statement แรกที่แตะข้อมูลเงิน (หลัง RBAC + reason)
  แล้วจึง `_lock_payments_in_order(conn, sorted(ids))` **ก่อน** ลูปต่อบิล
- **ห้าม `DELETE`** — void = `status='voided'` + `deleted_at=NOW()` คู่กันเสมอ
  (`finance_receipts` มี CHECK `chk_receipt_voided_is_deleted`; journal ใช้ convention เดียวกัน)
- `student_credits` append-only — ห้ามลบ/แก้แถว topup เพื่อ "ยกเลิก"; INSERT `reverse`
- **อ่าน `balance_after` ก่อน soft-delete แถว apply** (บทเรียน credits.py) ไม่งั้น
  `_load_credit_balance` อ่านยอดที่ "คืนแล้ว" แล้วบวกซ้ำ = คืนเครดิตสองรอบ
- `metadata->>'payment_event_id'` คืน **text** ⇒ ส่ง `str(id)`
- **ห้ามเรียก `_confirm_single_payment` ย้อนทาง** และห้ามเรียก `_undo_credit_locked`
  กับแถวที่เกิดจาก event — มัน raise `CreditEventManagedError` โดยเจตนา (§P3.3)
  ⇒ เราต้อง replicate การกลับแถว apply เองในไฟล์นี้
- journal ของ event มี 3 แบบ: bill ปิด `legacy_transaction_id`, topup ปิด
  `payment_event_id` + `legacy_transaction_id`, credit_apply ปิด
  `student_credits.journal_entry_id` (ไม่มีใน metadata) ⇒ ต้องครอบทั้งสามทาง
"""

import time
from typing import Dict, List, Optional

import asyncpg

from core.exceptions import PaymentNotFoundError, RoomNotFoundError
from core.rbac import require_permission

from .base import _lock_payments_in_order, _lock_room_money, service_logger
from .constants import (
    CREDIT_ENTRY_APPLY,
    CREDIT_ENTRY_REVERSE,
    DOC_STATUS_ACTIVE,
    DOC_STATUS_VOIDED,
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_DEPOSIT,
    DOC_TYPE_INVOICE,
    DOC_TYPE_MONTHLY_REPORT,
    DOC_TYPE_RECEIPT,
)
from .expense_vouchers import ExpenseVoucherNotFoundError
from .income_batches import IncomeBatchNotFoundError

# 🧮 ค่าคลาดเคลื่อนที่ยอมรับได้ (เท่ากับ `_MIN_AMOUNT`/ทศนิยม 2 ตำแหน่งของระบบ)
_EPS = 0.005


class VoidConflictError(Exception):
    """409 — สถานะไม่ให้ยกเลิก (ยกเลิกแล้ว / เครดิตถูกใช้ต่อ / เอกสารถูกอ้าง / เงินไม่พอ)

    🔴 **ห้าม** ให้ router กลืนเป็น 400: ผู้ใช้ทำถูกแล้ว แต่ระบบกันไม่ให้ทำ
       หน้าจอใช้รหัส 409 แยกได้ว่าต้องไปจัดการเอกสารอื่นก่อน
    """


def _money(value) -> float:
    """NUMERIC → float แล้วปัด 2 ตำแหน่ง (กฎ CLAUDE.md: cast ก่อน arithmetic)"""
    return round(float(value or 0), 2)


def _require_reason(value: Optional[str]) -> str:
    """เหตุผลบังคับ — ตรวจที่ service เพื่อให้ว่าง/ช่องว่างล้วนได้ **400** ไม่ใช่ 422"""
    reason = (value or "").strip()
    if not reason:
        raise ValueError("กรุณาระบุเหตุผลที่ยกเลิก")
    if len(reason) > 500:
        raise ValueError("เหตุผลที่ยกเลิกต้องไม่เกิน 500 ตัวอักษร")
    return reason


def _account_rows(deltas: Dict[int, float]) -> List[dict]:
    return [
        {"account_id": int(account_id), "delta": round(delta, 2)}
        for account_id, delta in sorted(deltas.items())
    ]


def _void_result(
    *, doc_type: str, doc_id: int, receipt_no: Optional[str],
    voided_at, amount: float, paid_amount_delta: float,
    credit_restored: float, accounts: Dict[int, float],
    message: str,
) -> dict:
    """รูปร่างคำตอบเดียวของทุก void (ตรงกับ `VoidResponse`) + `audit` ชั่วคราว"""
    return {
        "status": "success",
        "message": message,
        "doc_type": doc_type,
        "doc_id": int(doc_id),
        "receipt_no": receipt_no,
        "voided_at": voided_at,
        "reversed": {
            "amount": round(amount, 2),
            "paid_amount_delta": round(paid_amount_delta, 2),
            "credit_restored": round(credit_restored, 2),
            "accounts": _account_rows(accounts),
        },
    }


class VoidMixin:
    # ═════════════════════════════════════════════════════════════════════
    # ตัวช่วยเขียนเอกสาร (receipts) — void หลายใบด้วยคำสั่งเดียว
    # ═════════════════════════════════════════════════════════════════════
    @classmethod
    async def _void_receipt_ids_locked(
        cls, conn: asyncpg.Connection, *, room_id: int, receipt_ids: List[Optional[int]],
        reason: str, user_id: int,
    ) -> List[dict]:
        """void ใบเสร็จ/ใบแจ้งหนี้ตาม id — ตั้ง `status` + `deleted_at` **คู่กันเสมอ**

        ใบที่ void ไปแล้ว/ไม่มีอยู่ = no-op (idempotent ที่ระดับแถว) ⇒ caller
        ยังเอาผลลัพธ์ไปแสดง receipt_no ได้
        """
        ids = sorted({int(i) for i in receipt_ids if i is not None})
        if not ids:
            return []
        return await conn.fetch(
            """UPDATE finance_receipts
               SET status = $3, voided_at = CURRENT_TIMESTAMP, voided_by = $4,
                   void_reason = $5, deleted_at = NOW()
               WHERE room_id = $1 AND id = ANY($2::int[])
                 AND status = $6 AND deleted_at IS NULL
               RETURNING id, receipt_no, doc_type""",
            room_id, ids, DOC_STATUS_VOIDED, user_id, reason, DOC_STATUS_ACTIVE,
        )

    @staticmethod
    async def _log_void_failure(
        pool: asyncpg.Pool, *, room_id: Optional[int], user_id: int,
        entity_type: str, entity_id: str, endpoint: str,
        actor_identifier: str, client_source: str,
        error: Exception, start_time: float,
    ) -> None:
        """audit แถว 'failed' ด้วย connection แยก (transaction หลัก rollback ไปแล้ว)"""
        try:
            async with pool.acquire() as log_conn:
                await service_logger.log(
                    conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=room_id, user_id=user_id,
                    entity_type=entity_type, entity_id=entity_id,
                    status="failed", error_detail=str(error),
                    endpoint_or_command=endpoint,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
        except Exception:
            # audit ล้มไม่ควรกลบ error จริงที่ผู้ใช้ต้องเห็น
            pass

    # ═════════════════════════════════════════════════════════════════════
    # 1) ยกเลิกรายการรับเงิน (payment event) — คืนเงิน/บิล/เครดิต + void REC/DEP
    # ═════════════════════════════════════════════════════════════════════
    @classmethod
    async def void_payment_event(
        cls, pool: asyncpg.Pool, *, event_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิกรายการรับเงินทั้งรายการ (MANAGE_FINANCE) — atomic ทั้งก้อน"""
        start_time = time.time()
        target_room_id = room_id
        endpoint = "POST /finance/payment-events/{event_id}/void"
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    reason = _require_reason(getattr(req, "reason", None))
                    # 🔒 statement แรกที่แตะเงิน — ต้องมาก่อนการอ่านแถวเงินใด ๆ
                    await _lock_room_money(conn, target_room_id)

                    event = await conn.fetchrow(
                        """SELECT * FROM finance_payment_events
                           WHERE id = $1 AND room_id = $2 FOR UPDATE""",
                        event_id, target_room_id,
                    )
                    if event is None:
                        raise PaymentNotFoundError("ไม่พบรายการรับเงินนี้")

                    user_name = await cls._resolve_actor_name(conn, user_id)
                    result = await cls._void_event_locked(
                        conn, room_id=target_room_id, event=event, reason=reason,
                        user_id=user_id, user_name=user_name,
                    )
                    audit = result.pop("audit")

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_PAYMENT_EVENT",
                        entity_id=str(event_id), status="success",
                        old_values=audit["old"], new_values=audit["new"],
                        endpoint_or_command=endpoint,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    return result
        except Exception as e:
            await cls._log_void_failure(
                pool, room_id=target_room_id, user_id=user_id,
                entity_type="FINANCE_PAYMENT_EVENT", entity_id=str(event_id),
                endpoint=endpoint, actor_identifier=actor_identifier,
                client_source=client_source, error=e, start_time=start_time,
            )
            raise

    @classmethod
    async def _void_event_locked(
        cls, conn: asyncpg.Connection, *, room_id: int, event, reason: str,
        user_id: int, user_name: str,
    ) -> dict:
        """กลับทุกขาของ event — caller ถือ transaction + `_lock_room_money` แล้ว"""
        event_id = int(event["id"])
        if event["status"] == DOC_STATUS_VOIDED or event["voided_at"] is not None:
            raise VoidConflictError("รายการรับเงินนี้ถูกยกเลิกแล้ว")

        lines = await conn.fetch(
            """SELECT id, line_kind, student_payment_id, finance_transaction_id,
                      credit_entry_id, amount
               FROM finance_payment_event_lines
               WHERE event_id = $1
               ORDER BY id""",
            event_id,
        )
        if not lines:
            raise VoidConflictError("รายการรับเงินนี้ไม่มีบรรทัดให้ย้อนกลับ")

        amount_received = _money(event["amount_received"])
        credit_used = _money(event["credit_used"])
        credit_added = _money(event["credit_added"])

        # 1) 🔒 ล็อกกระเป๋าเงินของ event (ตามลำดับเดียวกับเส้นทางอื่น)
        wallet = await conn.fetchrow(
            """SELECT id, balance FROM finance_accounts
               WHERE id = $1 AND room_id = $2 FOR UPDATE""",
            event["wallet_account_id"], room_id,
        )
        if wallet is None:
            raise RoomNotFoundError("ไม่พบกระเป๋าเงินของรายการนี้")
        wallet_balance = _money(wallet["balance"])
        # ⚠️ brief บอก "ขาเข้าไม่ต้องเช็ค" — แต่ถ้าเงินนั้นถูกใช้ไปแล้ว การหักคืนจะทำให้
        #    `balance` ติดลบ (ตารางไม่มี CHECK) แล้ว dashboard/งบเพี้ยนโดยไม่มี error
        #    ⇒ ใช้เกณฑ์เดียวกับ INC: ต้องมีเงินพอคืน
        if amount_received > 0 and wallet_balance + _EPS < amount_received:
            raise VoidConflictError(
                f"เงินในกระเป๋าเหลือ {wallet_balance:,.2f} บาท "
                f"ไม่พอคืน {amount_received:,.2f} บาท"
            )

        # 2) 🧾 guard: เครดิตที่ event เติมไว้ถูก "ใช้ต่อ" หรือยัง
        topup_lines = [ln for ln in lines if ln["line_kind"] == "credit_topup"]
        credit_to_remove = round(sum(_money(ln["amount"]) for ln in topup_lines), 2)
        for ln in topup_lines:
            later = await conn.fetchval(
                """SELECT id FROM student_credits
                   WHERE room_id = $1 AND student_id = $2 AND id > $3
                     AND deleted_at IS NULL AND entry_type = ANY($4::text[])
                   ORDER BY id LIMIT 1""",
                room_id, event["student_id"], ln["credit_entry_id"],
                [CREDIT_ENTRY_APPLY, CREDIT_ENTRY_REVERSE],
            )
            if later is None:
                continue
            used = _money(await conn.fetchval(
                """SELECT COALESCE(SUM(amount), 0) FROM student_credits
                   WHERE room_id = $1 AND student_id = $2 AND id > $3
                     AND deleted_at IS NULL AND entry_type = $4""",
                room_id, event["student_id"], ln["credit_entry_id"],
                CREDIT_ENTRY_APPLY,
            ))
            if used <= 0:
                used = credit_to_remove
            raise VoidConflictError(
                f"เครดิตจากรายการนี้ถูกใช้ไปแล้ว {used:,.2f} บาท — "
                "ต้องยกเลิกการใช้เครดิตก่อน"
            )

        # 3) ⚖️ guards ของค่าปรับ + 🔒 ล็อกบิลตามลำดับ id (ก่อนเข้าลูปกลับบิล)
        payment_ids = sorted({
            int(ln["student_payment_id"])
            for ln in lines
            if ln["student_payment_id"] is not None
        })
        if payment_ids:
            await cls._assert_fine_cashflow_reversible(conn, payment_ids)
            await cls._assert_no_pending_fine_requests(conn, payment_ids)
            await _lock_payments_in_order(conn, payment_ids)

        # 4) 💰 กลับขาเงินสดของ event (wallet)
        accounts: Dict[int, float] = {}
        if amount_received > 0:
            await conn.execute(
                "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
                amount_received, event["wallet_account_id"],
            )
            wallet_id = int(event["wallet_account_id"])
            accounts[wallet_id] = round(accounts.get(wallet_id, 0.0) - amount_received, 2)

        # 5) ↩️ กลับบิลทุกบรรทัด (bill = เงินสด, credit_apply = เครดิต) + คืนแถวเครดิต
        paid_reduced = 0.0
        credit_restored = 0.0
        for ln in lines:
            kind = ln["line_kind"]
            if kind not in ("bill", "credit_apply"):
                continue
            payment_id = int(ln["student_payment_id"])
            applied = _money(ln["amount"])
            sp = await conn.fetchrow(
                """SELECT SP.paid_amount, FC.amount AS total_amount
                   FROM student_payments SP
                   JOIN fee_collections FC ON SP.collection_id = FC.id
                   WHERE SP.id = $1""",
                payment_id,
            )
            if sp is None:
                raise PaymentNotFoundError(f"ไม่พบรายการชำระเงิน #{payment_id}")
            old_paid = _money(sp["paid_amount"])
            new_paid = round(old_paid - applied, 2)
            if new_paid < -_EPS:
                raise VoidConflictError(
                    f"ยอดที่จ่ายแล้วของบิล ({old_paid:,.2f}) น้อยกว่ายอดที่จะคืน "
                    f"({applied:,.2f}) — ข้อมูลไม่สอดคล้อง"
                )
            bill_total = _money(sp["total_amount"])
            if new_paid <= _EPS:
                # ท่าเดียวกับ `revert_transaction`/`_undo_credit_locked`: กลับเป็น 0
                # ต้องล้างร่องรอยการชำระทั้งหมด ไม่ให้เหลือสถานะครึ่ง ๆ กลาง ๆ
                new_paid = 0.0
                await conn.execute(
                    """UPDATE student_payments
                       SET paid_amount = 0, status = 'pending', paid_to_account_id = NULL,
                           slip_image_url = NULL, recorded_by = NULL, paid_at = NULL,
                           transaction_id = NULL
                       WHERE id = $1""",
                    payment_id,
                )
            else:
                new_status = "paid" if new_paid >= bill_total else "pending"
                await conn.execute(
                    "UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3",
                    new_paid, new_status, payment_id,
                )
            paid_reduced = round(paid_reduced + applied, 2)

            if kind != "credit_apply":
                continue

            # 🧾 credit_apply: กลับแถว `apply` แบบเดียวกับ `_undo_credit_locked`
            #    (เรียกฟังก์ชันนั้นไม่ได้ — มันปฏิเสธแถวที่เกิดจาก event โดยเจตนา)
            entry = await conn.fetchrow(
                """SELECT * FROM student_credits
                   WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE""",
                ln["credit_entry_id"], room_id,
            )
            if entry is None:
                raise VoidConflictError(
                    "ไม่พบรายการหักเครดิตของรายการรับเงินนี้ (อาจถูกยกเลิกไปแล้ว)"
                )
            if entry["entry_type"] != CREDIT_ENTRY_APPLY:
                raise VoidConflictError(
                    "รายการเครดิตที่อ้างในรายการรับเงินนี้ไม่ใช่รายการหักปิดบิล"
                )
            back = _money(entry["amount"])

            # 🚫 void journal ของ apply (ผูกด้วย journal_entry_id — metadata ไม่มี event id)
            if entry["journal_entry_id"]:
                await conn.execute(
                    """UPDATE journal_entries
                       SET status = 'voided', deleted_at = NOW(),
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = $1 AND room_id = $2
                         AND status <> 'voided' AND deleted_at IS NULL""",
                    entry["journal_entry_id"], room_id,
                )

            # 🔴 อ่านยอดคงเหลือ **ก่อน** soft-delete แถวนี้ (กันคืนเครดิตสองรอบ)
            balance_before = await cls._load_credit_balance(
                conn, room_id=room_id, student_id=event["student_id"]
            )
            balance_after = round(balance_before + back, 2)
            await conn.execute(
                "UPDATE student_credits SET deleted_at = NOW() WHERE id = $1",
                entry["id"],
            )
            await conn.execute(
                """INSERT INTO student_credits
                       (room_id, student_id, entry_type, amount, balance_after,
                        student_payment_id, collection_id, note, recorded_by,
                        payment_event_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                room_id, event["student_id"], CREDIT_ENTRY_REVERSE, back, balance_after,
                payment_id, entry["collection_id"],
                f"ยกเลิกรายการรับเงิน #{event_id}: {reason}"[:200],
                user_name, event_id,
            )
            credit_restored = round(credit_restored + back, 2)

        if payment_ids:
            await cls._sync_fine_status(conn, payment_ids)

        # 6) ➖ ถอนเครดิตส่วนเกินที่ event เติมไว้ (append-only reverse)
        for ln in topup_lines:
            removed = _money(ln["amount"])
            balance_before = await cls._load_credit_balance(
                conn, room_id=room_id, student_id=event["student_id"]
            )
            balance_after = round(balance_before - removed, 2)
            if balance_after < -_EPS:
                raise VoidConflictError(
                    "เครดิตคงเหลือไม่พอตัดคืน — ข้อมูลไม่สอดคล้อง"
                )
            await conn.execute(
                """INSERT INTO student_credits
                       (room_id, student_id, entry_type, amount, balance_after,
                        finance_transaction_id, note, recorded_by, payment_event_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                room_id, event["student_id"], CREDIT_ENTRY_REVERSE, removed,
                balance_after, ln["finance_transaction_id"],
                f"ยกเลิกรายการรับเงิน #{event_id} (คืนเงินเกิน): {reason}"[:200],
                user_name, event_id,
            )
            credit_restored = round(credit_restored - removed, 2)

        # 7) 🗑️ soft-delete transactions ของ event (ไม่ DELETE — ประวัติต้องตรวจได้)
        await conn.execute(
            """UPDATE finance_transactions SET deleted_at = NOW()
               WHERE room_id = $1 AND payment_event_id = $2 AND deleted_at IS NULL""",
            room_id, event_id,
        )

        # 8) 🚫 void journal ทุกใบของ event ในคำสั่งเดียว
        #    - bill: metadata `legacy_transaction_id` (ไม่มี payment_event_id)
        #    - topup: มีทั้งสองคีย์
        #    - credit_apply: ไม่มีทั้งคู่ ⇒ void แล้วในลูปด้านบนด้วย journal_entry_id
        tx_ids = sorted({
            str(int(ln["finance_transaction_id"]))
            for ln in lines
            if ln["finance_transaction_id"] is not None
        })
        await conn.execute(
            """UPDATE journal_entries
               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                 AND (metadata->>'payment_event_id' = $2
                      OR metadata->>'legacy_transaction_id' = ANY($3::text[]))""",
            room_id, str(event_id), tx_ids,
        )

        # 9) 🧾 void เอกสารของ event (REC + DEP ในการยิงครั้งเดียว)
        voided_docs = await conn.fetch(
            """UPDATE finance_receipts
               SET status = $3, voided_at = CURRENT_TIMESTAMP, voided_by = $4,
                   void_reason = $5, deleted_at = NOW()
               WHERE room_id = $1 AND payment_event_id = $2
                 AND status = $6 AND deleted_at IS NULL
               RETURNING receipt_no, doc_type""",
            room_id, event_id, DOC_STATUS_VOIDED, user_id, reason, DOC_STATUS_ACTIVE,
        )
        receipt_no = next(
            (row["receipt_no"] for row in voided_docs
             if row["doc_type"] == DOC_TYPE_RECEIPT),
            None,
        )

        # 10) 🏷️ ปิด event
        voided_at = await conn.fetchval(
            """UPDATE finance_payment_events
               SET status = $1, voided_at = CURRENT_TIMESTAMP, voided_by = $2,
                   void_reason = $3
               WHERE id = $4 AND room_id = $5
               RETURNING voided_at""",
            DOC_STATUS_VOIDED, user_id, reason, event_id, room_id,
        )

        result = _void_result(
            doc_type="payment_event", doc_id=event_id, receipt_no=receipt_no,
            voided_at=voided_at, amount=amount_received,
            paid_amount_delta=-paid_reduced, credit_restored=credit_restored,
            accounts=accounts, message="ยกเลิกรายการรับเงินแล้ว",
        )
        result["audit"] = {
            "old": {
                "status": DOC_STATUS_ACTIVE,
                "student_id": event["student_id"],
                "amount_received": amount_received,
                "credit_used": credit_used,
                "credit_added": credit_added,
                "line_count": len(lines),
            },
            "new": {
                "status": DOC_STATUS_VOIDED,
                "void_reason": reason,
                "amount_reversed": amount_received,
                "paid_amount_reduced": paid_reduced,
                "credit_restored": credit_restored,
                "voided_documents": [row["receipt_no"] for row in voided_docs],
            },
        }
        return result

    # ═════════════════════════════════════════════════════════════════════
    # 2) ยกเลิกใบสำคัญจ่าย (PV) — คืนทุกกระเป๋า + void CERT พร้อมกัน
    # ═════════════════════════════════════════════════════════════════════
    @classmethod
    async def void_expense_voucher(
        cls, pool: asyncpg.Pool, *, voucher_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิกใบสำคัญจ่าย (MANAGE_FINANCE) — PV + CERT ต้องตายด้วยกันเสมอ"""
        start_time = time.time()
        target_room_id = room_id
        endpoint = "POST /finance/expense-vouchers/{id}/void"
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    reason = _require_reason(getattr(req, "reason", None))
                    await _lock_room_money(conn, target_room_id)

                    voucher = await conn.fetchrow(
                        """SELECT * FROM finance_expense_vouchers
                           WHERE id = $1 AND room_id = $2 FOR UPDATE""",
                        voucher_id, target_room_id,
                    )
                    if voucher is None:
                        raise ExpenseVoucherNotFoundError("ไม่พบใบสำคัญจ่ายนี้")

                    user_name = await cls._resolve_actor_name(conn, user_id)
                    result = await cls._void_voucher_locked(
                        conn, room_id=target_room_id, voucher=voucher,
                        reason=reason, user_id=user_id, user_name=user_name,
                    )
                    audit = result.pop("audit")

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_EXPENSE_VOUCHER",
                        entity_id=str(voucher_id), status="success",
                        old_values=audit["old"], new_values=audit["new"],
                        endpoint_or_command=endpoint,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    return result
        except Exception as e:
            await cls._log_void_failure(
                pool, room_id=target_room_id, user_id=user_id,
                entity_type="FINANCE_EXPENSE_VOUCHER", entity_id=str(voucher_id),
                endpoint=endpoint, actor_identifier=actor_identifier,
                client_source=client_source, error=e, start_time=start_time,
            )
            raise

    @classmethod
    async def _void_voucher_locked(
        cls, conn: asyncpg.Connection, *, room_id: int, voucher, reason: str,
        user_id: int, user_name: str,
    ) -> dict:
        voucher_id = int(voucher["id"])
        if voucher["status"] == DOC_STATUS_VOIDED or voucher["voided_at"] is not None:
            raise VoidConflictError("ใบสำคัญจ่ายนี้ถูกยกเลิกแล้ว")

        lines = await conn.fetch(
            """SELECT id, line_no, amount, wallet_account_id, description
               FROM finance_expense_lines
               WHERE voucher_id = $1
               ORDER BY line_no, id""",
            voucher_id,
        )
        if not lines:
            raise VoidConflictError("ใบสำคัญจ่ายนี้ไม่มีบรรทัดให้ย้อนกลับ")

        # 🔒 ล็อกกระเป๋าทุกใบ **ตาม id เรียงขึ้น** (ท่าเดียวกับตอนสร้าง)
        account_ids = sorted({int(ln["wallet_account_id"]) for ln in lines})
        locked = await conn.fetch(
            """SELECT id FROM finance_accounts
               WHERE id = ANY($1::int[]) AND room_id = $2
               ORDER BY id FOR UPDATE""",
            account_ids, room_id,
        )
        if len(locked) != len(account_ids):
            raise RoomNotFoundError("ไม่พบกระเป๋าเงินของใบสำคัญจ่ายนี้")

        # 💰 คืนทุกกระเป๋า — กระเป๋าเดียวกันหลายบรรทัด = หลาย UPDATE (ยอดรวมกลับครบ)
        accounts: Dict[int, float] = {}
        for ln in lines:
            amount = _money(ln["amount"])
            account_id = int(ln["wallet_account_id"])
            await conn.execute(
                "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
                amount, account_id,
            )
            accounts[account_id] = round(
                accounts.get(account_id, 0.0) + amount, 2
            )

        # 🗑️ soft-delete transactions ของ voucher
        await conn.execute(
            """UPDATE finance_transactions SET deleted_at = NOW()
               WHERE room_id = $1 AND expense_voucher_id = $2 AND deleted_at IS NULL""",
            room_id, voucher_id,
        )

        # 🚫 void journal ทุกใบ (1 ใบต่อบรรทัด — ผูกด้วย metadata.expense_voucher_id)
        await conn.execute(
            """UPDATE journal_entries
               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                 AND metadata->>'expense_voucher_id' = $2""",
            room_id, str(voucher_id),
        )

        # 🧾 void CERT ก่อน แล้ว void PV — ทั้งคู่ในการยิงรูปแบบเดียวกัน
        voided_docs = await cls._void_receipt_ids_locked(
            conn, room_id=room_id,
            receipt_ids=[voucher["cert_receipt_id"]],
            reason=f"ยกเลิกพร้อมใบสำคัญจ่าย #{voucher_id}: {reason}",
            user_id=user_id,
        )
        voided_docs += await cls._void_receipt_ids_locked(
            conn, room_id=room_id,
            receipt_ids=[voucher["pv_receipt_id"]],
            reason=reason, user_id=user_id,
        )

        voided_at = await conn.fetchval(
            """UPDATE finance_expense_vouchers
               SET status = $1, voided_at = CURRENT_TIMESTAMP, voided_by = $2,
                   void_reason = $3
               WHERE id = $4 AND room_id = $5
               RETURNING voided_at""",
            DOC_STATUS_VOIDED, user_id, reason, voucher_id, room_id,
        )

        pv_receipt_no = next(
            (row["receipt_no"] for row in voided_docs
             if row["doc_type"] == "payment_voucher"),
            None,
        )
        result = _void_result(
            doc_type="expense_voucher", doc_id=voucher_id, receipt_no=pv_receipt_no,
            voided_at=voided_at, amount=_money(voucher["total_amount"]),
            paid_amount_delta=0.0, credit_restored=0.0, accounts=accounts,
            message="ยกเลิกใบสำคัญจ่ายแล้ว",
        )
        result["audit"] = {
            "old": {
                "status": DOC_STATUS_ACTIVE,
                "total_amount": _money(voucher["total_amount"]),
                "line_count": len(lines),
                "pv_receipt_id": voucher["pv_receipt_id"],
                "cert_receipt_id": voucher["cert_receipt_id"],
            },
            "new": {
                "status": DOC_STATUS_VOIDED,
                "void_reason": reason,
                "amount_reversed": _money(voucher["total_amount"]),
                "accounts": _account_rows(accounts),
                "voided_documents": [row["receipt_no"] for row in voided_docs],
            },
        }
        return result

    # ═════════════════════════════════════════════════════════════════════
    # 3) ยกเลิกใบรับเงิน (INC) — ต้องมีเงินในกระเป๋าพอคืน
    # ═════════════════════════════════════════════════════════════════════
    @classmethod
    async def void_income_batch(
        cls, pool: asyncpg.Pool, *, batch_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิกใบรับเงินรายรับอื่น (MANAGE_FINANCE) — กันยอดกระเป๋าติดลบ"""
        start_time = time.time()
        target_room_id = room_id
        endpoint = "POST /finance/income-batches/{id}/void"
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    reason = _require_reason(getattr(req, "reason", None))
                    await _lock_room_money(conn, target_room_id)

                    batch = await conn.fetchrow(
                        """SELECT * FROM finance_income_batches
                           WHERE id = $1 AND room_id = $2 FOR UPDATE""",
                        batch_id, target_room_id,
                    )
                    if batch is None:
                        raise IncomeBatchNotFoundError("ไม่พบใบรับเงินนี้")

                    user_name = await cls._resolve_actor_name(conn, user_id)
                    result = await cls._void_income_locked(
                        conn, room_id=target_room_id, batch=batch,
                        reason=reason, user_id=user_id, user_name=user_name,
                    )
                    audit = result.pop("audit")

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_INCOME_BATCH",
                        entity_id=str(batch_id), status="success",
                        old_values=audit["old"], new_values=audit["new"],
                        endpoint_or_command=endpoint,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    return result
        except Exception as e:
            await cls._log_void_failure(
                pool, room_id=target_room_id, user_id=user_id,
                entity_type="FINANCE_INCOME_BATCH", entity_id=str(batch_id),
                endpoint=endpoint, actor_identifier=actor_identifier,
                client_source=client_source, error=e, start_time=start_time,
            )
            raise

    @classmethod
    async def _void_income_locked(
        cls, conn: asyncpg.Connection, *, room_id: int, batch, reason: str,
        user_id: int, user_name: str,
    ) -> dict:
        batch_id = int(batch["id"])
        if batch["status"] == DOC_STATUS_VOIDED or batch["voided_at"] is not None:
            raise VoidConflictError("ใบรับเงินนี้ถูกยกเลิกแล้ว")

        lines = await conn.fetch(
            """SELECT id, line_no, amount FROM finance_income_lines
               WHERE batch_id = $1 ORDER BY line_no, id""",
            batch_id,
        )
        if not lines:
            raise VoidConflictError("ใบรับเงินนี้ไม่มีบรรทัดให้ย้อนกลับ")

        total = _money(batch["total_amount"])

        # 🔒 ล็อกกระเป๋าของ batch + guard ยอดพอคืน (ตารางไม่มี CHECK กันติดลบ)
        wallet = await conn.fetchrow(
            """SELECT id, balance FROM finance_accounts
               WHERE id = $1 AND room_id = $2 FOR UPDATE""",
            batch["wallet_account_id"], room_id,
        )
        if wallet is None:
            raise RoomNotFoundError("ไม่พบกระเป๋าเงินของใบรับเงินนี้")
        balance = _money(wallet["balance"])
        if balance + _EPS < total:
            raise VoidConflictError(
                f"เงินในกระเป๋าเหลือ {balance:,.2f} บาท "
                f"ไม่พอคืน {total:,.2f} บาท"
            )

        await conn.execute(
            "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
            total, batch["wallet_account_id"],
        )
        wallet_id = int(batch["wallet_account_id"])
        accounts = {wallet_id: round(-total, 2)}

        await conn.execute(
            """UPDATE finance_transactions SET deleted_at = NOW()
               WHERE room_id = $1 AND income_batch_id = $2 AND deleted_at IS NULL""",
            room_id, batch_id,
        )
        await conn.execute(
            """UPDATE journal_entries
               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                 AND metadata->>'income_batch_id' = $2""",
            room_id, str(batch_id),
        )

        voided_docs = await cls._void_receipt_ids_locked(
            conn, room_id=room_id, receipt_ids=[batch["inc_receipt_id"]],
            reason=f"ยกเลิกพร้อมใบรับเงิน #{batch_id}: {reason}", user_id=user_id,
        )

        # ⚠️ `finance_income_batches` **ไม่มีคอลัมน์ `voided_by`** (ต่างจาก PV/event)
        voided_at = await conn.fetchval(
            """UPDATE finance_income_batches
               SET status = $1, voided_at = CURRENT_TIMESTAMP, void_reason = $2
               WHERE id = $3 AND room_id = $4
               RETURNING voided_at""",
            DOC_STATUS_VOIDED, reason, batch_id, room_id,
        )

        result = _void_result(
            doc_type="income_batch", doc_id=batch_id,
            receipt_no=next(
                (row["receipt_no"] for row in voided_docs
                 if row["doc_type"] == "income"),
                None,
            ),
            voided_at=voided_at, amount=total,
            paid_amount_delta=0.0, credit_restored=0.0, accounts=accounts,
            message="ยกเลิกใบรับเงินแล้ว",
        )
        result["audit"] = {
            "old": {
                "status": DOC_STATUS_ACTIVE,
                "total_amount": total,
                "line_count": len(lines),
                "inc_receipt_id": batch["inc_receipt_id"],
            },
            "new": {
                "status": DOC_STATUS_VOIDED,
                "void_reason": reason,
                "amount_reversed": total,
                "accounts": _account_rows(accounts),
                "voided_documents": [row["receipt_no"] for row in voided_docs],
            },
        }
        return result

    # ═════════════════════════════════════════════════════════════════════
    # 4) ยกเลิกเอกสารตาม doc_type (dispatch) — INV/CERT + กันข้ามเจ้าของ
    # ═════════════════════════════════════════════════════════════════════
    @classmethod
    async def void_document(
        cls, pool: asyncpg.Pool, *, doc_type: str, doc_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """`POST /finance/documents/{doc_type}/{doc_id}/void` — INV/CERT + กันข้ามเจ้าของ"""
        start_time = time.time()
        target_room_id = room_id
        endpoint = "POST /finance/documents/{doc_type}/{doc_id}/void"
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    reason = _require_reason(getattr(req, "reason", None))
                    await _lock_room_money(conn, target_room_id)

                    user_name = await cls._resolve_actor_name(conn, user_id)
                    result = await cls._void_receipt_doc_locked(
                        conn, room_id=target_room_id, doc_type=doc_type,
                        doc_id=doc_id, reason=reason, user_id=user_id,
                        user_name=user_name,
                    )
                    audit = result.pop("audit")

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_DOCUMENT",
                        entity_id=f"{doc_type}:{doc_id}", status="success",
                        old_values=audit["old"], new_values=audit["new"],
                        endpoint_or_command=endpoint,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    return result
        except Exception as e:
            await cls._log_void_failure(
                pool, room_id=target_room_id, user_id=user_id,
                entity_type="FINANCE_DOCUMENT", entity_id=f"{doc_type}:{doc_id}",
                endpoint=endpoint, actor_identifier=actor_identifier,
                client_source=client_source, error=e, start_time=start_time,
            )
            raise

    @classmethod
    async def _void_receipt_doc_locked(
        cls, conn: asyncpg.Connection, *, room_id: int, doc_type: str, doc_id: int,
        reason: str, user_id: int, user_name: str,
    ) -> dict:
        """dispatch ตามชนิดเอกสาร — เอกสารที่แตะเงินต้องยกเลิกผ่านเส้นทางของมันเอง"""
        # 🚫 ชนิดที่มีเจ้าของเส้นทาง void เฉพาะ — ปฏิเสธพร้อมชี้ทาง
        if doc_type == DOC_TYPE_CERTIFICATE:
            raise VoidConflictError(
                "ใบรับรองแทนใบเสร็จยกเลิกเดี่ยวไม่ได้ — "
                "ต้องยกเลิกพร้อมใบสำคัญจ่าย (PV) ที่ออกคู่กัน"
            )
        if doc_type == DOC_TYPE_ACKNOWLEDGEMENT:
            raise VoidConflictError(
                "ใบรับทราบยอดค้างยกเลิกผ่าน "
                "POST /finance/acknowledgements/{receipt_no}/void"
            )
        if doc_type == DOC_TYPE_MONTHLY_REPORT:
            raise VoidConflictError(
                "รายงานปิดงบยกเลิกผ่าน POST /finance/monthly-reports/{id}/void"
            )
        if doc_type not in (DOC_TYPE_INVOICE, DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT):
            raise ValueError(f"ไม่รองรับการยกเลิกเอกสารชนิด '{doc_type}'")

        row = await conn.fetchrow(
            """SELECT id, receipt_no, doc_type, status, deleted_at, payment_event_id
               FROM finance_receipts
               WHERE room_id = $1 AND id = $2 AND doc_type = $3
               FOR UPDATE""",
            room_id, doc_id, doc_type,
        )
        if row is None:
            raise RoomNotFoundError("ไม่พบเอกสารเลขที่นี้")
        if row["status"] == DOC_STATUS_VOIDED or row["deleted_at"] is not None:
            raise VoidConflictError("เอกสารนี้ถูกยกเลิกแล้ว")

        if doc_type == DOC_TYPE_INVOICE:
            # 🔗 ถูกอ้างโดยเอกสารอื่น (link ทั่วไป หรือ ACK ที่แจ้งยอดค้างของนักเรียน)
            linked = await conn.fetchval(
                """SELECT 1 FROM finance_document_links
                   WHERE room_id = $1 AND to_doc_type = $2 AND to_doc_id = $3
                   LIMIT 1""",
                room_id, DOC_TYPE_INVOICE, doc_id,
            )
            if linked is None:
                linked = await conn.fetchval(
                    """SELECT 1 FROM finance_ack_entries
                       WHERE room_id = $1 AND invoice_receipt_id = $2
                       LIMIT 1""",
                    room_id, doc_id,
                )
            if linked is not None:
                raise VoidConflictError(
                    "ใบแจ้งหนี้นี้ถูกอ้างโดยเอกสารอื่นแล้ว — "
                    "ยกเลิกเอกสารที่อ้างก่อน"
                )
        elif row["payment_event_id"] is not None:
            # 🧾 REC/DEP ของ event — เงิน/เครดิตต้องกลับพร้อมกันทั้ง event
            raise VoidConflictError(
                "เอกสารนี้เกิดจากรายการรับเงิน — ยกเลิกที่ "
                f"POST /finance/payment-events/{row['payment_event_id']}/void"
            )
        else:
            # legacy layout 1 — การยกเลิกเงินทำที่รายการธุรกรรมเท่านั้น
            raise VoidConflictError(
                "เอกสารรุ่นก่อนยกเลิกผ่านรายการเงินที่ออกเอกสาร (ประวัติการทำรายการ)"
            )

        voided_at = await conn.fetchval(
            """UPDATE finance_receipts
               SET status = $3, voided_at = CURRENT_TIMESTAMP, voided_by = $4,
                   void_reason = $5, deleted_at = NOW()
               WHERE room_id = $1 AND id = $2
               RETURNING voided_at""",
            room_id, doc_id, DOC_STATUS_VOIDED, user_id, reason,
        )

        result = _void_result(
            doc_type=doc_type, doc_id=doc_id, receipt_no=row["receipt_no"],
            voided_at=voided_at, amount=0.0, paid_amount_delta=0.0,
            credit_restored=0.0, accounts={}, message="ยกเลิกเอกสารแล้ว",
        )
        result["audit"] = {
            "old": {"status": DOC_STATUS_ACTIVE, "receipt_no": row["receipt_no"]},
            "new": {
                "status": DOC_STATUS_VOIDED,
                "void_reason": reason,
                "receipt_no": row["receipt_no"],
            },
        }
        return result
