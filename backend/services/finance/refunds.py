"""คืนเงินค่าปรับ (refund) — คำขอ → อนุมัติ/ปฏิเสธ/ยกเลิก

═══════════════════════════════════════════════════════════════════════════════
📒 Journal ตอนอนุมัติ: Dr 49003 คืนค่าปรับ / Cr บัญชีสินทรัพย์ (กระเป๋าที่จ่ายคืน)
═══════════════════════════════════════════════════════════════════════════════
🔴 **ไม่แตะ** `student_payments.paid_amount` หรือ AR 11002 — การคืนเงินคือการคืนเงินสด
   หลังบิลปิดยอดแล้ว ไม่เปิดหนี้ใหม่ · ถ้าต้องเรียกเก็บใหม่ให้ออกค่าปรับใหม่

🧾 เอกสาร: ออก **ใบสำคัญจ่าย (PV-)** ผูกกับ `finance_transactions` ที่สร้างใหม่
   (`transaction_type='refund'`) — และ revert_transaction ปฏิเสธรายการชนิดนี้
   โดยเจตนา (ดู transactions.py) เพื่อไม่ให้ `fines.refunded_amount` เพี้ยน
"""
from __future__ import annotations

import time
from typing import Optional

import asyncpg

from core.exceptions import ForbiddenError, RoomNotFoundError
from core.rbac import require_member, require_permission
from services.action_service import ActionService
from services.notification_service import notify_user

from .base import _lock_room_money, service_logger
from .constants import (
    FINE_REFUND_CODE,
    FINE_STATUS_CANCELLED,
    REFERENCE_TYPE_FINE_REFUND,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_PENDING,
    REQUEST_STATUS_REJECTED,
)
from .helpers import _as_utc, _full_name
from .waivers import _notify_finance_managers

_EPS = 0.005


class RefundsMixin:
    # =================================================================
    # คำขอ
    # =================================================================
    @classmethod
    async def request_refund(
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
                    fine = await cls._load_fine_for_update(conn, fine_id, target_room_id)

                    if fine["status"] == FINE_STATUS_CANCELLED:
                        raise ValueError("ค่าปรับนี้ถูกยกเลิกแล้ว — ขอคืนเงินไม่ได้")
                    paid = round(float(fine["paid_amount"] or 0), 2)
                    refunded = round(float(fine["refunded_amount"] or 0), 2)
                    refundable = round(paid - refunded, 2)
                    if refundable <= _EPS:
                        raise ValueError("ค่าปรับนี้ยังไม่มีเงินที่ชำระแล้วให้คืน")
                    amount = round(float(req.amount), 2)
                    if amount > refundable + _EPS:
                        raise ValueError(
                            f"ยอดคืน {amount:,.2f} เกินยอดที่คืนได้ {refundable:,.2f} บาท"
                        )
                    account = await conn.fetchrow(
                        """SELECT id FROM finance_accounts
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                        req.account_id, target_room_id,
                    )
                    if not account:
                        raise ValueError("ไม่พบบัญชีเงินนี้ในห้อง")
                    await cls._assert_no_pending_fine_requests(
                        conn, [fine["student_payment_id"]]
                    )

                    refund_id = await conn.fetchval(
                        """INSERT INTO fine_refunds
                               (room_id, fine_id, account_id, amount, reason,
                                status, requested_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)
                           RETURNING id""",
                        target_room_id, fine_id, req.account_id, amount, req.reason,
                        REQUEST_STATUS_PENDING, user_id,
                    )
                    await _notify_finance_managers(
                        conn, target_room_id, exclude_user_id=user_id,
                        type="fine_refund_requested",
                        title=f"มีคำขอคืนเงินค่าปรับ {amount:,.2f} บาท",
                        body=f"{fine['fine_type_name']} · {req.reason}",
                        entity_type="fine_refund", entity_id=refund_id,
                        url="/finance/fines?tab=waivers",
                    )
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND",
                        entity_id=str(refund_id), status="success",
                        new_values={
                            "fine_id": fine_id, "amount": amount,
                            "account_id": req.account_id, "reason": req.reason,
                        },
                        endpoint_or_command="FinanceService.request_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {
                "status": "success",
                "message": f"ส่งคำขอคืนเงิน {amount:,.2f} บาท เพื่อรออนุมัติแล้ว",
                "id": refund_id,
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.request_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    # =================================================================
    # อ่าน
    # =================================================================
    @classmethod
    async def list_fine_refunds(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, status: Optional[str] = None, fine_id: Optional[int] = None,
        limit: int = 200, offset: int = 0,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            conds = ["R.room_id = $1", "R.deleted_at IS NULL"]
            params: list = [target_room_id]
            if status:
                params.append(status)
                conds.append(f"R.status = ${len(params)}")
            if fine_id is not None:
                params.append(int(fine_id))
                conds.append(f"R.fine_id = ${len(params)}")
            where = " AND ".join(conds)
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM fine_refunds R WHERE {where}", *params
            )
            params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
            rows = await conn.fetch(
                f"""SELECT R.* FROM fine_refunds R WHERE {where}
                    ORDER BY R.id DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}""",
                *params,
            )
        return {
            "refunds": [cls._shape_request(r, "refund") for r in rows],
            "total": int(total or 0),
        }

    # =================================================================
    # อนุมัติ / ปฏิเสธ / ยกเลิก
    # =================================================================
    @classmethod
    async def _load_refund_for_update(
        cls, conn: asyncpg.Connection, refund_id: int, room_id: int
    ):
        row = await conn.fetchrow(
            """SELECT * FROM fine_refunds
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
               FOR UPDATE""",
            refund_id, room_id,
        )
        if not row:
            raise RoomNotFoundError("ไม่พบคำขอคืนเงินนี้")
        return row

    @classmethod
    async def approve_refund(
        cls, pool: asyncpg.Pool, refund_id: int, req, user_id: int,
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
                    refund = await cls._load_refund_for_update(conn, refund_id, target_room_id)
                    if refund["status"] != REQUEST_STATUS_PENDING:
                        raise ValueError("คำขอนี้ถูกดำเนินการไปแล้ว")
                    fine = await cls._load_fine_for_update(
                        conn, refund["fine_id"], target_room_id
                    )
                    if user_id in (fine["created_by"], refund["requested_by"]):
                        raise ForbiddenError(
                            "ห้ามอนุมัติคำขอที่ตัวเองสร้างหรือขอเอง — ให้ผู้ดูแลการเงินคนอื่นอนุมัติ"
                        )
                    if fine["status"] == FINE_STATUS_CANCELLED:
                        raise ValueError("ค่าปรับนี้ถูกยกเลิกแล้ว")

                    amount = round(float(refund["amount"]), 2)
                    paid = round(float(fine["paid_amount"] or 0), 2)
                    refunded = round(float(fine["refunded_amount"] or 0), 2)
                    if amount > round(paid - refunded, 2) + _EPS:
                        raise ValueError(
                            "ยอดคืนเกินยอดที่ชำระไว้ — กรุณาปฏิเสธแล้วออกคำขอใหม่"
                        )

                    balance = await conn.fetchval(
                        """SELECT balance FROM finance_accounts
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                           FOR UPDATE""",
                        refund["account_id"], target_room_id,
                    )
                    if balance is None:
                        raise ValueError("ไม่พบบัญชีเงินนี้ในห้อง")
                    if float(balance) < amount:
                        raise ValueError(
                            f"เงินในบัญชีไม่พอคืน (คงเหลือ {float(balance):,.2f} บาท)"
                        )

                    # 👤 ชื่อผู้รับเงินบนเอกสาร = นักเรียนเจ้าของค่าปรับ
                    student = await conn.fetchrow(
                        """SELECT S.student_no, U.prefix, U.first_name, U.last_name,
                                  U.first_name_en, U.last_name_en
                           FROM students S LEFT JOIN v_student_profiles U ON U.student_id = S.id
                           WHERE S.id = $1""",
                        fine["student_id"],
                    )
                    payee_name = "นักเรียน"
                    if student:
                        payee_name = _full_name(student) or "นักเรียน"

                    description = (
                        f"คืนเงินค่าปรับ #{refund['fine_id']} · {fine['fine_type_name']} · "
                        f"{refund['reason']}"
                    )
                    new_tx = await conn.fetchrow(
                        """INSERT INTO finance_transactions
                               (room_id, account_id, category_id, amount, description,
                                transaction_type, recorded_by, payee_name)
                           VALUES ($1, $2, NULL, $3, $4, 'refund', $5, $6)
                           RETURNING id, created_at""",
                        target_room_id, refund["account_id"], amount, description,
                        actor_identifier, payee_name,
                    )
                    transaction_id = new_tx["id"]
                    event_at = _as_utc(new_tx["created_at"])

                    await conn.execute(
                        "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
                        amount, refund["account_id"],
                    )

                    # 📒 Dr 49003 คืนค่าปรับ / Cr บัญชีสินทรัพย์
                    refund_ledger_id = await cls._resolve_fine_refund_ledger(
                        conn, target_room_id
                    )
                    asset_ledger_id = await cls._resolve_asset_ledger(
                        conn, target_room_id, refund["account_id"]
                    )
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type=REFERENCE_TYPE_FINE_REFUND,
                        reference_id=str(refund_id),
                        description=description,
                        recorded_by=actor_identifier,
                        metadata={
                            "fine_id": refund["fine_id"],
                            "refund_id": refund_id,
                            "legacy_transaction_id": transaction_id,
                            "account_id": refund["account_id"],
                            "accrual": "fine_refund",
                        },
                        lines=[
                            {"ledger_id": refund_ledger_id, "debit": amount, "credit": 0,
                             "line_description": f"คืนค่าปรับ (บัญชี {FINE_REFUND_CODE})"},
                            {"ledger_id": asset_ledger_id, "debit": 0, "credit": amount,
                             "line_description": f"เงินออกจากบัญชี #{refund['account_id']}"},
                        ],
                    )

                    # 🧾 ใบสำคัญจ่าย (PV-) — หมวดหมู่ไม่มี (รายการคืนเงิน ไม่ใช่รายจ่ายงบ)
                    issued_at = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
                    voucher = await cls._issue_payment_voucher(
                        conn, target_room_id, transaction_id, amount,
                        payee_name, user_id, actor_identifier,
                        note=description,
                        event_at_db=event_at, issued_at_db=issued_at,
                        account_id=refund["account_id"], category_id=None,
                        approver_name=getattr(req, "user_name", None),
                        attachment_count=0,
                        category_label_override="คืนค่าปรับ",
                    )
                    document_id = voucher["receipt"]["id"]

                    await conn.execute(
                        """UPDATE fines
                           SET refunded_amount = refunded_amount + $1,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = $2""",
                        amount, refund["fine_id"],
                    )
                    await cls._sync_fine_status(conn, [fine["student_payment_id"]])

                    decided = await conn.fetchrow(
                        """UPDATE fine_refunds
                           SET status = $1, decided_by = $2, decided_at = CURRENT_TIMESTAMP,
                               decision_note = $3, transaction_id = $4, document_id = $5,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = $6
                           RETURNING *""",
                        REQUEST_STATUS_APPROVED, user_id, getattr(req, "note", None),
                        transaction_id, document_id, refund_id,
                    )

                    owner_user_id = await conn.fetchval(
                        "SELECT user_id FROM students WHERE id = $1", fine["student_id"]
                    )
                    targets = {int(uid) for uid in (refund["requested_by"], owner_user_id) if uid}
                    for uid in targets:
                        await notify_user(
                            conn, room_id=target_room_id, user_id=uid,
                            group_type="finance", type="fine_refund_decided",
                            title=f"อนุมัติคืนเงินค่าปรับ {amount:,.2f} บาท",
                            body=f"{fine['fine_type_name']} · ใบสำคัญจ่าย {voucher['receipt']['receipt_no']}",
                            entity_type="fine", entity_id=refund["fine_id"],
                            url=f"/finance/fines/{refund['fine_id']}",
                        )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND",
                        entity_id=str(refund_id), status="success",
                        old_values=dict(refund),
                        new_values={
                            "status": REQUEST_STATUS_APPROVED,
                            "transaction_id": transaction_id,
                            "document_id": document_id,
                            "receipt_no": voucher["receipt"]["receipt_no"],
                        },
                        endpoint_or_command="FinanceService.approve_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                    # 📢 ข้อมูลที่ต้องใช้ publish — อ่านใน transaction ก่อน commit
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
                    student_name = await cls._resolve_student_name(conn, fine["student_id"])
            if room_server_id:
                await ActionService.notify_fine_refunded(
                    server_id=room_server_id,
                    student_name=student_name,
                    fine_type_name=fine["fine_type_name"],
                    amount=amount,
                    receipt_no=voucher["receipt"]["receipt_no"],
                    user_name=actor_identifier,
                )
            return {
                "status": "success",
                "message": (
                    f"อนุมัติคืนเงิน {amount:,.2f} บาทแล้ว — ออกใบสำคัญจ่าย "
                    f"{voucher['receipt']['receipt_no']}"
                ),
                "refund": cls._shape_request(decided, "refund"),
                "receipt_no": voucher["receipt"]["receipt_no"],
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND",
                        entity_id=str(refund_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.approve_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def reject_refund(
        cls, pool: asyncpg.Pool, refund_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        return await cls._decide_refund_without_money(
            pool, refund_id, req, user_id, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, new_status=REQUEST_STATUS_REJECTED,
        )

    @classmethod
    async def cancel_refund(
        cls, pool: asyncpg.Pool, refund_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        return await cls._decide_refund_without_money(
            pool, refund_id, req, user_id, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, new_status=REQUEST_STATUS_CANCELLED,
        )

    @classmethod
    async def _decide_refund_without_money(
        cls, pool: asyncpg.Pool, refund_id: int, req, user_id: int,
        client_source: str, actor_identifier: str, *,
        server_id: Optional[int], room_id: Optional[int], new_status: str,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)
                    refund = await cls._load_refund_for_update(conn, refund_id, target_room_id)
                    if refund["status"] != REQUEST_STATUS_PENDING:
                        raise ValueError("คำขอนี้ถูกดำเนินการไปแล้ว")
                    decided = await conn.fetchrow(
                        """UPDATE fine_refunds
                           SET status = $1, decided_by = $2, decided_at = CURRENT_TIMESTAMP,
                               decision_note = $3, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $4
                           RETURNING *""",
                        new_status, user_id, getattr(req, "note", None), refund_id,
                    )
                    label = {
                        REQUEST_STATUS_REJECTED: "ไม่อนุมัติ",
                        REQUEST_STATUS_CANCELLED: "ยกเลิกคำขอ",
                    }[new_status]
                    if refund["requested_by"]:
                        await notify_user(
                            conn, room_id=target_room_id,
                            user_id=refund["requested_by"],
                            group_type="finance", type="fine_refund_decided",
                            title=f"{label}คืนเงินค่าปรับ {float(refund['amount']):,.2f} บาท",
                            body=f"ค่าปรับ #{refund['fine_id']}",
                            entity_type="fine", entity_id=refund["fine_id"],
                            url=f"/finance/fines/{refund['fine_id']}",
                        )
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND",
                        entity_id=str(refund_id), status="success",
                        old_values=dict(refund), new_values=dict(decided),
                        endpoint_or_command=f"FinanceService.{new_status}_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {
                "status": "success",
                "message": f"{label}แล้ว",
                "refund": cls._shape_request(decided, "refund"),
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_REFUND",
                        entity_id=str(refund_id), status="failed", error_detail=str(e),
                        endpoint_or_command=f"FinanceService.{new_status}_refund",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e
