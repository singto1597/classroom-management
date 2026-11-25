"""💸 [FIN-V2 / P4.1] ใบสำคัญจ่ายหลายบรรทัด (expense vouchers)

═══════════════════════════════════════════════════════════════════════════════
🎯 1 ใบ = 1 `finance_expense_vouchers` + N `finance_expense_lines`
═══════════════════════════════════════════════════════════════════════════════
ทุกบรรทัดมี **กระเป๋า/หมวด/งบของตัวเอง** และเขียน **journal แยกใบต่อบรรทัด**
(Dr ค่าใช้จ่าย / Cr สินทรัพย์) — ห้ามรวมเป็นก้อนเดียว เพราะงบประมาณและรายงาน
อ่านยอดใช้จาก `journal_lines → accounting_ledgers.legacy_category_id` ต่อหมวด
⇒ ยอดรวมก้อนเดียวจะทำให้ยอดหมวดเพี้ยนและย้อนกลับทีละบรรทัดไม่ได้

🔴 กฎที่ห้ามพลาด
   1. ตรวจ **ทุกอย่าง** (จำนวนบรรทัด/ยอด/หมวด/งบ/กระเป๋า/เงินพอ) ก่อนเขียนแถวแรก
   2. `_lock_room_money` ก่อนแตะแถวใด ๆ แล้วล็อกกระเป๋าทุกใบ **ตาม id เรียงขึ้น**
      (สองคำขอที่ใช้กระเป๋าคู่เดียวกันแต่คนละลำดับบรรทัดจะไม่ deadlock)
   3. **PV ออกเสมอ 1 ใบต่อ voucher** (`layout_version=2`, `idempotency_key='pv:{id}'`)
      โดย `legacy_transaction_id` = transaction ของ **บรรทัดแรก** (index เดิม
      `idx_finance_receipts_voucher_active` ใช้กันซ้ำต่อ txn)
   4. retry คีย์เดิม + payload เดิม ⇒ คืนใบเดิม (`reused=true`) — ตรวจด้วย
      `document_meta.request_hash` ของ PV; payload ต่าง ⇒ 409
   5. CERT **ไม่ใช่ของ P4.1** — P4.2 ออก CERT สำหรับบรรทัด `receipt_status='none'`
      (`cert_receipt_id` ยังเป็น NULL ที่นี่)

ℹ️ ไฟล์นี้ไม่เรียก `_issue_payment_voucher` (ของเดิมเป็นใบบรรทัดเดียวและ snapshot
   คนละ shape) และ **ไม่แตะ** `receipts.py`/`documents.py`/`transactions.py`
"""
import hashlib
import json
import time
from datetime import date
from decimal import Decimal
from typing import Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
# 🧾 [FIN-V2 / P4.2] CERT พ่วง PV — ฟังก์ชันระดับโมดูล ไม่ใช่ mixin (ไม่มีชื่อชน)
from .certificates import issue_certificate_locked
from .constants import (
    BUDDHIST_ERA_OFFSET, DOC_TYPE_PAYMENT_VOUCHER, DOC_TYPE_PREFIXES,
    RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_MAX, RECEIPT_SEQ_OVERFLOW_MSG, THAI_TZ,
)
from .helpers import _as_utc

# 🧾 ชนิดเอกสารของลายเซ็น — ตรงกับ `doc_type` ใน `finance_receipts`
_SIGN_DOC_TYPE = DOC_TYPE_PAYMENT_VOUCHER
# 🛡️ เพดานบรรทัดต่อใบ (brief: 1..50) — ตรวจใน service เพื่อให้ได้ 400 พร้อมข้อความไทย
_MAX_LINES = 50
# 🎭 สถานะใบตัด/gตรวจได้
_ALLOWED_STATUS = ("active", "voided")


class ExpenseVoucherNotFoundError(Exception):
    """ไม่พบใบสำคัญจ่ายของห้อง ⇒ router แปลเป็น 404"""


class ExpenseVoucherIdempotencyConflict(ValueError):
    """คีย์เดิมแต่ payload ต่าง ⇒ router แปลเป็น 409 (ต้องจับก่อน ValueError)"""


def _json_of(value) -> dict:
    """อ่าน jsonb ที่ asyncpg คืนเป็น **สตริง** (ไม่มี codec) ให้เป็น dict อย่างปลอดภัย"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _money(value) -> float:
    """Decimal/float → float 2 ตำแหน่ง (สำหรับ response/snapshot เท่านั้น)"""
    return round(float(value or 0), 2)


def _dec(value: float) -> Decimal:
    """float → Decimal 2 ตำแหน่ง (ค่าที่ส่งเข้า NUMERIC ต้องไม่มี binary noise)"""
    return Decimal(f"{value:.2f}")


def _budget_label(row) -> Optional[str]:
    """ป้ายงบสำหรับ snapshot — derive จากช่วงวันที่ที่ materialize ไว้"""
    if not row:
        return None
    if row["period_type"] == "monthly" and row["period_month"]:
        return f"รายเดือน {row['period_year']}-{int(row['period_month']):02d}"
    if row["period_type"] == "yearly":
        return f"รายปี {row['period_year']}"
    return f"{row['start_date']} – {row['end_date']}"


class ExpenseVouchersMixin:
    """ใบสำคัญจ่ายหลายบรรทัด — สร้าง/อ่าน (void เป็นของ P6.1)"""

    # ─────────────────────────────────────────────────────────────────────
    # ตัวช่วยภายใน (caller เป็นเจ้าของ transaction)
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _expense_request_hash(req) -> str:
        """hash ของ payload ทั้งก้อน — เก็บใน `document_meta` ของ PV เพื่อตรวจ replay

        ⚠️ ใช้ `model_dump(mode="json")` เพื่อให้ `date`/`Decimal` กลายเป็นค่า
           ที่ serialize ได้แน่นอน (ถ้าใช้ `mode="python"` ค่า `Decimal`/`date`
           จะทำให้ `json.dumps` ระเบิดหรือ hash ไม่คงที่)
        """
        payload = json.dumps(
            req.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    async def _issue_expense_pv_locked(
        cls,
        conn: asyncpg.Connection,
        target_room_id: int,
        voucher_id: int,
        total: float,
        payee_name: str,
        user_id: int,
        user_name: str,
        note: Optional[str],
        first_txn_id: int,
        first_txn_created_at,
        snapshot: str,
        document_meta: str,
    ) -> dict:
        """ออก PV ของ voucher (caller ยึด `_lock_room_money` ไว้แล้ว)

        🔑 `idempotency_key = f"pv:{voucher_id}"` ⇒ `idx_finance_receipts_idem`
           กัน PV ซ้ำต่อ voucher ได้โดยไม่พึ่ง `legacy_transaction_id`
        🗓️ ปี พ.ศ. มาจาก **เวลาที่จ่ายจริง** (`finance_transactions.created_at` naive
           UTC) ไม่ใช่เวลาที่กดออกเอกสาร
        🔁 SAVEPOINT ครอบ INSERT — ห้ามจับ `UniqueViolationError` แล้วอ่าน `conn`
           ใน transaction ที่ aborted (`25P02`) ⇒ ต้องมี savepoint (บทเรียน skills.md)
        """
        event_at = _as_utc(first_txn_created_at)
        issued_at = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        year_be = event_at.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        idem = f"pv:{voucher_id}"

        # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน)
        existing = await conn.fetchrow(
            """SELECT id, receipt_no FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 AND idempotency_key = $3
                 AND deleted_at IS NULL""",
            target_room_id, _SIGN_DOC_TYPE, idem,
        )
        if existing:
            return {"id": existing["id"], "receipt_no": existing["receipt_no"]}

        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, _SIGN_DOC_TYPE,
        )
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[_SIGN_DOC_TYPE], year_be=year_be, seq=seq,
        )

        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                            issued_to_name, issued_by, issued_by_name, note, event_at, issued_at,
                            line_items, voucher_snapshot, layout_version, idempotency_key, document_meta)
                       VALUES ($1,$2,$3,$4,$5,NULL,$6,NULL,NULL,$7,$8,$9,$10,$11,$12,$13,$14,
                               NULL,$15,2,$16,$17)
                       RETURNING id, receipt_no""",
                    target_room_id, receipt_no, _SIGN_DOC_TYPE, year_be, seq,
                    first_txn_id, _dec(total), _dec(total),
                    payee_name, user_id, user_name, note,
                    event_at, issued_at,
                    snapshot, idem, document_meta,
                )
        except asyncpg.UniqueViolationError:
            # 🔁 แพ้การแข่งขัน: คืนใบที่ชนะ (savepoint ทำให้ transaction ยังใช้ได้)
            raced = await conn.fetchrow(
                """SELECT id, receipt_no FROM finance_receipts
                   WHERE room_id = $1 AND doc_type = $2 AND idempotency_key = $3
                     AND deleted_at IS NULL""",
                target_room_id, _SIGN_DOC_TYPE, idem,
            )
            if raced:
                return {"id": raced["id"], "receipt_no": raced["receipt_no"]}
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")
        return {"id": row["id"], "receipt_no": row["receipt_no"]}

    @classmethod
    async def _resolve_actor_name(cls, conn: asyncpg.Connection, user_id: int) -> str:
        """ชื่อผู้ใช้สำหรับลายเซ็นผู้จัดทำ — อ่านจากโปรไฟล์ (รูปแบบเดียวกับ `_display_name`)"""
        row = await conn.fetchrow(
            """SELECT first_name, first_name_en, nickname, username
               FROM users WHERE id = $1""",
            user_id,
        )
        if not row:
            return "ผู้ใช้"
        name = row["first_name"] or row["first_name_en"] or row["username"] or "ผู้ใช้"
        if row["nickname"]:
            name += f" ({row['nickname']})"
        return name

    @classmethod
    async def _insert_voucher_signatures(
        cls,
        conn: asyncpg.Connection,
        target_room_id: int,
        pv_receipt_id: int,
        signatures: list,
    ) -> None:
        """บันทึก 3 ลายเซ็น (prepared/approved/receiver) — `signed_at` NULL โดยเจตนา

        🔴 `receiver` คือ **ผู้รับเงิน (payee)** ไม่ใช่ current user; `approved`
           fallback เป็น current user ได้ แต่ต้องบันทึกธงไว้ใน `document_meta`
        """
        for sort_order, sig in enumerate(signatures):
            await conn.execute(
                """INSERT INTO finance_document_signatures
                       (room_id, doc_type, doc_id, role, person_id, signer_name, signed_at, sort_order)
                   VALUES ($1, $2, $3, $4, $5, $6, NULL, $7)""",
                target_room_id, _SIGN_DOC_TYPE, pv_receipt_id,
                sig["role"], sig.get("person_id"), sig["signer_name"], sort_order,
            )

    # ─────────────────────────────────────────────────────────────────────
    # สร้างใบสำคัญจ่าย
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def create_expense_voucher(
        cls,
        pool: asyncpg.Pool,
        *,
        req,
        user_id: int,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """สร้างใบสำคัญจ่ายหลายบรรทัด — 1 คำขอ = 1 transaction = atomic ทั้งใบ"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🖊️ ชื่อผู้จัดทำ — payload มาก่อน ถ้าไม่มีอ่านจากโปรไฟล์ผู้ใช้
                    user_name = (user_name or "").strip() or await cls._resolve_actor_name(
                        conn, user_id
                    )

                    # 🧾 "อีกฝ่าย" บนกระดาษ — บังคับก่อนเขียนใด ๆ (แบบเดียวกับ add_transaction)
                    payee_name = (req.payee_name or "").strip()
                    if not payee_name:
                        raise ValueError("ต้องระบุผู้รับเงิน/ผู้เบิก เพราะชื่อนี้พิมพ์ลงบนใบสำคัญจ่าย")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ — protocol เดียวกันทั้งระบบ
                    await _lock_room_money(conn, target_room_id)

                    key = (req.idempotency_key or "").strip()
                    if not 8 <= len(key) <= 128:
                        raise ValueError("idempotency_key ต้องยาว 8–128 ตัวอักษร")

                    request_hash = cls._expense_request_hash(req)

                    # 🔁 idempotency ชั้นที่ 1 — อ่านก่อนเขียนใต้ล็อกห้อง
                    existing = await conn.fetchrow(
                        """SELECT id, total_amount, pv_receipt_id, cert_receipt_id, created_at
                           FROM finance_expense_vouchers
                           WHERE room_id = $1 AND idempotency_key = $2""",
                        target_room_id, key,
                    )
                    if existing:
                        line_count = await conn.fetchval(
                            "SELECT COUNT(*) FROM finance_expense_lines WHERE voucher_id = $1",
                            existing["id"],
                        )
                        pv = None
                        if existing["pv_receipt_id"]:
                            pv = await conn.fetchrow(
                                """SELECT id, receipt_no, document_meta FROM finance_receipts
                                   WHERE id = $1""",
                                existing["pv_receipt_id"],
                            )
                        stored_hash = _json_of(pv["document_meta"] if pv else None).get("request_hash")
                        if pv and stored_hash == request_hash:
                            # 🧾 P4.2 — replay ต้องคืน CERT เดิมด้วย (ไม่สร้างใหม่)
                            cert_row = None
                            if existing["cert_receipt_id"]:
                                cert_row = await conn.fetchrow(
                                    """SELECT id, receipt_no, amount, document_meta
                                       FROM finance_receipts WHERE id = $1""",
                                    existing["cert_receipt_id"],
                                )
                            cert_meta = (
                                _json_of(cert_row["document_meta"]) if cert_row else {}
                            )
                            return {
                                "id": existing["id"],
                                "total_amount": _money(existing["total_amount"]),
                                "line_count": int(line_count or 0),
                                "pv_receipt_id": pv["id"],
                                "pv_receipt_no": pv["receipt_no"],
                                "cert_receipt_id": cert_row["id"] if cert_row else None,
                                "cert_receipt_no": cert_row["receipt_no"] if cert_row else None,
                                "cert_amount": _money(cert_row["amount"]) if cert_row else None,
                                "cert_line_nos": cert_meta.get("source_line_nos") or [],
                                "created_at": existing["created_at"],
                                "reused": True,
                            }
                        raise ExpenseVoucherIdempotencyConflict(
                            "idempotency key นี้ถูกใช้กับใบสำคัญจ่ายใบอื่นแล้ว "
                            "(payload ไม่ตรงกับใบเดิม) — เปิดใบเดิมแทนการสร้างใหม่"
                        )

                    # ─────────────────────────────────────────────────
                    # 1) ตรวจทุกอย่างก่อนเขียนแถวแรก
                    # ─────────────────────────────────────────────────
                    lines = list(req.lines or [])
                    if not 1 <= len(lines) <= _MAX_LINES:
                        raise ValueError(f"ใบสำคัญจ่ายต้องมี 1–{_MAX_LINES} บรรทัด")

                    normalized = []
                    total = 0.0
                    for idx, line in enumerate(lines, start=1):
                        description = (line.description or "").strip()
                        if not description:
                            raise ValueError(f"บรรทัดที่ {idx}: ต้องระบุรายละเอียด")
                        amount = round(float(line.amount), 2)
                        if amount <= 0:
                            raise ValueError(f"บรรทัดที่ {idx}: ยอดต้องมากกว่า 0.00 บาท")
                        receipt_status = line.receipt_status or "none"
                        if receipt_status not in ("attached", "paper", "none"):
                            raise ValueError(f"บรรทัดที่ {idx}: สถานะใบเสร็จไม่ถูกต้อง")
                        funding_source = line.funding_source or "room_fund"
                        if funding_source not in ("room_fund", "pass_through"):
                            raise ValueError(f"บรรทัดที่ {idx}: แหล่งเงินไม่ถูกต้อง")
                        paper_bill_count = int(line.paper_bill_count or 0)
                        if paper_bill_count < 0:
                            raise ValueError(f"บรรทัดที่ {idx}: จำนวนบิลกระดาษต้องไม่ติดลบ")
                        normalized.append({
                            "line_no": idx,
                            "description": description,
                            "amount": amount,
                            "category_id": int(line.category_id),
                            "budget_id": int(line.budget_id) if line.budget_id else None,
                            "wallet_account_id": int(line.wallet_account_id),
                            "receipt_status": receipt_status,
                            "paper_bill_count": paper_bill_count,
                            "attachment_placeholder": (line.attachment_placeholder or "").strip() or None,
                            "funding_source": funding_source,
                        })
                        total += amount
                    total = round(total, 2)
                    if req.total_amount is not None and round(float(req.total_amount), 2) != total:
                        raise ValueError("ยอดรวมไม่ตรงกับผลรวมบรรทัด")

                    # 🏷️ หมวด — ต้องมีจริง ในห้องนี้ และเป็นประเภท expense เท่านั้น
                    category_ids = sorted({r["category_id"] for r in normalized})
                    category_rows = await conn.fetch(
                        """SELECT id, category_name, category_type FROM finance_categories
                           WHERE id = ANY($1::int[]) AND room_id = $2 AND deleted_at IS NULL""",
                        category_ids, target_room_id,
                    )
                    categories = {r["id"]: r for r in category_rows}
                    if len(categories) != len(category_ids):
                        raise RoomNotFoundError(
                            "มีหมวดหมู่ที่ไม่พบในห้องเรียนนี้ — กรุณาโหลดรายการหมวดใหม่"
                        )
                    for row in normalized:
                        if categories[row["category_id"]]["category_type"] != "expense":
                            raise ValueError(
                                f"บรรทัดที่ {row['line_no']}: หมวดนี้ไม่ใช่หมวดรายจ่าย"
                            )

                    # 📊 งบ (ถ้ามี) — ต้องเป็นของห้องนี้และต้องผูกหมวดเดียวกับบรรทัด
                    budget_ids = sorted({r["budget_id"] for r in normalized if r["budget_id"]})
                    budgets = {}
                    if budget_ids:
                        budget_rows = await conn.fetch(
                            """SELECT B.id, B.category_id, B.period_type, B.period_year,
                                      B.period_month, B.start_date, B.end_date
                               FROM finance_budgets B
                               WHERE B.id = ANY($1::int[]) AND B.room_id = $2 AND B.deleted_at IS NULL""",
                            budget_ids, target_room_id,
                        )
                        budgets = {r["id"]: r for r in budget_rows}
                        if len(budgets) != len(budget_ids):
                            raise RoomNotFoundError("มีงบประมาณที่ไม่พบในห้องเรียนนี้")
                    for row in normalized:
                        budget = budgets.get(row["budget_id"]) if row["budget_id"] else None
                        if budget and budget["category_id"] != row["category_id"]:
                            raise ValueError(
                                f"บรรทัดที่ {row['line_no']}: งบประมาณไม่ได้ผูกกับหมวดของบรรทัดนี้"
                            )

                    # 🏦 กระเป๋า — ล็อกทุกใบตาม id เรียงขึ้น **หลัง** room lock
                    wallet_ids = sorted(
                        {r["wallet_account_id"] for r in normalized}
                        | {int(req.default_wallet_account_id)}
                    )
                    wallet_rows = await conn.fetch(
                        """SELECT id, account_name, balance, is_custody
                           FROM finance_accounts
                           WHERE id = ANY($1::int[]) AND room_id = $2 AND deleted_at IS NULL
                           ORDER BY id
                           FOR UPDATE""",
                        wallet_ids, target_room_id,
                    )
                    wallets = {r["id"]: r for r in wallet_rows}
                    if len(wallets) != len(wallet_ids):
                        raise RoomNotFoundError("มีกระเป๋าเงินที่ไม่พบในห้องเรียนนี้")
                    for row in normalized:
                        wallet = wallets[row["wallet_account_id"]]
                        if wallet["is_custody"] and row["funding_source"] == "room_fund":
                            raise ValueError(
                                f"บรรทัดที่ {row['line_no']}: กระเป๋าเงินสดรอส่งมอบต้องใช้ "
                                "แหล่งเงิน 'เงินผ่านมือ' (pass_through)"
                            )

                    # 💰 เงินพอหรือไม่ — รวมต่อกระเป๋า แล้วเทียบ **ก่อน** เขียนแถวใด ๆ
                    sums: dict = {}
                    for row in normalized:
                        wid = row["wallet_account_id"]
                        sums[wid] = round(sums.get(wid, 0.0) + row["amount"], 2)
                    for wid, need in sums.items():
                        if float(wallets[wid]["balance"] or 0) < need:
                            raise ValueError(
                                f"เงินไม่พอในกระเป๋า {wallets[wid]['account_name']} "
                                f"(ต้องใช้ {need:.2f} บาท)"
                            )

                    # 👥 ผู้รับ/ผู้อนุมัติ (ถ้าส่ง person_id มาต้องอยู่ในทะเบียนของห้อง)
                    person_ids = [
                        pid for pid in (
                            req.payee_person_id, req.approved_by_person_id
                        ) if pid is not None
                    ]
                    people = {}
                    if person_ids:
                        person_rows = await conn.fetch(
                            """SELECT id, display_name FROM finance_people
                               WHERE id = ANY($1::bigint[]) AND room_id = $2
                                 AND deleted_at IS NULL""",
                            person_ids, target_room_id,
                        )
                        people = {r["id"]: r["display_name"] for r in person_rows}
                        if len(people) != len(set(person_ids)):
                            raise RoomNotFoundError(
                                "ไม่พบผู้รับเงิน/ผู้อนุมัติคนนี้ในทะเบียนของห้อง"
                            )

                    approved_name = (req.approved_by_name or "").strip() or (
                        people.get(req.approved_by_person_id) if req.approved_by_person_id else None
                    )
                    approver_fallback = not approved_name
                    if approver_fallback:
                        approved_name = user_name
                    signature_specs = [
                        {"role": "prepared", "person_id": None, "signer_name": user_name},
                        {
                            "role": "approved",
                            "person_id": req.approved_by_person_id,
                            "signer_name": approved_name,
                        },
                        {
                            "role": "receiver",
                            "person_id": req.payee_person_id,
                            "signer_name": payee_name,
                        },
                    ]

                    # ─────────────────────────────────────────────────
                    # 2) เขียน (voucher → ต่อบรรทัด: txn + ยอด + line + journal)
                    # ─────────────────────────────────────────────────
                    voucher = await conn.fetchrow(
                        """INSERT INTO finance_expense_vouchers
                               (room_id, default_wallet_account_id, payee_person_id, payee_name,
                                voucher_date, note, total_amount, idempotency_key)
                           VALUES ($1, $2, $3, $4, COALESCE($5::date, CURRENT_DATE), $6, $7, $8)
                           RETURNING id, created_at, voucher_date""",
                        target_room_id, req.default_wallet_account_id,
                        req.payee_person_id, payee_name, req.voucher_date,
                        (req.note or "").strip() or None, _dec(total), key,
                    )
                    voucher_id = voucher["id"]
                    first_txn_id = None
                    first_txn_created_at = None

                    snapshot_lines = []
                    for row in normalized:
                        wid = row["wallet_account_id"]
                        txn = await conn.fetchrow(
                            """INSERT INTO finance_transactions
                                   (room_id, account_id, category_id, amount, description,
                                    transaction_type, recorded_by, payee_name, approver_name,
                                    attachment_count, expense_voucher_id, funding_source)
                               VALUES ($1, $2, $3, $4, $5, 'expense', $6, $7, $8, $9, $10, $11)
                               RETURNING id, created_at""",
                            target_room_id, wid, row["category_id"], _dec(row["amount"]),
                            row["description"], user_name, payee_name, approved_name,
                            0, voucher_id, row["funding_source"],
                        )
                        txn_id = txn["id"]
                        # 🧾 P4.2 — เก็บ txn ต่อบรรทัดไว้ให้ CERT อ้าง (บรรทัด none แรก)
                        row["finance_transaction_id"] = txn_id
                        if first_txn_id is None:
                            first_txn_id = txn_id
                            first_txn_created_at = txn["created_at"]

                        await conn.execute(
                            "UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2",
                            _dec(row["amount"]), wid,
                        )

                        await conn.execute(
                            """INSERT INTO finance_expense_lines
                                   (voucher_id, line_no, description, amount, category_id,
                                    budget_id, wallet_account_id, finance_transaction_id,
                                    receipt_status, paper_bill_count, attachment_placeholder,
                                    funding_source)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                            voucher_id, row["line_no"], row["description"], _dec(row["amount"]),
                            row["category_id"], row["budget_id"], wid, txn_id,
                            row["receipt_status"], row["paper_bill_count"],
                            row["attachment_placeholder"], row["funding_source"],
                        )

                        # 🧾 journal **ต่อบรรทัด** — งบประมาณอ่านยอดใช้จากหมวดของ ledger
                        asset_ledger_id = await cls._resolve_asset_ledger(
                            conn, target_room_id, wid
                        )
                        category_ledger_id = await cls._resolve_category_ledger(
                            conn, target_room_id, row["category_id"], "expense"
                        )
                        await cls._insert_journal_entry(
                            conn, target_room_id,
                            reference_type="expense_voucher",
                            reference_id=str(txn_id),
                            description=row["description"],
                            recorded_by=user_name,
                            metadata={
                                "legacy_transaction_id": txn_id,
                                "expense_voucher_id": voucher_id,
                                "line_no": row["line_no"],
                            },
                            lines=[
                                {"ledger_id": category_ledger_id, "debit": row["amount"],
                                 "credit": 0,
                                 "line_description": f"ค่าใช้จ่าย: {row['description']}"},
                                {"ledger_id": asset_ledger_id, "debit": 0,
                                 "credit": row["amount"],
                                 "line_description": f"เงินออกจากบัญชี: {wallets[wid]['account_name']}"},
                            ],
                        )

                        budget = budgets.get(row["budget_id"]) if row["budget_id"] else None
                        snapshot_lines.append({
                            "line_no": row["line_no"],
                            "description": row["description"],
                            "amount": row["amount"],
                            "category_name": categories[row["category_id"]]["category_name"],
                            "budget_label": _budget_label(budget),
                            "wallet_name": wallets[wid]["account_name"],
                            "receipt_status": row["receipt_status"],
                            "paper_bill_count": row["paper_bill_count"],
                            "funding_source": row["funding_source"],
                        })

                    # ─────────────────────────────────────────────────
                    # 3) PV (เสมอ) + snapshot v2 + 3 ลายเซ็น
                    # ─────────────────────────────────────────────────
                    snapshot = json.dumps({
                        "layout_version": 2,
                        "payee_name": payee_name,
                        "payee_person_id": req.payee_person_id,
                        "voucher_date": voucher["voucher_date"].isoformat(),
                        "note": (req.note or "").strip(),
                        "total_amount": total,
                        "default_wallet": {
                            "id": int(req.default_wallet_account_id),
                            "name": wallets[int(req.default_wallet_account_id)]["account_name"],
                        },
                        "lines": snapshot_lines,
                        "signatures": [
                            {"role": s["role"], "signer_name": s["signer_name"]}
                            for s in signature_specs
                        ],
                        "total_paper_bill_count": sum(
                            r["paper_bill_count"] for r in normalized
                        ),
                    }, ensure_ascii=False)

                    document_meta = json.dumps({
                        "voucher_id": voucher_id,
                        "request_hash": request_hash,
                        "line_count": len(normalized),
                        "signatures": [
                            {"role": s["role"], "signer_name": s["signer_name"]}
                            for s in signature_specs
                        ],
                        "approver_fallback": approver_fallback,
                    }, ensure_ascii=False)

                    pv = await cls._issue_expense_pv_locked(
                        conn, target_room_id, voucher_id, total, payee_name,
                        user_id, user_name, (req.note or "").strip() or None,
                        first_txn_id, first_txn_created_at, snapshot, document_meta,
                    )
                    await conn.execute(
                        "UPDATE finance_expense_vouchers SET pv_receipt_id = $1 WHERE id = $2",
                        pv["id"], voucher_id,
                    )
                    await cls._insert_voucher_signatures(
                        conn, target_room_id, pv["id"], signature_specs
                    )

                    # 🧾 [FIN-V2 / P4.2] CERT อัตโนมัติ — เฉพาะประเภท `none`
                    #    🔴 ไม่ลง journal/txn/balance (CERT เป็นเอกสารรับรอง ไม่ใช่เงิน)
                    none_lines = [
                        r for r in normalized if r["receipt_status"] == "none"
                    ]
                    cert = await issue_certificate_locked(
                        conn,
                        room_id=target_room_id,
                        voucher_id=voucher_id,
                        pv_receipt_id=pv["id"],
                        pv_receipt_no=pv["receipt_no"],
                        payee_name=payee_name,
                        payee_person_id=req.payee_person_id,
                        user_id=user_id,
                        user_name=user_name,
                        event_at_db=_as_utc(first_txn_created_at),
                        issued_at_db=await conn.fetchval("SELECT CURRENT_TIMESTAMP"),
                        none_lines=none_lines,
                        snapshot=snapshot,
                        signatures=signature_specs,
                    )
                    cert_row = cert["receipt"]
                    cert_meta = _json_of(cert_row["document_meta"]) if cert_row else {}

                    result = {
                        "id": voucher_id,
                        "total_amount": total,
                        "line_count": len(normalized),
                        "pv_receipt_id": pv["id"],
                        "pv_receipt_no": pv["receipt_no"],
                        "cert_receipt_id": int(cert_row["id"]) if cert_row else None,
                        "cert_receipt_no": cert_row["receipt_no"] if cert_row else None,
                        "cert_amount": _money(cert_row["amount"]) if cert_row else None,
                        "cert_line_nos": cert_meta.get("source_line_nos") or [],
                        "created_at": voucher["created_at"],
                        "reused": False,
                    }
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_EXPENSE_VOUCHER",
                        entity_id=str(voucher_id), status="success",
                        new_values={
                            "total_amount": total,
                            "line_count": len(normalized),
                            "pv_receipt_id": pv["id"],
                            "cert_receipt_id": result["cert_receipt_id"],
                            "idempotency_key": key,
                        },
                        endpoint_or_command="FinanceService.create_expense_voucher",
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
                        user_id=user_id, entity_type="FINANCE_EXPENSE_VOUCHER",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_expense_voucher",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # อ่าน (list/detail) — สมาชิกห้องอ่านได้
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def list_expense_vouchers(
        cls,
        pool: asyncpg.Pool,
        *,
        client_source: str,
        actor_identifier: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        status: Optional[str] = None,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายการใบสำคัญจ่ายของห้อง — เรียงใหม่สุดก่อน"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if status is not None and status not in _ALLOWED_STATUS:
                    raise ValueError("สถานะต้องเป็น active หรือ voided")
                if from_date and to_date and from_date > to_date:
                    raise ValueError("ช่วงวันที่เริ่มต้องไม่เกินวันสิ้นสุด")

                rows = await conn.fetch(
                    """SELECT V.id, V.voucher_date, V.payee_name, V.total_amount,
                              V.status, V.created_at, V.pv_receipt_id,
                              R.receipt_no AS pv_receipt_no,
                              (SELECT COUNT(*) FROM finance_expense_lines L
                                WHERE L.voucher_id = V.id) AS line_count
                       FROM finance_expense_vouchers V
                       LEFT JOIN finance_receipts R ON R.id = V.pv_receipt_id
                       WHERE V.room_id = $1
                         AND ($2::date IS NULL OR V.voucher_date >= $2::date)
                         AND ($3::date IS NULL OR V.voucher_date <= $3::date)
                         AND ($4::text IS NULL OR V.status = $4)
                       ORDER BY V.voucher_date DESC, V.id DESC""",
                    target_room_id, from_date, to_date, status,
                )
                items = [
                    {
                        "id": r["id"],
                        "voucher_date": r["voucher_date"],
                        "payee_name": r["payee_name"],
                        "total_amount": _money(r["total_amount"]),
                        "line_count": int(r["line_count"] or 0),
                        "status": r["status"],
                        "pv_receipt_id": r["pv_receipt_id"],
                        "pv_receipt_no": r["pv_receipt_no"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
                total = round(sum(i["total_amount"] for i in items), 2)
                return {"items": items, "total": total}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_EXPENSE_VOUCHER",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.list_expense_vouchers",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_expense_voucher(
        cls,
        pool: asyncpg.Pool,
        *,
        voucher_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายละเอียดใบสำคัญจ่าย — voucher + lines + PV/CERT no + signatures"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                voucher = await conn.fetchrow(
                    """SELECT V.id, V.voucher_date, V.payee_person_id, V.payee_name,
                              V.default_wallet_account_id, V.note, V.total_amount, V.status,
                              V.pv_receipt_id, V.cert_receipt_id, V.created_at,
                              PR.receipt_no AS pv_receipt_no,
                              CR.receipt_no AS cert_receipt_no,
                              CR.amount AS cert_amount,
                              CR.document_meta AS cert_meta
                       FROM finance_expense_vouchers V
                       LEFT JOIN finance_receipts PR ON PR.id = V.pv_receipt_id
                       LEFT JOIN finance_receipts CR ON CR.id = V.cert_receipt_id
                       WHERE V.id = $1 AND V.room_id = $2""",
                    voucher_id, target_room_id,
                )
                if not voucher:
                    raise ExpenseVoucherNotFoundError("ไม่พบใบสำคัญจ่ายใบนี้ในห้องเรียน")

                line_rows = await conn.fetch(
                    """SELECT L.line_no, L.description, L.amount, L.category_id,
                              L.budget_id, L.wallet_account_id, L.finance_transaction_id,
                              L.receipt_status, L.paper_bill_count,
                              L.attachment_placeholder, L.funding_source,
                              C.category_name, A.account_name AS wallet_name,
                              B.period_type, B.period_year, B.period_month,
                              B.start_date, B.end_date
                       FROM finance_expense_lines L
                       LEFT JOIN finance_categories C ON C.id = L.category_id
                       LEFT JOIN finance_accounts A ON A.id = L.wallet_account_id
                       LEFT JOIN finance_budgets B ON B.id = L.budget_id
                       WHERE L.voucher_id = $1
                       ORDER BY L.line_no""",
                    voucher_id,
                )
                lines = [
                    {
                        "line_no": r["line_no"],
                        "description": r["description"],
                        "amount": _money(r["amount"]),
                        "category_id": r["category_id"],
                        "category_name": r["category_name"],
                        "budget_id": r["budget_id"],
                        "budget_label": _budget_label(r if r["budget_id"] else None),
                        "wallet_account_id": r["wallet_account_id"],
                        "wallet_name": r["wallet_name"],
                        "finance_transaction_id": r["finance_transaction_id"],
                        "receipt_status": r["receipt_status"],
                        "paper_bill_count": r["paper_bill_count"],
                        "attachment_placeholder": r["attachment_placeholder"],
                        "funding_source": r["funding_source"],
                    }
                    for r in line_rows
                ]

                signature_rows = await conn.fetch(
                    """SELECT role, person_id, signer_name
                       FROM finance_document_signatures
                       WHERE doc_type = $1 AND doc_id = $2
                       ORDER BY sort_order""",
                    _SIGN_DOC_TYPE, voucher["pv_receipt_id"] or 0,
                )
                return {
                    "id": voucher["id"],
                    "voucher_date": voucher["voucher_date"],
                    "payee_person_id": voucher["payee_person_id"],
                    "payee_name": voucher["payee_name"],
                    "default_wallet_account_id": voucher["default_wallet_account_id"],
                    "note": voucher["note"],
                    "total_amount": _money(voucher["total_amount"]),
                    "status": voucher["status"],
                    "pv_receipt_id": voucher["pv_receipt_id"],
                    "pv_receipt_no": voucher["pv_receipt_no"],
                    "cert_receipt_id": voucher["cert_receipt_id"],
                    "cert_receipt_no": voucher["cert_receipt_no"],
                    "cert_amount": (
                        _money(voucher["cert_amount"])
                        if voucher["cert_receipt_id"] else None
                    ),
                    "cert_line_nos": (
                        _json_of(voucher["cert_meta"]).get("source_line_nos") or []
                        if voucher["cert_receipt_id"] else []
                    ),
                    "created_at": voucher["created_at"],
                    "lines": lines,
                    "signatures": [
                        {
                            "role": s["role"],
                            "person_id": s["person_id"],
                            "signer_name": s["signer_name"],
                        }
                        for s in signature_rows
                    ],
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_EXPENSE_VOUCHER",
                        entity_id=str(voucher_id), status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.get_expense_voucher",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
