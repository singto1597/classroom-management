"""ยกเว้น/ลดค่าปรับ (waiver) — คำขอ → อนุมัติ/ปฏิเสธ/ยกเลิก

═══════════════════════════════════════════════════════════════════════════════
📒 Journal ตอนอนุมัติ (Dr ค่าใช้จ่าย/ส่วนลด / Cr AR 11002)
═══════════════════════════════════════════════════════════════════════════════
  discount       → Dr 49002 ส่วนลดค่าปรับ (contra-revenue) / Cr 11002
  uncollectible  → Dr 59001 หนี้สูญค่าปรับ (expense)        / Cr 11002

🔴 การอนุมัติ **ห้ามอนุมัติรายการที่ตัวเองขอหรือตัวเองออกค่าปรับ** — ผู้มี
   MANAGE_FINANCE คนใดก็อนุมัติได้ ยกเว้นสองคนนั้น (ข้อตกลง #20)

🧮 ยอดที่ลดได้ต้องไม่เกินยอดคงเหลือจริง (`fines.amount - paid_amount`) — คำขอถูก
   คำนวณ ณ เวลาขอ แต่ตอนอนุมัติต้องเช็กซ้ำกับยอดจริงเสมอ
"""
from __future__ import annotations

import time
from typing import List, Optional

import asyncpg

from core.exceptions import ForbiddenError, RoomNotFoundError
from core.rbac import require_permission
from services.action_service import ActionService
from services.notification_service import notify_user

from .base import _lock_room_money, service_logger
from .constants import (
    COLLECTION_KIND_FINE,
    FINE_STATUS_CANCELLED,
    FINE_WAIVER_CATEGORY_DISCOUNT,
    FINE_WAIVER_CATEGORY_LABELS,
    REFERENCE_TYPE_FINE_WAIVER,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_CANCELLED,
    REQUEST_STATUS_PENDING,
    REQUEST_STATUS_REJECTED,
)

_EPS = 0.005


async def _notify_finance_managers(
    conn: asyncpg.Connection, room_id: int, *, exclude_user_id: Optional[int],
    type: str, title: str, body: str, entity_type: str, entity_id: int, url: str,
) -> None:
    """แจ้งผู้มี MANAGE_FINANCE ในห้อง (ยกเว้นคนที่ทำรายการเอง)

    ⚠️ `permissions` เป็น JSONB array — ใช้ operator `?` (key exists ใน array)
    และ `is_admin` bypass เหมือน `require_permission`
    """
    rows = await conn.fetch(
        """SELECT DISTINCT user_id FROM students
           WHERE room_id = $1 AND user_id IS NOT NULL AND deleted_at IS NULL
             AND status = 'active'
             AND (is_admin = TRUE OR (permissions ? 'MANAGE_FINANCE'))""",
        room_id,
    )
    for row in rows:
        uid = row["user_id"]
        if exclude_user_id is not None and int(uid) == int(exclude_user_id):
            continue
        await notify_user(
            conn, room_id=room_id, user_id=uid, group_type="finance",
            type=type, title=title, body=body,
            entity_type=entity_type, entity_id=entity_id, url=url,
        )


class WaiversMixin:
    # =================================================================
    # คำขอ
    # =================================================================
    @classmethod
    async def request_waiver(
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
                        raise ValueError("ค่าปรับนี้ถูกยกเลิกแล้ว — ขอยกเว้นไม่ได้")
                    outstanding = round(
                        float(fine["amount"] or 0) - float(fine["paid_amount"] or 0), 2
                    )
                    if outstanding <= _EPS:
                        raise ValueError("ค่าปรับนี้ไม่มียอดคงเหลือให้ยกเว้น")
                    amount = round(float(req.amount), 2)
                    if amount > outstanding + _EPS:
                        raise ValueError(
                            f"ยอดยกเว้น {amount:,.2f} เกินยอดคงเหลือ {outstanding:,.2f} บาท"
                        )
                    await cls._assert_no_pending_fine_requests(
                        conn, [fine["student_payment_id"]]
                    )

                    waiver_id = await conn.fetchval(
                        """INSERT INTO fine_waivers
                               (room_id, fine_id, amount, reason_category, reason,
                                status, requested_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)
                           RETURNING id""",
                        target_room_id, fine_id, amount, req.reason_category,
                        req.reason, REQUEST_STATUS_PENDING, user_id,
                    )
                    await _notify_finance_managers(
                        conn, target_room_id, exclude_user_id=user_id,
                        type="fine_waiver_requested",
                        title=f"มีคำขอยกเว้นค่าปรับ {amount:,.2f} บาท",
                        body=f"{fine['fine_type_name']} · {req.reason}",
                        entity_type="fine_waiver", entity_id=waiver_id,
                        url="/finance/fines?tab=waivers",
                    )
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER",
                        entity_id=str(waiver_id), status="success",
                        new_values={
                            "fine_id": fine_id, "amount": amount,
                            "reason_category": req.reason_category,
                            "reason": req.reason,
                        },
                        endpoint_or_command="FinanceService.request_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {
                "status": "success",
                "message": f"ส่งคำขอยกเว้น {amount:,.2f} บาท เพื่อรออนุมัติแล้ว",
                "id": waiver_id,
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.request_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    # =================================================================
    # อ่าน
    # =================================================================
    @classmethod
    async def list_fine_waivers(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        *, status: Optional[str] = None, fine_id: Optional[int] = None,
        limit: int = 200, offset: int = 0,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        from core.rbac import require_member

        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            conds = ["W.room_id = $1", "W.deleted_at IS NULL"]
            params: list = [target_room_id]
            if status:
                params.append(status)
                conds.append(f"W.status = ${len(params)}")
            if fine_id is not None:
                params.append(int(fine_id))
                conds.append(f"W.fine_id = ${len(params)}")
            where = " AND ".join(conds)
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM fine_waivers W WHERE {where}", *params
            )
            params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
            rows = await conn.fetch(
                f"""SELECT W.* FROM fine_waivers W WHERE {where}
                    ORDER BY W.id DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}""",
                *params,
            )
        return {
            "waivers": [cls._shape_request(w, "waiver") for w in rows],
            "total": int(total or 0),
        }

    # =================================================================
    # อนุมัติ / ปฏิเสธ / ยกเลิก
    # =================================================================
    @classmethod
    async def _load_waiver_for_update(
        cls, conn: asyncpg.Connection, waiver_id: int, room_id: int
    ):
        row = await conn.fetchrow(
            """SELECT * FROM fine_waivers
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
               FOR UPDATE""",
            waiver_id, room_id,
        )
        if not row:
            raise RoomNotFoundError("ไม่พบคำขอยกเว้นนี้")
        return row

    @classmethod
    async def approve_waiver(
        cls, pool: asyncpg.Pool, waiver_id: int, req, user_id: int,
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
                    waiver = await cls._load_waiver_for_update(conn, waiver_id, target_room_id)
                    if waiver["status"] != REQUEST_STATUS_PENDING:
                        raise ValueError("คำขอนี้ถูกดำเนินการไปแล้ว")
                    fine = await cls._load_fine_for_update(
                        conn, waiver["fine_id"], target_room_id
                    )
                    if user_id in (fine["created_by"], waiver["requested_by"]):
                        raise ForbiddenError(
                            "ห้ามอนุมัติคำขอที่ตัวเองสร้างหรือขอเอง — ให้ผู้ดูแลการเงินคนอื่นอนุมัติ"
                        )
                    if fine["status"] == FINE_STATUS_CANCELLED:
                        raise ValueError("ค่าปรับนี้ถูกยกเลิกแล้ว")

                    amount = round(float(waiver["amount"]), 2)
                    outstanding = round(
                        float(fine["amount"] or 0) - float(fine["paid_amount"] or 0), 2
                    )
                    if amount > outstanding + _EPS:
                        raise ValueError(
                            f"ยอดยกเว้น {amount:,.2f} เกินยอดคงเหลือ {outstanding:,.2f} บาท "
                            "— กรุณาปฏิเสธแล้วออกคำขอใหม่ตามยอดจริง"
                        )
                    if amount <= _EPS:
                        raise ValueError("ยอดยกเว้นเหลือ 0 — ไม่มีอะไรให้อนุมัติ")

                    # 📒 Dr 49002 (ส่วนลด) หรือ 59001 (หนี้สูญ) / Cr 11002
                    if waiver["reason_category"] == FINE_WAIVER_CATEGORY_DISCOUNT:
                        contra_ledger_id = await cls._resolve_fine_discount_ledger(
                            conn, target_room_id
                        )
                    else:
                        contra_ledger_id = await cls._resolve_fine_bad_debt_ledger(
                            conn, target_room_id
                        )
                    ar_ledger_id = await cls._resolve_ar_fine_ledger(conn, target_room_id)
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type=REFERENCE_TYPE_FINE_WAIVER,
                        reference_id=str(waiver_id),
                        description=(
                            f"ยกเว้นค่าปรับ #{waiver['fine_id']} "
                            f"({FINE_WAIVER_CATEGORY_LABELS.get(waiver['reason_category'], '')})"
                        ),
                        recorded_by=actor_identifier,
                        metadata={
                            "fine_id": waiver["fine_id"],
                            "waiver_id": waiver_id,
                            "student_payment_id": fine["student_payment_id"],
                            "collection_kind": COLLECTION_KIND_FINE,
                            "reason_category": waiver["reason_category"],
                            "accrual": "fine_waiver",
                        },
                        lines=[
                            {"ledger_id": contra_ledger_id, "debit": amount, "credit": 0,
                             "line_description": "ยกเว้น/ลดค่าปรับ"},
                            {"ledger_id": ar_ledger_id, "debit": 0, "credit": amount,
                             "line_description": "ตัดผู้ค้างชำระค่าปรับ"},
                        ],
                    )

                    new_amount = round(float(fine["amount"]) - amount, 2)
                    await conn.execute(
                        "UPDATE fee_collections SET amount = $1 WHERE id = $2",
                        new_amount, fine["hidden_collection_id"],
                    )
                    await conn.execute(
                        """UPDATE fines
                           SET amount = $1,
                               waived_amount = waived_amount + $2,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = $3""",
                        new_amount, amount, waiver["fine_id"],
                    )

                    paid = round(float(fine["paid_amount"] or 0), 2)
                    remaining = round(new_amount - paid, 2)
                    if remaining <= _EPS:
                        # ปิดยอด: จ่ายครบแล้ว -> paid, ยังไม่จ่ายเลย -> waived
                        await conn.execute(
                            """UPDATE student_payments SET status = $1
                               WHERE id = $2""",
                            "paid" if paid > _EPS else "waived",
                            fine["student_payment_id"],
                        )
                    await cls._sync_fine_status(conn, [fine["student_payment_id"]])

                    # 🧾 ใบเดิมเป็น snapshot ของยอดเก่า ⇒ void แล้วออกใหม่ (ถ้ายังมียอด)
                    await cls._void_invoice_for_payment(
                        conn, room_id=target_room_id,
                        payment_id=fine["student_payment_id"], user_id=user_id,
                        reason=f"อนุมัติยกเว้นค่าปรับ #{waiver['fine_id']} — ออกใบใหม่",
                    )
                    if remaining > _EPS:
                        inv = await cls._issue_fine_invoice(
                            conn, room_id=target_room_id,
                            payment_id=fine["student_payment_id"],
                            fine_id=waiver["fine_id"],
                            fine_type_name=fine["fine_type_name"],
                            incident_date=fine["incident_date"], due_date=fine["due_date"],
                            reason=fine["reason"], amount=remaining,
                            user_id=user_id, user_name=actor_identifier,
                        )
                        await conn.execute(
                            "UPDATE fines SET invoice_receipt_id = $1 WHERE id = $2",
                            inv["id"], waiver["fine_id"],
                        )

                    decided = await conn.fetchrow(
                        """UPDATE fine_waivers
                           SET status = $1, decided_by = $2, decided_at = CURRENT_TIMESTAMP,
                               decision_note = $3, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $4
                           RETURNING *""",
                        REQUEST_STATUS_APPROVED, user_id, getattr(req, "note", None),
                        waiver_id,
                    )

                    # 🔔 แจ้งผู้ขอ + เจ้าของค่าปรับ
                    owner_user_id = await conn.fetchval(
                        "SELECT user_id FROM students WHERE id = $1", fine["student_id"]
                    )
                    targets = {int(uid) for uid in (waiver["requested_by"], owner_user_id) if uid}
                    for uid in targets:
                        await notify_user(
                            conn, room_id=target_room_id, user_id=uid,
                            group_type="finance", type="fine_waiver_decided",
                            title=f"อนุมัติยกเว้นค่าปรับ {amount:,.2f} บาท",
                            body=f"{fine['fine_type_name']} · ยอดคงเหลือ {max(remaining, 0):,.2f} บาท",
                            entity_type="fine", entity_id=waiver["fine_id"],
                            url=f"/finance/fines/{waiver['fine_id']}",
                        )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER",
                        entity_id=str(waiver_id), status="success",
                        old_values=dict(waiver), new_values=dict(decided),
                        endpoint_or_command="FinanceService.approve_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                    # 📢 ข้อมูลที่ต้องใช้ publish — อ่านใน transaction ก่อน commit
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
                    student_name = await cls._resolve_student_name(conn, fine["student_id"])
            if room_server_id:
                await ActionService.notify_fine_waived(
                    server_id=room_server_id,
                    student_name=student_name,
                    fine_type_name=fine["fine_type_name"],
                    amount=amount,
                    remaining_amount=round(max(remaining, 0), 2),
                    reason_category=waiver["reason_category"],
                    user_name=actor_identifier,
                )
            return {
                "status": "success",
                "message": f"อนุมัติยกเว้น {amount:,.2f} บาทแล้ว",
                "waiver": cls._shape_request(decided, "waiver"),
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER",
                        entity_id=str(waiver_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.approve_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def reject_waiver(
        cls, pool: asyncpg.Pool, waiver_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        return await cls._decide_waiver_without_money(
            pool, waiver_id, req, user_id, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, new_status=REQUEST_STATUS_REJECTED,
        )

    @classmethod
    async def cancel_waiver(
        cls, pool: asyncpg.Pool, waiver_id: int, req, user_id: int,
        client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        return await cls._decide_waiver_without_money(
            pool, waiver_id, req, user_id, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, new_status=REQUEST_STATUS_CANCELLED,
        )

    @classmethod
    async def _decide_waiver_without_money(
        cls, pool: asyncpg.Pool, waiver_id: int, req, user_id: int,
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
                    waiver = await cls._load_waiver_for_update(conn, waiver_id, target_room_id)
                    if waiver["status"] != REQUEST_STATUS_PENDING:
                        raise ValueError("คำขอนี้ถูกดำเนินการไปแล้ว")
                    decided = await conn.fetchrow(
                        """UPDATE fine_waivers
                           SET status = $1, decided_by = $2, decided_at = CURRENT_TIMESTAMP,
                               decision_note = $3, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $4
                           RETURNING *""",
                        new_status, user_id, getattr(req, "note", None), waiver_id,
                    )
                    label = {
                        REQUEST_STATUS_REJECTED: "ไม่อนุมัติ",
                        REQUEST_STATUS_CANCELLED: "ยกเลิกคำขอ",
                    }[new_status]
                    if waiver["requested_by"]:
                        await notify_user(
                            conn, room_id=target_room_id,
                            user_id=waiver["requested_by"],
                            group_type="finance", type="fine_waiver_decided",
                            title=f"{label}ยกเว้นค่าปรับ {float(waiver['amount']):,.2f} บาท",
                            body=f"ค่าปรับ #{waiver['fine_id']}",
                            entity_type="fine", entity_id=waiver["fine_id"],
                            url=f"/finance/fines/{waiver['fine_id']}",
                        )
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER",
                        entity_id=str(waiver_id), status="success",
                        old_values=dict(waiver), new_values=dict(decided),
                        endpoint_or_command=f"FinanceService.{new_status}_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            return {
                "status": "success",
                "message": f"{label}แล้ว",
                "waiver": cls._shape_request(decided, "waiver"),
            }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINE_WAIVER",
                        entity_id=str(waiver_id), status="failed", error_detail=str(e),
                        endpoint_or_command=f"FinanceService.{new_status}_waiver",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e
