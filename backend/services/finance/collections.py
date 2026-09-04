"""แคมเปญเก็บเงิน (fee_collections) + การชำระเงิน + ลูกหนี้"""
import asyncpg
import io
import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

from .constants import (
    THAI_TZ, CUTOFF_DATE, MONEY_NUM_FMT, PCT_NUM_FMT, ACCOUNT_TYPE_LABELS,
    COLLECTION_STATUS_LABELS, REFERENCE_TYPE_LABELS, MANAGEMENT_TAB_COLORS,
    ACCOUNTING_TAB_COLORS, RECONCILE_REFERENCE_TYPE, RECONCILE_EQUITY_CODE,
    RECONCILE_EQUITY_NAME, _CLAMP_START_NOTE, _CLAMP_EMPTY_NOTE,
    DEFAULT_INCOME_CATEGORIES, DEFAULT_EXPENSE_CATEGORIES, DEFAULT_FINANCE_ACCOUNTS,
)
from .helpers import (
    _naive_thai_dt, _clamp_to_cutoff, _ExportPeriodView, _resolve_inclusive_period,
    _legacy_id_from_journal,
)
from .base import service_logger


class CollectionsMixin:
    @classmethod
    async def create_fee_collection(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    collection_id = await conn.fetchval(
                        "INSERT INTO fee_collections (room_id, title, amount, due_date) VALUES ($1, $2, $3, $4) RETURNING id",
                        target_room_id, req.title, req.amount, req.due_date
                    )
                    
                    target_students = []
                    if req.student_ids is not None:
                        if len(req.student_ids) == 0:
                            raise ValueError("ไม่สามารถสร้างรายการได้ เนื่องจากไม่ได้เลือกนักเรียนเลยแม้แต่คนเดียว")

                        # 💡 กรอง id ซ้ำก่อน query + INSERT กัน UniqueViolationError (student_payments มี UNIQUE(collection_id, student_id))
                        unique_ids = list(dict.fromkeys(req.student_ids))
                        valid_students = await conn.fetch(
                            "SELECT id FROM students WHERE room_id = $1 AND id = ANY($2) AND status = 'active'",
                            target_room_id, unique_ids
                        )
                        target_students = [s['id'] for s in valid_students]
                    else:
                        all_students = await conn.fetch("SELECT id FROM students WHERE room_id = $1 AND status = 'active'", target_room_id)
                        target_students = [s['id'] for s in all_students]

                    if target_students:
                        # 🛡️ กัน id ซ้ำใน target_students (ป้องกัน UniqueViolation ถ้า query คืนค่าซ้ำ)
                        target_students = list(dict.fromkeys(target_students))
                        records = [(collection_id, sid, 'pending') for sid in target_students]
                        await conn.executemany("INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, $3)", records)
                    
                    new_values = cls._extract_req_data(req)
                    new_values["resolved_target_students"] = target_students
                    msg = f"สร้างแคมเปญสำเร็จ เรียกเก็บเพื่อน {len(target_students)} คน"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", entity_id=str(collection_id), status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_fee_collection", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: สร้างแคมเปญเก็บเงินใหม่ → @everyone (ทุกคนต้องรู้)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_new_collection(
                    server_id=room_server_id,
                    title=req.title,
                    amount=float(req.amount),
                    due_date=req.due_date,
                    user_name=req.user_name,
                )
            return {"status": "success", "message": msg}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_fee_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _confirm_single_payment(
        cls, conn: asyncpg.Connection, target_room_id: int,
        payment_id: int, paid_amount: float, paid_to_account_id: int,
        slip_image_url: Optional[str], user_name: str,
    ) -> dict:
        """[SHARED] รับเงิน 1 บิล (student_payment) — ใช้ร่วมโดย confirm_payment (บิลเดียว)
        และ batch_confirm_payments (รวบยอด). ต้องถูกเรียกภายใน `async with conn.transaction():`
        ของ caller เสมอ (batch จะได้ atomic ทั้งชุด). คืนข้อมูลสำหรับ audit log + publish."""
        valid_account = await conn.fetchval("SELECT id FROM finance_accounts WHERE id = $1 AND room_id = $2", paid_to_account_id, target_room_id)
        if not valid_account: raise ValueError("กระเป๋าเงินไม่มีอยู่ หรือไม่ใช่ของห้องนี้!")

        old_sp_data = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1 FOR UPDATE", payment_id)
        old_values = dict(old_sp_data) if old_sp_data else {}

        payment_info = await conn.fetchrow(
            """SELECT FC.amount as total_amount, SP.paid_amount as current_paid, FC.title,
                      U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               JOIN students S ON SP.student_id = S.id
               LEFT JOIN users U ON S.user_id = U.id
               WHERE SP.id = $1 AND FC.room_id = $2 AND FC.status = 'active'""",
            payment_id, target_room_id
        )
        if not payment_info: raise PaymentNotFoundError("ไม่พบรายการนี้ หรือแคมเปญถูกปิดไปแล้ว")

        current_paid = float(payment_info['current_paid'])
        total_amount = float(payment_info['total_amount'])

        if current_paid >= total_amount: raise ValueError("บิลนี้จ่ายครบไปเรียบร้อยแล้วครับ!")

        # 🛡️ กัน overpay: ห้ามรับเงินเกินยอดที่เหลือค้าง (current_paid + paid_amount > total)
        if paid_amount > total_amount - current_paid:
            raise ValueError(
                f"จำนวนเงินที่รับเกินยอดที่เหลือค้าง! "
                f"เหลือค้าง {total_amount - current_paid:.2f} บาท แต่ส่งมา {paid_amount:.2f} บาท"
            )

        new_total_paid = current_paid + paid_amount
        new_status = 'paid' if new_total_paid >= total_amount else 'pending'
        status_msg = "จ่ายครบแล้ว" if new_status == 'paid' else f"ทยอยจ่าย (ขาดอีก {total_amount - new_total_paid} ฿)"

        stu_name = payment_info['first_name'] or payment_info.get('first_name_en') or "Unknown"
        if payment_info['nickname']: stu_name += f" ({payment_info['nickname']})"
        dynamic_desc = f"รับเงิน: {payment_info['title']} จาก {stu_name} [{status_msg}]"

        trans_id = await conn.fetchval(
            """INSERT INTO finance_transactions
               (room_id, account_id, amount, description, transaction_type, slip_image_url, recorded_by, student_payment_id)
               VALUES ($1, $2, $3, $4, 'income', $5, $6, $7) RETURNING id""",
            target_room_id, paid_to_account_id, paid_amount, dynamic_desc, slip_image_url, user_name, payment_id
        )

        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", paid_amount, paid_to_account_id)
        await conn.execute(
            """UPDATE student_payments
               SET status = $1, paid_amount = $2, paid_to_account_id = $3, slip_image_url = $4, recorded_by = $5, paid_at = NOW(), transaction_id = $6
               WHERE id = $7""",
            new_status, new_total_paid, paid_to_account_id, slip_image_url, user_name, trans_id, payment_id
        )

        # [DUAL-WRITE] เขียนฝั่ง Double-Entry: รับชำระเงินจากนักเรียน (Dr สินทรัพย์ / Cr รายได้เก็บเงินห้อง)
        asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, paid_to_account_id)
        # Credit ขาเป็นรายได้ "เก็บเงินห้องปกติ" — ถ้าไม่มี mapping ให้หา ledger ตามชื่อ
        # (seed ค่าเริ่มต้น DEFAULT_INCOME_CATEGORIES[0] = '📥 เก็บเงินห้องปกติ')
        revenue_ledger_id = await cls._find_revenue_ledger_by_name(
            conn, target_room_id, account_name=DEFAULT_INCOME_CATEGORIES[0]
        )
        if revenue_ledger_id is None:
            # [FIX A] ปิดรอยรั่วข้าม dual-write: ห้องที่ยังไม่มี ledger รายได้/หมวดหมู่ค่าเริ่มต้น
            # → สร้างหมวด '📥 เก็บเงินห้องปกติ' (ถ้ายังไม่มี) + revenue ledger ให้อัตโนมัติ
            # เพื่อให้ journal ครบฝั่ง (กัน "legacy ได้เงิน แต่บัญชีคู่ไม่มีบิล")
            legacy_cat_id = await cls._find_or_create_default_income_category(conn, target_room_id)
            if legacy_cat_id:
                revenue_ledger_id = await cls._resolve_category_ledger(conn, target_room_id, legacy_cat_id, 'income')
        # ห้ามข้าม dual-write: ถ้าหา/สร้าง ledger รายได้ไม่ได้ → error (rollback ทั้งชุด) แทนที่จะเงียบ
        if revenue_ledger_id is None:
            raise ValueError("ไม่สามารถหา/สร้าง ledger รายได้ '📥 เก็บเงินห้องปกติ' เพื่อบันทึกบัญชีคู่ได้")
        else:
            await cls._insert_journal_entry(
                conn, target_room_id,
                reference_type="student_payment",
                reference_id=str(payment_id),
                description=dynamic_desc,
                slip_image_url=slip_image_url,
                recorded_by=user_name,
                metadata={"student_payment_id": payment_id, "legacy_transaction_id": trans_id},
                lines=[
                    {"ledger_id": asset_ledger_id, "debit": paid_amount, "credit": 0, "line_description": f"รับเงินจากนักเรียน (student_payment #{payment_id})"},
                    {"ledger_id": revenue_ledger_id, "debit": 0, "credit": paid_amount, "line_description": f"รายได้: {payment_info['title']}"},
                ],
            )

        return {
            "payment_id": payment_id,
            "student_payment_id": payment_id,
            "trans_id": trans_id,
            "payer_name": stu_name,
            "title": payment_info['title'],
            "amount": paid_amount,
            "status_msg": status_msg,
            "old_values": old_values,
            "new_values": {
                "payment_id": payment_id,
                "paid_amount": paid_amount,
                "paid_to_account_id": paid_to_account_id,
                "slip_image_url": slip_image_url,
                "user_name": user_name,
            },
        }

    @classmethod
    async def confirm_payment(cls, pool: asyncpg.Pool, payment_id: int, req, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: มีแค่ผู้ดูแลการเงิน (MANAGE_FINANCE) ถึงจะรับเงินได้
                    if user_id is not None:
                        await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    result = await cls._confirm_single_payment(
                        conn=conn, target_room_id=target_room_id,
                        payment_id=payment_id,
                        paid_amount=req.paid_amount,
                        paid_to_account_id=req.paid_to_account_id,
                        slip_image_url=req.slip_image_url,
                        user_name=req.user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(payment_id), status="success",
                        old_values=result["old_values"], new_values=result["new_values"], endpoint_or_command="FinanceService.confirm_payment", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: มีคนจ่ายเงินแล้ว (ไม่ @everyone — โชว์ความโปร่งใส)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_payment_confirmed(
                    server_id=room_server_id,
                    payer_name=result["payer_name"],
                    title=result["title"],
                    amount=float(result["amount"]),
                    user_name=req.user_name,
                )
            return {"status": "success", "message": f"รับเงินสำเร็จ! สถานะ: {result['status_msg']}"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(payment_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.confirm_payment", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def batch_confirm_payments(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        """✨ รับเงินรวบยอด (Batch): ปลดหนี้หลายบิลของนักเรียนคนเดียวกันใน transaction เดียว
        → publish แจ้งเตือน Discord แค่รอบเดียว (ไม่เด้งหลาย embed เหมือนยิงทีละบิล).
        ถ้าบิลใดบิลหนึ่ง error → rollback ทั้งชุด (atomic)."""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: มีแค่ผู้ดูแลการเงิน (MANAGE_FINANCE) ถึงจะรับเงินได้
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 กันรายการซ้ำใน request (จ่ายบิลเดียวกันเบิ้ล) — เอาแค่ตัวแรก
                    seen_ids, items = set(), []
                    for item in req.items:
                        if item.payment_id in seen_ids:
                            continue
                        seen_ids.add(item.payment_id)
                        items.append(item)

                    payment_ids = [item.payment_id for item in items]
                    rows = await conn.fetch(
                        """SELECT SP.id, SP.student_id
                           FROM student_payments SP
                           JOIN fee_collections FC ON SP.collection_id = FC.id
                           WHERE SP.id = ANY($1) AND FC.room_id = $2 AND FC.status = 'active'""",
                        payment_ids, target_room_id
                    )
                    found_ids = {r['id'] for r in rows}
                    for item in items:
                        if item.payment_id not in found_ids:
                            raise PaymentNotFoundError(f"ไม่พบรายการ #{item.payment_id} หรือแคมเปญถูกปิดไปแล้ว")

                    # 🛡️ Batch ต้องเป็นบิลของนักเรียนคนเดียวกัน (มิฉะนั้นแจ้งเตือนรวมจะงง + จ่ายข้ามคน)
                    student_ids = {r['student_id'] for r in rows}
                    if len(student_ids) > 1:
                        raise ValueError("รายการชำระเงินต้องเป็นของนักเรียนคนเดียวกัน!")

                    results = []
                    for item in items:
                        result = await cls._confirm_single_payment(
                            conn=conn, target_room_id=target_room_id,
                            payment_id=item.payment_id,
                            paid_amount=item.paid_amount,
                            paid_to_account_id=req.paid_to_account_id,
                            slip_image_url=req.slip_image_url,
                            user_name=req.user_name,
                        )
                        results.append(result)

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                            room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(item.payment_id), status="success",
                            old_values=result["old_values"], new_values=result["new_values"], endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                        )

                    # audit log ระดับ batch (ยืนยันว่ารับกี่รายการ ผ่าน endpoint ไหน)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT_BATCH", status="success",
                        new_values=cls._extract_req_data(req), endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                    )

                    # 📢 publish ครั้งเดียว หลัง commit (รวบรวมบิลทั้งหมด)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id and results:
                await ActionService.notify_payments_confirmed(
                    server_id=room_server_id,
                    payer_name=results[0]["payer_name"],
                    items=[{"title": r["title"], "amount": float(r["amount"])} for r in results],
                    total_amount=float(sum(r["amount"] for r in results)),
                    user_name=req.user_name,
                )
            return {"status": "success", "message": f"รับเงินรวบยอด {len(results)} รายการสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT_BATCH", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_collection_status(cls, pool: asyncpg.Pool, collection_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                sql = """
                    SELECT 
                        SP.id as payment_id, SP.student_id, SP.status, SP.paid_amount, SP.paid_at, SP.slip_image_url,
                        S.student_no, U.first_name, U.last_name, U.nickname,
                        U.first_name_en, U.last_name_en, U.nickname_en, FC.amount as total_amount
                    FROM student_payments SP
                    JOIN students S ON SP.student_id = S.id
                    LEFT JOIN users U ON S.user_id = U.id
                    JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE SP.collection_id = $1 AND S.room_id = $2
                    ORDER BY S.student_no ASC
                """
                rows = await conn.fetch(sql, collection_id, target_room_id)
                total = len(rows)
                paid_count = sum(1 for r in rows if r['status'] == 'paid')
                result = {"collection_id": collection_id, "summary": {"total": total, "paid": paid_count, "pending": total - paid_count}, "students": [dict(r) for r in rows]}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(collection_id), status="success",
                    endpoint_or_command="FinanceService.get_collection_status", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(collection_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_collection_status", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def remove_student_from_collection(cls, pool: asyncpg.Pool, collection_id: int, student_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    payment = await conn.fetchrow("""
                        SELECT SP.*, FC.title 
                        FROM student_payments SP
                        JOIN fee_collections FC ON SP.collection_id = FC.id
                        WHERE SP.collection_id = $1 AND SP.student_id = $2 AND FC.room_id = $3
                        FOR UPDATE OF SP
                    """, collection_id, student_id, target_room_id)

                    if not payment:
                        raise PaymentNotFoundError("ไม่พบข้อมูลการเรียกเก็บเงินของนักเรียนคนนี้")
                    
                    old_values = dict(payment)
                    if payment['paid_amount'] > 0:
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากนักเรียนมีการจ่ายเงิน (หรือทยอยจ่าย) เข้ามาแล้ว ให้ใช้วิธียกเลิกธุรกรรมการเงินแทน")

                    await conn.execute("DELETE FROM student_payments WHERE id = $1", payment['id'])

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", entity_id=str(payment['id']), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.remove_student_from_collection", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "ลบรายชื่อนักเรียนออกจากรายการนี้สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.remove_student_from_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_student_debts(cls, pool: asyncpg.Pool, student_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                student = await conn.fetchrow("SELECT S.id, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en FROM students S LEFT JOIN users U ON S.user_id = U.id WHERE S.id = $1 AND S.room_id = $2", student_id, target_room_id)
                if not student: raise RoomNotFoundError("ไม่พบข้อมูลนักเรียนคนนี้ในห้อง")

                rows = await conn.fetch("""
                    SELECT SP.id as payment_id, FC.id as collection_id, FC.title, (FC.amount - COALESCE(SP.paid_amount, 0)) AS amount, FC.due_date, FC.status AS collection_status
                    FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE SP.student_id = $1 AND SP.status = 'pending' AND FC.room_id = $2
                    ORDER BY FC.status ASC, FC.due_date ASC
                """, student_id, target_room_id)

                formatted_debts, total_pending = [], 0.0
                for r in rows:
                    row_dict = dict(r)
                    row_dict['amount'] = float(row_dict['amount'])
                    formatted_debts.append(row_dict)
                    total_pending += row_dict['amount']

                formatted_name = student['first_name'] or student.get('first_name_en') or "Unknown"
                if student['nickname']: formatted_name += f" ({student['nickname']})"

                result = {"student_id": student_id, "student_name": formatted_name, "total_pending_amount": total_pending, "debts": formatted_debts}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_DEBT", entity_id=str(student_id), status="success",
                    endpoint_or_command="FinanceService.get_student_debts", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_DEBT", entity_id=str(student_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_student_debts", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def add_student_to_collection(cls, pool: asyncpg.Pool, collection_id: int, student_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🛡️ ต้องเป็นสมาชิก active เท่านั้น (กัน pending/left student เข้ารายการเก็บเงิน)
                    if not await conn.fetchval("SELECT id FROM students WHERE id = $1 AND room_id = $2 AND status = 'active'", student_id, target_room_id):
                        raise RoomNotFoundError("ไม่พบเด็กคนนี้ในห้อง")
                    if not await conn.fetchval("SELECT id FROM fee_collections WHERE id = $1 AND room_id = $2 AND status = 'active'", collection_id, target_room_id):
                        raise ValueError("ไม่พบรายการเรียกเก็บเงินนี้ หรือแคมเปญถูกปิดไปแล้ว!")

                    try:
                        await conn.execute("INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, 'pending')", collection_id, student_id)
                    except asyncpg.exceptions.UniqueViolationError:
                        raise ValueError("เพื่อนคนนี้มีชื่อในรายการนี้อยู่แล้ว")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="success",
                        new_values={"collection_id": collection_id, "student_id": student_id}, endpoint_or_command="FinanceService.add_student_to_collection", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "เพิ่มเพื่อนเข้าสู่การเก็บเงินแล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.add_student_to_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_all_collections(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("SELECT id, title, amount, due_date, status FROM fee_collections WHERE room_id = $1 ORDER BY id DESC", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FEE_COLLECTION", status="success",
                    endpoint_or_command="FinanceService.get_all_collections", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_all_collections", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_collection(cls, pool: asyncpg.Pool, collection_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    current_data = await conn.fetchrow("SELECT * FROM fee_collections WHERE id = $1 AND room_id = $2", collection_id, target_room_id)
                    if not current_data: raise RoomNotFoundError("ไม่พบแคมเปญนี้")
                    old_values = dict(current_data)

                    updates, values, idx, changed_labels = [], [], 1, []
                    
                    if req.title is not None:
                        updates.append(f"title = ${idx}"); values.append(req.title); idx += 1; changed_labels.append("title")
                    if req.amount is not None and float(req.amount) != float(current_data['amount']):
                        if await conn.fetchval("SELECT 1 FROM student_payments WHERE collection_id = $1 AND paid_amount > 0 LIMIT 1", collection_id):
                            raise ValueError("ไม่สามารถแก้จำนวนเงินได้ เนื่องจากมีเงินโอนเข้ามาแล้ว!")
                        updates.append(f"amount = ${idx}"); values.append(req.amount); idx += 1; changed_labels.append("amount")
                    if req.due_date is not None:
                        updates.append(f"due_date = ${idx}"); values.append(req.due_date); idx += 1; changed_labels.append("due_date")
                    if req.status is not None:
                        updates.append(f"status = ${idx}"); values.append(req.status); idx += 1; changed_labels.append("status")

                    if not updates: return {"status": "success", "message": "ไม่มีข้อมูลให้เปลี่ยนแปลง"}

                    values.extend([collection_id, target_room_id])
                    res = await conn.execute(f"UPDATE fee_collections SET {', '.join(updates)} WHERE id = ${idx} AND room_id = ${idx + 1}", *values)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบแคมเปญนี้")

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", entity_id=str(collection_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_collection", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตข้อมูลสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_all_debtors(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id as student_id, S.student_no, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en,
                           COUNT(SP.id) as overdue_count, SUM(FC.amount - SP.paid_amount) as total_pending_amount
                    FROM students S LEFT JOIN users U ON S.user_id = U.id
                    JOIN student_payments SP ON S.id = SP.student_id JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE S.room_id = $1 AND SP.status = 'pending'
                    GROUP BY S.id, S.student_no, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en ORDER BY S.student_no ASC
                """, target_room_id)
                debtors = []
                for r in rows:
                    name = r['first_name'] or r.get('first_name_en') or "Unknown"
                    if r['nickname']: name += f" ({r['nickname']})"
                    debtors.append({"student_id": r['student_id'], "student_no": r['student_no'], "student_name": name, "overdue_count": r['overdue_count'], "total_pending_amount": float(r['total_pending_amount'])})
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="DEBTOR_LIST", status="success",
                    endpoint_or_command="FinanceService.get_all_debtors", execution_time_ms=exec_time
                )
                return debtors
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="DEBTOR_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_all_debtors", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
