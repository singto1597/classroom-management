import asyncpg
import time
from typing import List, Optional, Dict, Any
from datetime import date

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission, require_member

service_logger = AuditLogger(service_name="FINANCE")

class FinanceService:
    @staticmethod
    def _extract_req_data(req) -> dict:
        if isinstance(req, dict):
            return req
        if hasattr(req, 'dict') and callable(req.dict):
            return req.dict()
        try:
            return vars(req)
        except Exception:
            return {"raw_data": str(req)}

    @staticmethod
    def _finance_actor(req) -> str:
        n = getattr(req, "user_name", None)
        if n is not None and str(n).strip():
            return str(n).strip()[:200]
        return "—"

    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: 
                raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id")

    @classmethod
    async def get_active_students(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id, S.student_no, U.first_name, U.last_name, U.nickname
                    FROM students S
                    LEFT JOIN users U ON S.user_id = U.id
                    WHERE S.room_id = $1 AND S.status = 'active' AND S.deleted_at IS NULL
                    ORDER BY S.student_no ASC
                """, target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="success",
                    endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def create_account(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    await conn.execute(
                        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3)",
                        target_room_id, req.account_name, req.initial_balance
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"สร้างบัญชี {req.account_name} สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_accounts(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("SELECT id, account_name, balance FROM finance_accounts WHERE room_id = $1 ORDER BY id", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="success",
                    endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def add_transaction(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 FOR UPDATE",
                        req.account_id, target_room_id
                    )
                    if current_balance is None: raise ValueError("ไม่พบบัญชีนี้ในห้องของคุณ")
                    if req.transaction_type == 'expense' and current_balance < req.amount:
                        raise ValueError(f"เงินไม่พอ! ยอดคงเหลือคือ {current_balance} บาท")
                    
                    cat = await conn.fetchrow("SELECT room_id, category_type FROM finance_categories WHERE id = $1", req.category_id)
                    if not cat or cat['room_id'] != target_room_id: raise ValueError("หมวดหมู่นี้ไม่มีอยู่ หรือไม่ใช่ของห้องคุณ!")
                    if cat['category_type'] != req.transaction_type:
                        raise ValueError(f"ประเภทหมวดหมู่ ({cat['category_type']}) ไม่ตรงกับประเภทการบันทึก ({req.transaction_type})!")

                    await conn.execute(
                        """INSERT INTO finance_transactions 
                           (room_id, account_id, category_id, amount, description, transaction_type, slip_image_url, recorded_by) 
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        target_room_id, req.account_id, req.category_id, req.amount, 
                        req.description, req.transaction_type, req.slip_image_url, req.user_name
                    )
                    
                    if req.transaction_type == 'income':
                        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.account_id)
                    elif req.transaction_type == 'expense':
                        await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.account_id)

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "บันทึกรายการสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def transfer_money(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        if req.from_account_id == req.to_account_id: raise ValueError("โอนเงินเข้าบัญชีเดิมไม่ได้!")

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 FOR UPDATE", 
                        req.from_account_id, target_room_id
                    )
                    if current_balance is None: raise RoomNotFoundError("ไม่พบบัญชีต้นทาง")
                    if current_balance < req.amount: raise ValueError("ยอดเงินในบัญชีต้นทางไม่เพียงพอ!")

                    group_id = await conn.fetchval("SELECT nextval('transfer_group_id_seq')")
                    
                    await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.from_account_id)
                    await conn.execute(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by) 
                           VALUES ($1, $2, $3, $4, 'expense', $5, $6)""",
                        target_room_id, req.from_account_id, req.amount, f"โอนออก: {req.description}", group_id, req.user_name
                    )
                    
                    await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.to_account_id)
                    await conn.execute(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by) 
                           VALUES ($1, $2, $3, $4, 'income', $5, $6)""",
                        target_room_id, req.to_account_id, req.amount, f"รับโอน: {req.description}", group_id, req.user_name
                    )
                    
                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", entity_id=str(group_id), status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "โอนเงินสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_transactions(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                where_clause = "WHERE T.room_id = $1 AND T.deleted_at IS NULL"
                params = [target_room_id]
                param_idx = 2
                
                if start_date:
                    where_clause += f" AND DATE(T.created_at) >= ${param_idx}"
                    params.append(start_date); param_idx += 1
                if end_date:
                    where_clause += f" AND DATE(T.created_at) <= ${param_idx}"
                    params.append(end_date); param_idx += 1
                if account_id:
                    where_clause += f" AND T.account_id = ${param_idx}"
                    params.append(account_id); param_idx += 1
                if category_id:
                    where_clause += f" AND T.category_id = ${param_idx}"
                    params.append(category_id); param_idx += 1
                if transaction_type:
                    where_clause += f" AND T.transaction_type = ${param_idx}"
                    params.append(transaction_type); param_idx += 1
                    
                total_count = await conn.fetchval(f"SELECT COUNT(*) FROM finance_transactions T {where_clause}", *params)

                data_sql = f"""
                    SELECT 
                        T.id, T.amount, T.description, T.transaction_type, T.created_at, 
                        T.slip_image_url, T.recorded_by, T.transfer_group_id,
                        A.account_name, C.category_name 
                    FROM finance_transactions T
                    LEFT JOIN finance_accounts A ON T.account_id = A.id
                    LEFT JOIN finance_categories C ON T.category_id = C.id
                    {where_clause}
                    ORDER BY T.created_at DESC LIMIT ${param_idx} OFFSET ${param_idx+1}
                """
                data_params = params.copy()
                data_params.extend([limit, offset])
                
                rows = await conn.fetch(data_sql, *data_params)
                result = {"total_count": total_count, "items": [dict(row) for row in rows]}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                    endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

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
                        
                        valid_students = await conn.fetch(
                            "SELECT id FROM students WHERE room_id = $1 AND id = ANY($2) AND status = 'active'", 
                            target_room_id, req.student_ids
                        )
                        target_students = [s['id'] for s in valid_students]
                    else:
                        all_students = await conn.fetch("SELECT id FROM students WHERE room_id = $1 AND status = 'active'", target_room_id)
                        target_students = [s['id'] for s in all_students]
                    
                    if target_students:
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
    async def confirm_payment(cls, pool: asyncpg.Pool, payment_id: int, req, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    valid_account = await conn.fetchval("SELECT id FROM finance_accounts WHERE id = $1 AND room_id = $2", req.paid_to_account_id, target_room_id)
                    if not valid_account: raise ValueError("กระเป๋าเงินไม่มีอยู่ หรือไม่ใช่ของห้องนี้!")

                    old_sp_data = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1 FOR UPDATE", payment_id)
                    old_values = dict(old_sp_data) if old_sp_data else {}

                    payment_info = await conn.fetchrow(
                        """SELECT FC.amount as total_amount, SP.paid_amount as current_paid, FC.title, U.first_name, U.nickname 
                           FROM student_payments SP
                           JOIN fee_collections FC ON SP.collection_id = FC.id
                           JOIN students S ON SP.student_id = S.id
                           LEFT JOIN users U ON S.user_id = U.id 
                           WHERE SP.id = $1 AND FC.room_id = $2""", 
                        payment_id, target_room_id 
                    )
                    if not payment_info: raise PaymentNotFoundError("ไม่พบรายการนี้")
                    
                    current_paid = float(payment_info['current_paid'])
                    total_amount = float(payment_info['total_amount'])

                    if current_paid >= total_amount: raise ValueError("บิลนี้จ่ายครบไปเรียบร้อยแล้วครับ!")

                    new_total_paid = current_paid + req.paid_amount
                    new_status = 'paid' if new_total_paid >= total_amount else 'pending'
                    status_msg = "จ่ายครบแล้ว" if new_status == 'paid' else f"ทยอยจ่าย (ขาดอีก {total_amount - new_total_paid} ฿)"

                    stu_name = payment_info['first_name'] or "Unknown"
                    if payment_info['nickname']: stu_name += f" ({payment_info['nickname']})"
                    dynamic_desc = f"รับเงิน: {payment_info['title']} จาก {stu_name} [{status_msg}]"
                    
                    trans_id = await conn.fetchval(
                        """INSERT INTO finance_transactions 
                           (room_id, account_id, amount, description, transaction_type, slip_image_url, recorded_by, student_payment_id) 
                           VALUES ($1, $2, $3, $4, 'income', $5, $6, $7) RETURNING id""",
                        target_room_id, req.paid_to_account_id, req.paid_amount, dynamic_desc, req.slip_image_url, req.user_name, payment_id
                    )
                    
                    await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.paid_amount, req.paid_to_account_id)
                    await conn.execute(
                        """UPDATE student_payments 
                           SET status = $1, paid_amount = $2, paid_to_account_id = $3, slip_image_url = $4, recorded_by = $5, paid_at = NOW(), transaction_id = $6 
                           WHERE id = $7""",
                        new_status, new_total_paid, req.paid_to_account_id, req.slip_image_url, req.user_name, trans_id, payment_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(payment_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.confirm_payment", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": f"รับเงินสำเร็จ! สถานะ: {status_msg}"}
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
                        S.student_no, U.first_name, U.last_name, U.nickname, FC.amount as total_amount
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
    async def create_category(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await conn.execute("INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3)", target_room_id, req.category_name, req.category_type)
                    
                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"เพิ่มหมวดหมู่ {req.category_name} แล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_categories(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, cat_type: Optional[str] = None, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                if cat_type:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 AND category_type = $2 ORDER BY id", target_room_id, cat_type)
                else:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 ORDER BY id", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="success",
                    endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def revert_transaction(cls, pool: asyncpg.Pool, transaction_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    t = await conn.fetchrow(
                        "SELECT * FROM finance_transactions WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        transaction_id, target_room_id
                    )
                    if not t: raise TransactionNotFoundError("ไม่พบรายการธุรกรรมนี้")
                    old_values = dict(t)

                    if t['transfer_group_id']:
                        group_trans = await conn.fetch("SELECT * FROM finance_transactions WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE", t['transfer_group_id'], target_room_id)
                        for gt in group_trans:
                            if gt['transaction_type'] == 'expense': 
                                await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", gt['amount'], gt['account_id'])
                            elif gt['transaction_type'] == 'income': 
                                curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", gt['account_id'])
                                if curr_bal < gt['amount']: raise ValueError("เงินในบัญชีรับโอนไม่พอหักคืน")
                                await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", gt['amount'], gt['account_id'])
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE transfer_group_id = $1 AND room_id = $2", t['transfer_group_id'], target_room_id)
                        action_detail = "ยกเลิกรายการโอนเงิน"
                    else:
                        if t['transaction_type'] == 'income': 
                            curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", t['account_id'])
                            if curr_bal < t['amount']: raise ValueError("เงินในบัญชีไม่พอหักคืน")
                            await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", t['amount'], t['account_id'])
                            
                            if t['student_payment_id']:
                                sp_id = t['student_payment_id']
                                sp_info = await conn.fetchrow("SELECT paid_amount, FC.amount as total_amount FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id WHERE SP.id = $1 FOR UPDATE", sp_id)
                                new_paid = float(sp_info['paid_amount']) - float(t['amount'])
                                new_status = 'paid' if new_paid >= float(sp_info['total_amount']) else 'pending'
                                await conn.execute("UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3", new_paid, new_status, sp_id)

                        elif t['transaction_type'] == 'expense': 
                            await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", t['amount'], t['account_id'])
                        
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", transaction_id)
                        action_detail = f"ยกเลิกรายการ {t['transaction_type']}"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="success",
                        old_values=old_values, new_values={"action": action_detail}, endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": action_detail}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
            
    @classmethod
    async def get_summary(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, month: Optional[int] = None, year: Optional[int] = None, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                net_worth = await conn.fetchval("SELECT SUM(balance) FROM finance_accounts WHERE room_id = $1", target_room_id) or 0.0

                params = [target_room_id]
                if month and year:
                    date_cond = "AND EXTRACT(MONTH FROM created_at) = $2 AND EXTRACT(YEAR FROM created_at) = $3"
                    date_cond_t = "AND EXTRACT(MONTH FROM T.created_at) = $2 AND EXTRACT(YEAR FROM T.created_at) = $3"
                    params.extend([month, year])
                    period_str = f"{year}-{month:02d}"
                else:
                    date_cond = "AND date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)"
                    date_cond_t = "AND date_trunc('month', T.created_at) = date_trunc('month', CURRENT_DATE)"
                    period_str = "current_month"
                
                stats = await conn.fetchrow(f"""
                    SELECT 
                        SUM(CASE WHEN transaction_type = 'income' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_inc,
                        SUM(CASE WHEN transaction_type = 'expense' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_exp
                    FROM finance_transactions WHERE room_id = $1 AND deleted_at IS NULL {date_cond}
                """, *params)
                
                breakdown = await conn.fetch(f"""
                    SELECT C.category_name, SUM(T.amount) as total_amount
                    FROM finance_transactions T
                    JOIN finance_categories C ON T.category_id = C.id
                    WHERE T.room_id = $1 AND T.transaction_type = 'expense' AND T.transfer_group_id IS NULL AND T.deleted_at IS NULL {date_cond_t}
                    GROUP BY C.category_name ORDER BY total_amount DESC
                """, *params)

                pending_collection = await conn.fetchval("""
                    SELECT SUM(FC.amount - SP.paid_amount) FROM student_payments SP
                    JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE SP.status = 'pending' AND FC.room_id = $1 AND FC.status = 'active'
                """, target_room_id) or 0.0

                result = {
                    "net_worth": float(net_worth), "total_income": float(stats['total_inc'] or 0),       
                    "total_expense": float(stats['total_exp'] or 0), "pending_collection_amount": float(pending_collection),
                    "period": period_str, "expense_breakdown": [dict(b) for b in breakdown]
                }

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="success",
                    endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
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
                student = await conn.fetchrow("SELECT S.id, U.first_name, U.nickname FROM students S LEFT JOIN users U ON S.user_id = U.id WHERE S.id = $1 AND S.room_id = $2", student_id, target_room_id)
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

                formatted_name = student['first_name'] or "Unknown"
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

                    if not await conn.fetchval("SELECT id FROM students WHERE id = $1 AND room_id = $2", student_id, target_room_id):
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
                    if req.amount is not None and req.amount != current_data['amount']:
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
    async def update_account(cls, pool: asyncpg.Pool, account_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)

                    res = await conn.execute("UPDATE finance_accounts SET account_name = $1 WHERE id = $2 AND room_id = $3", req.account_name, account_id, target_room_id)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    
                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_account(cls, pool: asyncpg.Pool, account_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)
                    
                    bal = old_data['balance']
                    if bal > 0: raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากยังมีเงินคงเหลืออยู่!")
                    if await conn.fetchval("SELECT 1 FROM student_payments WHERE paid_to_account_id = $1 LIMIT 1", account_id):
                        raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติการรับเงินผูกกับบัญชีนี้อยู่!")
                    
                    await conn.execute("DELETE FROM finance_accounts WHERE id = $1", account_id)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
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
                    SELECT S.id as student_id, S.student_no, U.first_name, U.nickname, COUNT(SP.id) as overdue_count, SUM(FC.amount - SP.paid_amount) as total_pending_amount
                    FROM students S LEFT JOIN users U ON S.user_id = U.id
                    JOIN student_payments SP ON S.id = SP.student_id JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE S.room_id = $1 AND SP.status = 'pending'
                    GROUP BY S.id, S.student_no, U.first_name, U.nickname ORDER BY S.student_no ASC
                """, target_room_id)
                debtors = []
                for r in rows:
                    name = r['first_name'] or "Unknown"
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
    
    @classmethod
    async def update_category(cls, pool: asyncpg.Pool, category_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    res = await conn.execute("UPDATE finance_categories SET category_name = $1 WHERE id = $2 AND room_id = $3", req.category_name, category_id, target_room_id)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    
                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_category(cls, pool: asyncpg.Pool, category_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE category_id = $1 LIMIT 1", category_id):
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากมีการใช้หมวดหมู่นี้อยู่!")
                    res = await conn.execute("DELETE FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if res == "DELETE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e