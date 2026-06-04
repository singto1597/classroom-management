import asyncpg
from typing import List, Optional
from datetime import date

from core.audit import log_action
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission

class FinanceService:
    @staticmethod
    def _finance_actor(req) -> str:
        """ชื่อผู้กระทำสำหรับ audit — ใช้ user_name จาก body ถ้ามี"""
        n = getattr(req, "user_name", None)
        if n is not None and str(n).strip():
            return str(n).strip()[:200]
        return "—"

    # 🚨 เปลี่ยนจาก _get_room_id เป็น resolve_room_id รองรับทั้งระบบ Web และ Discord
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

    # ==========================================
    # 1. จัดการกระเป๋าเงิน (Accounts)
    # ==========================================
    @classmethod
    async def create_account(
        cls, pool: asyncpg.Pool, req, requester_discord_id: int, 
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                await conn.execute(
                    "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3)",
                    target_room_id, req.account_name, req.initial_balance
                )
                actor = cls._finance_actor(req)
                await log_action(
                    conn, target_room_id, actor, "Finance: Create Account",
                    f"สร้างบัญชี {req.account_name} ยอดตั้งต้น {req.initial_balance}",
                )
            return {"status": "success", "message": f"สร้างบัญชี {req.account_name} สำเร็จ"}

    @classmethod
    async def get_accounts(
        cls, pool: asyncpg.Pool, 
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> List[dict]:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            rows = await conn.fetch(
                "SELECT id, account_name, balance FROM finance_accounts WHERE room_id = $1 ORDER BY id",
                target_room_id
            )
            return [dict(row) for row in rows]

    # ==========================================
    # 2. รายการเดินบัญชี (Transactions & Transfers)
    # ==========================================
    @classmethod
    async def add_transaction(
        cls, pool: asyncpg.Pool, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                
                # ตรวจสอบว่าเป็นกระเป๋าของห้องนี้จริงไหม และเช็คยอดเงินกรณีจ่ายออก
                current_balance = await conn.fetchval(
                    "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 FOR UPDATE",
                    req.account_id, target_room_id
                )
                if current_balance is None:
                    raise ValueError("ไม่พบบัญชีนี้ในห้องของคุณ")
                
                if req.transaction_type == 'expense' and current_balance < req.amount:
                    raise ValueError(f"เงินไม่พอ! ยอดคงเหลือคือ {current_balance} บาท")
                
                cat = await conn.fetchrow("SELECT room_id, category_type FROM finance_categories WHERE id = $1", req.category_id)
                if not cat or cat['room_id'] != target_room_id:
                    raise ValueError("หมวดหมู่นี้ไม่มีอยู่ หรือไม่ใช่ของห้องคุณ!")
                if cat['category_type'] != req.transaction_type:
                    raise ValueError(f"ประเภทหมวดหมู่ ({cat['category_type']}) ไม่ตรงกับประเภทการบันทึก ({req.transaction_type})!")

                # 1. บันทึกประวัติ
                await conn.execute(
                    """INSERT INTO finance_transactions 
                       (room_id, account_id, category_id, amount, description, transaction_type, slip_image_url, recorded_by) 
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    target_room_id, req.account_id, req.category_id, req.amount, 
                    req.description, req.transaction_type, req.slip_image_url, req.user_name
                )
                
                # 2. อัปเดตยอดเงินในกระเป๋า
                if req.transaction_type == 'income':
                    await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.account_id)
                elif req.transaction_type == 'expense':
                    await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.account_id)

                desc = req.description if len(req.description) <= 120 else req.description[:117] + "..."
                await log_action(
                    conn, target_room_id, req.user_name, "Finance: Add Transaction",
                    f"{req.transaction_type} บัญชี {req.account_id} จำนวน {req.amount} — {desc}",
                )

                return {"status": "success", "message": "บันทึกรายการสำเร็จ"}

    @classmethod
    async def transfer_money(
        cls, pool: asyncpg.Pool, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        if req.from_account_id == req.to_account_id:
            raise ValueError("โอนเงินเข้าบัญชีเดิมไม่ได้!")

        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                
                current_balance = await conn.fetchval(
                    "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 FOR UPDATE", 
                    req.from_account_id, target_room_id
                )
                if current_balance is None:
                    raise RoomNotFoundError("ไม่พบบัญชีต้นทาง")
                if current_balance < req.amount:
                    raise ValueError("ยอดเงินในบัญชีต้นทางไม่เพียงพอ!")

                group_id = await conn.fetchval("SELECT nextval('transfer_group_id_seq')")
                
                # ขาออก
                await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.from_account_id)
                await conn.execute(
                    """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by) 
                       VALUES ($1, $2, $3, $4, 'expense', $5, $6)""",
                    target_room_id, req.from_account_id, req.amount, f"โอนออก: {req.description}", group_id, req.user_name
                )
                
                # ขาเข้า
                await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.to_account_id)
                await conn.execute(
                    """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by) 
                       VALUES ($1, $2, $3, $4, 'income', $5, $6)""",
                    target_room_id, req.to_account_id, req.amount, f"รับโอน: {req.description}", group_id, req.user_name
                )
                
                d = req.description if len(req.description) <= 80 else req.description[:77] + "..."
                await log_action(
                    conn, target_room_id, req.user_name, "Finance: Transfer",
                    f"group_id={group_id} ฿{req.amount} จากบัญชี {req.from_account_id} → {req.to_account_id}: {d}",
                )
                return {"status": "success", "message": "โอนเงินสำเร็จ"}

    @classmethod
    async def get_transactions(
        cls, pool: asyncpg.Pool, limit: int = 50, offset: int = 0,
        start_date: date = None, end_date: date = None,
        account_id: int = None, category_id: int = None, transaction_type: str = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict: 
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            
            where_clause = "WHERE T.room_id = $1 AND T.deleted_at IS NULL"
            params = [target_room_id]
            param_idx = 2
            
            if start_date:
                where_clause += f" AND DATE(T.created_at) >= ${param_idx}"
                params.append(start_date)
                param_idx += 1
            if end_date:
                where_clause += f" AND DATE(T.created_at) <= ${param_idx}"
                params.append(end_date)
                param_idx += 1
            if account_id:
                where_clause += f" AND T.account_id = ${param_idx}"
                params.append(account_id)
                param_idx += 1
            if category_id:
                where_clause += f" AND T.category_id = ${param_idx}"
                params.append(category_id)
                param_idx += 1
            if transaction_type:
                where_clause += f" AND T.transaction_type = ${param_idx}"
                params.append(transaction_type)
                param_idx += 1
                
            count_sql = f"SELECT COUNT(*) FROM finance_transactions T {where_clause}"
            total_count = await conn.fetchval(count_sql, *params)

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
            return {
                "total_count": total_count,
                "items": [dict(row) for row in rows]
            }

    # ==========================================
    # 3. ระบบเก็บเงินห้อง (Fee Collections)
    # ==========================================
    @classmethod
    async def create_fee_collection(
        cls, pool: asyncpg.Pool, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                
                collection_id = await conn.fetchval(
                    "INSERT INTO fee_collections (room_id, title, amount, due_date) VALUES ($1, $2, $3, $4) RETURNING id",
                    target_room_id, req.title, req.amount, req.due_date
                )
                
                all_students = await conn.fetch("SELECT id, status FROM students WHERE room_id = $1", target_room_id)
                active_students = [s['id'] for s in all_students if s['status'] == 'active']
                inactive_count = len(all_students) - len(active_students)
                
                if active_students:
                    records = [(collection_id, sid, 'pending') for sid in active_students]
                    await conn.executemany("INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, $3)", records)
                
                msg = f"สร้างแคมเปญสำเร็จ เรียกเก็บเพื่อน {len(active_students)} คน"
                if inactive_count > 0: msg += f" (ข้ามคน Inactive {inactive_count} คน)"
                
                await log_action(
                    conn, target_room_id, cls._finance_actor(req), "Finance: Create Collection",
                    f"id={collection_id} {req.title} ยอดเป้าหมาย {req.amount} บาท กำหนด {req.due_date} จำนวนนศ.ที่เข้าร่วมกำลังรอจ่าย {len(active_students)}",
                )
                return {"status": "success", "message": msg}

    @classmethod
    async def confirm_payment(
        cls, pool: asyncpg.Pool, payment_id: int, req,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                
                valid_account = await conn.fetchval("SELECT id FROM finance_accounts WHERE id = $1 AND room_id = $2", req.paid_to_account_id, target_room_id)
                if not valid_account: raise ValueError("กระเป๋าเงินที่เลือกรับเงิน ไม่มีอยู่ หรือไม่ใช่ของห้องนี้!")

                # 🚨 ซ่อม SQL JOIN: โยงตาราง users เข้ามาเพื่อนำ first_name และ nickname มาใช้
                payment_info = await conn.fetchrow(
                    """SELECT FC.amount as total_amount, SP.paid_amount as current_paid, FC.title, U.first_name, U.nickname 
                       FROM student_payments SP
                       JOIN fee_collections FC ON SP.collection_id = FC.id
                       JOIN students S ON SP.student_id = S.id
                       LEFT JOIN users U ON S.user_id = U.id 
                       WHERE SP.id = $1 AND FC.room_id = $2 FOR UPDATE""", 
                    payment_id, target_room_id 
                )
                if not payment_info: raise PaymentNotFoundError("ไม่พบรายการนี้")
                
                current_paid = float(payment_info['current_paid'])
                total_amount = float(payment_info['total_amount'])

                if current_paid >= total_amount:
                    raise ValueError("บิลนี้จ่ายครบไปเรียบร้อยแล้วครับ!")

                new_total_paid = current_paid + req.paid_amount
                
                if new_total_paid >= total_amount:
                    new_status = 'paid'
                    status_msg = "จ่ายครบแล้ว"
                else:
                    new_status = 'pending' 
                    status_msg = f"ทยอยจ่าย (ขาดอีก {total_amount - new_total_paid} ฿)"

                # Fallback ให้กรณีที่ไม่มีข้อมูล First Name (ถึงแม้ Database จะบังคับ แต่ทำ Defensive ไว้ก่อน)
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
                       SET status = $1, paid_amount = $2, paid_to_account_id = $3, 
                           slip_image_url = $4, recorded_by = $5, paid_at = NOW(), transaction_id = $6 
                       WHERE id = $7""",
                    new_status, new_total_paid, req.paid_to_account_id, req.slip_image_url, req.user_name, trans_id, payment_id
                )

                await log_action(
                    conn, target_room_id, req.user_name, "Finance: Confirm Payment",
                    f"payment_id={payment_id} trans_id={trans_id} รับ ฿{req.paid_amount} เข้าบัญชี {req.paid_to_account_id} — {status_msg}",
                )

                return {"status": "success", "message": f"รับเงินสำเร็จ! สถานะ: {status_msg}"}

    @classmethod
    async def get_collection_status(
        cls, pool: asyncpg.Pool, collection_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            
            # 🚨 ซ่อม SQL JOIN: ดึงข้อมูลส่วนตัวมาจาก users U
            sql = """
                SELECT 
                    SP.id as payment_id, SP.status, SP.paid_amount, SP.paid_at, SP.slip_image_url,
                    S.student_no, U.first_name, U.last_name, U.nickname,
                    FC.amount as total_amount
                FROM student_payments SP
                JOIN students S ON SP.student_id = S.id
                LEFT JOIN users U ON S.user_id = U.id
                JOIN fee_collections FC ON SP.collection_id = FC.id
                WHERE SP.collection_id = $1 AND S.room_id = $2
                ORDER BY S.student_no ASC
            """
            rows = await conn.fetch(sql, collection_id, target_room_id)
            
            total_students = len(rows)
            paid_count = sum(1 for r in rows if r['status'] == 'paid')
            pending_count = sum(1 for r in rows if r['status'] == 'pending') 
            
            return {
                "collection_id": collection_id,
                "summary": {
                    "total": total_students,
                    "paid": paid_count,
                    "pending": pending_count
                },
                "students": [dict(row) for row in rows]
            }
    
    # ==========================================
    # 4. จัดการหมวดหมู่ (Categories)
    # ==========================================
    @classmethod
    async def create_category(
        cls, pool: asyncpg.Pool, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                await conn.execute(
                    "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3)",
                    target_room_id, req.category_name, req.category_type
                )
                await log_action(
                    conn, target_room_id, cls._finance_actor(req), "Finance: Create Category",
                    f"{req.category_name} ({req.category_type})",
                )
            return {"status": "success", "message": f"เพิ่มหมวดหมู่ {req.category_name} แล้ว"}

    @classmethod
    async def get_categories(
        cls, pool: asyncpg.Pool, cat_type: str = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> List[dict]:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            if cat_type:
                rows = await conn.fetch(
                    "SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 AND category_type = $2 ORDER BY id", 
                    target_room_id, cat_type
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 ORDER BY id", 
                    target_room_id
                )
            return [dict(row) for row in rows]

    # ==========================================
    # 5. ระบบ Revert / Undo Transaction (คืนเงิน)
    # ==========================================
    @classmethod
    async def revert_transaction(
        cls, pool: asyncpg.Pool, transaction_id: int, user_name: str, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                
                t = await conn.fetchrow(
                    "SELECT account_id, amount, transaction_type, transfer_group_id, student_payment_id FROM finance_transactions WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                    transaction_id, target_room_id
                )
                if not t: raise TransactionNotFoundError("ไม่พบรายการธุรกรรมนี้ หรือถูกยกเลิกไปแล้ว")

                if t['transfer_group_id']:
                    group_trans = await conn.fetch(
                        "SELECT id, account_id, amount, transaction_type FROM finance_transactions WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        t['transfer_group_id'], target_room_id
                    )
                    for gt in group_trans:
                        if gt['transaction_type'] == 'expense': 
                            await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", gt['amount'], gt['account_id'])
                        elif gt['transaction_type'] == 'income': 
                            curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", gt['account_id'])
                            if curr_bal < gt['amount']:
                                raise ValueError(f"ไม่สามารถยกเลิกได้! เงินในบัญชีรับโอนไม่พอหักคืน (เหลือ {curr_bal} แต่ต้องดึงกลับ {gt['amount']})")
                            await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", gt['amount'], gt['account_id'])
                    
                    await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE transfer_group_id = $1 AND room_id = $2", t['transfer_group_id'], target_room_id)
                    action_detail = "ยกเลิกรายการโอนเงินและคืนยอด"
                
                else:
                    if t['transaction_type'] == 'income': 
                        curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", t['account_id'])
                        if curr_bal < t['amount']:
                            raise ValueError(f"ไม่สามารถยกเลิกได้! ยอดเงินในบัญชีไม่พอหักคืน (เหลือ {curr_bal} ต้องหัก {t['amount']})")
                        await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", t['amount'], t['account_id'])
                        
                        if t['student_payment_id']:
                            sp_id = t['student_payment_id']
                            sp_info = await conn.fetchrow(
                                """SELECT SP.paid_amount, FC.amount as total_amount
                                   FROM student_payments SP
                                   JOIN fee_collections FC ON SP.collection_id = FC.id
                                   WHERE SP.id = $1 FOR UPDATE""", sp_id
                            )
                            new_paid = float(sp_info['paid_amount']) - float(t['amount'])
                            new_status = 'paid' if new_paid >= float(sp_info['total_amount']) else 'pending'

                            await conn.execute(
                                "UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3",
                                new_paid, new_status, sp_id
                            )

                    elif t['transaction_type'] == 'expense': 
                        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", t['amount'], t['account_id'])
                    
                    await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", transaction_id)
                    action_detail = f"ยกเลิกรายการ {t['transaction_type']} ยอด {t['amount']} บาท"

                await log_action(conn, target_room_id, user_name, "Revert Finance", action_detail)
                return {"status": "success", "message": action_detail}
            
    # ==========================================
    # 6. สรุปยอดเงิน (Dashboard)
    # ==========================================
    @classmethod
    async def get_summary(
        cls, pool: asyncpg.Pool, month: int = None, year: int = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            
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
                FROM finance_transactions 
                WHERE room_id = $1 AND deleted_at IS NULL {date_cond}
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

            return {
                "net_worth": float(net_worth),
                "total_income": float(stats['total_inc'] or 0),       
                "total_expense": float(stats['total_exp'] or 0),      
                "pending_collection_amount": float(pending_collection),
                "period": period_str,                                 
                "expense_breakdown": [dict(b) for b in breakdown]
            }

    # ==========================================
    # 7. ทวงหนี้รายบุคคล (Student Debt Profile)
    # ==========================================
    @classmethod
    async def get_student_debts(
        cls, pool: asyncpg.Pool, student_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)

            # 🚨 ซ่อม SQL JOIN: นำ users เข้ามาร่วมดึงข้อมูล
            student = await conn.fetchrow(
                """SELECT S.id, U.first_name, U.nickname 
                   FROM students S
                   LEFT JOIN users U ON S.user_id = U.id
                   WHERE S.id = $1 AND S.room_id = $2""", 
                student_id, target_room_id
            )
            if not student:
                raise RoomNotFoundError("ไม่พบข้อมูลนักเรียนคนนี้ในห้อง")

            sql = """
                SELECT 
                    SP.id as payment_id, 
                    FC.id as collection_id, 
                    FC.title, 
                    (FC.amount - COALESCE(SP.paid_amount, 0)) AS amount, 
                    FC.due_date,
                    FC.status AS collection_status
                FROM student_payments SP
                JOIN fee_collections FC ON SP.collection_id = FC.id
                WHERE SP.student_id = $1 AND SP.status = 'pending' AND FC.room_id = $2
                ORDER BY FC.status ASC, FC.due_date ASC
            """
            
            rows = await conn.fetch(sql, student_id, target_room_id)

            formatted_debts = []
            total_pending = 0.0

            for r in rows:
                row_dict = dict(r)
                row_dict['amount'] = float(row_dict['amount'])
                formatted_debts.append(row_dict)
                total_pending += row_dict['amount']

            formatted_name = student['first_name'] or "Unknown"
            if student['nickname']:
                formatted_name += f" ({student['nickname']})"

            return {
                "student_id": student_id,
                "student_name": formatted_name,
                "total_pending_amount": total_pending,
                "debts": formatted_debts
            }


    @classmethod
    async def add_student_to_collection(
        cls, pool: asyncpg.Pool, collection_id: int, student_id: int, requester_discord_id: int, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")

                valid_student = await conn.fetchval("SELECT id FROM students WHERE id = $1 AND room_id = $2", student_id, target_room_id)
                if not valid_student:
                    raise RoomNotFoundError("ไม่พบเด็กคนนี้ในห้อง")

                valid_collection = await conn.fetchval(
                    "SELECT id FROM fee_collections WHERE id = $1 AND room_id = $2 AND status = 'active'",
                    collection_id, target_room_id
                )
                if not valid_collection:
                    raise ValueError("ไม่พบรายการเรียกเก็บเงินนี้ หรือแคมเปญถูกปิดไปแล้ว!")

                try:
                    await conn.execute(
                        "INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, 'pending')",
                        collection_id, student_id
                    )
                except asyncpg.exceptions.UniqueViolationError:
                    raise ValueError("เพื่อนคนนี้มีชื่อในรายการนี้อยู่แล้ว")

                await log_action(
                    conn, target_room_id, user_name, "Finance: Add Student To Collection",
                    f"collection_id={collection_id} student_id={student_id}",
                )
                return {"status": "success", "message": "เพิ่มเพื่อนเข้าสู่การเก็บเงินแล้ว"}
    
    @classmethod
    async def get_all_collections(
        cls, pool: asyncpg.Pool, 
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> List[dict]:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            rows = await conn.fetch(
                "SELECT id, title, amount, due_date, status FROM fee_collections WHERE room_id = $1 ORDER BY id DESC", 
                target_room_id
            )
            return [dict(row) for row in rows]

    @classmethod
    async def update_collection(
        cls, pool: asyncpg.Pool, collection_id: int, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")

                current_data = await conn.fetchrow(
                    "SELECT amount FROM fee_collections WHERE id = $1 AND room_id = $2", 
                    collection_id, target_room_id
                )
                if not current_data:
                    raise RoomNotFoundError("ไม่พบแคมเปญนี้")

                updates = []
                values = []
                idx = 1
                changed_labels: List[str] = []
                
                if req.title is not None:
                    updates.append(f"title = ${idx}")
                    values.append(req.title)
                    idx += 1
                    changed_labels.append("title")
                
                if req.amount is not None and req.amount != current_data['amount']:
                    paid_exists = await conn.fetchval(
                        "SELECT 1 FROM student_payments WHERE collection_id = $1 AND paid_amount > 0 LIMIT 1", collection_id
                    )
                    if paid_exists:
                        raise ValueError("ไม่สามารถแก้จำนวนเงินได้ เนื่องจากมีเพื่อนโอนเงิน/ทยอยจ่ายเข้ามาแล้ว!")
                    updates.append(f"amount = ${idx}")
                    values.append(req.amount)
                    idx += 1
                    changed_labels.append("amount")
                
                if req.due_date is not None:
                    updates.append(f"due_date = ${idx}")
                    values.append(req.due_date)
                    idx += 1
                    changed_labels.append("due_date")
                
                if req.status is not None:
                    updates.append(f"status = ${idx}")
                    values.append(req.status)
                    idx += 1
                    changed_labels.append("status")

                if not updates:
                    return {"status": "success", "message": "ไม่มีข้อมูลให้เปลี่ยนแปลง"}

                values.extend([collection_id, target_room_id])
                sql = f"UPDATE fee_collections SET {', '.join(updates)} WHERE id = ${idx} AND room_id = ${idx + 1}"

                res = await conn.execute(sql, *values)
                if res == "UPDATE 0":
                    raise RoomNotFoundError("ไม่พบแคมเปญนี้")

                await log_action(
                    conn, target_room_id, cls._finance_actor(req), "Finance: Update Collection",
                    f"id={collection_id} แก้: {', '.join(changed_labels)}",
                )
            return {"status": "success", "message": "อัปเดตข้อมูลแคมเปญสำเร็จ"}

    
    @classmethod
    async def update_account(
        cls, pool: asyncpg.Pool, account_id: int, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                res = await conn.execute(
                    "UPDATE finance_accounts SET account_name = $1 WHERE id = $2 AND room_id = $3",
                    req.account_name, account_id, target_room_id
                )
                if res == "UPDATE 0":
                    raise RoomNotFoundError("ไม่พบบัญชีนี้")
                await log_action(
                    conn, target_room_id, cls._finance_actor(req), "Finance: Update Account",
                    f"id={account_id} ชื่อใหม่={req.account_name}",
                )
            return {"status": "success", "message": "อัปเดตชื่อบัญชีสำเร็จ"}

    @classmethod
    async def delete_account(
        cls, pool: asyncpg.Pool, account_id: int, requester_discord_id: int, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")

                bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                if bal is None:
                    raise RoomNotFoundError("ไม่พบบัญชีนี้")
                if bal > 0:
                    raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากยังมีเงินคงเหลืออยู่!")

                existing_payments = await conn.fetchval(
                    "SELECT 1 FROM student_payments WHERE paid_to_account_id = $1 LIMIT 1", account_id
                )
                if existing_payments:
                    raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติการรับเงินของเพื่อนผูกกับบัญชีนี้อยู่!")

                await conn.execute("DELETE FROM finance_accounts WHERE id = $1", account_id)
                await log_action(conn, target_room_id, user_name, "Finance: Delete Account", f"ลบบัญชี id={account_id}")
            return {"status": "success", "message": "ลบบัญชีสำเร็จ"}

    @classmethod
    async def get_all_debtors(
        cls, pool: asyncpg.Pool, 
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> List[dict]:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            
            # 🚨 ซ่อม SQL JOIN: เชื่อมตาราง users เพื่อดึงข้อมูล U.first_name และ U.nickname 
            rows = await conn.fetch("""
                SELECT S.id as student_id, S.student_no, U.first_name, U.nickname,
                       COUNT(SP.id) as overdue_count,
                       SUM(FC.amount - SP.paid_amount) as total_pending_amount
                FROM students S
                LEFT JOIN users U ON S.user_id = U.id
                JOIN student_payments SP ON S.id = SP.student_id
                JOIN fee_collections FC ON SP.collection_id = FC.id
                WHERE S.room_id = $1 AND SP.status = 'pending'
                GROUP BY S.id, S.student_no, U.first_name, U.nickname
                ORDER BY S.student_no ASC
            """, target_room_id)
            
            debtors = []
            for r in rows:
                name = r['first_name'] or "Unknown"
                if r['nickname']: name += f" ({r['nickname']})"
                debtors.append({
                    "student_id": r['student_id'],
                    "student_no": r['student_no'],
                    "student_name": name,
                    "overdue_count": r['overdue_count'],
                    "total_pending_amount": float(r['total_pending_amount'])
                })
            return debtors
    
    @classmethod
    async def update_category(
        cls, pool: asyncpg.Pool, category_id: int, req, requester_discord_id: int,
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")
                res = await conn.execute(
                    "UPDATE finance_categories SET category_name = $1 WHERE id = $2 AND room_id = $3",
                    req.category_name, category_id, target_room_id
                )
                if res == "UPDATE 0":
                    raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                await log_action(
                    conn, target_room_id, cls._finance_actor(req), "Finance: Update Category",
                    f"id={category_id} ชื่อใหม่={req.category_name}",
                )
            return {"status": "success", "message": "อัปเดตชื่อหมวดหมู่สำเร็จ"}

    @classmethod
    async def delete_category(
        cls, pool: asyncpg.Pool, category_id: int, requester_discord_id: int, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None
    ) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, requester_discord_id, "MANAGE_FINANCE")

                used = await conn.fetchval("SELECT 1 FROM finance_transactions WHERE category_id = $1 LIMIT 1", category_id)
                if used:
                    raise ValueError("ไม่สามารถลบได้ เนื่องจากมีประวัติรายรับ/รายจ่ายที่ใช้หมวดหมู่นี้อยู่!")

                res = await conn.execute("DELETE FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                if res == "DELETE 0":
                    raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                await log_action(conn, target_room_id, user_name, "Finance: Delete Category", f"ลบหมวดหมู่ id={category_id}")
            return {"status": "success", "message": "ลบหมวดหมู่สำเร็จ"}