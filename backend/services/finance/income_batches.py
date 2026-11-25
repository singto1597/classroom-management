"""💰 [FIN-V2 / P4.4] ใบรับเงินหลายบรรทัด (income batch)

═══════════════════════════════════════════════════════════════════════════════
🎯 1 batch = 1 `finance_income_batches` + N `finance_income_lines` + 1 INC
═══════════════════════════════════════════════════════════════════════════════
รายรับอื่นที่ไม่ใช่บิลนักเรียน (เงินสนับสนุน/ขายของที่ระลึก/บริจาค) — ใบเดียว
หลายบรรทัด แต่ **กระเป๋าเดียวทั้งใบ** และ **ผู้จ่ายเป็นข้อความอิสระ**

🔴 กฎที่ห้ามพลาด
   1. **ทุกบรรทัด = 1 `finance_transactions` + 1 journal แยกกัน** — รายงาน/งบ
      อ่านยอดใช้ต่อหมวดจากรายการ ⇒ รวมก้อนเดียวแล้วยอดหมวดเพี้ยน
   2. กระเป๋าเดียวต่อ batch — `finance_income_lines` ไม่มีคอลัมน์กระเป๋า
      (ข้อกำหนดของ schema; อย่ารับ wallet ต่อบรรทัดแล้ว ignore)
   3. `payer_name` เป็น snapshot อิสระ — **ห้าม JOIN students/people เพื่อยืนยัน**
   4. `receiver_name` จาก `finance_people.display_name` เมื่อส่ง person id
      — **ห้ามเชื่อชื่อที่ client ส่ง** เพราะชื่อบนเอกสารต้องตรงทะเบียน
   5. กระเป๋า `is_custody` ⇒ `funding_source='pass_through'` (รายงานเงินห้องไม่พอง)
   6. INC anchor `legacy_transaction_id` = txn **บรรทัดแรก**
   7. INC มี issuer ของตัวเอง (`inc:{batch_id}`) — **ห้ามใช้ `_issue_income_doc`**
      ของระบบเดิม เพราะมันผูก idempotency กับ txn เดียวและจะคืนใบของบรรทัดแรก
   8. ไม่ลง REC/DEP; ไม่แตะงบ (งบอ่านจาก journal)
   9. แจ้งเตือน Discord **หลัง commit เท่านั้น** และครั้งเดียวต่อใบ
"""
import hashlib
import json
import time
from decimal import Decimal
from typing import Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission
from services.action_service import ActionService

from .base import _lock_room_money, service_logger
from .constants import (
    BUDDHIST_ERA_OFFSET, DOC_TYPE_INCOME, DOC_TYPE_PREFIXES,
    RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_MAX, RECEIPT_SEQ_OVERFLOW_MSG, THAI_TZ,
)
from .helpers import _as_utc

# 🧾 ชนิดเอกสารของ INC/ลายเซ็น — ตรงกับ `doc_type` ใน `finance_receipts`
_SIGN_DOC_TYPE = DOC_TYPE_INCOME
# 🛡️ เพดานบรรทัดต่อใบ (brief: 1..50)
_MAX_LINES = 50
# 🎭 สถานะใบที่กรองได้
_ALLOWED_STATUS = ("active", "voided")


class IncomeBatchNotFoundError(Exception):
    """ไม่พบใบรับเงินของห้อง ⇒ router แปลเป็น 404"""


class IncomeBatchIdempotencyConflict(ValueError):
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


class IncomeBatchesMixin:
    """รายรับอื่นหลายบรรทัด — เขียนผ่านล็อกห้องเดียวกับเส้นทางเงินทุกเส้น"""

    @classmethod
    def _income_request_hash(cls, req) -> str:
        """hash ของ payload ทั้งก้อน (canonical JSON) — ใช้เทียบ replay"""
        payload = json.dumps(
            req.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    async def _issue_income_batch_doc_locked(
        cls,
        conn: asyncpg.Connection,
        target_room_id: int,
        batch_id: int,
        total: float,
        payer_name: str,
        receiver_person_id: Optional[int],
        user_id: int,
        user_name: str,
        note: Optional[str],
        first_txn_id: int,
        first_txn_created_at,
        line_items: str,
        snapshot: str,
        document_meta: str,
    ) -> dict:
        """ออก INC ของ batch (caller ถือ `_lock_room_money` อยู่แล้ว)

        🔑 `idempotency_key = f"inc:{batch_id}"` ⇒ `idx_finance_receipts_idem`
           กัน INC ซ้ำต่อ batch และ **ไม่ชน** กับ `_issue_income_doc` ของระบบเดิม
           (ตัวนั้นใช้ `idx_finance_receipts_income_active` จาก `legacy_transaction_id`)
        🗓️ ปี พ.ศ. จาก **เวลาที่รับเงินจริง** (`finance_transactions.created_at`)
        🔁 SAVEPOINT ครอบ INSERT — ห้ามอ่าน `conn` หลัง `UniqueViolationError`
           ใน transaction ที่ aborted (`25P02`)
        """
        event_at = _as_utc(first_txn_created_at)
        issued_at = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        year_be = event_at.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        idem = f"inc:{batch_id}"

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
                            legacy_transaction_id, student_id, collection_id, amount,
                            paid_total_after, issued_to_name, issued_by, issued_by_name, note,
                            event_at, issued_at, line_items, voucher_snapshot, layout_version,
                            idempotency_key, document_meta, receiver_person_id)
                       VALUES ($1,$2,$3,$4,$5,NULL,$6,NULL,NULL,$7,$8,$9,$10,$11,$12,$13,$14,
                               $15::jsonb,$16,2,$17,$18::jsonb,$19)
                       RETURNING id, receipt_no""",
                    target_room_id, receipt_no, _SIGN_DOC_TYPE, year_be, seq,
                    first_txn_id, _dec(total), _dec(total),
                    payer_name, user_id, user_name, note,
                    event_at, issued_at, line_items, snapshot, idem, document_meta,
                    receiver_person_id,
                )
        except asyncpg.UniqueViolationError:
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

    # ──────────────────────────────────────────────────────────────────
    # สร้างใบรับเงิน
    # ──────────────────────────────────────────────────────────────────
    @classmethod
    async def create_income_batch(
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
        """สร้างใบรับเงินหลายบรรทัด — 1 คำขอ = 1 transaction = atomic ทั้งใบ"""
        start_time = time.time()
        target_room_id = room_id
        room_server_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🖊️ ชื่อผู้ออกเอกสาร — payload มาก่อน ถ้าไม่มีอ่านจากโปรไฟล์ผู้ใช้
                    user_name = (user_name or "").strip() or await cls._resolve_actor_name(
                        conn, user_id
                    )

                    # 💬 ผู้จ่ายเป็นข้อความอิสระ — ห้ามว่าง (พิมพ์บนเอกสารจริง)
                    payer_name = (req.payer_name or "").strip()
                    if not payer_name:
                        raise ValueError("ต้องระบุชื่อผู้จ่าย เพราะชื่อนี้พิมพ์ลงบนใบรับเงิน")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ — protocol เดียวกันทั้งระบบ
                    await _lock_room_money(conn, target_room_id)

                    key = (req.idempotency_key or "").strip()
                    if not 8 <= len(key) <= 128:
                        raise ValueError("idempotency_key ต้องยาว 8–128 ตัวอักษร")

                    request_hash = cls._income_request_hash(req)

                    # 🔁 idempotency ชั้นที่ 1 — อ่านก่อนเขียนใต้ล็อกห้อง
                    existing = await conn.fetchrow(
                        """SELECT id, total_amount, inc_receipt_id, created_at
                           FROM finance_income_batches
                           WHERE room_id = $1 AND idempotency_key = $2""",
                        target_room_id, key,
                    )
                    if existing:
                        line_count = await conn.fetchval(
                            "SELECT COUNT(*) FROM finance_income_lines WHERE batch_id = $1",
                            existing["id"],
                        )
                        inc = None
                        if existing["inc_receipt_id"]:
                            inc = await conn.fetchrow(
                                """SELECT id, receipt_no, document_meta
                                   FROM finance_receipts WHERE id = $1""",
                                existing["inc_receipt_id"],
                            )
                        stored_hash = _json_of(
                            inc["document_meta"] if inc else None
                        ).get("request_hash")
                        if inc and stored_hash == request_hash:
                            return {
                                "id": existing["id"],
                                "total_amount": _money(existing["total_amount"]),
                                "line_count": int(line_count or 0),
                                "inc_receipt_id": inc["id"],
                                "inc_receipt_no": inc["receipt_no"],
                                "created_at": existing["created_at"],
                                "reused": True,
                            }
                        # 🚫 INC หาย/คีย์ชนของอื่น ⇒ 409 ไม่สร้างซ้ำเงียบ ๆ
                        raise IncomeBatchIdempotencyConflict(
                            "idempotency key นี้ถูกใช้กับใบรับเงินใบอื่นแล้ว "
                            "(payload ไม่ตรงกับใบเดิม) — เปิดใบเดิมแทนการสร้างใหม่"
                        )

                    # ─────────────────────────────────────────────────
                    # 1) ตรวจทุกอย่างก่อนเขียนแถวแรก
                    # ─────────────────────────────────────────────────
                    lines = list(req.lines or [])
                    if not 1 <= len(lines) <= _MAX_LINES:
                        raise ValueError(f"ใบรับเงินต้องมี 1–{_MAX_LINES} บรรทัด")

                    normalized = []
                    total = 0.0
                    for idx, line in enumerate(lines, start=1):
                        description = (line.description or "").strip()
                        if not description:
                            raise ValueError(f"บรรทัดที่ {idx}: ต้องระบุรายละเอียด")
                        amount = round(float(line.amount), 2)
                        if amount <= 0:
                            raise ValueError(f"บรรทัดที่ {idx}: ยอดต้องมากกว่า 0.00 บาท")
                        normalized.append({
                            "line_no": idx,
                            "description": description,
                            "amount": amount,
                            "category_id": int(line.category_id),
                        })
                        total += amount
                    total = round(total, 2)
                    if req.total_amount is not None and round(float(req.total_amount), 2) != total:
                        raise ValueError("ยอดรวมไม่ตรงกับผลรวมบรรทัด")

                    # 🏷️ หมวด — ต้องมีจริง ในห้องนี้ และเป็นประเภท income เท่านั้น
                    category_ids = sorted({r["category_id"] for r in normalized})
                    category_rows = await conn.fetch(
                        """SELECT id, category_name, category_type
                           FROM finance_categories
                           WHERE id = ANY($1::int[]) AND room_id = $2
                             AND deleted_at IS NULL""",
                        category_ids, target_room_id,
                    )
                    categories = {r["id"]: r for r in category_rows}
                    if len(categories) != len(category_ids):
                        raise RoomNotFoundError(
                            "มีหมวดหมู่ที่ไม่พบในห้องเรียนนี้ — กรุณาโหลดรายการหมวดใหม่"
                        )
                    for row in normalized:
                        cat = categories[row["category_id"]]
                        if cat["category_type"] != "income":
                            raise ValueError(
                                f"บรรทัดที่ {row['line_no']}: หมวดนี้ไม่ใช่หมวดรายรับ"
                            )

                    # 👜 กระเป๋าเดียวทั้งใบ
                    wallet = await conn.fetchrow(
                        """SELECT id, account_name, is_custody, balance
                           FROM finance_accounts
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL
                           FOR UPDATE""",
                        int(req.wallet_account_id), target_room_id,
                    )
                    if not wallet:
                        raise RoomNotFoundError("ไม่พบกระเป๋าเงินนี้ในห้องเรียน")
                    funding_source = "pass_through" if wallet["is_custody"] else "room_fund"

                    # 👤 ผู้รับเงิน — person มาก่อน (ชื่อจากทะเบียนเสมอ)
                    receiver_person_id = req.receiver_person_id
                    if receiver_person_id:
                        person = await conn.fetchrow(
                            """SELECT id, display_name, roles, is_active
                               FROM finance_people
                               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            int(receiver_person_id), target_room_id,
                        )
                        if not person:
                            raise RoomNotFoundError(
                                "ไม่พบผู้รับเงินคนนี้ในทะเบียนของห้อง"
                            )
                        if not person["is_active"]:
                            raise ValueError("ผู้รับเงินคนนี้ถูกปิดใช้งานในทะเบียนของห้อง")
                        if "receive" not in (person["roles"] or []):
                            raise ValueError(
                                "ผู้รับเงินคนนี้ไม่มีบทบาท 'รับเงิน' ในทะเบียนของห้อง"
                            )
                        receiver_name = person["display_name"]
                    else:
                        receiver_person_id = None
                        receiver_name = (req.receiver_name or "").strip()
                        if not receiver_name:
                            raise ValueError(
                                "ต้องระบุผู้รับเงิน (เลือกจากทะเบียนหรือพิมพ์ชื่อ)"
                            )

                    # 💳 ช่องทาง (ถ้ามี) — snapshot ไว้บนเอกสาร, ห้ามชนกระเป๋า
                    channel_snapshot = {}
                    if req.channel_id:
                        channel = await conn.fetchrow(
                            """SELECT id, channel_type, label, wallet_account_id,
                                      account_name, bank_name,
                                      account_number_masked, promptpay_id_masked,
                                      is_active
                               FROM finance_payment_channels
                               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            int(req.channel_id), target_room_id,
                        )
                        if not channel:
                            raise RoomNotFoundError("ไม่พบช่องทางชำระเงินนี้ในห้องเรียน")
                        if not channel["is_active"]:
                            raise ValueError("ช่องทางชำระเงินนี้ถูกปิดใช้งาน")
                        if (
                            channel["wallet_account_id"] is not None
                            and int(channel["wallet_account_id"]) != int(wallet["id"])
                        ):
                            raise ValueError(
                                "กระเป๋าที่เลือกไม่ตรงกับกระเป๋าของช่องทางชำระเงินนี้"
                            )
                        channel_snapshot = {
                            "channel_type": channel["channel_type"],
                            "label": channel["label"],
                            "account_name": channel["account_name"],
                            "bank_name": channel["bank_name"],
                            "account_number_masked": channel["account_number_masked"],
                            "promptpay_id_masked": channel["promptpay_id_masked"],
                        }

                    # ─────────────────────────────────────────────────
                    # 2) เขียน (batch → ต่อบรรทัด: txn + ยอด + line + journal)
                    # ─────────────────────────────────────────────────
                    batch = await conn.fetchrow(
                        """INSERT INTO finance_income_batches
                               (room_id, payer_name, receiver_person_id, receiver_name,
                                wallet_account_id, channel_id, channel_snapshot,
                                income_date, note, total_amount, idempotency_key)
                           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb,
                                   COALESCE($8::date, CURRENT_DATE), $9, $10, $11)
                           RETURNING id, created_at, income_date""",
                        target_room_id, payer_name, receiver_person_id, receiver_name,
                        int(wallet["id"]), int(req.channel_id) if req.channel_id else None,
                        json.dumps(channel_snapshot, ensure_ascii=False),
                        req.income_date, (req.note or "").strip() or None,
                        _dec(total), key,
                    )
                    batch_id = batch["id"]
                    first_txn_id = None
                    first_txn_created_at = None

                    snapshot_lines = []
                    for row in normalized:
                        txn = await conn.fetchrow(
                            """INSERT INTO finance_transactions
                                   (room_id, account_id, category_id, amount, description,
                                    transaction_type, recorded_by, payee_name,
                                    attachment_count, income_batch_id, funding_source)
                               VALUES ($1, $2, $3, $4, $5, 'income', $6, $7, 0, $8, $9)
                               RETURNING id, created_at""",
                            target_room_id, int(wallet["id"]), row["category_id"],
                            _dec(row["amount"]), row["description"], user_name,
                            payer_name, batch_id, funding_source,
                        )
                        txn_id = txn["id"]
                        row["finance_transaction_id"] = txn_id
                        if first_txn_id is None:
                            first_txn_id = txn_id
                            first_txn_created_at = txn["created_at"]

                        await conn.execute(
                            "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
                            _dec(row["amount"]), int(wallet["id"]),
                        )

                        await conn.execute(
                            """INSERT INTO finance_income_lines
                                   (batch_id, line_no, description, amount, category_id,
                                    finance_transaction_id, meta)
                               VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)""",
                            batch_id, row["line_no"], row["description"],
                            _dec(row["amount"]), row["category_id"], txn_id,
                            json.dumps({}, ensure_ascii=False),
                        )

                        # 🧾 journal **ต่อบรรทัด** — งบ/รายงานแยกหมวดอ่านจากที่นี่
                        asset_ledger_id = await cls._resolve_asset_ledger(
                            conn, target_room_id, int(wallet["id"])
                        )
                        category_ledger_id = await cls._resolve_category_ledger(
                            conn, target_room_id, row["category_id"], "income"
                        )
                        await cls._insert_journal_entry(
                            conn, target_room_id,
                            reference_type="income_batch",
                            reference_id=str(txn_id),
                            description=row["description"],
                            recorded_by=user_name,
                            metadata={
                                "legacy_transaction_id": txn_id,
                                "income_batch_id": batch_id,
                                "line_no": row["line_no"],
                            },
                            lines=[
                                {"ledger_id": asset_ledger_id, "debit": row["amount"],
                                 "credit": 0,
                                 "line_description": f"รับเงินเข้าบัญชี: {wallet['account_name']}"},
                                {"ledger_id": category_ledger_id, "debit": 0,
                                 "credit": row["amount"],
                                 "line_description": f"รายได้: {row['description']}"},
                            ],
                        )

                        snapshot_lines.append({
                            "line_no": row["line_no"],
                            "description": row["description"],
                            "amount": row["amount"],
                            "category_id": row["category_id"],
                            "category_name": categories[row["category_id"]]["category_name"],
                        })

                    # ─────────────────────────────────────────────────
                    # 3) INC (เสมอ) + snapshot v2 + 2 ลายเซ็น
                    # ─────────────────────────────────────────────────
                    signature_specs = [
                        {"role": "prepared", "person_id": None,
                         "signer_name": user_name},
                        {"role": "receiver", "person_id": receiver_person_id,
                         "signer_name": receiver_name},
                    ]
                    snapshot = json.dumps({
                        "layout_version": 2,
                        "payer_name": payer_name,
                        "receiver_name": receiver_name,
                        "receiver_person_id": receiver_person_id,
                        "income_date": batch["income_date"].isoformat(),
                        "note": (req.note or "").strip(),
                        "total_amount": total,
                        "wallet": {
                            "id": int(wallet["id"]),
                            "name": wallet["account_name"],
                            "is_custody": bool(wallet["is_custody"]),
                        },
                        "funding_source": funding_source,
                        "channel": channel_snapshot,
                        "lines": snapshot_lines,
                        "signatures": signature_specs,
                    }, ensure_ascii=False)

                    document_meta = json.dumps({
                        "batch_id": batch_id,
                        "request_hash": request_hash,
                        "line_count": len(normalized),
                        "receiver_name": receiver_name,
                        "channel": channel_snapshot,
                        "signatures": signature_specs,
                    }, ensure_ascii=False)

                    # 📋 `line_items` = บรรทัดทั้งหมดบนเอกสาร (P4.6 ใช้พิมพ์ตาราง)
                    line_items = json.dumps([
                        {
                            "line_no": s["line_no"],
                            "title": s["description"],
                            "amount_applied": s["amount"],
                            "category_id": s["category_id"],
                        }
                        for s in snapshot_lines
                    ], ensure_ascii=False)

                    inc = await cls._issue_income_batch_doc_locked(
                        conn, target_room_id, batch_id, total, payer_name,
                        receiver_person_id, user_id, user_name,
                        (req.note or "").strip() or None,
                        first_txn_id, first_txn_created_at,
                        line_items, snapshot, document_meta,
                    )
                    await conn.execute(
                        "UPDATE finance_income_batches SET inc_receipt_id = $1 WHERE id = $2",
                        inc["id"], batch_id,
                    )

                    # ✍️ 2 ลายเซ็นตาม doc-matrix §2.8 (prepared / receiver)
                    for sort_order, sig in enumerate(signature_specs):
                        await conn.execute(
                            """INSERT INTO finance_document_signatures
                                   (room_id, doc_type, doc_id, role, person_id,
                                    signer_name, signed_at, sort_order)
                               VALUES ($1, $2, $3, $4, $5, $6, NULL, $7)""",
                            target_room_id, _SIGN_DOC_TYPE, inc["id"], sig["role"],
                            sig["person_id"], sig["signer_name"], sort_order,
                        )

                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_INCOME_BATCH",
                        entity_id=str(batch_id), status="success",
                        new_values={
                            "total_amount": total,
                            "line_count": len(normalized),
                            "inc_receipt_id": inc["id"],
                            "idempotency_key": key,
                        },
                        endpoint_or_command="FinanceService.create_income_batch",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)

            # 📢 แจ้งเตือน **หลัง commit** ครั้งเดียวต่อใบ
            if room_server_id:
                await ActionService.notify_new_finance(
                    server_id=room_server_id,
                    txn_type="income",
                    amount=total,
                    description=(req.note or "").strip() or "รายรับอื่น",
                    user_name=user_name,
                    receipt_nos=[inc["receipt_no"]],
                )
            return {
                "id": batch_id,
                "total_amount": total,
                "line_count": len(normalized),
                "inc_receipt_id": inc["id"],
                "inc_receipt_no": inc["receipt_no"],
                "created_at": batch["created_at"],
                "reused": False,
            }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_INCOME_BATCH",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_income_batch",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ──────────────────────────────────────────────────────────────────
    # อ่าน
    # ──────────────────────────────────────────────────────────────────
    @classmethod
    async def list_income_batches(
        cls,
        pool: asyncpg.Pool,
        *,
        client_source: str,
        actor_identifier: str,
        from_date=None,
        to_date=None,
        status: Optional[str] = None,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายการใบรับเงินของห้อง (สมาชิกอ่านได้) — เรียงใหม่สุดก่อน"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if status is not None and status not in _ALLOWED_STATUS:
                    raise ValueError("status ต้องเป็น active หรือ voided")
                if from_date and to_date and from_date > to_date:
                    raise ValueError("วันที่เริ่มต้องไม่เกินวันที่สิ้นสุด")

                rows = await conn.fetch(
                    """SELECT B.id, B.income_date, B.payer_name, B.receiver_name,
                              B.total_amount, B.status, B.inc_receipt_id, B.created_at,
                              R.receipt_no AS inc_receipt_no,
                              (SELECT COUNT(*) FROM finance_income_lines L
                                WHERE L.batch_id = B.id) AS line_count
                       FROM finance_income_batches B
                       LEFT JOIN finance_receipts R ON R.id = B.inc_receipt_id
                       WHERE B.room_id = $1
                         AND ($2::date IS NULL OR B.income_date >= $2)
                         AND ($3::date IS NULL OR B.income_date <= $3)
                         AND ($4::text IS NULL OR B.status = $4)
                       ORDER BY B.income_date DESC, B.id DESC""",
                    target_room_id, from_date, to_date, status,
                )
                items = [
                    {
                        "id": r["id"],
                        "income_date": r["income_date"],
                        "payer_name": r["payer_name"],
                        "receiver_name": r["receiver_name"],
                        "total_amount": _money(r["total_amount"]),
                        "line_count": int(r["line_count"] or 0),
                        "status": r["status"],
                        "inc_receipt_id": r["inc_receipt_id"],
                        "inc_receipt_no": r["inc_receipt_no"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
                return {
                    "items": items,
                    "total": round(sum(i["total_amount"] for i in items), 2),
                }
        except Exception as e:
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_INCOME_BATCH",
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.list_income_batches",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_income_batch(
        cls,
        pool: asyncpg.Pool,
        *,
        batch_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """รายละเอียดใบรับเงิน — batch + lines + INC no + signatures"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                batch = await conn.fetchrow(
                    """SELECT B.id, B.income_date, B.payer_name, B.receiver_person_id,
                              B.receiver_name, B.wallet_account_id, B.channel_id,
                              B.channel_snapshot, B.note, B.total_amount, B.status,
                              B.inc_receipt_id, B.created_at,
                              R.receipt_no AS inc_receipt_no
                       FROM finance_income_batches B
                       LEFT JOIN finance_receipts R ON R.id = B.inc_receipt_id
                       WHERE B.id = $1 AND B.room_id = $2""",
                    batch_id, target_room_id,
                )
                if not batch:
                    raise IncomeBatchNotFoundError("ไม่พบใบรับเงินใบนี้ในห้องเรียน")

                line_rows = await conn.fetch(
                    """SELECT L.line_no, L.description, L.amount, L.category_id,
                              L.finance_transaction_id, C.category_name
                       FROM finance_income_lines L
                       LEFT JOIN finance_categories C ON C.id = L.category_id
                       WHERE L.batch_id = $1
                       ORDER BY L.line_no""",
                    batch_id,
                )
                signature_rows = await conn.fetch(
                    """SELECT role, person_id, signer_name
                       FROM finance_document_signatures
                       WHERE doc_type = $1 AND doc_id = $2
                       ORDER BY sort_order""",
                    _SIGN_DOC_TYPE, batch["inc_receipt_id"] or 0,
                )
                return {
                    "id": batch["id"],
                    "income_date": batch["income_date"],
                    "payer_name": batch["payer_name"],
                    "receiver_person_id": batch["receiver_person_id"],
                    "receiver_name": batch["receiver_name"],
                    "wallet_account_id": batch["wallet_account_id"],
                    "channel_id": batch["channel_id"],
                    # 🎭 คืนแค่ snapshot ที่ shape แล้ว ไม่ใช่ jsonb ดิบทั้งก้อน
                    "channel": _json_of(batch["channel_snapshot"]),
                    "note": batch["note"],
                    "total_amount": _money(batch["total_amount"]),
                    "status": batch["status"],
                    "inc_receipt_id": batch["inc_receipt_id"],
                    "inc_receipt_no": batch["inc_receipt_no"],
                    "created_at": batch["created_at"],
                    "lines": [
                        {
                            "line_no": r["line_no"],
                            "description": r["description"],
                            "amount": _money(r["amount"]),
                            "category_id": r["category_id"],
                            "category_name": r["category_name"],
                            "finance_transaction_id": r["finance_transaction_id"],
                        }
                        for r in line_rows
                    ],
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
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id, entity_type="FINANCE_INCOME_BATCH",
                        entity_id=str(batch_id), status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.get_income_batch",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception:
                pass
            raise e
