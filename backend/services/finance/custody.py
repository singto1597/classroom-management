"""👜 [FIN-V2 / P3.1] เงินสดรอส่งมอบ (custody)

═══════════════════════════════════════════════════════════════════════════════
🎯 หลักคิด: custody ไม่ใช่บัญชีแยกประเภทใหม่
═══════════════════════════════════════════════════════════════════════════════
กระเป๋า "เงินสดรอส่งมอบ" คือแถวปกติของ `finance_accounts` ที่
`is_custody = TRUE` + `owner_person_id` ⇒ ใช้ balance/journal/`_scan_account_diffs`/
`_resolve_asset_ledger` เดิมได้ทั้งหมด การส่งมอบคือ **โอนสินทรัพย์→สินทรัพย์**
(Dr ปลายทาง / Cr ต้นทาง) ไม่ใช่รายรับ/รายจ่าย

🔴 กฎเหล็ก 3 ข้อ
   1. **ห้ามเขียน `finance_transactions`** สำหรับ handover — การย้ายเงินภายในห้อง
      ไม่ใช่รายรับ/รายจ่าย; ถ้าเขียน dashboard/งบประมาณจะนับซ้ำ
   2. **ห้ามออกเอกสาร** (REC/PV/INC/DEP) — handover ไม่มีเอกสารพิมพ์
   3. ทุกเมธอดเขียนต้องยึด `_lock_room_money` **ก่อน**แตะแถวใด ๆ แล้วค่อยล็อก
      กระเป๋าตาม `ORDER BY id` (ลำดับที่สองเท่านั้น ไม่ใช่ด่านแรก)

🔁 idempotency
   `finance_custody_handovers` (migration 0012) **ไม่มี** `idempotency_key` ⇒ เก็บคีย์
   ใน `journal_entries.metadata->>'idempotency_key'` แล้ว SELECT ก่อน INSERT ภายใต้
   room lock (คำขอในห้องเดียวกันถูก serialize ⇒ ไม่ต้องมี unique index)

🗑️ void ต้อง void journal เดิม **และ** เขียน journal กลับรายการ
   ถ้าทำอย่างเดียว ยอดบัญชีจะไม่ตรงกับ journal (บทเรียน "อ่านยอดคงเหลือแบบ snapshot
   หลัง soft delete")
"""
import hashlib
import time
from datetime import date
from decimal import Decimal
from typing import List, Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger

# 🎭 `finance_people.roles` ที่ต้องมีก่อนเป็นผู้ถือเงิน
_RECEIVE_ROLE = "receive"
# 🧾 `account_kind` มี CHECK `cash|transfer` ใน init_db ⇒ อย่าส่งค่านอกนี้
_VALID_ACCOUNT_KINDS = ("cash", "transfer")


class CustodyNotFoundError(Exception):
    """ไม่พบกระเป๋า custody / การส่งมอบของห้อง ⇒ router แปลเป็น 404"""


class CustodyPersonNotFoundError(Exception):
    """ไม่พบผู้เกี่ยวข้องในทะเบียนของห้อง ⇒ router แปลเป็น 404"""


class CustodyConflictError(Exception):
    """ข้อขัดแย้งทางสถานะ (idempotency คนละ payload / void ไม่ได้) ⇒ router แปลเป็น 409"""


def _money(value) -> str:
    """Decimal/float → สตริง 2 ตำแหน่ง (สำหรับ hash/audit เท่านั้น)"""
    return f"{float(value):.2f}"


class CustodyMixin:
    """เงินสดรอส่งมอบ — กระเป๋าผู้ถือ + การส่งมอบ + รายการเคลื่อนไหว"""

    # ─────────────────────────────────────────────────────────────────────
    # ตัวช่วยภายใน (ไม่เปิด transaction — caller เป็นเจ้าของ)
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def _ensure_custody_account_locked(
        cls, conn: asyncpg.Connection, room_id: int, person_id: int,
        account_kind: str = "cash",
    ) -> int:
        """คืน id ของกระเป๋า custody ของคนนี้ (สร้าง/ฟื้นให้ถ้ายังไม่มี)

        ⚠️ partial unique `idx_finance_accounts_custody_owner` **ไม่ครอบ** แถวที่
           `deleted_at` ไม่ null ⇒ ถ้าเจอแถวที่ถูกลบและยอดเป็น 0 ให้ **ฟื้น** แถวเดิม
           (ไม่ INSERT ใหม่) เพื่อไม่ให้ประวัติ/ledger ผูกขาดสองเส้น
        ⚠️ กระเป๋า custody ต้อง **ไม่ตั้ง** `is_primary` — unique
           `idx_finance_accounts_primary (room_id, account_kind)` จะชนกระเป๋าหลัก
        """
        if account_kind not in _VALID_ACCOUNT_KINDS:
            raise ValueError("ชนิดกระเป๋าต้องเป็น cash หรือ transfer")

        person = await conn.fetchrow(
            """SELECT id, display_name, roles FROM finance_people
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            person_id, room_id,
        )
        if not person:
            raise CustodyPersonNotFoundError("ไม่พบผู้เกี่ยวข้องคนนี้ในห้องเรียน")
        if _RECEIVE_ROLE not in (person["roles"] or []):
            raise ValueError("คนนี้ยังไม่มีบทบาทรับเงิน")

        existing = await conn.fetchval(
            """SELECT id FROM finance_accounts
               WHERE room_id = $1 AND owner_person_id = $2
                 AND is_custody AND deleted_at IS NULL""",
            room_id, person_id,
        )
        if existing:
            return existing

        deleted = await conn.fetchrow(
            """SELECT id, balance FROM finance_accounts
               WHERE room_id = $1 AND owner_person_id = $2 AND is_custody
                 AND deleted_at IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            room_id, person_id,
        )
        if deleted:
            if float(deleted["balance"] or 0) != 0.0:
                raise CustodyConflictError(
                    "กระเป๋าเงินสดรอส่งมอบเดิมถูกลบไปแล้วแต่ยังมียอดคงเหลือ — "
                    "ต้องเคลียร์ยอดก่อนสร้างใหม่"
                )
            return await conn.fetchval(
                """UPDATE finance_accounts SET deleted_at = NULL
                   WHERE id = $1 RETURNING id""",
                deleted["id"],
            )

        return await conn.fetchval(
            """INSERT INTO finance_accounts
                   (room_id, account_name, balance, account_kind,
                    owner_person_id, is_custody, is_primary)
               VALUES ($1, $2, 0, $3, $4, TRUE, FALSE)
               RETURNING id""",
            room_id, f"{person['display_name']} (เงินสดรอส่งมอบ)",
            account_kind, person_id,
        )

    @classmethod
    async def _find_handover_by_idempotency(
        cls, conn: asyncpg.Connection, room_id: int, key: str,
    ):
        """หา handover ที่ยัง active ซึ่ง journal ระบุคีย์นี้ (ใต้ room lock เท่านั้น)

        🔴 ห้ามเปลี่ยนไปใช้ `created_at`/`amount` เป็นคีย์ — จะ replay ผิดรายการ
        """
        return await conn.fetchrow(
            """SELECT h.*, je.id AS je_id
               FROM finance_custody_handovers h
               JOIN journal_entries je ON je.id = h.journal_entry_id
               WHERE h.room_id = $1 AND h.status = 'active'
                 AND je.metadata->>'idempotency_key' = $2
               ORDER BY h.id DESC LIMIT 1""",
            room_id, key,
        )

    @staticmethod
    def _shape_handover(row) -> dict:
        entry_id = row["journal_entry_id"]
        return {
            "id": row["id"],
            "from_account_id": row["from_account_id"],
            "to_account_id": row["to_account_id"],
            "amount": round(float(row["amount"]), 2),
            "status": row["status"],
            "journal_entry_id": str(entry_id) if entry_id else None,
            "created_at": row["created_at"],
        }

    @staticmethod
    def _handover_hash(from_id: int, to_id: int, amount: float) -> str:
        raw = f"{from_id}:{to_id}:{amount:.2f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ─────────────────────────────────────────────────────────────────────
    # สร้างกระเป๋า custody
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def create_custody_account(
        cls,
        pool: asyncpg.Pool,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """สร้างกระเป๋าเงินสดรอส่งมอบให้ผู้เกี่ยวข้อง 1 คน (idempotent ต่อคน)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                async with conn.transaction():
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    account_id = await cls._ensure_custody_account_locked(
                        conn, target_room_id, req.owner_person_id, req.account_kind
                    )
                    row = await conn.fetchrow(
                        """SELECT a.id, a.account_name, a.account_kind, a.balance,
                                  a.owner_person_id
                           FROM finance_accounts a
                           WHERE a.id = $1 AND a.room_id = $2""",
                        account_id, target_room_id,
                    )

                    result = {
                        "person_id": row["owner_person_id"],
                        "account_id": row["id"],
                        "account_name": row["account_name"],
                        "account_kind": row["account_kind"],
                        "balance": round(float(row["balance"] or 0), 2),
                        "is_custody": True,
                    }
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_ACCOUNT",
                        entity_id=str(row["id"]), status="success",
                        new_values=result,
                        endpoint_or_command="FinanceService.create_custody_account",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_ACCOUNT",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_custody_account",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # อ่านรายชื่อผู้ถือเงิน (รวมยอด 0)
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def list_custody(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ทุกคนที่มีกระเป๋า custody ในห้อง + ยอดถือรวม (อ่านล้วน ไม่ล็อกห้อง)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                rows = await conn.fetch(
                    """SELECT a.id AS account_id, a.account_name, a.account_kind,
                              a.balance, a.owner_person_id,
                              p.display_name,
                              (SELECT MAX(h.created_at)
                                 FROM finance_custody_handovers h
                                WHERE h.room_id = a.room_id
                                  AND h.status = 'active'
                                  AND (h.from_account_id = a.id
                                       OR h.to_account_id = a.id)) AS last_handover_at
                       FROM finance_accounts a
                       JOIN finance_people p
                         ON p.id = a.owner_person_id AND p.room_id = a.room_id
                       WHERE a.room_id = $1 AND a.is_custody
                         AND a.deleted_at IS NULL
                       ORDER BY p.display_name ASC, a.id ASC""",
                    target_room_id,
                )

                items = [
                    {
                        "person_id": r["owner_person_id"],
                        "display_name": r["display_name"],
                        "account_id": r["account_id"],
                        "account_name": r["account_name"],
                        "account_kind": r["account_kind"],
                        "balance": round(float(r["balance"] or 0), 2),
                        "last_handover_at": r["last_handover_at"],
                    }
                    for r in rows
                ]
                total_held = round(sum(i["balance"] for i in items), 2)

                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    user_id=user_id, entity_type="FINANCE_CUSTODY", status="success",
                    endpoint_or_command="FinanceService.list_custody",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
                return {"total_held": total_held, "items": items}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.list_custody",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # ส่งมอบเงิน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def create_handover(
        cls,
        pool: asyncpg.Pool,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ส่งมอบเงินระหว่างกระเป๋า (อย่างน้อยหนึ่งฝั่งต้องเป็น custody)

        ลำดับ: RBAC → room lock → idempotency → ล็อกกระเป๋าตาม id → guards →
        UPDATE balance → INSERT handover → journal Dr to / Cr from → ผูก journal id
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                async with conn.transaction():
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    # 🔁 idempotency — อ่านก่อนเขียนใต้ room lock
                    key = (req.idempotency_key or "").strip()
                    existing = await cls._find_handover_by_idempotency(
                        conn, target_room_id, key
                    )
                    if existing:
                        same = (
                            existing["from_account_id"] == req.from_account_id
                            and existing["to_account_id"] == req.to_account_id
                            and float(existing["amount"]) == round(float(req.amount), 2)
                        )
                        if same:
                            return cls._shape_handover(existing)
                        raise CustodyConflictError(
                            "idempotency key นี้ถูกใช้กับรายการอื่นแล้ว"
                        )

                    # 💰 เงิน — ปัด 2 ตำแหน่งแล้วตรวจซ้ำ (กัน 0.004 ที่ผ่าน gt=0 มาแล้ว)
                    amount = round(float(req.amount), 2)
                    if amount <= 0:
                        raise ValueError("ยอดส่งมอบต้องมากกว่า 0")
                    amount_dec = Decimal(f"{amount:.2f}")

                    # 🔒 ล็อกกระเป๋าทั้งคู่ตาม id จากน้อยไปมาก (ลำดับเดียวทั้งระบบ)
                    accounts = await conn.fetch(
                        """SELECT id, balance, is_custody, account_name
                           FROM finance_accounts
                           WHERE id = ANY($1::int[]) AND room_id = $2
                             AND deleted_at IS NULL
                           ORDER BY id
                           FOR UPDATE""",
                        [req.from_account_id, req.to_account_id], target_room_id,
                    )
                    by_id = {r["id"]: r for r in accounts}
                    src = by_id.get(req.from_account_id)
                    dst = by_id.get(req.to_account_id)
                    if not src or not dst:
                        raise RoomNotFoundError(
                            "ไม่พบกระเป๋าเงินต้นทางหรือปลายทางในห้องเรียนนี้"
                        )
                    if req.from_account_id == req.to_account_id:
                        raise ValueError("ส่งมอบเข้ากระเป๋าเดิมไม่ได้")
                    if not (src["is_custody"] or dst["is_custody"]):
                        raise ValueError(
                            "การส่งมอบต้องมีกระเป๋าเงินสดรอส่งมอบอย่างน้อยหนึ่งฝั่ง"
                        )

                    # 🛡️ negative-balance guard **ก่อน** UPDATE ใด ๆ
                    if float(src["balance"] or 0) < amount:
                        raise ValueError("เงินในกระเป๋าต้นทางไม่พอสำหรับส่งมอบ")

                    # 👤 ผู้ส่ง/ผู้รับ (ถ้าส่งมาต้องอยู่ในทะเบียนของห้อง)
                    person_ids = [
                        pid for pid in (
                            req.handed_over_by_person_id, req.received_by_person_id
                        ) if pid is not None
                    ]
                    people = {}
                    if person_ids:
                        rows = await conn.fetch(
                            """SELECT id, display_name FROM finance_people
                               WHERE id = ANY($1::bigint[]) AND room_id = $2
                                 AND deleted_at IS NULL""",
                            person_ids, target_room_id,
                        )
                        people = {r["id"]: r["display_name"] for r in rows}
                        if len(people) != len(set(person_ids)):
                            raise CustodyPersonNotFoundError(
                                "ไม่พบผู้ส่งหรือผู้รับเงินคนนี้ในทะเบียนของห้อง"
                            )

                    # DB คำนวณยอดเอง (DECIMAL) — ไม่คำนวณใน Python
                    await conn.execute(
                        "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
                        amount_dec, req.from_account_id,
                    )
                    await conn.execute(
                        "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
                        amount_dec, req.to_account_id,
                    )

                    handover = await conn.fetchrow(
                        """INSERT INTO finance_custody_handovers
                               (room_id, from_account_id, to_account_id, amount,
                                handed_over_by_person_id, received_by_person_id,
                                note, status)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
                           RETURNING id, created_at""",
                        target_room_id, req.from_account_id, req.to_account_id,
                        amount_dec, req.handed_over_by_person_id,
                        req.received_by_person_id, req.note,
                    )
                    handover_id = handover["id"]

                    ledger_from = await cls._resolve_asset_ledger(
                        conn, target_room_id, req.from_account_id
                    )
                    ledger_to = await cls._resolve_asset_ledger(
                        conn, target_room_id, req.to_account_id
                    )
                    recorded_by = people.get(req.handed_over_by_person_id)
                    journal_id = await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="custody_handover",
                        reference_id=str(handover_id),
                        description=(
                            f"ส่งมอบเงินสด: {src['account_name']} → {dst['account_name']}"
                        ),
                        recorded_by=recorded_by,
                        metadata={
                            "handover_id": handover_id,
                            "idempotency_key": key,
                            "request_hash": cls._handover_hash(
                                req.from_account_id, req.to_account_id, amount
                            ),
                            "from_account_id": req.from_account_id,
                            "to_account_id": req.to_account_id,
                        },
                        lines=[
                            {"ledger_id": ledger_to, "debit": float(amount_dec),
                             "credit": 0},
                            {"ledger_id": ledger_from, "debit": 0,
                             "credit": float(amount_dec)},
                        ],
                    )
                    await conn.execute(
                        """UPDATE finance_custody_handovers
                           SET journal_entry_id = $1 WHERE id = $2""",
                        journal_id, handover_id,
                    )

                    result = {
                        "id": handover_id,
                        "from_account_id": req.from_account_id,
                        "to_account_id": req.to_account_id,
                        "amount": amount,
                        "status": "active",
                        "journal_entry_id": str(journal_id),
                        "created_at": handover["created_at"],
                    }
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_HANDOVER",
                        entity_id=str(handover_id), status="success",
                        new_values=result,
                        endpoint_or_command="FinanceService.create_handover",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_HANDOVER",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_handover",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # ยกเลิกการส่งมอบ
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def void_handover(
        cls,
        pool: asyncpg.Pool,
        handover_id: int,
        reason: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ยกเลิก handover — คืนยอดสองฝั่ง, void journal เดิม, เขียน journal กลับรายการ

        🛡️ guard: เงิน **ปลายทาง** ต้องยังพอคืน — ถ้าถูกใช้ไปแล้วให้ 409
           (คืนเงินจากปลายทางไม่ได้; ผู้ใช้ต้องเติมหรือใช้เส้นทางแก้ไขอื่น)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                async with conn.transaction():
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    handover = await conn.fetchrow(
                        """SELECT * FROM finance_custody_handovers
                           WHERE id = $1 AND room_id = $2
                           FOR UPDATE""",
                        handover_id, target_room_id,
                    )
                    if not handover:
                        raise CustodyNotFoundError("ไม่พบรายการส่งมอบนี้ในห้องเรียน")
                    # 🔁 idempotent — ยกเลิกซ้ำได้ผลเดิม ไม่เขียนอะไรเพิ่ม
                    if handover["status"] == "voided":
                        return {
                            "status": "success",
                            "message": "รายการส่งมอบนี้ถูกยกเลิกไปแล้ว",
                        }

                    amount = round(float(handover["amount"]), 2)
                    amount_dec = Decimal(f"{amount:.2f}")
                    from_id = handover["from_account_id"]
                    to_id = handover["to_account_id"]

                    accounts = await conn.fetch(
                        """SELECT id, balance, account_name FROM finance_accounts
                           WHERE id = ANY($1::int[]) AND room_id = $2
                           ORDER BY id
                           FOR UPDATE""",
                        [from_id, to_id], target_room_id,
                    )
                    by_id = {r["id"]: r for r in accounts}
                    src = by_id.get(from_id)
                    dst = by_id.get(to_id)
                    if not src or not dst:
                        raise CustodyNotFoundError(
                            "ไม่พบกระเป๋าต้นทางหรือปลายทางของการส่งมอบนี้"
                        )

                    if float(dst["balance"] or 0) < amount:
                        raise CustodyConflictError(
                            "ยกเลิกไม่ได้: เงินปลายทางถูกใช้ไปแล้ว"
                        )

                    await conn.execute(
                        "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
                        amount_dec, from_id,
                    )
                    await conn.execute(
                        "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
                        amount_dec, to_id,
                    )

                    if handover["journal_entry_id"]:
                        await conn.execute(
                            """UPDATE journal_entries
                               SET status = 'voided', deleted_at = NOW()
                               WHERE id = $1""",
                            handover["journal_entry_id"],
                        )

                    ledger_from = await cls._resolve_asset_ledger(
                        conn, target_room_id, from_id
                    )
                    ledger_to = await cls._resolve_asset_ledger(
                        conn, target_room_id, to_id
                    )
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="custody_handover_void",
                        reference_id=str(handover_id),
                        description=(
                            f"ยกเลิกการส่งมอบเงินสด: {src['account_name']} ← "
                            f"{dst['account_name']}"
                        ),
                        metadata={
                            "handover_id": handover_id,
                            "void_reason": reason,
                            "original_journal_entry_id": (
                                str(handover["journal_entry_id"])
                                if handover["journal_entry_id"] else None
                            ),
                        },
                        lines=[
                            {"ledger_id": ledger_from, "debit": float(amount_dec),
                             "credit": 0},
                            {"ledger_id": ledger_to, "debit": 0,
                             "credit": float(amount_dec)},
                        ],
                    )

                    await conn.execute(
                        """UPDATE finance_custody_handovers
                           SET status = 'voided', voided_at = NOW(), void_reason = $1
                           WHERE id = $2""",
                        reason, handover_id,
                    )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_HANDOVER",
                        entity_id=str(handover_id), status="success",
                        old_values=cls._shape_handover(handover),
                        new_values={
                            "status": "voided", "void_reason": reason,
                            "amount_restored": amount,
                        },
                        endpoint_or_command="FinanceService.void_handover",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return {
                    "status": "success",
                    "message": "ยกเลิกการส่งมอบเรียบร้อย",
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY_HANDOVER",
                        entity_id=str(handover_id), status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.void_handover",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # รายการเคลื่อนไหวของกระเป๋า custody
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def get_custody_movements(
        cls,
        pool: asyncpg.Pool,
        person_id: int,
        client_source: str,
        actor_identifier: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ส่งมอบ + รายการเงินที่ใช้กระเป๋านี้ (ใหม่→เก่า, ไม่เกิน 500 แถว)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                account = await conn.fetchrow(
                    """SELECT id FROM finance_accounts
                       WHERE room_id = $1 AND owner_person_id = $2
                         AND is_custody AND deleted_at IS NULL""",
                    target_room_id, person_id,
                )
                if not account:
                    raise CustodyNotFoundError(
                        "คนนี้ยังไม่มีกระเป๋าเงินสดรอส่งมอบในห้องนี้"
                    )
                account_id = account["id"]

                rows = await conn.fetch(
                    """SELECT * FROM (
                           SELECT 'handover_out'::text AS kind, h.id::bigint AS source_id,
                                  -h.amount AS amount,
                                  COALESCE(h.note, 'ส่งมอบเงินออก') AS description,
                                  NULL::text AS reference_no, h.created_at AS occurred_at
                             FROM finance_custody_handovers h
                            WHERE h.room_id = $1 AND h.from_account_id = $2
                              AND h.status = 'active'
                           UNION ALL
                           SELECT 'handover_in'::text, h.id::bigint, h.amount,
                                  COALESCE(h.note, 'รับมอบเงิน'),
                                  NULL::text, h.created_at
                             FROM finance_custody_handovers h
                            WHERE h.room_id = $1 AND h.to_account_id = $2
                              AND h.status = 'active'
                           UNION ALL
                           SELECT CASE WHEN ft.transaction_type = 'expense'
                                            THEN 'expense' ELSE 'income' END,
                                  ft.id::bigint,
                                  CASE WHEN ft.transaction_type = 'expense'
                                            THEN -ft.amount ELSE ft.amount END,
                                  ft.description,
                                  r.receipt_no,
                                  ft.created_at
                             FROM finance_transactions ft
                             LEFT JOIN finance_receipts r
                               ON r.legacy_transaction_id = ft.id
                              AND r.room_id = ft.room_id
                              AND r.deleted_at IS NULL
                            WHERE ft.room_id = $1 AND ft.account_id = $2
                              AND ft.deleted_at IS NULL
                       ) m
                       WHERE ($3::date IS NULL OR m.occurred_at >= $3::date)
                         AND ($4::date IS NULL OR m.occurred_at < ($4::date + INTERVAL '1 day'))
                       ORDER BY m.occurred_at DESC, m.source_id DESC
                       LIMIT 500""",
                    target_room_id, account_id, from_date, to_date,
                )

                items = [
                    {
                        "kind": r["kind"],
                        "source_id": str(r["source_id"]),
                        "amount": round(float(r["amount"] or 0), 2),
                        "description": r["description"],
                        "reference_no": r["reference_no"] or r["description"],
                        "occurred_at": r["occurred_at"],
                    }
                    for r in rows
                ]

                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    user_id=user_id, entity_type="FINANCE_CUSTODY", status="success",
                    endpoint_or_command="FinanceService.get_custody_movements",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
                return {
                    "person_id": person_id,
                    "account_id": account_id,
                    "items": items,
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_CUSTODY",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_custody_movements",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
