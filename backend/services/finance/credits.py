"""[F4] เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน

═══════════════════════════════════════════════════════════════════════════════
แนวคิด (ล็อกกับผู้ใช้แล้ว — ห้ามเปลี่ยนโดยไม่ถาม)
═══════════════════════════════════════════════════════════════════════════════
ระบบเดิมเป็นแบบ **"บิลมาก่อน เงินมาทีหลัง"** เท่านั้น (สร้าง fee_collection → ระบบออก
student_payments ให้ทุกคน → ครูกดรับเงิน) ซึ่ง **รับเงินก่อนมีบิลไม่ได้เลย** เพราะ
`_confirm_single_payment` บล็อก overpay ที่ `collections.py:140-144` และไม่มีที่ให้
"เก็บเงินที่ยังไม่มีบิล"

งานนี้เพิ่มทางเข้าที่สอง (ไม่แก้ของเดิมแม้แต่บรรทัดเดียว):

    เติมเครดิต (top-up)   รับเงินก้อนเข้าพักไว้รายคน
                          → Dr สินทรัพย์ / Cr **หนี้สิน 2099**  ⇒ ⚠️ **ยังไม่ใช่รายได้**
    หักเครดิต (apply)     เอาที่พักไว้ไปปิดบิล (ระบบเสนอ → ครูยืนยัน)
                          → Dr หนี้สิน 2099 / Cr **รายได้**       ⇒ รายได้เกิด **ตรงนี้**

🔴 กฎที่ห้ามละเมิด: **ขา "เงินพัก" ต้องเป็น liability/equity ห้ามเป็น revenue**
   ถ้าปล่อยให้ top-up ลง revenue ตรง ๆ รายได้ของห้องจะพองตั้งแต่ยังไม่มีบิล
   และ **ไม่มีอะไรฟ้องเลย** (ยอดยัง Dr=Cr ครบ งบดุลยังดูปกติ) — ดู docs/skills.md

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีตาราง `student_credits` ของตัวเอง
═══════════════════════════════════════════════════════════════════════════════
ขาหนี้สินต้อง "แยกได้รายคน" แต่ `journal_lines` ไม่มี `student_id` (มีแต่ ledger_id)
⇒ ยอดคงเหลือรายคนต้องมีที่เก็บของตัวเอง เป็น **append-only ledger**
(ห้าม UPDATE ยอดเดิม) ⇒ ยอดปัจจุบัน = `balance_after` ของแถวล่าสุด
ไม่ใช่ `SUM()` ที่เพี้ยนได้เมื่อมีรายการ reverse

═══════════════════════════════════════════════════════════════════════════════
เอกสาร (ผู้ใช้เลือกไว้)
═══════════════════════════════════════════════════════════════════════════════
    เติมเครดิต   → ออก **ใบรับเงินล่วงหน้า** `DEP-2569-0001` (หลักฐานการรับเงิน)
    หักปิดบิล    → **ไม่ออกเอกสารใหม่** (บันทึกใน journal + ประวัติเครดิต)
                   ใบ DEP ต้นทางคือหลักฐาน ⇒ ไม่มีปัญหาการกันออกซ้ำของใบเสร็จ
                   ที่ต้องมี `student_payment_id` (ดู `receipts._issue_deposit`)

═══════════════════════════════════════════════════════════════════════════════
เส้นทางที่ **ยังไม่** หักเครดิต (เขียนกำกับไว้ ไม่กลบ — ดูหัวข้อความเสี่ยงในแผน)
═══════════════════════════════════════════════════════════════════════════════
ใบแจ้งหนี้/Excel AR อีก 6 จุดนับ "ยอดค้าง" แบบดิบ (ไม่หักเครดิต) โดยเจตนา —
งานนี้แตะแค่ `get_all_debtors` (เพิ่มฟิลด์ใหม่ ไม่แก้ความหมายฟิลด์เดิม)
"""
import asyncpg
import time
from datetime import datetime
from typing import List, Optional

from core.exceptions import RoomNotFoundError, StudentNotFoundError, PaymentNotFoundError
from core.rbac import require_permission, require_member

from .base import _lock_payments_in_order, _lock_room_money, service_logger
from .constants import (
    CREDIT_ENTRY_APPLY, CREDIT_ENTRY_REVERSE, CREDIT_ENTRY_TOPUP,
    REFERENCE_TYPE_CREDIT_APPLY, REFERENCE_TYPE_CREDIT_TOPUP,
)
from .helpers import _as_utc

# 💰 ยอดที่ "น้อยกว่าหนึ่งสตางค์" ถือว่าไม่มีนัยสำคัญ — ใช้เป็นด่านเดียวกันทั้งไฟล์
#    (ปัดเป็นทศนิยม 2 ตำแหน่งก่อนเทียบเสมอ เพราะ DECIMAL(15,2) เก็บได้แค่นั้น)
_MIN_AMOUNT = 0.01


class CreditsMixin:
    # =================================================================
    # ตัวช่วยอ่าน (ไม่เขียนอะไร) — ใช้ร่วมกันทั้ง plan และ apply
    # =================================================================
    @classmethod
    async def _load_credit_balance(
        cls, conn: asyncpg.Connection, *, room_id: int, student_id: int
    ) -> float:
        """ยอดเครดิตคงเหลือของนักเรียน = `balance_after` ของแถวล่าสุด

        ⚠️ **ห้ามเปลี่ยนไปใช้ `SUM(amount)`** — ตารางนี้เป็น append-only ledger ที่มี
        `reverse` ปนอยู่ ⇒ SUM จะได้ "ยอดตามความเชื่อตอนนี้" ซึ่งไม่ใช่ยอดที่เป็นจริง
        ณ เวลาที่รายการนั้นเกิด และจะเพี้ยนทันทีที่มีการยกเลิก/แก้ย้อนหลัง
        (เหตุผลเต็มอยู่ที่คอมเมนต์ `balance_after` ใน init_db.py)
        """
        bal = await conn.fetchval(
            """SELECT balance_after FROM student_credits
               WHERE room_id = $1 AND student_id = $2 AND deleted_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            room_id, student_id,
        )
        return float(bal) if bal is not None else 0.0

    @classmethod
    async def _load_open_bills(
        cls, conn: asyncpg.Connection, *, room_id: int, student_id: int
    ) -> List[dict]:
        """บิลที่ยังค้างของนักเรียนคนนี้ เรียง "ครบกำหนดก่อน"

        🔴 predicate ต้อง **ตรงกับ `get_all_debtors` (`collections.py:730-737`) เป๊ะ**:
           - กรองด้วย `S.room_id` (ห้องของ **นักเรียน**) ไม่ใช่ `FC.room_id`
           - **ไม่** กรอง `FC.status` / `FC.deleted_at` — เหตุผลเดียวกับที่
             `receipts.py:340-348` อธิบายไว้ (บิลที่ค้างอยู่ต้องโชว์ ไม่ว่าแคมเปญจะถูกปิดไปแล้ว)
           - ใช้ `SP.status = 'pending'`

           ถ้าเผลอเพิ่มเงื่อนไขที่อีกฝั่งไม่มี ยอดที่หักจะ **ไม่ตรงกับยอดที่หน้าลูกหนี้โชว์**
           แล้วผู้ใช้จะเห็น "หักแล้วยังค้างเท่าเดิม" โดยหาสาเหตุไม่ได้
           (มีเทสต์ยิงเทียบสองหน้าตรง ๆ ปิดไว้)
        """
        return await conn.fetch(
            """SELECT SP.id AS payment_id, SP.paid_amount AS paid_amount,
                      FC.id AS collection_id, FC.title, FC.amount AS total_amount,
                      FC.due_date
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               JOIN students S ON S.id = SP.student_id
               WHERE S.room_id = $2 AND SP.student_id = $1 AND SP.status = 'pending'
               ORDER BY FC.due_date ASC NULLS LAST, FC.id ASC""",
            student_id, room_id,
        )

    @classmethod
    def _build_plan(cls, *, balance: float, bills: List[dict]) -> dict:
        """จัดสรรเครดิตแบบ greedy "บิลครบกำหนดก่อน" — **อ่านล้วน ไม่แตะ DB**

        คืนข้อเสนอที่ frontend เอาไปโชว์ให้ครูยืนยัน ก่อนจะเรียก `apply_credit`
        (ผู้ใช้เลือกไว้ว่า "ระบบเสนอ → ครูยืนยัน" ไม่ใช่หักเองเงียบ ๆ)

        ⚠️ ทุกยอดปัดเป็นทศนิยม 2 ตำแหน่ง **ทุกก้าว** ไม่ใช่แค่ตอนจบ — มิฉะนั้น
        เศษทศนิยมจะสะสมข้ามบิลแล้วยอดรวมไม่เท่ากับยอดที่หักจริง (ผลต่าง 1 สตางค์
        ที่ตรวจสอบไม่ได้คือความผิดพลาดที่แพงที่สุดในระบบการเงิน)
        """
        remaining = round(float(balance), 2)
        allocations: List[dict] = []
        for b in bills:
            total = round(float(b["total_amount"]), 2)
            paid = round(float(b["paid_amount"]), 2)
            bill_remaining = round(total - paid, 2)
            if bill_remaining <= 0:
                # บิลที่จ่ายครบแล้วแต่สถานะยัง pending (ข้อมูลผิดปกติ) — ข้ามไป ไม่ทำให้พัง
                continue
            pay = round(min(remaining, bill_remaining), 2)
            if pay < _MIN_AMOUNT:
                break  # เครดิตหมดแล้ว — บิลที่เหลือ (ซึ่งครบกำหนดทีหลัง) ไม่ต้องดูต่อ
            allocations.append({
                "payment_id": b["payment_id"],
                "collection_id": b["collection_id"],
                "title": b["title"],
                "due_date": b["due_date"],
                "bill_total": total,
                "bill_paid_before": paid,
                "bill_remaining_before": bill_remaining,
                "apply_amount": pay,
                "bill_paid_after": round(paid + pay, 2),
                "bill_status_after": (
                    "paid" if round(paid + pay, 2) >= total else "pending"
                ),
                "remaining_after": round(remaining - pay, 2),
            })
            remaining = round(remaining - pay, 2)
        total_applied = round(sum(a["apply_amount"] for a in allocations), 2)
        return {
            "balance_before": round(float(balance), 2),
            "allocations": allocations,
            "total_applied": total_applied,
            "balance_after": round(float(balance) - total_applied, 2),
        }

    @staticmethod
    def _shape_credit_entry(row) -> dict:
        """แถว `student_credits` → dict (cast Decimal → float ตามกฎ CLAUDE.md)"""
        d = dict(row)
        for k in ("amount", "balance_after"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        d["entry_type_label"] = {
            CREDIT_ENTRY_TOPUP: "เติมเงินล่วงหน้า",
            CREDIT_ENTRY_APPLY: "หักปิดบิล",
            CREDIT_ENTRY_REVERSE: "ยกเลิกการหัก",
        }.get(d.get("entry_type"), d.get("entry_type"))
        return d

    # =================================================================
    # 4.1 เติมเครดิต
    # =================================================================
    @classmethod
    async def top_up_credit(
        cls, pool: asyncpg.Pool, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """รับเงินก้อนเข้าพักเป็นเครดิตของนักเรียน 1 คน → ออกใบรับเงินล่วงหน้า (DEP)

        🔑 **idempotency มาจาก `idempotency_key` ที่ client ส่งมา** ไม่ใช่จากเลขที่เอกสาร:
           การเติมเครดิต 1 ครั้งสร้างแถวใหม่ใน `finance_transactions` ⇒
           `idx_finance_receipts_deposit_active` (ที่คีย์ด้วย legacy_transaction_id)
           **กันการกดซ้ำให้ไม่ได้เลย** เพราะคนละ transaction ⇒ ต้องมีคีย์จาก client
           (ดูเหตุผลเต็มที่ `idx_student_credits_idem` ใน init_db.py)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                try:
                    async with conn.transaction():
                        target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                        # 🛡️ RBAC: เฉพาะผู้ดูแลการเงินเท่านั้นที่รับเงินได้ (เหมือน confirm_payment)
                        await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                        # 🔒 ล็อกห้องเป็นคำสั่งแรกก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ)
                        await _lock_room_money(conn, target_room_id)

                        result = await cls._top_up_credit_locked(
                            conn, target_room_id=target_room_id, req=req, user_id=user_id,
                        )

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="CREATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id, user_id=user_id,
                            entity_type="STUDENT_CREDIT", entity_id=str(result["credit_entry_id"]),
                            status="success",
                            new_values={
                                "student_id": result["student_id"],
                                "amount": result["amount"],
                                "balance_after": result["balance_after"],
                                "receipt_no": result.get("receipt_no"),
                                "reused": result.get("reused", False),
                            },
                            endpoint_or_command="FinanceService.top_up_credit",
                            execution_time_ms=exec_time,
                        )
                except asyncpg.UniqueViolationError:
                    # 🔁 กดบันทึกซ้ำด้วยคีย์เดิม (double-click / retry หลัง timeout):
                    #    transaction ทั้งก้อนถูก rollback ไปแล้ว (เงินไม่เข้า 2 รอบ เลข DEP
                    #    ไม่ถูกกิน) ⇒ ตามหา "ผลลัพธ์ที่ชนะ" ด้วยคีย์เดิมแล้วคืนกลับ
                    #    เหมือนเป็นคำขอเดียวกัน — ไม่ใช่ error เพราะผู้ใช้ไม่ได้ทำอะไรผิด
                    #
                    # ⚠️ ต้องดัก **นอก** `async with conn.transaction()`: หลัง UniqueViolation
                    #    transaction อยู่ในสภาพ abort แล้ว คำสั่งถัดไปจะล้มด้วย
                    #    InFailedSQLTransactionError ถ้ายิงต่อในบล็อกเดิม
                    key = cls._normalize_idempotency_key(req)
                    winner_credit_id = await conn.fetchval(
                        """SELECT id FROM student_credits
                           WHERE room_id = $1 AND idempotency_key = $2 AND deleted_at IS NULL
                           ORDER BY id LIMIT 1""",
                        target_room_id, key,
                    )
                    if winner_credit_id is None:
                        # ไม่ใช่การกดซ้ำ — เป็น unique อื่น (เช่นเลขเอกสารชนกัน) ⇒ ให้ error ขึ้นตามปกติ
                        raise
                    result = await cls._load_topup_result(
                        conn, room_id=target_room_id, credit_entry_id=winner_credit_id,
                    )
                    result["reused"] = True

            return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_CREDIT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.top_up_credit",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @staticmethod
    def _normalize_idempotency_key(req) -> str:
        """🔑 คีย์กันส่งซ้ำ — **บังคับต้องมี** (ไม่ปล่อยว่างแล้วเงียบ ๆ)

        ⚠️ ทำไมต้อง raise แทนที่จะยอมให้เป็น NULL: index `idx_student_credits_idem`
           กรอง `WHERE idempotency_key IS NOT NULL` เพื่อกัน NULL หลายแถวในห้องเดียว
           (Postgres ถือ NULL แต่ละตัวไม่ซ้ำกัน) ⇒ **แถวที่ไม่มีคีย์จะไม่ถูกกันเลย**
           ถ้าเรา "ยอม" ให้ไม่มีคีย์เมื่อ client ลืมส่ง ช่องโหว่จะกลับมาแบบเงียบ ๆ
        """
        key = (getattr(req, "idempotency_key", None) or "").strip()
        if not key:
            raise ValueError(
                "ไม่พบรหัสกันบันทึกซ้ำ (idempotency_key) — "
                "กรุณารีเฟรชหน้าแล้วทำรายการใหม่"
            )
        return key[:64]

    @classmethod
    async def _top_up_credit_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, req, user_id: int,
    ) -> dict:
        """ตัวทำงานจริง — caller ถือ transaction และ `_lock_room_money` มาแล้ว"""
        student_id = int(req.student_id)

        # 💰 ด่านยอดเงิน **ต้องมาก่อนการเขียนทุกอย่าง** (โดยเฉพาะก่อนจองเลขเอกสาร)
        #    ⇒ คำขอที่ยอดไม่ถูกต้องจะไม่กินเลข DEP และไม่ทิ้งแถวขยะไว้ให้ตามลบ
        amount = round(float(req.amount), 2)
        if amount < _MIN_AMOUNT:
            raise ValueError(
                f"ยอดเติมเงินล่วงหน้าต้องมีค่าตั้งแต่ {_MIN_AMOUNT:.2f} บาทขึ้นไป "
                f"(ปัดเป็นสตางค์แล้วได้ {amount:.2f})"
            )

        key = cls._normalize_idempotency_key(req)

        # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน) — กดซ้ำแบบไม่ชนกันเลยก็เจอตรงนี้
        existing_id = await conn.fetchval(
            """SELECT id FROM student_credits
               WHERE room_id = $1 AND idempotency_key = $2 AND deleted_at IS NULL
               ORDER BY id LIMIT 1""",
            target_room_id, key,
        )
        if existing_id is not None:
            result = await cls._load_topup_result(
                conn, room_id=target_room_id, credit_entry_id=existing_id,
            )
            result["reused"] = True
            return result

        # 👤 ตรวจนักเรียน: ต้องเป็นของห้องนี้ ยังไม่ถูกลบ และยัง active
        student = await conn.fetchrow(
            """SELECT S.id, S.student_no, U.first_name, U.nickname, U.first_name_en
               FROM students S LEFT JOIN users U ON S.user_id = U.id
               WHERE S.id = $1 AND S.room_id = $2 AND S.deleted_at IS NULL
                 AND S.status = 'active'""",
            student_id, target_room_id,
        )
        if not student:
            raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้อง (หรือพ้นสภาพไปแล้ว)")

        # 🏦 กระเป๋าที่รับเงินต้องเป็นของห้องนี้
        account_id = int(req.paid_to_account_id)
        valid_account = await conn.fetchval(
            "SELECT id FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
            account_id, target_room_id,
        )
        if not valid_account:
            raise ValueError("กระเป๋าเงินไม่มีอยู่ หรือไม่ใช่ของห้องนี้!")

        payer_name = student["first_name"] or student["first_name_en"] or "Unknown"
        if student["nickname"]:
            payer_name += f" ({student['nickname']})"
        description = f"รับเงินล่วงหน้า: {payer_name}"

        # 📝 1) แถว legacy — เงินเข้าจริงในกระเป๋า ⇒ ต้องมีร่องรอยใน "เงินเคลื่อนไหว"
        #
        # 🔴 `category_id = NULL` **โดยเจตนา และห้ามเติมเด็ดขาด**
        #    ถ้าใส่หมวดรายได้ (เช่น '📥 เก็บเงินห้องปกติ') ลงไป:
        #    `budgets.py` clause (ก) (`:456-467`) อ่าน `finance_transactions` โดยกรอง
        #    `category_id = B.category_id AND transaction_type = C.category_type`
        #    และตัว clamp `_LEGACY_LO/_LEGACY_HI` นั้นเป็น **clamp ของ "ช่วงงบ"**
        #    ไม่ใช่ clamp ของ "ยุค" (`budgets.py:64-70`) ⇒ เงินรับล่วงหน้าจะถูกนับเป็น
        #    **การใช้จ่าย/รายรับของงบประมาณทันทีที่รับเงิน** ทั้งที่ยังไม่มีบิล
        #    = รายได้เกิดสองรอบ (ตอนเติม และตอนหักปิดบิล) โดยไม่มีอะไรฟ้อง
        #    💡 NULL จึงไม่ใช่ "ค่า default ที่ขี้เกียจใส่" แต่เป็นด่านความถูกต้องทางบัญชี
        row = await conn.fetchrow(
            """INSERT INTO finance_transactions
                   (room_id, account_id, category_id, amount, description,
                    transaction_type, slip_image_url, recorded_by, student_payment_id)
               VALUES ($1, $2, NULL, $3, $4, 'income', $5, $6, NULL)
               RETURNING id, created_at""",
            target_room_id, account_id, amount, description,
            req.slip_image_url, req.user_name or "—",
        )
        trans_id = row["id"]
        # ⏱️ `finance_transactions.created_at` เป็น TIMESTAMP naive ที่เก็บ **เวลา UTC**
        #    ⇒ ต้องติดป้าย UTC ก่อน (ห้าม astimezone กับค่า naive ตรง ๆ — ดู helpers.py)
        event_at = _as_utc(row["created_at"])

        # 💵 2) ยอดกระเป๋า (ระบบ legacy ยังใช้คอลัมน์นี้เป็นแหล่งความจริง)
        await conn.execute(
            "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
            amount, account_id,
        )

        # 📚 3) journal — **Dr สินทรัพย์ / Cr หนี้สิน 2099** (ไม่ใช่ revenue!)
        asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, account_id)
        advance_ledger_id = await cls._resolve_advance_ledger(conn, room_id=target_room_id)
        journal_entry_id = await cls._insert_journal_entry(
            conn, target_room_id,
            reference_type=REFERENCE_TYPE_CREDIT_TOPUP,
            reference_id=str(student_id),
            description=description,
            slip_image_url=req.slip_image_url,
            recorded_by=req.user_name or "—",
            metadata={"legacy_transaction_id": trans_id, "student_id": student_id},
            lines=[
                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"รับเงินล่วงหน้าจาก {payer_name}"},
                {"ledger_id": advance_ledger_id, "debit": 0, "credit": amount,
                 "line_description": "เงินรับล่วงหน้า (ยังไม่ใช่รายได้ — รอหักปิดบิล)"},
            ],
        )

        # 📒 4) แถวเครดิต — **คำสั่งนี้คือด่านกันซ้ำตัวจริง** (unique index ยิงที่นี่)
        balance_before = await cls._load_credit_balance(
            conn, room_id=target_room_id, student_id=student_id
        )
        balance_after = round(balance_before + amount, 2)
        credit_entry_id = await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after,
                    finance_transaction_id, journal_entry_id, note, recorded_by,
                    idempotency_key)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING id""",
            target_room_id, student_id, CREDIT_ENTRY_TOPUP, amount, balance_after,
            trans_id, journal_entry_id, req.note, req.user_name or "—", key,
        )

        # 🧾 5) ใบรับเงินล่วงหน้า (DEP) — หลักฐานการรับเงินชิ้นเดียวที่ผู้ใช้จะได้
        issued_at = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        deposit = await cls._issue_deposit(
            conn, target_room_id, student_id, trans_id, amount, user_id,
            req.user_name or "—", req.note, event_at_db=event_at, issued_at_db=issued_at,
        )

        return {
            "status": "success",
            "message": (
                f"รับเงินล่วงหน้า {amount:,.2f} บาท จาก {payer_name} "
                f"(เครดิตคงเหลือ {balance_after:,.2f} บาท) — "
                f"ออกใบรับเงินล่วงหน้า {deposit['receipt']['receipt_no']} แล้ว"
            ),
            "credit_entry_id": credit_entry_id,
            "student_id": student_id,
            "student_name": payer_name,
            "amount": amount,
            "balance_after": balance_after,
            "finance_transaction_id": trans_id,
            "journal_entry_id": str(journal_entry_id),
            "receipt": deposit["receipt"],
            "receipt_reused": deposit["reused"],
            "reused": False,
        }

    @classmethod
    async def _load_topup_result(
        cls, conn: asyncpg.Connection, *, room_id: int, credit_entry_id: int,
    ) -> dict:
        """ประกอบผลลัพธ์ของ "การเติมเครดิตที่สำเร็จไปแล้ว" กลับมา (สำหรับเส้นทางกดซ้ำ)"""
        row = await conn.fetchrow(
            """SELECT SC.id, SC.student_id, SC.amount, SC.balance_after,
                      SC.finance_transaction_id, SC.journal_entry_id,
                      U.first_name, U.nickname, U.first_name_en
               FROM student_credits SC
               LEFT JOIN students S ON S.id = SC.student_id
               LEFT JOIN users U ON U.id = S.user_id
               WHERE SC.id = $1 AND SC.room_id = $2 AND SC.deleted_at IS NULL""",
            credit_entry_id, room_id,
        )
        if not row:
            # คีย์ชนะการแข่งขันแต่แถวหายไปแล้ว (ถูกลบระหว่างนั้น) — ให้ผู้ใช้ลองใหม่
            # ดีกว่าเดาว่าอะไรเกิดขึ้น
            raise ValueError("ไม่พบรายการเติมเครดิตที่บันทึกไว้ กรุณาทำรายการใหม่")
        name = row["first_name"] or row["first_name_en"] or "Unknown"
        if row["nickname"]:
            name += f" ({row['nickname']})"
        # 🧾 ดึงใบ DEP เดิมด้วย "ตัวค้นเดียวกับที่ `_issue_deposit` ใช้กันซ้ำ"
        #    ⇒ เส้นทางกดซ้ำกับการออกเอกสารปกติไม่มีทางเห็น "ใบคนละใบ" กัน
        deposit = (
            await cls._find_existing_deposit(conn, row["finance_transaction_id"])
            if row["finance_transaction_id"] else None
        )
        receipt = cls._shape_receipt(deposit) if deposit else None
        return {
            "status": "success",
            "message": (
                f"รายการนี้ถูกบันทึกไว้แล้ว (กดซ้ำ) — เครดิตคงเหลือ "
                f"{float(row['balance_after']):,.2f} บาท ไม่ได้ถูกเพิ่มเป็นรอบที่สอง"
            ),
            "credit_entry_id": row["id"],
            "student_id": row["student_id"],
            "student_name": name,
            "amount": float(row["amount"]),
            "balance_after": float(row["balance_after"]),
            "finance_transaction_id": row["finance_transaction_id"],
            "journal_entry_id": str(row["journal_entry_id"]) if row["journal_entry_id"] else None,
            "receipt": receipt,
            "receipt_reused": True,
        }

    # =================================================================
    # 4.2 หักเครดิตปิดบิล
    # =================================================================
    @classmethod
    async def plan_credit_application(
        cls, pool: asyncpg.Pool, student_ids: List[int], client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> dict:
        """**อ่านล้วน** — ข้อเสนอว่าจะหักบิลไหน เท่าไร เหลือเท่าไร (ให้ครูยืนยันก่อน)

        ⚠️ เป็นการอ่าน ⇒ เปิดให้สมาชิกห้องดูได้ (`require_member`) เพื่อความโปร่งใส
           ตรงกับหน้าลูกหนี้ที่สมาชิกดูได้อยู่แล้ว (การหักจริงต้อง MANAGE_FINANCE)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                plan = await cls._build_plan_for_students(
                    conn, target_room_id=target_room_id, student_ids=student_ids,
                )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="STUDENT_CREDIT", status="success",
                    endpoint_or_command="FinanceService.plan_credit_application",
                    execution_time_ms=exec_time,
                )
                return plan
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="STUDENT_CREDIT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.plan_credit_application",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _build_plan_for_students(
        cls, conn: asyncpg.Connection, *, target_room_id: int, student_ids: List[int],
    ) -> dict:
        """ข้อเสนอการหักของนักเรียนหลายคน — ใช้ร่วมโดย plan (อ่าน) และ apply (เขียน)

        🔴 **ต้องเป็นฟังก์ชันเดียวกัน** เพราะสิ่งที่ครูเห็นในหน้าตรวจข้อเสนอกับสิ่งที่
           ระบบลงมือทำจริงต้องเป็นตัวเลขชุดเดียวกันเป๊ะ ถ้าต่างคนต่างคำนวณ วันหนึ่งจะมี
           คนแก้ข้างเดียวแล้ว "จอโชว์หัก 500 แต่ระบบหัก 700" โดยไม่มีอะไรฟ้อง
        """
        unique_ids = list(dict.fromkeys(int(s) for s in student_ids))
        students = await cls._load_students_in_room(
            conn, target_room_id=target_room_id, student_ids=unique_ids,
        )
        items = []
        for sid in unique_ids:
            stu = students.get(sid)
            if stu is None:
                raise StudentNotFoundError(
                    f"ไม่พบนักเรียนรหัส {sid} ในห้องนี้ — ยกเลิกทั้งชุดเพื่อความปลอดภัย"
                )
            balance = await cls._load_credit_balance(
                conn, room_id=target_room_id, student_id=sid
            )
            bills = await cls._load_open_bills(conn, room_id=target_room_id, student_id=sid)
            plan = cls._build_plan(balance=balance, bills=bills)
            plan["student_id"] = sid
            plan["student_no"] = stu["student_no"]
            plan["student_name"] = stu["display_name"]
            items.append(plan)

        return {
            "items": items,
            "total_applied": round(sum(i["total_applied"] for i in items), 2),
            "total_balance_after": round(sum(i["balance_after"] for i in items), 2),
        }

    @classmethod
    async def _load_students_in_room(
        cls, conn: asyncpg.Connection, *, target_room_id: int, student_ids: List[int],
    ) -> dict:
        """{student_id: {...}} ของนักเรียนที่ **อยู่ในห้องนี้จริง** (ที่เหลือ = ไม่พบ)"""
        if not student_ids:
            return {}
        rows = await conn.fetch(
            """SELECT S.id, S.student_no, U.first_name, U.nickname, U.first_name_en
               FROM students S LEFT JOIN users U ON S.user_id = U.id
               WHERE S.room_id = $1 AND S.deleted_at IS NULL AND S.id = ANY($2::int[])""",
            target_room_id, student_ids,
        )
        out = {}
        for r in rows:
            name = r["first_name"] or r["first_name_en"] or "Unknown"
            if r["nickname"]:
                name += f" ({r['nickname']})"
            out[r["id"]] = {
                "student_id": r["id"], "student_no": r["student_no"], "display_name": name,
            }
        return out

    @classmethod
    async def apply_credit(
        cls, pool: asyncpg.Pool, student_ids: List[int], user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_name: str = "—",
    ) -> dict:
        """หักเครดิตไปปิดบิลของนักเรียนที่เลือก — **ทั้งชุด all-or-nothing**

        🔴 **ไม่เขียน `finance_transactions` เลย** — เงินไม่ได้เคลื่อนไหวตอนนี้
           (เข้ามาตั้งแต่ตอนเติมเครดิต) ⇒ ตาราง "เงินเคลื่อนไหว" ไม่ควรมีแถวปลอม
           และถ้าเขียนด้วย `account_id = NULL` จะไปพัง `revert_transaction`
           ที่ทำ `float(curr_bal)` กับ `account_id IS NULL` (`transactions.py:619-622`)

        🔴 **ไม่ออกเอกสารใหม่** (ผู้ใช้เลือก) — ใบ DEP จากตอนเติมคือหลักฐาน
           ⇒ ตัดปัญหาการกันออกซ้ำของใบเสร็จที่ต้องมี `student_payment_id` ทิ้งไปทั้งหมด
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ลำดับการล็อก: ห้อง → บิลทั้งชุดตาม id (เหมือน batch_confirm_payments)
                    await _lock_room_money(conn, target_room_id)

                    # 📋 วางแผนใหม่ **ใต้ล็อก** — ไม่เชื่อตัวเลขที่ client เห็นมาก่อนหน้านี้
                    #    (ระหว่างที่ครูกดยืนยัน อาจมีคนรับเงินบิลเดียวกันไปแล้ว)
                    plan = await cls._build_plan_for_students(
                        conn, target_room_id=target_room_id, student_ids=student_ids,
                    )
                    bill_ids = [
                        a["payment_id"] for i in plan["items"] for a in i["allocations"]
                    ]
                    await _lock_payments_in_order(conn, bill_ids)

                    applied = await cls._apply_plan_locked(
                        conn, target_room_id=target_room_id, plan=plan, user_name=user_name,
                        actor_identifier=actor_identifier, client_source=client_source,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_CREDIT", status="success",
                        new_values={
                            "student_ids": applied["student_ids"],
                            "bills_paid": applied["bills_paid"],
                            "total_applied": applied["total_applied"],
                        },
                        endpoint_or_command="FinanceService.apply_credit",
                        execution_time_ms=exec_time,
                    )
            return applied
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_CREDIT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.apply_credit",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _apply_plan_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, plan: dict, user_name: str,
        actor_identifier: str, client_source: str,
    ) -> dict:
        """ลงมือหักตามข้อเสนอ — caller ถือ transaction + lock ทั้งห้องและบิลมาแล้ว"""
        # 🏦 ขารายได้: ต้องเป็น revenue ledger ที่ผูกกับ **หมวดหมู่จริง**
        #    (`legacy_category_id`) ไม่ใช่ ledger ลอย ๆ — เพราะ `budgets.py` นับรายได้
        #    โดย join `AL.legacy_category_id = B.category_id` ⇒ ถ้าไม่ผูก งบจะไม่เห็นรายได้นี้
        #    ใช้ตัวช่วยเดียวกับ `_confirm_single_payment` เป๊ะ (ดู `_resolve_default_income_ledger`)
        revenue_ledger_id = await cls._resolve_default_income_ledger(conn, target_room_id)
        advance_ledger_id = await cls._resolve_advance_ledger(conn, room_id=target_room_id)

        executed_items: List[dict] = []
        bills_paid = 0
        total_applied = 0.0
        for item in plan["items"]:
            student_id = item["student_id"]
            if not item["allocations"]:
                continue  # ไม่มีเครดิต หรือไม่มีบิลค้าง — ไม่ใช่ความผิดพลาด

            # 🔁 อ่านยอดเครดิตซ้ำใต้ล็อก **ก่อน** หัก (ยอดที่ plan อ่านมาก่อนหน้านี้
            #    อาจถูกเปลี่ยนโดยคำขออื่นที่แทรกเข้ามา — ตอนนี้ถูกล็อกห้องแล้วจึงนิ่ง)
            balance = await cls._load_credit_balance(
                conn, room_id=target_room_id, student_id=student_id
            )
            running = round(balance, 2)
            executed_allocs: List[dict] = []

            for alloc in item["allocations"]:
                pay = round(min(running, alloc["apply_amount"]), 2)
                if pay < _MIN_AMOUNT:
                    break
                payment_id = alloc["payment_id"]

                # 🔒 อ่านบิลซ้ำใต้ล็อก (ได้ FOR UPDATE แล้วจาก `_lock_payments_in_order`)
                #    ⇒ ยอดที่ใช้ตัดสินใจคือยอด ณ วินาทีนี้ ไม่ใช่ยอดที่อ่านมาก่อนหน้า
                sp = await conn.fetchrow(
                    """SELECT SP.paid_amount, FC.amount AS total_amount, FC.title, FC.id AS collection_id
                       FROM student_payments SP
                       JOIN fee_collections FC ON SP.collection_id = FC.id
                       WHERE SP.id = $1""",
                    payment_id,
                )
                if not sp:
                    raise PaymentNotFoundError(f"ไม่พบรายการชำระเงิน #{payment_id}")
                bill_total = round(float(sp["total_amount"]), 2)
                bill_paid_before = round(float(sp["paid_amount"]), 2)
                bill_remaining = round(bill_total - bill_paid_before, 2)
                if bill_remaining <= 0:
                    continue  # มีคนรับเงินบิลนี้ไปแล้วระหว่างนั้น
                pay = round(min(pay, bill_remaining), 2)
                if pay < _MIN_AMOUNT:
                    continue
                bill_paid_after = round(bill_paid_before + pay, 2)
                new_status = "paid" if bill_paid_after >= bill_total else "pending"
                remaining_after = round(running - pay, 2)

                # 📒 journal — Dr หนี้สิน 2099 / Cr รายได้  ⬅️ **รายได้เกิดที่นี่ที่เดียว**
                journal_entry_id = await cls._insert_journal_entry(
                    conn, target_room_id,
                    reference_type=REFERENCE_TYPE_CREDIT_APPLY,
                    reference_id=str(payment_id),
                    description=f"หักเงินรับล่วงหน้าปิดบิล: {sp['title']}",
                    recorded_by=user_name,
                    metadata={"student_credit_apply": True, "student_id": student_id},
                    lines=[
                        {"ledger_id": advance_ledger_id, "debit": pay, "credit": 0,
                         "line_description": "หักเงินรับล่วงหน้าไปปิดบิล"},
                        {"ledger_id": revenue_ledger_id, "debit": 0, "credit": pay,
                         "line_description": f"รายได้: {sp['title']}"},
                    ],
                )

                # 💳 ปิดบิล — `paid_to_account_id`/`transaction_id` เป็น NULL **โดยเจตนา**:
                #    เงินไม่ได้เข้าจากกระเป๋าใด ๆ ในขั้นนี้ (เข้ามาตั้งแต่ตอนเติมเครดิต)
                #    ⇒ NULL คือคำตอบที่ถูกต้อง และเป็นสถานะที่มีอยู่จริงแล้วในระบบ
                #      (`transactions.py:634` เขียน NULL ลงคอลัมน์นี้ตอน revert อยู่แล้ว)
                await conn.execute(
                    """UPDATE student_payments
                       SET paid_amount = $1, status = $2, paid_at = NOW(),
                           recorded_by = $3, paid_to_account_id = NULL, transaction_id = NULL
                       WHERE id = $4""",
                    bill_paid_after, new_status, user_name, payment_id,
                )

                credit_entry_id = await conn.fetchval(
                    """INSERT INTO student_credits
                           (room_id, student_id, entry_type, amount, balance_after,
                            student_payment_id, collection_id, journal_entry_id,
                            note, recorded_by)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                       RETURNING id""",
                    target_room_id, student_id, CREDIT_ENTRY_APPLY, pay, remaining_after,
                    payment_id, sp["collection_id"], journal_entry_id,
                    f"หักปิดบิล: {sp['title']}", user_name,
                )
                # 📋 audit ระดับรายการ (ท่าเดียวกับ `batch_confirm_payments` ที่ log ต่อใบ + ต่อชุด)
                #    ใช้ `actor_identifier`/`client_source` ของ **คำขอจริง** ไม่ใช่ค่าประดิษฐ์ —
                #    audit ที่แยกไม่ได้ว่าใครทำ ถือว่าไม่ใช่ audit
                await service_logger.log(
                    conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="STUDENT_CREDIT", entity_id=str(credit_entry_id),
                    status="success",
                    old_values={
                        "payment_id": payment_id, "paid_amount": bill_paid_before,
                        "status": "pending",
                    },
                    new_values={
                        "payment_id": payment_id, "paid_amount": bill_paid_after,
                        "status": new_status, "applied_from_credit": pay,
                    },
                    endpoint_or_command="FinanceService.apply_credit",
                )

                # 🧾 เก็บใน **รูปร่างเดียวกับข้อเสนอ** (`CreditAllocationItem`) เป๊ะ
                #    ⇒ สิ่งที่ครูเห็นตอนกดยืนยันกับสิ่งที่ระบบรายงานกลับมาต่างกันได้แค่
                #      "ตัวเลขที่แท้จริง ณ วินาทีที่ลงมือ" ไม่ใช่ "คนละรูปร่างข้อมูล"
                executed_allocs.append({
                    "payment_id": payment_id,
                    "collection_id": sp["collection_id"],
                    "title": sp["title"],
                    "due_date": alloc.get("due_date"),
                    "bill_total": bill_total,
                    "bill_paid_before": bill_paid_before,
                    "bill_remaining_before": bill_remaining,
                    "apply_amount": pay,
                    "bill_paid_after": bill_paid_after,
                    "bill_status_after": new_status,
                    "remaining_after": remaining_after,
                })
                running = remaining_after
                bills_paid += 1
                total_applied = round(total_applied + pay, 2)

            executed_items.append({
                "student_id": student_id,
                "student_no": item.get("student_no"),
                "student_name": item.get("student_name"),
                "balance_before": round(balance, 2),
                "allocations": executed_allocs,
                "total_applied": round(sum(a["apply_amount"] for a in executed_allocs), 2),
                "balance_after": running,
            })

        return {
            "status": "success",
            "items": executed_items,
            "student_ids": [i["student_id"] for i in executed_items],
            "bills_paid": bills_paid,
            "total_applied": total_applied,
            # 💡 คิดจาก `plan["items"]` **ทุกคน** (รวมคนที่ไม่มีอะไรถูกหัก ซึ่งยอดไม่เปลี่ยน)
            #    ไม่ใช่จาก `executed_items` — มิฉะนั้น "เครดิตคงเหลือรวมหลังทำรายการ"
            #    จะหายคนที่ไม่ได้ถูกแตะไปทั้งกลุ่ม แล้วผู้ใช้จะอ่านว่าระบบกินเครดิตไปเฉย ๆ
            "total_balance_after": round(
                sum(i["balance_after"] for i in plan["items"]), 2
            ),
            "message": (
                f"หักเครดิตปิดบิลสำเร็จ {bills_paid} รายการ "
                f"รวม {total_applied:,.2f} บาท"
                if bills_paid else "ไม่มีบิลที่ต้องหัก (เครดิตหมดหรือไม่มีบิลค้าง)"
            ),
        }

    # =================================================================
    # 4.4 ยกเลิกการหัก
    # =================================================================
    @classmethod
    async def undo_credit_application(
        cls, pool: asyncpg.Pool, credit_entry_id: int, user_id: int, client_source: str,
        actor_identifier: str, reason: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_name: str = "—",
    ) -> dict:
        """ยกเลิก "การหักเครดิต 1 รายการ" → คืนเครดิต + คืนสถานะบิล + void journal

        ⚠️ **ไม่แตะ `finance_transactions` และไม่แตะยอดกระเป๋า** — การหักไม่เคยแตะทั้งคู่
           ⇒ การยกเลิกก็ต้องไม่แตะ (ถ้าเผลอปรับกระเป๋าที่นี่ เงินจะงอกขึ้นมาจากอากาศ)

        ⚠️ ยกเลิกได้เฉพาะแถว `entry_type='apply'` และยกเลิกซ้ำไม่ได้ (แถวที่ถูกยกเลิก
           ไปแล้วจะถูก soft delete ⇒ หาไม่เจอในคำขอถัดไป)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    result = await cls._undo_credit_locked(
                        conn, target_room_id=target_room_id,
                        credit_entry_id=credit_entry_id, reason=reason, user_name=user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_CREDIT", entity_id=str(credit_entry_id),
                        status="success",
                        old_values=result["old_values"], new_values=result["new_values"],
                        endpoint_or_command="FinanceService.undo_credit_application",
                        execution_time_ms=exec_time,
                    )
            return result["response"]
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="STUDENT_CREDIT", entity_id=str(credit_entry_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.undo_credit_application",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _undo_credit_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, credit_entry_id: int,
        reason: Optional[str], user_name: str,
    ) -> dict:
        entry = await conn.fetchrow(
            """SELECT * FROM student_credits
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE""",
            credit_entry_id, target_room_id,
        )
        if not entry:
            raise ValueError("ไม่พบรายการเครดิตนี้ (อาจถูกยกเลิกไปแล้ว)")
        if entry["entry_type"] != CREDIT_ENTRY_APPLY:
            raise ValueError(
                "ยกเลิกได้เฉพาะรายการ 'หักปิดบิล' เท่านั้น — "
                "การเติมเงินล่วงหน้าต้องใช้วิธียกเลิกรายการธุรกรรม (ซึ่งจะยกเลิกใบ DEP ให้ด้วย)"
            )
        if entry["student_payment_id"] is None:
            raise ValueError("รายการนี้ไม่ผูกกับบิล จึงยกเลิกไม่ได้")

        payment_id = entry["student_payment_id"]
        applied = round(float(entry["amount"]), 2)
        # 🔒 ล็อกบิลตามลำดับปกติก่อนแก้
        await _lock_payments_in_order(conn, [payment_id])

        sp = await conn.fetchrow(
            """SELECT SP.paid_amount, SP.status, FC.amount AS total_amount, FC.title
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               WHERE SP.id = $1""",
            payment_id,
        )
        if not sp:
            raise PaymentNotFoundError(f"ไม่พบรายการชำระเงิน #{payment_id}")
        old_paid = round(float(sp["paid_amount"]), 2)
        new_paid = round(old_paid - applied, 2)
        if new_paid < 0:
            # ควรเป็นไปไม่ได้: หมายความว่ามีคนไปแก้ paid_amount ตรง ๆ ใน DB
            # ⇒ หยุดดีกว่าเขียนค่าติดลบลงไปแล้วปล่อยให้ยอดเพี้ยนกว่านี้
            raise ValueError(
                f"ยอดที่จ่ายแล้วของบิล ({old_paid:.2f}) น้อยกว่ายอดที่จะคืน ({applied:.2f}) "
                "— ข้อมูลไม่สอดคล้อง กรุณาตรวจสอบก่อน"
            )
        bill_total = round(float(sp["total_amount"]), 2)
        new_status = "paid" if new_paid >= bill_total else "pending"

        # ↩️ คืนสถานะบิล — ถ้ากลับเป็น 0 ให้ล้างร่องรอยการชำระทั้งหมด
        #    (ท่าเดียวกับ `revert_transaction:631-637` เป๊ะ เพื่อไม่ให้เหลือสถานะครึ่ง ๆ กลาง ๆ)
        if new_paid < _MIN_AMOUNT:
            await conn.execute(
                """UPDATE student_payments
                   SET paid_amount = 0, status = 'pending', paid_to_account_id = NULL,
                       slip_image_url = NULL, recorded_by = NULL, paid_at = NULL,
                       transaction_id = NULL
                   WHERE id = $1""",
                payment_id,
            )
        else:
            await conn.execute(
                """UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3""",
                new_paid, new_status, payment_id,
            )

        # 🚫 void journal — **ไม่ลบ** และ **ไม่เขียนรายการกลับทาง** เพราะ convention ของ
        #    repo นี้คือ void + deleted_at (ดู `revert_transaction:645-653`) ⇒ รายงานทุกตัว
        #    ที่กรอง `status <> 'voided' AND deleted_at IS NULL` จะตัดรายได้ก้อนนี้ออกพร้อมกัน
        if entry["journal_entry_id"]:
            await conn.execute(
                """UPDATE journal_entries
                   SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
                   WHERE id = $1 AND room_id = $2
                     AND status <> 'voided' AND deleted_at IS NULL""",
                entry["journal_entry_id"], target_room_id,
            )

        # 🔴 อ่านยอดคงเหลือ **ก่อน** soft delete แถวนี้ — ลำดับตรงนี้สำคัญมาก
        #    `_load_credit_balance` คืน `balance_after` ของแถวล่าสุดที่ยังไม่ถูกลบ ⇒
        #    ถ้าลบก่อน ยอดที่อ่านได้จะเป็น "ยอดที่คืนแล้ว" (เท่ากับยอดก่อนหัก) แล้ว
        #    `+ applied` อีกครั้ง = **คืนเครดิตสองรอบ** (เติม 800 → หัก 800 → ยกเลิก
        #    ได้ 1,600) โดยที่ไม่มีอะไรฟ้อง เพราะทั้งสองค่า "ดูสมเหตุสมผล" ทั้งคู่
        #    ✅ อ่านก่อนลบยังถูกต้องทุกกรณี รวมถึงการยกเลิกแถวที่ **ไม่ใช่** แถวล่าสุด:
        #       ยอดที่อ่านได้คือยอดจริง ณ ปัจจุบัน และแถว reverse ที่ต่อท้ายจะกลายเป็น
        #       แถวล่าสุดตัวใหม่ที่พายอดไปต่อได้ถูกต้อง (800→500→300 แล้ว +300 = 600)
        balance_before = await cls._load_credit_balance(
            conn, room_id=target_room_id, student_id=entry["student_id"]
        )
        balance_after = round(balance_before + applied, 2)

        # 🗑️ soft delete แถวที่ถูกยกเลิก — กัน "ยกเลิกซ้ำ"
        await conn.execute(
            "UPDATE student_credits SET deleted_at = NOW() WHERE id = $1", credit_entry_id,
        )

        # ➕ แถว reverse — เครดิตคืนเข้ากระเป๋านักเรียน (append-only เสมอ)
        reverse_id = await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after,
                    student_payment_id, collection_id, note, recorded_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING id""",
            target_room_id, entry["student_id"], CREDIT_ENTRY_REVERSE, applied, balance_after,
            payment_id, entry["collection_id"],
            reason or f"ยกเลิกการหักปิดบิล: {sp['title']}", user_name,
        )

        return {
            "old_values": {
                "credit_entry_id": credit_entry_id,
                "paid_amount": old_paid,
                "status": sp["status"],
            },
            "new_values": {
                "credit_entry_id": credit_entry_id,
                "reverse_entry_id": reverse_id,
                "paid_amount": new_paid,
                "status": new_status,
                "credit_balance_after": balance_after,
                "voided_journal_entry_id": (
                    str(entry["journal_entry_id"]) if entry["journal_entry_id"] else None
                ),
            },
            "response": {
                "status": "success",
                "credit_entry_id": credit_entry_id,
                "reverse_entry_id": reverse_id,
                "student_id": entry["student_id"],
                "student_payment_id": payment_id,
                "reverted_amount": applied,
                "bill_paid_amount": new_paid,
                "bill_status": new_status,
                "credit_balance_after": balance_after,
                "message": (
                    f"ยกเลิกการหัก {applied:,.2f} บาท เรียบร้อย "
                    f"(เครดิตคงเหลือ {balance_after:,.2f} บาท)"
                ),
            },
        }

    # =================================================================
    # อ่านอย่างเดียว (API)
    # =================================================================
    @classmethod
    async def get_credit_balances(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[dict]:
        """นักเรียนทุกคนของห้อง + ยอดเครดิตคงเหลือ (0 สำหรับคนที่ไม่มี) + ยอดค้างดิบ

        💡 ใช้ `LEFT JOIN` กับ "แถวล่าสุด" ของ `student_credits` ⇒ คนที่ไม่มีเครดิตก็ยัง
           อยู่ในลิสต์ (ยอด 0) เพื่อให้หน้าจอเดียวใช้เติมเครดิตให้ใครก็ได้
           ไม่ต้องมีอีกหน้าจอสำหรับ "คนที่ยังไม่มีเครดิต"
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch(
                    """SELECT S.id AS student_id, S.student_no,
                              U.first_name, U.nickname, U.first_name_en, U.last_name_en,
                              U.nickname_en,
                              COALESCE(SC.balance_after, 0) AS credit_balance,
                              COALESCE(D.pending_amount, 0) AS total_pending_amount
                       FROM students S
                       LEFT JOIN users U ON S.user_id = U.id
                       LEFT JOIN LATERAL (
                           SELECT balance_after FROM student_credits
                           WHERE room_id = S.room_id AND student_id = S.id
                             AND deleted_at IS NULL
                           ORDER BY id DESC LIMIT 1
                       ) SC ON TRUE
                       LEFT JOIN LATERAL (
                           SELECT SUM(FC.amount - SP.paid_amount) AS pending_amount
                           FROM student_payments SP
                           JOIN fee_collections FC ON SP.collection_id = FC.id
                           WHERE SP.student_id = S.id AND SP.status = 'pending'
                       ) D ON TRUE
                       WHERE S.room_id = $1 AND S.status = 'active' AND S.deleted_at IS NULL
                       ORDER BY S.student_no ASC""",
                    target_room_id,
                )
                out = []
                for r in rows:
                    name = r["first_name"] or r["first_name_en"] or "Unknown"
                    if r["nickname"]:
                        name += f" ({r['nickname']})"
                    credit = round(float(r["credit_balance"]), 2)
                    pending = round(float(r["total_pending_amount"]), 2)
                    out.append({
                        "student_id": r["student_id"],
                        "student_no": r["student_no"],
                        "student_name": name,
                        "credit_balance": credit,
                        "total_pending_amount": pending,
                        # 🎯 ยอดที่ต้องเก็บจริงหลังหักเครดิต — ชื่อฟิลด์บอกชัดว่าหักแล้ว
                        #    (ไม่ไปแก้ความหมายของ `total_pending_amount` เดิม เพราะ
                        #     `DebtorList.vue` และบอทใช้ฟิลด์นั้นอยู่)
                        "net_pending_amount": round(max(pending - credit, 0.0), 2),
                    })

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="STUDENT_CREDIT", status="success",
                    endpoint_or_command="FinanceService.get_credit_balances",
                    execution_time_ms=exec_time,
                )
                return out
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="STUDENT_CREDIT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_credit_balances",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_student_credit(
        cls, pool: asyncpg.Pool, student_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> dict:
        """รายละเอียดเครดิตของนักเรียน 1 คน: ยอดคงเหลือ + ประวัติ + บิลค้าง + ข้อเสนอการหัก"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                students = await cls._load_students_in_room(
                    conn, target_room_id=target_room_id, student_ids=[student_id],
                )
                stu = students.get(student_id)
                if stu is None:
                    raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้อง")

                balance = await cls._load_credit_balance(
                    conn, room_id=target_room_id, student_id=student_id
                )
                bills = await cls._load_open_bills(
                    conn, room_id=target_room_id, student_id=student_id
                )
                plan = cls._build_plan(balance=balance, bills=bills)
                # 🔴 `_build_plan` ไม่รู้จักนักเรียน (มันรับแค่ยอดกับบิล) ⇒ ต้องเติมตัวตน
                #    ของเจ้าของแผนเอง ไม่งั้น `StudentCreditDetailResponse.plan`
                #    (ชนิด `CreditPlanItem` ที่บังคับ `student_id`) จะ validation ไม่ผ่าน
                #    ⇒ **500 ทุกครั้งที่เรียก endpoint นี้** ทั้งที่ตัวเลขถูกต้องครบ
                #    ⚠️ ต้องเติมชุดเดียวกับ `_build_plan_for_students:553-555` เป๊ะ
                plan["student_id"] = student_id
                plan["student_no"] = stu["student_no"]
                plan["student_name"] = stu["display_name"]

                entries = await conn.fetch(
                    """SELECT SC.id, SC.entry_type, SC.amount, SC.balance_after,
                              SC.student_payment_id, SC.collection_id, SC.note,
                              SC.recorded_by, SC.created_at, SC.finance_transaction_id,
                              FC.title AS collection_title,
                              R.receipt_no, R.event_at AS receipt_event_at
                       FROM student_credits SC
                       LEFT JOIN fee_collections FC ON FC.id = SC.collection_id
                       LEFT JOIN finance_receipts R
                              ON R.legacy_transaction_id = SC.finance_transaction_id
                             AND R.doc_type = 'deposit' AND R.deleted_at IS NULL
                       WHERE SC.room_id = $1 AND SC.student_id = $2 AND SC.deleted_at IS NULL
                       ORDER BY SC.id DESC""",
                    target_room_id, student_id,
                )
                shaped = []
                for e in entries:
                    d = cls._shape_credit_entry(e)
                    # ⏱️ `created_at` เป็น timestamptz อยู่แล้ว (ตารางนี้ใช้ WITH TIME ZONE)
                    #    แต่ `receipt_event_at` อาจเป็น naive ถ้าคอลัมน์เปลี่ยนชนิดในอนาคต
                    d["created_at"] = _as_utc(d.get("created_at"))
                    d["receipt_event_at"] = _as_utc(d.get("receipt_event_at"))
                    shaped.append(d)

                result = {
                    "student_id": student_id,
                    "student_no": stu["student_no"],
                    "student_name": stu["display_name"],
                    "credit_balance": round(balance, 2),
                    "entries": shaped,
                    "open_bills": [
                        {
                            "payment_id": b["payment_id"],
                            "collection_id": b["collection_id"],
                            "title": b["title"],
                            "due_date": b["due_date"],
                            "total_amount": round(float(b["total_amount"]), 2),
                            "paid_amount": round(float(b["paid_amount"]), 2),
                            "remaining_amount": round(
                                float(b["total_amount"]) - float(b["paid_amount"]), 2
                            ),
                        }
                        for b in bills
                    ],
                    "plan": plan,
                }

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="STUDENT_CREDIT", entity_id=str(student_id), status="success",
                    endpoint_or_command="FinanceService.get_student_credit",
                    execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="STUDENT_CREDIT", entity_id=str(student_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_student_credit",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
