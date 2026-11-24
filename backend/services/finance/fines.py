"""ค่าปรับ (fine core) — ออกบิล/ใบแจ้งหนี้ · แก้ · ยกเลิก · สถานะ

═══════════════════════════════════════════════════════════════════════════════
🧱 รูปแบบข้อมูล
═══════════════════════════════════════════════════════════════════════════════
ค่าปรับ 1 ครั้ง (1 นักเรียน) = 3 แถวที่ต้องเกิดพร้อมกัน:
  1. `fee_collections` โปรเจกต์ซ่อน (`collection_kind='fine'`, 1 คน/แคมเปญ)
  2. `student_payments` บิล 1 ใบ (ใช้ระบบรับเงิน/เครดิตเดิมทั้งชุด)
  3. `fines` โดเมนค่าปรับ (ประเภท/วันที่เกิด/สถานะ/ waiver/refund)

📒 Journal ตามเกณฑ์คงค้าง:
  ออกค่าปรับ       Dr 11002 ผู้ค้างชำระค่าปรับ / Cr 49001 รายได้ค่าปรับ  (ผ่าน AccrualMixin)
  แก้ยอดก่อนจ่าย   ปรับส่วนต่างกับ 49001 (`fine_adjustment`)
  ยกเลิกก่อนจ่าย   Dr 49001 / Cr 11002 (`fine_cancel`)
  ชำระ/เครดิต      ลด AR 11002 — collections.py / credits.py จัดการเอง (`collection_kind`)

🔴 สถานะค่าปรับมีเจ้าของเดียว: `_sync_fine_status` — ห้ามเขียน `fines.status` ตรง ๆ
   จากที่อื่น (การชำระ/เครดิต/revert/waiver/refund เรียกฟังก์ชันนี้ทั้งหมด)
"""
from __future__ import annotations

import time
from typing import List, Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import has_any_permission, require_member, require_permission
from services.action_service import ActionService
from services.notification_service import notify_user

from .base import _lock_room_money, service_logger
from .constants import (
    COLLECTION_KIND_FINE,
    FINE_STATUS_CANCELLED,
    FINE_STATUS_ISSUED,
    FINE_STATUS_PARTIALLY_PAID,
    FINE_STATUS_PAID,
    FINE_STATUS_REFUNDED,
    FINE_STATUS_WAIVED,
    REFERENCE_TYPE_FINE_ADJUSTMENT,
    REFERENCE_TYPE_FINE_CANCEL,
    REQUEST_STATUS_PENDING,
)

# ความคลาดที่เล็กกว่านี้ถือว่าเป็นศูนย์ (สตางค์ครึ่ง) — ใช้ทั้งไฟล์ให้ตรงกัน
_EPS = 0.005

_ACTIVE_INVOICE_JOIN = """
    LEFT JOIN LATERAL (
        SELECT R.id, R.receipt_no
          FROM finance_receipts R
         WHERE R.student_payment_id = SP.id
           AND R.doc_type = 'invoice'
           AND R.status = 'active' AND R.deleted_at IS NULL
         ORDER BY R.id DESC LIMIT 1
    ) INV ON TRUE
"""

_FINE_SELECT = f"""
    SELECT F.id, F.room_id, F.batch_id, F.fine_type_id, F.fine_type_name,
           F.student_id, F.hidden_collection_id, F.student_payment_id,
           F.invoice_receipt_id, F.incident_date, F.due_date, F.reason,
           F.original_amount, F.amount, F.waived_amount, F.refunded_amount,
           F.status, F.evidence_url, F.note, F.created_by, F.created_at,
           COALESCE(SP.paid_amount, 0) AS paid_amount,
           SP.status AS payment_status,
           SP.deleted_at AS payment_deleted_at,
           S.student_no, U.first_name, U.nickname, U.first_name_en,
           U.last_name_en, U.nickname_en,
           INV.receipt_no AS invoice_no
    FROM fines F
    JOIN student_payments SP ON SP.id = F.student_payment_id
    JOIN fee_collections FC ON FC.id = SP.collection_id
    LEFT JOIN students S ON S.id = F.student_id
    LEFT JOIN v_student_profiles U ON U.student_id = F.student_id
    {_ACTIVE_INVOICE_JOIN}
"""


class FinesMixin:
    # =================================================================
    # shape / อ่าน
    # =================================================================
    @staticmethod
    def _student_display_name(row) -> str:
        name = row["first_name"] or row["first_name_en"] or "Unknown"
        if row["nickname"]:
            name += f" ({row['nickname']})"
        return name

    @classmethod
    def _shape_fine(cls, row) -> dict:
        amount = float(row["amount"] or 0)
        paid = float(row["paid_amount"] or 0)
        return {
            "id": row["id"],
            "room_id": row["room_id"],
            "batch_id": row["batch_id"],
            "fine_type_id": row["fine_type_id"],
            "fine_type_name": row["fine_type_name"],
            "student_id": row["student_id"],
            "student_no": row["student_no"],
            "student_name": cls._student_display_name(row),
            "hidden_collection_id": row["hidden_collection_id"],
            "student_payment_id": row["student_payment_id"],
            "invoice_receipt_id": row["invoice_receipt_id"],
            "invoice_no": row["invoice_no"],
            "incident_date": row["incident_date"],
            "due_date": row["due_date"],
            "reason": row["reason"],
            "original_amount": float(row["original_amount"] or 0),
            "amount": amount,
            "waived_amount": float(row["waived_amount"] or 0),
            "refunded_amount": float(row["refunded_amount"] or 0),
            "paid_amount": paid,
            "outstanding": round(max(amount - paid, 0.0), 2),
            "status": row["status"],
            "evidence_url": row["evidence_url"],
            "note": row["note"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "collection_kind": COLLECTION_KIND_FINE,
        }

    @classmethod
    async def _load_fine_row(cls, conn: asyncpg.Connection, fine_id: int, room_id: int):
        return await conn.fetchrow(
            f"{_FINE_SELECT} WHERE F.id = $1 AND F.room_id = $2 AND F.deleted_at IS NULL",
            fine_id, room_id,
        )

    @classmethod
    async def _load_fine_rows_for_batch(cls, conn: asyncpg.Connection, batch_id: int, room_id: int) -> List:
        return await conn.fetch(
            f"{_FINE_SELECT} WHERE F.batch_id = $1 AND F.room_id = $2 AND F.deleted_at IS NULL "
            f"ORDER BY F.id ASC",
            batch_id, room_id,
        )

    # =================================================================
    # สถานะ (single source of truth)
    # =================================================================
    @classmethod
    async def _sync_fine_status(
        cls, conn: asyncpg.Connection, payment_ids: List[int]
    ) -> None:
        """คำนวณ `fines.status` ใหม่จากยอดจริง — เรียกหลังทุกเหตุการณ์ที่แตะยอด

        🚫 ค่าปรับที่ `cancelled` แล้วคงไว้ (ยกเลิกเป็น terminal state — ต้องออกใหม่)
        """
        if not payment_ids:
            return
        rows = await conn.fetch(
            """SELECT F.id, F.status, F.amount, F.waived_amount, F.refunded_amount,
                      COALESCE(SP.paid_amount, 0) AS paid_amount
               FROM fines F
               JOIN student_payments SP ON SP.id = F.student_payment_id
               WHERE F.student_payment_id = ANY($1::int[]) AND F.deleted_at IS NULL""",
            [int(p) for p in payment_ids],
        )
        for r in rows:
            if r["status"] == FINE_STATUS_CANCELLED:
                continue
            amount = float(r["amount"] or 0)
            paid = float(r["paid_amount"] or 0)
            waived = float(r["waived_amount"] or 0)
            refunded = float(r["refunded_amount"] or 0)
            outstanding = round(amount - paid, 2)
            net_paid = round(paid - refunded, 2)

            if outstanding <= _EPS and waived > 0:
                new_status = FINE_STATUS_WAIVED
            elif outstanding <= _EPS and net_paid <= _EPS:
                new_status = FINE_STATUS_REFUNDED
            elif outstanding <= _EPS:
                new_status = FINE_STATUS_PAID
            elif net_paid > _EPS:
                new_status = FINE_STATUS_PARTIALLY_PAID
            else:
                new_status = FINE_STATUS_ISSUED

            if new_status != r["status"]:
                await conn.execute(
                    """UPDATE fines SET status = $1, updated_at = CURRENT_TIMESTAMP
                       WHERE id = $2""",
                    new_status, r["id"],
                )

    @classmethod
    async def _assert_no_pending_fine_requests(
        cls, conn: asyncpg.Connection, payment_ids: List[int]
    ) -> None:
        """🚧 บิลค่าปรับที่มีคำขอ pending ⇒ ห้ามรับชำระ/ใช้เครดิต/แก้/ยกเลิก/ย้อนรายการ

        เหตุผล: คำขอถูกคำนวณจากยอด ณ เวลาขอ — ถ้ามีเงินแทรกแล้วอนุมัติตามยอดเดิม
        ตัวเลข waiver/refund จะไม่ตรงกับบิลจริงแบบหาสาเหตุไม่ได้
        """
        if not payment_ids:
            return
        pending = await conn.fetchval(
            """SELECT 1 FROM fines F
               WHERE F.student_payment_id = ANY($1::int[]) AND F.deleted_at IS NULL
                 AND (
                   EXISTS (SELECT 1 FROM fine_waivers W
                            WHERE W.fine_id = F.id AND W.status = $2 AND W.deleted_at IS NULL)
                   OR EXISTS (SELECT 1 FROM fine_refunds R
                            WHERE R.fine_id = F.id AND R.status = $2 AND R.deleted_at IS NULL)
                 )
               LIMIT 1""",
            [int(p) for p in payment_ids], REQUEST_STATUS_PENDING,
        )
        if pending:
            raise ValueError(
                "ค่าปรับนี้มีคำขอรออนุมัติอยู่ — ต้องรอผลอนุมัติ/ปฏิเสธ/ยกเลิกคำขอก่อน "
                "จึงจะรับชำระเงินหรือใช้เครดิตได้"
            )

    @classmethod
    async def _assert_fine_cashflow_reversible(
        cls, conn: asyncpg.Connection, payment_ids: List[int]
    ) -> None:
        """กันการย้อนรายการ (revert/undo credit) ที่จะทำให้ค่าปรับที่ปิดยอดแล้วเพี้ยน"""
        if not payment_ids:
            return
        locked = await conn.fetchval(
            """SELECT 1 FROM fines F
               WHERE F.student_payment_id = ANY($1::int[]) AND F.deleted_at IS NULL
                 AND (F.status IN ($2, $3, $4)
                      OR F.waived_amount > 0 OR F.refunded_amount > 0)
               LIMIT 1""",
            [int(p) for p in payment_ids],
            FINE_STATUS_WAIVED, FINE_STATUS_CANCELLED, FINE_STATUS_REFUNDED,
        )
        if locked:
            raise ValueError(
                "ค่าปรับนี้ถูกยกเว้น/ยกเลิก/คืนเงินไปแล้ว — จัดการผ่านหน้าค่าปรับ "
                "ไม่ใช่ย้อนรายการการชำระเงิน"
            )

    # =================================================================
    # ออกค่าปรับ
    # =================================================================
    @classmethod
    async def issue_fines(
        cls, pool: asyncpg.Pool, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """ออกค่าปรับ 1 รอบ (หลายคน ความผิดเดียวกัน) — all-or-nothing

        Idempotency: `(room_id, idempotency_key)` มีอยู่แล้ว ⇒ คืนผลของรอบเดิม
        (ตาราง `fine_batches` + fine rows + เลข INV-)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    # 🔁 retry/double-submit — คืนของเดิม
                    existing_batch = await conn.fetchrow(
                        """SELECT * FROM fine_batches
                           WHERE room_id = $1 AND idempotency_key = $2 AND deleted_at IS NULL""",
                        target_room_id, req.idempotency_key,
                    )
                    if existing_batch:
                        rows = await cls._load_fine_rows_for_batch(
                            conn, existing_batch["id"], target_room_id
                        )
                        fines = [cls._shape_fine(r) for r in rows]
                        return {
                            "batch": cls._shape_fine_batch(existing_batch),
                            "fines": fines,
                            "totals": {
                                "student_count": existing_batch["student_count"],
                                "total_amount": float(existing_batch["total_amount"]),
                            },
                            "invoice_nos": [f["invoice_no"] for f in fines if f["invoice_no"]],
                            "reused": True,
                        }

                    fine_type = await conn.fetchrow(
                        """SELECT id, name, default_amount, default_due_days
                           FROM fine_types
                           WHERE id = $1 AND room_id = $2 AND is_active = TRUE AND deleted_at IS NULL""",
                        req.fine_type_id, target_room_id,
                    )
                    if not fine_type:
                        raise ValueError("ไม่พบประเภทความผิดนี้ หรือถูกปิดใช้งานแล้ว")

                    due_date = req.due_date
                    if due_date is None:
                        from datetime import timedelta
                        due_date = req.incident_date + timedelta(days=fine_type["default_due_days"])
                    if due_date < req.incident_date:
                        raise ValueError("กำหนดชำระต้องไม่ก่อนวันที่เกิดเหตุ")

                    # 🧮 คำนวณยอดต่อคน + dedupe + ตรวจนักเรียนจริงของห้อง
                    wanted: dict[int, float] = {}
                    for item in req.students:
                        sid = int(item.student_id)
                        if sid in wanted:
                            continue
                        amount = item.amount if item.amount is not None else float(fine_type["default_amount"])
                        if amount <= 0:
                            raise ValueError(
                                "จำนวนเงินค่าปรับต้องมากกว่า 0 บาท "
                                "(ประเภท 'อื่น ๆ' ต้องกรอกยอดเอง)"
                            )
                        wanted[sid] = round(float(amount), 2)
                    if not wanted:
                        raise ValueError("ต้องเลือกนักเรียนอย่างน้อย 1 คน")

                    valid = await conn.fetch(
                        """SELECT id FROM students
                           WHERE room_id = $1 AND id = ANY($2::int[])
                             AND status = 'active' AND deleted_at IS NULL""",
                        target_room_id, list(wanted.keys()),
                    )
                    valid_ids = {r["id"] for r in valid}
                    missing = [sid for sid in wanted if sid not in valid_ids]
                    if missing:
                        raise ValueError("มีนักเรียนที่ไม่อยู่ในห้องนี้หรือไม่ active อยู่ในรายการ")

                    # ⚠️ `fine_batches.amount_per_student` เป็น snapshot — ใช้ยอดแรก
                    #    ถ้ายอดต่างกันจริง ตัวบิลรายคนคือความจริง (batch.amount_per_student
                    #    จะแสดง "ยอดอ้างอิง" และ total ยังถูกต้อง)
                    amounts = list(wanted.values())
                    amount_per_student = amounts[0] if len(set(amounts)) == 1 else 0.0
                    total_amount = round(sum(amounts), 2)

                    batch_id = await conn.fetchval(
                        """INSERT INTO fine_batches
                               (room_id, fine_type_id, fine_type_name, incident_date, due_date,
                                reason, amount_per_student, student_count, total_amount,
                                idempotency_key, created_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                           RETURNING id""",
                        target_room_id, fine_type["id"], fine_type["name"],
                        req.incident_date, due_date, req.reason,
                        amount_per_student, len(wanted), total_amount,
                        req.idempotency_key, user_id,
                    )

                    issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
                    invoice_nos: List[str] = []
                    total_issued = 0.0

                    for student_id, amount in wanted.items():
                        title = f"ค่าปรับ · {fine_type['name']} · {req.incident_date.isoformat()}"
                        collection_id = await conn.fetchval(
                            """INSERT INTO fee_collections
                                   (room_id, title, amount, due_date, collection_kind)
                               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                            target_room_id, title, amount, due_date, COLLECTION_KIND_FINE,
                        )
                        payment_ids = await cls._create_bills_with_accrual(
                            conn,
                            room_id=target_room_id,
                            collection_id=collection_id,
                            student_ids=[student_id],
                            amount=amount,
                            collection_kind=COLLECTION_KIND_FINE,
                            recorded_by=actor_identifier,
                            metadata={"fine_batch_id": batch_id},
                        )
                        payment_id = payment_ids[0]

                        fine_id = await conn.fetchval(
                            """INSERT INTO fines
                                   (room_id, batch_id, fine_type_id, fine_type_name, student_id,
                                    hidden_collection_id, student_payment_id, incident_date,
                                    due_date, reason, original_amount, amount, status,
                                    evidence_url, note, created_by)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                               RETURNING id""",
                            target_room_id, batch_id, fine_type["id"], fine_type["name"],
                            student_id, collection_id, payment_id, req.incident_date,
                            due_date, req.reason, amount, amount, FINE_STATUS_ISSUED,
                            req.evidence_url, req.note, user_id,
                        )

                        inv = await cls._issue_fine_invoice(
                            conn, room_id=target_room_id, payment_id=payment_id,
                            fine_id=fine_id, fine_type_name=fine_type["name"],
                            incident_date=req.incident_date, due_date=due_date,
                            reason=req.reason, amount=amount,
                            user_id=user_id, user_name=actor_identifier,
                            issued_at_db=issued_at_db,
                        )
                        await conn.execute(
                            "UPDATE fines SET invoice_receipt_id = $1 WHERE id = $2",
                            inv["id"], fine_id,
                        )
                        invoice_nos.append(inv["receipt_no"])
                        total_issued += amount

                        # 🔔 แจ้งเจ้าของบิลในแอป (ถ้าผูกบัญชีแล้ว)
                        owner_user_id = await conn.fetchval(
                            "SELECT user_id FROM students WHERE id = $1", student_id
                        )
                        if owner_user_id:
                            await notify_user(
                                conn, room_id=target_room_id, user_id=owner_user_id,
                                group_type="finance", type="fine_issued",
                                title=f"มีค่าปรับใหม่ {amount:,.2f} บาท",
                                body=f"{fine_type['name']} · {req.reason}",
                                entity_type="fine", entity_id=fine_id,
                                url=f"/finance/fines/{fine_id}",
                            )

                        await service_logger.log(
                            conn=conn, action="CREATE", actor_identifier=actor_identifier,
                            client_source=client_source, room_id=target_room_id,
                            user_id=user_id, entity_type="FINE", entity_id=str(fine_id),
                            status="success",
                            new_values={
                                "batch_id": batch_id, "student_id": student_id,
                                "amount": amount, "fine_type": fine_type["name"],
                                "invoice_no": inv["receipt_no"],
                            },
                            endpoint_or_command="FinanceService.issue_fines",
                            execution_time_ms=int((time.time() - start_time) * 1000),
                        )

                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_BATCH", entity_id=str(batch_id),
                        status="success",
                        new_values={
                            "fine_type": fine_type["name"],
                            "student_count": len(wanted),
                            "total_amount": total_amount,
                        },
                        endpoint_or_command="FinanceService.issue_fines",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                    rows = await cls._load_fine_rows_for_batch(conn, batch_id, target_room_id)
                    fines = [cls._shape_fine(r) for r in rows]
                    batch_row = await conn.fetchrow(
                        "SELECT * FROM fine_batches WHERE id = $1", batch_id
                    )
                    # 📢 ดึง server_id ใน transaction (commit แล้วจะอ่านไม่ได้ก็ต่อเมื่อห้องถูกลบ)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            # ⚠️ publish **หลัง** commit เท่านั้น — event ที่อ้างค่าปรับที่ rollback ไปแล้วคือข้อมูลปลอม
            if room_server_id:
                await ActionService.notify_fines_issued(
                    server_id=room_server_id,
                    fine_type_name=fine_type["name"],
                    student_count=len(wanted),
                    total_amount=round(total_issued, 2),
                    due_date=due_date,
                    user_name=actor_identifier,
                )
            return {
                "batch": cls._shape_fine_batch(batch_row),
                "fines": fines,
                "totals": {"student_count": len(wanted), "total_amount": round(total_issued, 2)},
                "invoice_nos": invoice_nos,
                "reused": False,
            }
        except asyncpg.UniqueViolationError as e:
            # แพ้การแข่ง idempotency (คำขอเดียวกันเข้าก่อน) — ให้ผู้เรียกยิงซ้ำแล้วได้ผลเดิม
            raise ValueError("คำขอนี้ถูกบันทึกไปแล้ว (idempotency key ซ้ำ) — ลองโหลดรายการใหม่") from e
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_BATCH", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_fines",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @staticmethod
    def _shape_fine_batch(row) -> dict:
        """⚠️ ห้ามตั้งชื่อ `_shape_batch` — ชนกับ `ReceiptBatchesMixin._shape_batch`
        ใน MRO ของ `FinanceService` (FinesMixin มาก่อน) และทำให้ชุดเอกสารพังเงียบ ๆ"""
        return {
            "id": row["id"],
            "fine_type_id": row["fine_type_id"],
            "fine_type_name": row["fine_type_name"],
            "incident_date": row["incident_date"],
            "due_date": row["due_date"],
            "reason": row["reason"],
            "amount_per_student": float(row["amount_per_student"] or 0),
            "student_count": row["student_count"],
            "total_amount": float(row["total_amount"] or 0),
        }

    # =================================================================
    # อ่าน
    # =================================================================
    @classmethod
    async def list_fines(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, status: Optional[str] = None, student_id: Optional[int] = None,
        fine_type_id: Optional[int] = None, batch_id: Optional[int] = None,
        from_date=None, to_date=None, search: Optional[str] = None,
        limit: int = 200, offset: int = 0,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายการค่าปรับ — สมาชิกห้องดูได้ แต่ **นักเรียนเห็นเฉพาะของตัวเอง**

        🔐 กติกาสิทธิ์: ผู้ที่ถือ `MANAGE_FINANCE` (หรือ admin) เห็นทั้งห้อง —
           ครู/เหรัญญิกก็มีแถว `students` ในห้องเหมือนกัน จึง **ห้ามกรองแค่
           "มีแถว students"** ไม่งั้นเจ้าของค่าปรับจะเปิดหน้าค่าปรับแล้วเจอแต่ของตัวเอง
           (เจอจริงในเทสต์ Phase 5: admin เห็น count = 0 ทั้งที่ห้องมีค่าปรับ)
           คนที่ไม่มีสิทธิ์ ⇒ บังคับ `student_id = ตัวเอง` แม้ส่ง query อื่นมา
        """
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            if not await has_any_permission(conn, target_room_id, user_id, ("MANAGE_FINANCE",)):
                my_student_id = await conn.fetchval(
                    "SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL ORDER BY id LIMIT 1",
                    target_room_id, int(user_id),
                )
                if my_student_id is not None:
                    student_id = my_student_id

            conds = ["F.room_id = $1", "F.deleted_at IS NULL"]
            params: list = [target_room_id]
            if status:
                params.append(status)
                conds.append(f"F.status = ${len(params)}")
            if student_id is not None:
                params.append(int(student_id))
                conds.append(f"F.student_id = ${len(params)}")
            if fine_type_id is not None:
                params.append(int(fine_type_id))
                conds.append(f"F.fine_type_id = ${len(params)}")
            if batch_id is not None:
                params.append(int(batch_id))
                conds.append(f"F.batch_id = ${len(params)}")
            if from_date is not None:
                params.append(from_date)
                conds.append(f"F.incident_date >= ${len(params)}")
            if to_date is not None:
                params.append(to_date)
                conds.append(f"F.incident_date <= ${len(params)}")
            if search:
                params.append(f"%{search.strip()}%")
                conds.append(
                    f"(F.reason ILIKE ${len(params)} OR F.fine_type_name ILIKE ${len(params)})"
                )

            where = " AND ".join(conds)
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM fines F WHERE {where}", *params
            )
            params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
            rows = await conn.fetch(
                f"""{_FINE_SELECT} WHERE {where}
                    ORDER BY F.id DESC
                    LIMIT ${len(params) - 1} OFFSET ${len(params)}""",
                *params,
            )
        return {"fines": [cls._shape_fine(r) for r in rows], "total": int(total or 0)}

    @classmethod
    async def get_fine(
        cls, pool: asyncpg.Pool, fine_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            row = await cls._load_fine_row(conn, fine_id, target_room_id)
            if not row:
                raise RoomNotFoundError("ไม่พบค่าปรับนี้")
            # 🔐 นักเรียน (ไม่มี MANAGE_FINANCE) เห็นได้เฉพาะค่าปรับของตัวเอง
            #    ⚠️ ห้ามใช้แค่ "มีแถว students" — ครูก็มีแถว (ดู `list_fines`)
            if not await has_any_permission(conn, target_room_id, user_id, ("MANAGE_FINANCE",)):
                my_student_id = await conn.fetchval(
                    "SELECT id FROM students WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL ORDER BY id LIMIT 1",
                    target_room_id, int(user_id),
                )
                if my_student_id is not None and row["student_id"] != my_student_id:
                    raise RoomNotFoundError("ไม่พบค่าปรับนี้")
            waivers = await conn.fetch(
                """SELECT * FROM fine_waivers
                   WHERE fine_id = $1 AND deleted_at IS NULL ORDER BY id DESC""",
                fine_id,
            )
            refunds = await conn.fetch(
                """SELECT * FROM fine_refunds
                   WHERE fine_id = $1 AND deleted_at IS NULL ORDER BY id DESC""",
                fine_id,
            )
        result = cls._shape_fine(row)
        result["waivers"] = [cls._shape_request(w, "waiver") for w in waivers]
        result["refunds"] = [cls._shape_request(r, "refund") for r in refunds]
        return result

    @staticmethod
    def _shape_request(row, kind: str) -> dict:
        base = {
            "id": row["id"],
            "room_id": row["room_id"],
            "fine_id": row["fine_id"],
            "amount": float(row["amount"]),
            "reason": row["reason"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_at": row["requested_at"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
            "decision_note": row["decision_note"],
            "kind": kind,
        }
        if kind == "waiver":
            base["reason_category"] = row["reason_category"]
        else:
            base["account_id"] = row["account_id"]
            base["transaction_id"] = row["transaction_id"]
            base["document_id"] = row["document_id"]
        return base

    # =================================================================
    # แก้ไข / ยกเลิก (ก่อนจ่ายเท่านั้น)
    # =================================================================
    @classmethod
    async def _load_fine_for_update(cls, conn, fine_id: int, room_id: int):
        row = await conn.fetchrow(
            f"""{_FINE_SELECT}
                WHERE F.id = $1 AND F.room_id = $2 AND F.deleted_at IS NULL
                FOR UPDATE OF F""",
            fine_id, room_id,
        )
        if not row:
            raise RoomNotFoundError("ไม่พบค่าปรับนี้")
        return row

    @classmethod
    async def update_fine(
        cls, pool: asyncpg.Pool, fine_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)
                    row = await cls._load_fine_for_update(conn, fine_id, target_room_id)

                    if float(row["paid_amount"] or 0) > 0:
                        raise ValueError("ค่าปรับนี้มีการชำระเงินแล้ว — แก้ยอดไม่ได้ (ต้องยกเว้น/คืนเงิน)")
                    if row["status"] == FINE_STATUS_CANCELLED:
                        raise ValueError("ค่าปรับนี้ถูกยกเลิกแล้ว")
                    await cls._assert_no_pending_fine_requests(conn, [row["student_payment_id"]])

                    data = req.model_dump(exclude_unset=True)
                    old_amount = float(row["amount"])
                    new_amount = round(float(data["amount"]), 2) if data.get("amount") is not None else old_amount
                    if new_amount <= 0:
                        raise ValueError("จำนวนเงินต้องมากกว่า 0 บาท")
                    incident = data.get("incident_date") or row["incident_date"]
                    due = data.get("due_date") or row["due_date"]
                    if due < incident:
                        raise ValueError("กำหนดชำระต้องไม่ก่อนวันที่เกิดเหตุ")

                    invoice_fields_changed = any(
                        k in data and data[k] is not None
                        for k in ("amount", "incident_date", "due_date", "reason")
                    )

                    if new_amount != old_amount:
                        # 📒 ปรับ AR + รายได้ค่าปรับตามส่วนต่าง
                        await cls._post_bill_adjustment(
                            conn, target_room_id, row["student_payment_id"],
                            delta=round(new_amount - old_amount, 2),
                            collection_kind=COLLECTION_KIND_FINE,
                            reference_type=REFERENCE_TYPE_FINE_ADJUSTMENT,
                            description=f"ปรับยอดค่าปรับ #{fine_id}",
                            recorded_by=actor_identifier,
                            metadata={"fine_id": fine_id},
                        )
                        await conn.execute(
                            "UPDATE fee_collections SET amount = $1 WHERE id = $2",
                            new_amount, row["hidden_collection_id"],
                        )
                        await conn.execute(
                            "UPDATE fines SET amount = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                            new_amount, fine_id,
                        )

                    sets, values, idx = [], [], 1
                    for key in ("incident_date", "due_date", "reason", "evidence_url", "note"):
                        if key in data and data[key] is not None:
                            sets.append(f"{key} = ${idx}")
                            values.append(data[key])
                            idx += 1
                    if sets:
                        values.append(fine_id)
                        await conn.execute(
                            f"UPDATE fines SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ${idx}",
                            *values,
                        )

                    if invoice_fields_changed:
                        # 🧾 ใบเดิมเป็น snapshot ของข้อมูลเก่า ⇒ void แล้วออกใหม่ (ถ้ายังมียอด)
                        await cls._void_invoice_for_payment(
                            conn, room_id=target_room_id,
                            payment_id=row["student_payment_id"], user_id=user_id,
                            reason=f"แก้ไขค่าปรับ #{fine_id} — ออกใบใหม่",
                        )
                        fresh = await cls._load_fine_row(conn, fine_id, target_room_id)
                        if float(fresh["amount"]) > 0:
                            inv = await cls._issue_fine_invoice(
                                conn, room_id=target_room_id,
                                payment_id=fresh["student_payment_id"],
                                fine_id=fine_id, fine_type_name=fresh["fine_type_name"],
                                incident_date=fresh["incident_date"], due_date=fresh["due_date"],
                                reason=fresh["reason"], amount=float(fresh["amount"]),
                                user_id=user_id, user_name=actor_identifier,
                            )
                            await conn.execute(
                                "UPDATE fines SET invoice_receipt_id = $1 WHERE id = $2",
                                inv["id"], fine_id,
                            )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE", entity_id=str(fine_id),
                        status="success", old_values=dict(row), new_values=data,
                        endpoint_or_command="FinanceService.update_fine",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    updated = await cls._load_fine_row(conn, fine_id, target_room_id)
            return {"status": "success", "message": "แก้ไขค่าปรับสำเร็จ", "fine": cls._shape_fine(updated)}
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE", entity_id=str(fine_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_fine",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def cancel_fine(
        cls, pool: asyncpg.Pool, fine_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)
                    row = await cls._load_fine_for_update(conn, fine_id, target_room_id)

                    if float(row["paid_amount"] or 0) > 0 or float(row["refunded_amount"] or 0) > 0:
                        raise ValueError(
                            "ค่าปรับนี้มีการชำระ/คืนเงินแล้ว — ยกเลิกไม่ได้ "
                            "ให้ใช้การยกเว้น/ลด หรือคืนเงินแทน"
                        )
                    if row["status"] == FINE_STATUS_CANCELLED:
                        return {"status": "success", "message": "ค่าปรับนี้ถูกยกเลิกอยู่แล้ว"}
                    await cls._assert_no_pending_fine_requests(conn, [row["student_payment_id"]])

                    amount = round(float(row["amount"]), 2)
                    if amount > 0:
                        # 📒 กลับรายได้ค่าปรับ: Dr 49001 / Cr 11002
                        #    source-aware — ถ้า AR มาจาก opening ให้กลับกับ equity 31002 แทน
                        source = await cls._bill_ar_source(conn, row["student_payment_id"])
                        contra_ledger_id = await cls._resolve_contra_ledger(
                            conn, room_id=target_room_id,
                            collection_kind=COLLECTION_KIND_FINE, source=source,
                        )
                        if contra_ledger_id is not None:
                            ar_ledger_id = await cls._resolve_ar_fine_ledger(conn, target_room_id)
                            await cls._insert_journal_entry(
                                conn, target_room_id,
                                reference_type=REFERENCE_TYPE_FINE_CANCEL,
                                reference_id=str(fine_id),
                                description=f"ยกเลิกค่าปรับ #{fine_id}: {row['fine_type_name']}",
                                recorded_by=actor_identifier,
                                metadata={
                                    "fine_id": fine_id,
                                    "student_payment_id": row["student_payment_id"],
                                    "collection_kind": COLLECTION_KIND_FINE,
                                    "ar_source": source,
                                    "accrual": "fine_cancel",
                                },
                                lines=[
                                    {"ledger_id": contra_ledger_id, "debit": amount, "credit": 0,
                                     "line_description": "กลับรายได้ค่าปรับที่ยกเลิก"},
                                    {"ledger_id": ar_ledger_id, "debit": 0, "credit": amount,
                                     "line_description": "ตัดผู้ค้างชำระค่าปรับ"},
                                ],
                            )

                    # 🧾 ยกเลิกเอกสาร/บิล/โปรเจกต์ซ่อน
                    await cls._void_invoice_for_payment(
                        conn, room_id=target_room_id,
                        payment_id=row["student_payment_id"], user_id=user_id,
                        reason=f"ยกเลิกค่าปรับ #{fine_id}",
                    )
                    await conn.execute(
                        """UPDATE student_payments
                           SET status = 'cancelled', deleted_at = NOW()
                           WHERE id = $1 AND deleted_at IS NULL""",
                        row["student_payment_id"],
                    )
                    await conn.execute(
                        """UPDATE fee_collections SET deleted_at = NOW(), status = 'closed'
                           WHERE id = $1 AND deleted_at IS NULL""",
                        row["hidden_collection_id"],
                    )
                    # 🗂️ ค่าปรับไม่ soft-delete — ต้องคงไว้ให้ประวัติ/รายงานเห็นสถานะ cancelled
                    #    (บิลถูก soft-delete แล้ว ⇒ ไม่โผล่ในยอดค้าง/ใบเสร็จ)
                    await conn.execute(
                        """UPDATE fines SET status = $1, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $2""",
                        FINE_STATUS_CANCELLED, fine_id,
                    )
                    await conn.execute(
                        """UPDATE fine_waivers SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE fine_id = $1 AND status = 'pending' AND deleted_at IS NULL""",
                        fine_id,
                    )
                    await conn.execute(
                        """UPDATE fine_refunds SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE fine_id = $1 AND status = 'pending' AND deleted_at IS NULL""",
                        fine_id,
                    )

                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE", entity_id=str(fine_id),
                        status="success", old_values=dict(row),
                        new_values={"cancel_reason": getattr(req, "reason", None)},
                        endpoint_or_command="FinanceService.cancel_fine",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {"status": "success", "message": "ยกเลิกค่าปรับสำเร็จ"}
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE", entity_id=str(fine_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.cancel_fine",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e
