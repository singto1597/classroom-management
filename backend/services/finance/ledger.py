"""Double-Entry (journal_entries/journal_lines) helpers + reconcile"""
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
    ADVANCE_LIABILITY_CODE, ADVANCE_LIABILITY_NAME, REFERENCE_TYPE_CREDIT_APPLY,
)
from .helpers import (
    _naive_thai_dt, _clamp_to_cutoff, _ExportPeriodView, _resolve_inclusive_period,
    _legacy_id_from_journal,
)
from .base import _lock_room_money, service_logger


class LedgerMixin:
    @classmethod
    async def _resolve_asset_ledger(cls, conn: asyncpg.Connection, room_id: int, legacy_account_id: int) -> int:
        """คืน ledger_id ของบัญชีสินทรัพย์ที่ map กับ finance_accounts.
        ถ้ายังไม่มีแถว → provision เอง (รหัสบัญชี '1' || LPAD(id,4,'0') เหมือน Phase 2)
        และถ้า legacy row ไม่อยู่จริง → raise ValueError (กันข้อมูลไม่ตรงกัน)."""
        ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_account_id = $1", legacy_account_id
        )
        if ledger_id:
            return ledger_id
        acc = await conn.fetchrow(
            "SELECT account_name FROM finance_accounts WHERE id = $1 AND room_id = $2",
            legacy_account_id, room_id,
        )
        if not acc:
            raise ValueError(f"[DUAL-WRITE] ไม่พบ ledger mapping สำหรับบัญชีสินทรัพย์ legacy_account_id={legacy_account_id}")
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description)
               VALUES ($1, $2, $3, 'asset', $4, 'Auto-provisioned by dual-write')
               RETURNING id""",
            room_id, f"1{legacy_account_id:04d}", acc["account_name"], legacy_account_id,
        )

    @classmethod
    async def _resolve_category_ledger(cls, conn: asyncpg.Connection, room_id: int, legacy_category_id: int, category_type: Optional[str] = None) -> int:
        """คืน ledger_id ของหมวดหมู่ revenue/expense ที่ map กับ finance_categories.
        category_type (income/expense) ใช้ตอน provision ถ้า caller ไม่รู้ (income → 'revenue' 4xxxx, expense → 5xxxx)."""
        ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_category_id = $1", legacy_category_id
        )
        if ledger_id:
            return ledger_id
        cat = await conn.fetchrow(
            "SELECT category_name, category_type FROM finance_categories WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
            legacy_category_id, room_id,
        )
        if not cat:
            raise ValueError(f"[DUAL-WRITE] ไม่พบ ledger mapping สำหรับหมวดหมู่ legacy_category_id={legacy_category_id}")
        effective_type = category_type or cat["category_type"]
        if effective_type == "income":
            account_type, code = "revenue", f"4{legacy_category_id:04d}"
        else:
            account_type, code = "expense", f"5{legacy_category_id:04d}"
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_category_id, description)
               VALUES ($1, $2, $3, $4, $5, 'Auto-provisioned by dual-write')
               RETURNING id""",
            room_id, code, cat["category_name"], account_type, legacy_category_id,
        )

    @classmethod
    async def _find_revenue_ledger_by_name(cls, conn: asyncpg.Connection, room_id: int, legacy_category_id: Optional[int] = None, account_name: Optional[str] = None) -> Optional[int]:
        """ค้นหา revenue ledger สำหรับเครดิตขาของ confirm_payment.
        ลำดับการค้นหา: (1) legacy_category_id ที่ mapping ตรง ๆ, (2) ชื่อบัญชี (เช่น '📥 เก็บเงินห้องปกติ'),
        (3) revenue ตัวแรกสุดของห้อง (fallback ยืดหยุ่น). คืน None ถ้าไม่มี revenue เลย (เช่น ห้องที่ seed ยังไม่ครบ)."""
        if legacy_category_id is not None:
            ledger_id = await conn.fetchval("SELECT id FROM accounting_ledgers WHERE legacy_category_id = $1", legacy_category_id)
            if ledger_id:
                return ledger_id
        if account_name:
            ledger_id = await conn.fetchval(
                "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND account_name = $2 AND account_type = 'revenue'",
                room_id, account_name,
            )
            if ledger_id:
                return ledger_id
        return await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND account_type = 'revenue' ORDER BY id LIMIT 1",
            room_id,
        )

    @classmethod
    async def _find_or_create_default_income_category(cls, conn: asyncpg.Connection, room_id: int) -> Optional[int]:
        """[FIX A] หา/สร้าง finance_categories รายได้ค่าเริ่มต้น '📥 เก็บเงินห้องปกติ' ให้ห้อง.

        กันกรณีห้องเก่าที่ seed หมวดหมู่ไม่ครบ: ถ้าสร้างไม่เจอตอน confirm_payment ระบบเดิมจะ
        ข้าม dual-write (pass) → เงินเข้า legacy แต่ journal ไม่มี → ยอด 2 ระบบเบี้ยว.
        สร้างหมวดนี้ + ให้ `_resolve_category_ledger` สร้าง revenue ledger ตามมา
        → ทำให้ทุก path เจอหมวด+ledger ตัวเดียวกัน (find-or-create idempotent).
        """
        # 🗑️ [SOFT DELETE] `deleted_at IS NULL` ทุก SELECT ในฟังก์ชันนี้ — **ห้ามถอด**
        #
        # ฟังก์ชันนี้เป็น find-or-create ถ้าไม่กรอง มันจะ "ฟื้น" หมวดที่ถูกลบไปแล้ว:
        # SELECT เจอแถวที่ `deleted_at` ไม่ null → คืน id นั้น → `confirm_payment` ทุกครั้ง
        # หลังจากนั้น dual-write ลง ledger ของหมวดที่ผู้ใช้ลบไปแล้ว และหมวดนั้นก็ยังไม่โผล่
        # ใน `get_categories` ⇒ เงินเข้าฝั่ง legacy แต่ผู้ใช้หาหมวดไม่เจอ = งงถาวร
        # (สำคัญเป็นพิเศษเพราะฟังก์ชันนี้เป็น **ทางเดียว** ที่หมวดนี้ถูกสร้าง — ดู docstring)
        cat_id = await conn.fetchval(
            """SELECT id FROM finance_categories
               WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
                 AND deleted_at IS NULL
               ORDER BY id LIMIT 1""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
        if cat_id:
            return cat_id
        # 🛡️ INSERT ... WHERE NOT EXISTS กัน race (2 request พร้อมกันสร้างหมวดซ้ำ)
        #    ⚠️ subquery ต้องกรอง `deleted_at IS NULL` **ด้วยเหตุผลเดียวกัน** — ถ้าไม่กรอง
        #    มันจะเห็นหมวดที่ลบไปแล้วว่า "มีอยู่" แล้วไม่ยอมสร้างใหม่ ⇒ INSERT คืน NULL
        #    → ตกไป branch `if cat_id is None` → คืน id ของหมวดที่ถูกลบ = บั๊กเดิมกลับมา
        cat_id = await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               SELECT $1, $2, 'income'
               WHERE NOT EXISTS (
                   SELECT 1 FROM finance_categories
                   WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
                     AND deleted_at IS NULL
               )
               RETURNING id""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
        if cat_id is None:
            # อีก request สร้างไปแล้วระหว่าง SELECT กับ INSERT → ดึงกลับมา
            return await conn.fetchval(
                """SELECT id FROM finance_categories
                   WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
                     AND deleted_at IS NULL
                   ORDER BY id LIMIT 1""",
                room_id, DEFAULT_INCOME_CATEGORIES[0],
            )
        return cat_id

    @classmethod
    async def _resolve_default_income_ledger(cls, conn: asyncpg.Connection, room_id: int) -> int:
        """[F4] หา/สร้าง revenue ledger "รายได้ค่าเริ่มต้น" ของห้อง แล้ว **คืน id หรือ raise**

        🔴 ใช้ร่วมกันโดย `_confirm_single_payment` (รับเงินสด) และ `_apply_plan_locked`
        (หักเครดิตปิดบิล) — **ต้องเป็นตัวเดียวกันจริง ๆ** ไม่ใช่โค้ดท่าคล้ายกัน 2 ชุด
        เพราะทั้งคู่ต้องได้ ledger **ตัวเดียวกัน** ไม่งั้นรายได้ของบิลเดียวกันจะไปอยู่คนละ
        บัญชีขึ้นกับว่าจ่ายด้วยเงินสดหรือเครดิต แล้วรายงานแยกตามหมวดจะเพี้ยนแบบหาสาเหตุยาก

        ⚠️ ต้องเป็น ledger ที่มี `legacy_category_id` ชี้ไปหมวดจริง (ไม่ใช่ ledger ลอย ๆ)
           เพราะ `budgets.py` นับการใช้/รับของงบประมาณด้วย `AL.legacy_category_id = B.category_id`
           ⇒ ledger ที่ไม่ผูกหมวดจะทำให้ "งบประมาณไม่เห็นรายได้ก้อนนี้" เงียบ ๆ
           ขั้นตอนที่ (2) จึงต้องผ่าน `_resolve_category_ledger` (ซึ่งใส่ legacy_category_id ให้)
           ไม่ใช่ INSERT ledger เอง

        ลำดับ: (1) หา ledger รายได้ชื่อ '📥 เก็บเงินห้องปกติ' → (2) สร้างหมวดนั้นแล้ว
        resolve ledger ตามหมวด → (3) ถ้ายังไม่ได้ = raise (rollback ทั้งชุด)
        """
        revenue_ledger_id = await cls._find_revenue_ledger_by_name(
            conn, room_id, account_name=DEFAULT_INCOME_CATEGORIES[0]
        )
        if revenue_ledger_id is None:
            # [FIX A] ปิดรอยรั่วข้าม dual-write: ห้องที่ยังไม่มี ledger รายได้/หมวดหมู่ค่าเริ่มต้น
            # → สร้างหมวด '📥 เก็บเงินห้องปกติ' (ถ้ายังไม่มี) + revenue ledger ให้อัตโนมัติ
            # เพื่อให้ journal ครบฝั่ง (กัน "legacy ได้เงิน แต่บัญชีคู่ไม่มีบิล")
            legacy_cat_id = await cls._find_or_create_default_income_category(conn, room_id)
            if legacy_cat_id:
                revenue_ledger_id = await cls._resolve_category_ledger(
                    conn, room_id, legacy_cat_id, 'income'
                )
        # ห้ามข้าม dual-write: ถ้าหา/สร้าง ledger รายได้ไม่ได้ → error (rollback ทั้งชุด) แทนที่จะเงียบ
        if revenue_ledger_id is None:
            raise ValueError("ไม่สามารถหา/สร้าง ledger รายได้ '📥 เก็บเงินห้องปกติ' เพื่อบันทึกบัญชีคู่ได้")
        return revenue_ledger_id

    @classmethod
    async def _insert_journal_entry(
        cls, conn: asyncpg.Connection, room_id: int,
        *,
        reference_type: str, reference_id: Optional[str] = None,
        description: str, recorded_by: Optional[str] = None, slip_image_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        lines: List[dict],  # [{"ledger_id": int, "debit": float, "credit": float}, ...]
        transaction_date: Optional[datetime] = None,
    ) -> str:
        """[DUAL-WRITE] สร้าง journal_entries (หัวบิล) + journal_lines (เดบิต/เครดิต) ใน transaction เดียวกับ legacy.
        คืน UUID ของ journal entry (สำหรับ revert ตาม reference ภายหลัง).
        💡 เงินทุกจำนวน cast float() ก่อน (กฎ CLAUDE.md: NUMERIC ต้อง cast ก่อน arithmetic)

        `transaction_date` — ระบุเฉพาะตอน **backfill ย้อนหลัง** (ดู `finance/backfill.py`)
        - ค่าเริ่มต้น (`None`) = ปล่อยให้ DB ใช้ `DEFAULT CURRENT_TIMESTAMP` ซึ่งถูกต้องสำหรับ
          dual-write ปกติ เพราะรายการถูกบันทึกตอนที่เงินเคลื่อนไหวจริง
        - backfill ต้องส่ง **เวลาที่เงินเคลื่อนไหวจริง** (จาก `finance_transactions.created_at`)
          ไม่งั้นรายการย้อนหลังจะไปกองอยู่ที่ "วันนี้" และเดือนที่แล้วก็ยังขาดรายการนั้นอยู่ดี
        - ⚠️ ต้องเป็น datetime แบบ **tz-aware** เสมอ (ส่ง `_as_utc(row["created_at"])` มา)
          ห้ามส่ง naive เพราะการตีความของ asyncpg ขึ้นกับ TZ ของเครื่องที่รัน
        - 💡 `created_at` ของ journal **ไม่**ถูกตั้งตาม — ปล่อยเป็น NOW() เพื่อให้ยังตรวจสอบได้ว่า
          แถวนี้ถูกสร้างขึ้นเมื่อไหร่ (ไม่มีโค้ดส่วนใดอ่าน `journal_entries.created_at`)
        """
        if transaction_date is None:
            entry_id = await conn.fetchval(
                """INSERT INTO journal_entries (room_id, reference_type, reference_id, description, slip_image_url, recorded_by, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                   RETURNING id""",
                room_id, reference_type, reference_id, description, slip_image_url, recorded_by,
                json.dumps(metadata or {}, ensure_ascii=False),
            )
        else:
            entry_id = await conn.fetchval(
                """INSERT INTO journal_entries (room_id, reference_type, reference_id, description, slip_image_url, recorded_by, metadata, transaction_date)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                   RETURNING id""",
                room_id, reference_type, reference_id, description, slip_image_url, recorded_by,
                json.dumps(metadata or {}, ensure_ascii=False), transaction_date,
            )
        for line in lines:
            debit = line.get("debit", 0) or 0
            credit = line.get("credit", 0) or 0
            await conn.execute(
                """INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                   VALUES ($1, $2, $3, $4, $5)""",
                entry_id, line["ledger_id"], float(debit), float(credit), line.get("line_description"),
            )
        return entry_id

    @classmethod
    async def _scan_account_diffs(
        cls, conn: asyncpg.Connection, *, room_id: int, threshold: float = 0.01
    ) -> List[dict]:
        """[RECONCILE] อ่านล้วน ๆ: เปรียบเทียบ finance_accounts.balance (ระบบเดิม)
        กับยอดสุทธิ asset-ledger ของบัญชีนั้นในบัญชีคู่ (SUM(debit−credit) เฉพาะ journal
        ที่ไม่ void / ไม่ลบ — เงื่อนไขเดียวกับ _get_summary_v2).

        คืน list: {account_id, account_name, legacy_balance, ledger_net, ledger_id,
                   diff, amount, action} โดย action ∈ 'dr_asset'|'cr_asset'|'skip'
        (ledger_id เป็น None ถ้ายังไม่มี asset ledger ของบัญชี → ถือ net = 0)"""
        rows = await conn.fetch(
            """SELECT
                    FA.id AS account_id,
                    FA.account_name AS account_name,
                    FA.balance AS legacy_balance,
                    AL.id AS ledger_id,
                    COALESCE(NET.net, 0) AS ledger_net
                FROM finance_accounts FA
                LEFT JOIN LATERAL (
                    SELECT id FROM accounting_ledgers
                    WHERE legacy_account_id = FA.id
                      AND room_id = FA.room_id
                      AND account_type = 'asset'
                    ORDER BY id
                    LIMIT 1
                ) AL ON TRUE
                LEFT JOIN LATERAL (
                    SELECT SUM(L.debit - L.credit) AS net
                    FROM journal_lines L
                    JOIN journal_entries JE ON L.journal_entry_id = JE.id
                    WHERE L.ledger_id = AL.id
                      AND JE.room_id = FA.room_id
                      AND JE.deleted_at IS NULL
                      AND JE.status <> 'voided'
                ) NET ON TRUE
                WHERE FA.room_id = $1
                  AND FA.deleted_at IS NULL
                ORDER BY FA.id""",
            room_id,
        )
        result = []
        for r in rows:
            legacy = float(r["legacy_balance"])
            net = float(r["ledger_net"])
            diff = round(legacy - net, 4)
            if abs(diff) < threshold:
                action = "skip"
                amount = 0.0
            else:
                action = "dr_asset" if diff > 0 else "cr_asset"
                amount = abs(diff)
            result.append({
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "legacy_balance": legacy,
                "ledger_net": net,
                "ledger_id": r["ledger_id"],
                "diff": diff,
                "amount": amount,
                "action": action,
            })
        return result

    @classmethod
    async def _resolve_reconcile_equity_ledger(cls, conn: asyncpg.Connection, *, room_id: int) -> int:
        """[RECONCILE] หา/สร้าง ledger equity '3001' (ปรับปรุงยอด) ให้ห้อง — ใช้เป็นขา
        สะท้อน (mirror) ของรายการปรับปรุง เพื่อให้ Dr = Cr โดยไม่แตะ Net Worth (asset-only)
        และไม่ปนรายได้/รายจ่ายของงวด"""
        ledger_id = await conn.fetchval(
            """SELECT id FROM accounting_ledgers
               WHERE room_id = $1 AND account_code = $2 AND account_type = 'equity'
               ORDER BY id LIMIT 1""",
            room_id, RECONCILE_EQUITY_CODE,
        )
        if ledger_id:
            return ledger_id
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description)
               VALUES ($1, $2, $3, 'equity', $4)
               RETURNING id""",
            room_id, RECONCILE_EQUITY_CODE, RECONCILE_EQUITY_NAME,
            "บัญชีพักปรับปรุงผลต่างระหว่างยอด Legacy กับบัญชีคู่ (สร้างอัตโนมัติโดย reconcile_finance)",
        )

    @classmethod
    async def _resolve_advance_ledger(cls, conn: asyncpg.Connection, *, room_id: int) -> int:
        """[F4] หา/สร้าง ledger **หนี้สิน** '2099' (เงินรับล่วงหน้า) ให้ห้อง — ใช้เป็นขา Cr
        ของการรับเงินล่วงหน้า และขา Dr ของการหักเครดิตไปปิดบิล

        🔴 นี่คือ liability ledger **ตัวแรกของระบบ** — ก่อนหน้านี้ไม่มีใครสร้างเลย
        (ACCOUNT_TYPE_LABELS มี 'liability' และงบดุลก็รวม liability_total อยู่แล้ว
        ⇒ ชั้นรายงานไม่ต้องแก้อะไร งานนี้แค่ทำให้มีข้อมูลจริง ๆ สักที)

        ⚠️ ต่างจาก `_resolve_asset_ledger`/`_resolve_category_ledger` ตรงที่ **ไม่มี
        `legacy_account_id`/`legacy_category_id`** — ไม่ได้ map กับตาราง legacy ใดเลย
        ⇒ `_scan_account_diffs` (reconcile) ซึ่งวนจาก `finance_accounts` และกรอง
        `account_type = 'asset'` จะ **มองไม่เห็น ledger นี้** ⇒ สร้าง diff ปลอมไม่ได้

        ⚠️ ใช้ `(room_id, account_code, account_type)` เป็นคีย์ค้น — ไม่ใช่ `account_code`
        เดี่ยว ๆ เพราะเลขรหัสบัญชีไม่ unique ข้ามห้อง
        """
        ledger_id = await conn.fetchval(
            """SELECT id FROM accounting_ledgers
               WHERE room_id = $1 AND account_code = $2 AND account_type = 'liability'
               ORDER BY id LIMIT 1""",
            room_id, ADVANCE_LIABILITY_CODE,
        )
        if ledger_id:
            return ledger_id
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description)
               VALUES ($1, $2, $3, 'liability', $4)
               RETURNING id""",
            room_id, ADVANCE_LIABILITY_CODE, ADVANCE_LIABILITY_NAME,
            "เงินที่รับมาก่อนที่จะมีบิล — ยังไม่ใช่รายได้จนกว่าจะหักปิดบิล (สร้างอัตโนมัติโดย credits)",
        )

    @classmethod
    async def reconcile_balances(
        cls,
        pool: asyncpg.Pool,
        *,
        room_id: Optional[int] = None,
        server_id: Optional[int] = None,
        apply: bool = False,
        threshold: float = 0.01,
    ) -> dict:
        """[RECONCILE] กระทบยอดเงินของห้องเดียว: เทียบ finance_accounts.balance (ระบบเดิม
        = แหล่งความจริง) กับยอดสุทธิ asset-ledger ในบัญชีคู่ของแต่ละบัญชี.

        - dry-run (default): แค่รายงานผลต่าง ไม่เขียนอะไร
        - apply=True: ใน transaction เดียว สร้าง asset ledger ที่ขาด + equity '3001' (ถ้ายังไม่มี)
          แล้ว insert journal_entries reference_type='adjustment' 1 ใบต่อบัญชีที่ต่างกัน
          (asset Dr / equity Cr เมื่อ legacy มากกว่า, asset Cr / equity Dr เมื่อ ledger เกิน)
          ให้ยอดบัญชีคู่กลับมาเท่ากับ Legacy เป๊ะ ๆ

        ⚠️ Ops tool: ไม่ล็อก **แถว** ระหว่าง apply → ควรวิ่งช่วงที่ไม่มีรายการสด
           แต่ตั้งแต่มี lock protocol ตัวนี้ยึด advisory lock ของห้องด้วย (ดู `_lock_room_money`)
           ⇒ ถ้ามีคนรันระหว่างที่มีรายการสด มันจะ **รอ** จนเส้นทางเงินปล่อยล็อก แทนที่จะแทรก
             กลางtransaction ของเขา (ความเสี่ยงเดิมคืออ่านยอดแล้วเขียนทับระหว่างที่ยอดขยับ)
        คืน dict รายงาน (ตัวเลขเป็น float, journal_entry_id เป็น str)
        """
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            async with conn.transaction():
                # 🔒 ล็อกห้องก่อนสแกน/เขียนใด ๆ (protocol เดียวกันทั้งระบบ)
                await _lock_room_money(conn, resolved_room_id)
                rows = await cls._scan_account_diffs(conn, room_id=resolved_room_id, threshold=threshold)
                mismatches = [r for r in rows if r["action"] != "skip"]
                room_name = await conn.fetchval(
                    "SELECT room_name FROM rooms WHERE id = $1", resolved_room_id
                )
                report = {
                    "room_id": resolved_room_id,
                    "room_name": room_name,
                    "apply": apply,
                    "threshold": threshold,
                    "checked_accounts": len(rows),
                    "adjustments_created": 0,
                    "total_adjustment_amount": 0.0,
                    "mismatches": mismatches,
                }
                if apply and mismatches:
                    equity_ledger_id = None
                    for m in mismatches:
                        asset_ledger_id = m["ledger_id"]
                        if asset_ledger_id is None:
                            asset_ledger_id = await cls._resolve_asset_ledger(
                                conn, resolved_room_id, m["account_id"]
                            )
                        if equity_ledger_id is None:
                            equity_ledger_id = await cls._resolve_reconcile_equity_ledger(
                                conn, room_id=resolved_room_id
                            )
                        amount = float(m["amount"])
                        if m["action"] == "dr_asset":
                            lines = [
                                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                                 "line_description": f"ปรับปรุงยอดบัญชีให้ตรงกับระบบเดิม (เดิมขาด {amount:.2f} บาท)"},
                                {"ledger_id": equity_ledger_id, "debit": 0, "credit": amount,
                                 "line_description": "ปรับปรุงยอด (Reconciliation) ฝั่งทุน"},
                            ]
                        else:  # cr_asset
                            lines = [
                                {"ledger_id": asset_ledger_id, "debit": 0, "credit": amount,
                                 "line_description": f"ปรับปรุงยอดบัญชีให้ตรงกับระบบเดิม (เดิมเกิน {amount:.2f} บาท)"},
                                {"ledger_id": equity_ledger_id, "debit": amount, "credit": 0,
                                 "line_description": "ปรับปรุงยอด (Reconciliation) ฝั่งทุน"},
                            ]
                        entry_id = await cls._insert_journal_entry(
                            conn, resolved_room_id,
                            reference_type=RECONCILE_REFERENCE_TYPE,
                            description=f"ปรับปรุงยอดคงเหลือให้ตรงกับระบบเดิม: {m['account_name']} (Reconciliation)",
                            recorded_by="SYSTEM",
                            metadata={
                                "adjustment_type": "reconcile",
                                "finance_account_id": m["account_id"],
                                "legacy_balance": float(m["legacy_balance"]),
                                "ledger_net_before": float(m["ledger_net"]),
                                "direction": "debit_asset" if m["action"] == "dr_asset" else "credit_asset",
                            },
                            lines=lines,
                        )
                        m["journal_entry_id"] = str(entry_id)
                        report["adjustments_created"] += 1
                        report["total_adjustment_amount"] = round(report["total_adjustment_amount"] + amount, 4)
                    if report["adjustments_created"]:
                        await service_logger.log(
                            conn=conn, action="RECONCILE", actor_identifier="SYSTEM",
                            client_source="script", room_id=resolved_room_id,
                            entity_type="FINANCE_RECONCILE", entity_id=str(resolved_room_id),
                            status="success",
                            new_values={
                                "adjustments_created": report["adjustments_created"],
                                "total_amount": report["total_adjustment_amount"],
                            },
                            endpoint_or_command="FinanceService.reconcile_balances",
                        )
            return report

    @classmethod
    def _classify_journal_entry(cls, entry: dict, transaction_type: Optional[str] = None) -> Optional[dict]:
        """[DOUBLE-ENTRY] จัดประเภทบิลจากชุด journal_lines เป็นแถว TransactionResponse
        ที่ frontend ใช้อยู่ (amount, description, transaction_type, account_name, category_name).

        คืน None ถ้าบิลไม่ตรง transaction_type ที่กรอง (คล้าย WHERE ใน legacy).
        """
        lines = entry["lines"]

        # [F4] 🔴 การหักเครดิตปิดบิล **ต้องไม่โผล่ในประวัติเงินเคลื่อนไหว** — คืน None ทิ้งไป
        #
        # เหตุผล: ตารางที่ hàm นี้ป้อนคือ **"เงินเข้าออกของกระเป๋า"** (ระบบเดิมนับจาก
        # `finance_transactions`) และการหักเครดิต **ไม่มีแถว legacy เลยโดยเจตนา** —
        # เงินเข้ามาตั้งแต่ตอน "เติมเครดิต" แล้ว (ดู `CreditsMixin.top_up_credit`)
        #
        # ⚠️ ถ้าไม่กรอง รายการนี้จะถูกจัดเป็น `income` (เพราะมี Cr ฝั่ง revenue) แล้ว
        #    ประวัติจะโชว์เงินเข้า 2 ครั้งจากการรับเงินจริงครั้งเดียว (1000 ตอนเติม + 700 ตอนหัก)
        #    ⇒ "รายรับ" ในชีตเดินบัญชีสูงกว่ากระเป๋าจริง ⇒ ผู้ใช้เชื่อตัวเลขไม่ได้ทั้งหน้า
        #
        # 💡 รายได้ก้อนนี้ **ไม่หายไปไหน** — ยังอยู่ในงบกำไรขาดทุน / `_get_summary_v2` /
        #    งบประมาณ / GL / Trial Balance ทั้งหมด เพราะพวกนั้นอ่าน `journal_lines` ตรง ๆ
        #    โดยไม่ผ่าน hàmนี้ (มีเทสต์ปิดไว้)
        if entry["reference_type"] == REFERENCE_TYPE_CREDIT_APPLY:
            return None

        asset_lines = [ln for ln in lines if ln["account_type"] == "asset"]
        revenue_lines = [ln for ln in lines if ln["account_type"] == "revenue"]
        expense_lines = [ln for ln in lines if ln["account_type"] == "expense"]
        # [F4] ขา liability — จำเป็นสำหรับ "เงินรับล่วงหน้า" (Dr สินทรัพย์ / Cr หนี้สิน)
        #      ⚠️ **ไม่ใช่** รายได้ ⇒ ไม่มีทางถูกนับใน `revenue_cr` (คนละ account_type)
        #      ⇒ งบกำไรขาดทุน/`_get_summary_v2` ที่กรอง `account_type = 'revenue'`
        #        ไม่เห็นรายการนี้เลยโดยอัตโนมัติ (ไม่ต้องแก้อะไรฝั่งนั้น)
        liability_lines = [ln for ln in lines if ln["account_type"] == "liability"]
        asset_dr = sum(float(ln["debit"]) for ln in asset_lines)
        asset_cr = sum(float(ln["credit"]) for ln in asset_lines)
        revenue_cr = sum(float(ln["credit"]) for ln in revenue_lines)
        expense_dr = sum(float(ln["debit"]) for ln in expense_lines)
        liability_cr = sum(float(ln["credit"]) for ln in liability_lines)

        description = entry["description"] or ""
        recorded_by = entry["recorded_by"]
        txn_type: Optional[str] = None
        amount = 0.0
        account_name: Optional[str] = None
        category_name: Optional[str] = None
        transfer_group_id = None

        # [DOUBLE-ENTRY] 1) ยอดยกมา (Opening Balance) → เงินเข้าสินทรัพย์ = 'income'
        if entry["reference_type"] == "opening_balance":
            txn_type = "income"
            # ยอด = เดบิตฝั่ง Asset (เงินที่มีจริงในกระเป๋า) ไม่รวมขา Equity
            amount = asset_dr
            # ถ้าสินทรัพย์ติดลบ (credit asset) → ให้รวมเครดิตเข้าด้วยเพื่อไม่ให้ amount เป็น 0
            if amount == 0.0:
                amount = asset_cr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            category_name = "ยอดยกมา (เปิดระบบบัญชีคู่)"
            description = description or "ยอดยกมา"

        # [DOUBLE-ENTRY] 2) Transfer ระหว่างบัญชีสินทรัพย์ → 'expense' (ขาออก) + transfer_group_id
        elif len(asset_lines) >= 2 and asset_dr > 0 and asset_cr > 0:
            txn_type = "expense"
            amount = asset_cr
            # บัญชีที่เงินออก (credit) — เป็นบัญชีต้นทาง
            out_line = next((ln for ln in asset_lines if float(ln["credit"]) > 0), asset_lines[0])
            account_name = out_line["account_name"]
            category_name = "โอนเงิน"
            transfer_group_id = entry["reference_id"] and int(entry["reference_id"]) or None
            recorded_by = recorded_by

        # [DOUBLE-ENTRY] 3) รายได้: Asset เดบิต + Revenue เครดิต (รับเงินเข้า)
        elif asset_dr > 0 and revenue_cr > 0:
            txn_type = "income"
            amount = asset_dr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            if revenue_lines:
                category_name = revenue_lines[0]["account_name"]
            description = description or "รายได้"

        # [DOUBLE-ENTRY] 4) รายจ่าย: Expense เดบิต + Asset เครดิต (เงินออก)
        elif expense_dr > 0 and asset_cr > 0:
            txn_type = "expense"
            amount = asset_cr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            if expense_lines:
                category_name = expense_lines[0]["account_name"]
            description = description or "รายจ่าย"

        # [F4] 5) เงินรับล่วงหน้า: Asset เดบิต + Liability เครดิต (รับเงินเข้ามาพัก)
        #     🔴 ถ้าไม่มีสาขานี้ เงินที่เข้าจริงในกระเป๋าจะ **หายจากประวัติธุรกรรมทั้งหน้า**
        #        เพราะ Dr asset / Cr liability ตกลงไปที่ `else` แล้ว `return None` (บรรทัดล่าง)
        #        อาการที่เห็น: `finance_accounts.balance` เพิ่มขึ้น แต่ประวัติไม่แสดงอะไรเลย
        #        ⇒ "ยอดในกระเป๋า อธิบายจากรายการไม่ได้" ซึ่งเป็นอาการที่ repo นี้เฝ้าระวังที่สุด
        #
        #     ⚠️ จัดเป็น `income` โดยเจตนา — **ไม่ใช่** การบอกว่ามันเป็น "รายได้":
        #        ช่องนี้คือ "กระแสเงินเข้า/ออก" ของกระเป๋า ไม่ใช่รายได้ทางบัญชี
        #        มีแบบอย่างอยู่แล้วในสาขา 1) (ยอดยกมา = Dr asset / Cr equity → `income`)
        #        ซึ่ง **ไม่ถูกนับเป็นรายได้ในงบกำไรขาดทุน** เช่นเดียวกัน
        #        (`_get_income_statement` กรอง `reference_type <> 'opening_balance'`
        #         และนับเฉพาะ `account_type = 'revenue'` ⇒ ไม่มีทางนับ top-up เป็นรายได้)
        #        ⇒ ตัวเลขคอลัมน์ "รายรับ" ของชีตเดินบัญชี ≠ `total_revenue` ของงบ P&L ได้
        #          อยู่แล้วโดยการออกแบบ ไม่ใช่ความไม่สอดคล้องที่เกิดจากงานนี้
        #     💡 `category_name` ใช้ชื่อ ledger หนี้สิน ("เงินรับล่วงหน้า (เครดิตนักเรียน)")
        #        ⇒ คอลัมน์ "หมวด" บอกความจริงว่าไม่ใช่หมวดรายได้
        elif asset_dr > 0 and liability_cr > 0:
            txn_type = "income"
            amount = asset_dr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            if liability_lines:
                category_name = liability_lines[0]["account_name"]
            description = description or "รับเงินล่วงหน้า"

        # [DOUBLE-ENTRY] 6) กรณีโครงสร้างอื่น (ไม่มี asset) → พยายามเดาจากฝั่งที่มี
        else:
            if revenue_cr > 0:
                txn_type = "income"
                amount = revenue_cr
                if revenue_lines:
                    category_name = revenue_lines[0]["account_name"]
            elif expense_dr > 0:
                txn_type = "expense"
                amount = expense_dr
                if expense_lines:
                    category_name = expense_lines[0]["account_name"]
            else:
                return None

        # [DOUBLE-ENTRY] รองรับ filter transaction_type (income/expense) แบบเดียวกับ legacy
        if transaction_type and txn_type != transaction_type:
            return None

        # 💡 เก็บบรรทัดแรกของ asset ไว้เป็น account (หน้า frontend ใช้แสดงกระเป๋าเงิน)
        if not account_name and asset_lines:
            account_name = asset_lines[0]["account_name"]
        if not account_name:
            account_name = "—"

        return {
            "id": _legacy_id_from_journal(entry.get("metadata") or {}, entry.get("journal_entry_id")),
            "amount": float(amount),
            "description": description,
            "transaction_type": txn_type,
            "created_at": entry["transaction_date"],
            "slip_image_url": entry["slip_image_url"],
            "recorded_by": recorded_by,
            "account_name": account_name,
            "category_name": category_name,
            "transfer_group_id": transfer_group_id,
        }
