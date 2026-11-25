"""🧾 [FIN-V2 / P2.1] รายการรับเงิน (payment event) — 1 ครั้งรับเงิน = 1 event

═══════════════════════════════════════════════════════════════════════════════
หัวใจของ package นี้
═══════════════════════════════════════════════════════════════════════════════
ระบบเดิม: 1 บิล = 1 รายการรับเงิน = 1 ใบเสร็จ
ระบบใหม่: 1 ครั้งรับเงิน (ของนักเรียน 1 คน) = 1 payment event ที่ปิดได้หลายบิล
          → ออก **REC 1 ใบ (หลาย line_items)** + DEP 1 ใบเมื่อมีเงินเกินเป็นเครดิต

🔴 กฎเหล็ก: **ห้ามเขียน Dr/Cr รับเงินเองในไฟล์นี้**
   - เงินสดต่อบิล → `_confirm_single_payment` (collections.py) เท่านั้น
   - เครดิตหักปิดบิล → `_apply_plan_locked` (credits.py) เท่านั้น
   ⇒ journal/ยอดกระเป๋า/สถานะค่าปรับ ยังมาจากที่เดียวกับเส้นทางเดิม ไม่มีทางเดินคู่

สมการที่ DB บังคับ (`chk_event_balanced`): ยอดรับเงินบวกเครดิตที่ใช้
   = ยอดที่ลงบิลบวกเครดิตที่เพิ่ม ⇒ event ที่ยอดไม่สมดุลบันทึกไม่ได้เลย แม้ service จะพลาด

═══════════════════════════════════════════════════════════════════════════════
ลำดับล็อก (ห้ามสลับ)
═══════════════════════════════════════════════════════════════════════════════
RBAC → `_lock_room_money` (advisory ต่อห้อง) → อ่าน/เขียนทุกอย่าง
→ `_lock_payments_in_order` (เรียง id) → `_confirm_single_payment` ต่อบิล
→ `_apply_plan_locked` รอบเดียว → เขียน lines/เอกสาร
และ **publish หลัง commit เท่านั้น** (ไม่ notify ตอน replay)

⚠️ idempotency = `(room_id, idempotency_key)` — ชนแล้วคืน event เดิม (200) ไม่สร้างซ้ำ
"""
import json
import time
from datetime import date
from typing import List, Optional

import asyncpg

from core.exceptions import PaymentNotFoundError, StudentNotFoundError
from core.rbac import require_member, require_permission

from services.action_service import ActionService

from .allocation import (
    ChannelNotFoundError, assert_plan_equation,
    build_allocation_plan, from_satang, to_satang,
)
from .base import _lock_payments_in_order, _lock_room_money, service_logger
from .baht_text import baht_text
from .constants import (
    CREDIT_ENTRY_TOPUP, DOC_TYPE_DEPOSIT, DOC_TYPE_RECEIPT,
    DOC_STATUS_ACTIVE, REFERENCE_TYPE_CREDIT_TOPUP,
)
from .helpers import _as_utc


class PaymentEventAccountNotFoundError(Exception):
    """กระเป๋าเงินที่ระบุไม่มี/ไม่ใช่ของห้อง — router แปลเป็น 404"""


class PaymentEventsMixin:
    # ================================================================ helpers
    @staticmethod
    def _normalize_event_key(req) -> str:
        """🔑 คีย์กันส่งซ้ำของ event — ตัดช่องว่างและจำกัด 64 ตัว (index เป็น TEXT)"""
        key = (getattr(req, "idempotency_key", None) or "").strip()
        if not key:
            raise ValueError(
                "ไม่พบรหัสกันบันทึกซ้ำ (idempotency_key) — "
                "กรุณารีเฟรชหน้าแล้วทำรายการใหม่"
            )
        return key[:64]

    @classmethod
    async def _load_event_lines(
        cls, conn: asyncpg.Connection, event_id: int,
    ) -> List[dict]:
        return await conn.fetch(
            """SELECT id, line_kind, student_payment_id, finance_transaction_id,
                      credit_entry_id, amount, bill_amount_before, bill_amount_after, meta
               FROM finance_payment_event_lines
               WHERE event_id = $1
               ORDER BY id""",
            event_id,
        )

    @classmethod
    async def _load_event_documents(
        cls, conn: asyncpg.Connection, event_id: int,
    ) -> List[dict]:
        rows = await conn.fetch(
            """SELECT id, doc_type, receipt_no, amount, layout_version,
                      event_at, issued_at, status
               FROM finance_receipts
               WHERE payment_event_id = $1 AND deleted_at IS NULL
                 AND status = $2
               ORDER BY id""",
            event_id, DOC_STATUS_ACTIVE,
        )
        return [cls._shape_event_document(r) for r in rows]

    @staticmethod
    def _parse_meta(raw) -> dict:
        """jsonb จาก asyncpg กลับมาเป็น `str` — ต้อง json.loads (เหมือน `_parse_line_items`)"""
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return dict(raw) if isinstance(raw, dict) else {}

    @classmethod
    def _shape_event_result(
        cls, row, lines: List[dict], documents: List[dict], *, reused: bool,
        warnings: Optional[List[str]] = None,
    ) -> dict:
        """ประกอบ response จากแถว event + lines + เอกสาร (ใช้ทั้ง create และ replay)"""
        receipt_no = next(
            (d["receipt_no"] for d in documents if d["doc_type"] == DOC_TYPE_RECEIPT),
            None,
        )
        deposit_no = next(
            (d["receipt_no"] for d in documents if d["doc_type"] == DOC_TYPE_DEPOSIT),
            None,
        )
        allocations = []
        for ln in lines:
            if ln["line_kind"] not in ("bill", "credit_apply"):
                continue
            meta = cls._parse_meta(ln["meta"])
            allocations.append({
                "student_payment_id": ln["student_payment_id"],
                "collection_id": meta.get("collection_id"),
                "title": meta.get("title") or "",
                "source": meta.get("source") or (
                    "cash" if ln["line_kind"] == "bill" else "credit"
                ),
                "amount": cls._money_str(to_satang(ln["amount"])),
                "bill_before": cls._money_str(to_satang(ln["bill_amount_before"])),
                "bill_after": cls._money_str(to_satang(ln["bill_amount_after"])),
            })
        return {
            "event_id": row["id"],
            "receipt_no": receipt_no,
            "deposit_no": deposit_no,
            "amount_received": cls._money_str(to_satang(row["amount_received"])),
            "credit_used": cls._money_str(to_satang(row["credit_used"])),
            "credit_added": cls._money_str(to_satang(row["credit_added"])),
            "total_applied": cls._money_str(to_satang(row["total_applied"])),
            "allocations": allocations,
            "documents": documents,
            "reused": reused,
            "warnings": list(warnings or []),
        }

    @classmethod
    async def _build_event_result(
        cls, conn: asyncpg.Connection, row, *, reused: bool,
        warnings: Optional[List[str]] = None,
    ) -> dict:
        lines = await cls._load_event_lines(conn, row["id"])
        documents = await cls._load_event_documents(conn, row["id"])
        return cls._shape_event_result(
            row, lines, documents, reused=reused, warnings=warnings
        )

    @staticmethod
    def _shape_event_detail(row, result: dict, lines: List[dict]) -> dict:
        """รายละเอียดสำหรับ GET /payment-events/{id} — ไม่คืน channel_snapshot ดิบ"""
        snapshot = row["channel_snapshot"]
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except (TypeError, ValueError):
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        detail = dict(result)
        detail.update({
            "student_id": row["student_id"],
            "payer_name": row["payer_name"],
            "receiver_name": row["receiver_name"],
            "channel": snapshot,
            "note": row["note"],
            "status": row["status"],
            "event_at": row["event_at"],
            "created_at": row["created_at"],
            "lines": [
                {
                    "id": ln["id"],
                    "line_kind": ln["line_kind"],
                    "student_payment_id": ln["student_payment_id"],
                    "finance_transaction_id": ln["finance_transaction_id"],
                    "credit_entry_id": ln["credit_entry_id"],
                    "amount": f"{float(ln['amount']):.2f}",
                    "bill_amount_before": (
                        f"{float(ln['bill_amount_before']):.2f}"
                        if ln["bill_amount_before"] is not None else None
                    ),
                    "bill_amount_after": (
                        f"{float(ln['bill_amount_after']):.2f}"
                        if ln["bill_amount_after"] is not None else None
                    ),
                    "meta": PaymentEventsMixin._parse_meta(ln["meta"]),
                }
                for ln in lines
            ],
        })
        return detail

    # ================================================================ top-up
    @classmethod
    async def _create_excess_credit_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, student_id: int,
        event_id: int, amount_stang: int, account_id: int, payer_name: str,
        user_name: str, slip_image_url: Optional[str], note: Optional[str],
        idempotency_key: str,
    ) -> dict:
        """เก็บ **เงินเกินของ event** เป็นเครดิต — caller ถือ transaction + lock แล้ว

        ลอกลำดับบัญชีจาก `_top_up_credit_locked` ทุกบรรทัด แต่เพิ่ม `payment_event_id`
        ⇒ ตามรอยได้ว่าเครดิตนี้เกิดจาก event ไหน และ DEP ที่ out อยู่นั้นเป็นของ event นี้

        🔴 `category_id = NULL` โดยเจตนา: ถ้าใส่หมวดรายได้ งบประมาณจะนับเงินรับล่วงหน้า
           เป็นรายรับทันที (รายละเอียดเต็มใน `_top_up_credit_locked`)

        คืน `{trans_id, trans_event_at, journal_entry_id, credit_entry_id,
              balance_before, balance_after}`
        """
        amount = from_satang(amount_stang)
        description = f"รับเงินเกินเป็นเครดิต: {payer_name}"

        row = await conn.fetchrow(
            """INSERT INTO finance_transactions
                   (room_id, account_id, category_id, amount, description,
                    transaction_type, slip_image_url, recorded_by, student_payment_id,
                    payment_event_id)
               VALUES ($1, $2, NULL, $3, $4, 'income', $5, $6, NULL, $7)
               RETURNING id, created_at""",
            target_room_id, account_id, amount, description,
            slip_image_url, user_name, event_id,
        )
        trans_id = row["id"]
        trans_event_at = _as_utc(row["created_at"])

        await conn.execute(
            "UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2",
            amount, account_id,
        )

        # 📚 Dr สินทรัพย์ / Cr หนี้สิน 2099 — **ไม่ใช่รายได้** (เหมือน top-up เดิมเป๊ะ)
        asset_ledger_id = await cls._resolve_asset_ledger(
            conn, target_room_id, account_id
        )
        advance_ledger_id = await cls._resolve_advance_ledger(
            conn, room_id=target_room_id
        )
        journal_entry_id = await cls._insert_journal_entry(
            conn, target_room_id,
            reference_type=REFERENCE_TYPE_CREDIT_TOPUP,
            reference_id=str(student_id),
            description=description,
            slip_image_url=slip_image_url,
            recorded_by=user_name,
            metadata={
                "legacy_transaction_id": trans_id,
                "student_id": student_id,
                "payment_event_id": event_id,
                "accrual": "payment_event_topup",
            },
            lines=[
                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"รับเงินเกินจาก {payer_name}"},
                {"ledger_id": advance_ledger_id, "debit": 0, "credit": amount,
                 "line_description": "เงินรับล่วงหน้า (ยังไม่ใช่รายได้ — รอหักปิดบิล)"},
            ],
        )

        balance_before = await cls._load_credit_balance(
            conn, room_id=target_room_id, student_id=student_id
        )
        balance_after = round(balance_before + amount, 2)
        credit_entry_id = await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after,
                    finance_transaction_id, journal_entry_id, note, recorded_by,
                    idempotency_key, payment_event_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               RETURNING id""",
            target_room_id, student_id, CREDIT_ENTRY_TOPUP, amount, balance_after,
            trans_id, journal_entry_id, note, user_name, idempotency_key, event_id,
        )

        return {
            "trans_id": trans_id,
            "trans_event_at": trans_event_at,
            "journal_entry_id": journal_entry_id,
            "credit_entry_id": credit_entry_id,
            "balance_before": balance_before,
            "balance_after": balance_after,
        }

    # ================================================================ create
    @classmethod
    async def create_payment_event(
        cls, pool: asyncpg.Pool, *, server_id: Optional[int] = None,
        room_id: Optional[int] = None, req, user_id: int,
        client_source: str, actor_identifier: str,
    ) -> dict:
        """รับเงิน 1 ครั้ง → 1 event (+REC/DEP) — atomic ทั้งก้อน

        `server_id`/`room_id` มาจาก `target` ของ router; service เป็นผู้ resolve
        เป็น room_id จริง (ห้าม router แปลงเอง — ดู `routers/_common.py`)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                try:
                    async with conn.transaction():
                        result, notify_payload, room_server_id = await cls._create_locked(
                            conn, target_room_id=target_room_id, req=req,
                            user_id=user_id, client_source=client_source,
                            actor_identifier=actor_identifier,
                            start_time=start_time,
                        )
                except asyncpg.UniqueViolationError:
                    # 🔁 แพ้การแข่งขันของ idempotency key เดียวกัน (หรือกดซ้ำพร้อมกัน)
                    #    ⚠️ ต้องดัก **นอก** transaction: ในนี้ transaction aborted แล้ว
                    #    ⇒ query ต่อจะได้ 25P02 ถ้าไม่มี savepoint
                    existing = await conn.fetchrow(
                        """SELECT * FROM finance_payment_events
                           WHERE room_id = $1 AND idempotency_key = $2
                           ORDER BY id LIMIT 1""",
                        target_room_id, cls._normalize_event_key(req),
                    )
                    if existing is None:
                        raise
                    if existing["status"] != "active":
                        raise ValueError(
                            "รายการรับเงินนี้ถูกยกเลิกไปแล้ว — "
                            "กรุณาทำรายการใหม่ด้วยรหัสใหม่"
                        )
                    return await cls._build_event_result(
                        conn, existing, reused=True
                    )

            # 📢 แจ้งเตือน **หลัง commit เท่านั้น** และครั้งเดียว — replay ไม่ notify
            if notify_payload and room_server_id:
                await ActionService.notify_payments_confirmed(
                    server_id=room_server_id,
                    payer_name=notify_payload["payer_name"],
                    items=notify_payload["items"],
                    total_amount=notify_payload["total_amount"],
                    user_name=notify_payload["user_name"],
                    receipt_nos=notify_payload.get("receipt_nos"),
                )
            return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="PAYMENT_EVENT", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.create_payment_event",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    @classmethod
    async def _create_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, req, user_id: int,
        client_source: str, actor_identifier: str, start_time: float,
    ):
        """เนื้อใน transaction ของ `create_payment_event` (แยกเพื่ออ่านง่าย)"""
        # 2) RBAC
        await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

        # 3) 🔒 ล็อกห้องก่อนแตะข้อมูลใด ๆ — protocol เดียวกันทั้งระบบ
        await _lock_room_money(conn, target_room_id)

        key = cls._normalize_event_key(req)

        # 4) 🔁 idempotency อ่านก่อนเขียน — เจอแล้วคืนผลเดิม ไม่กินเลข/ไม่ notify
        existing = await conn.fetchrow(
            """SELECT * FROM finance_payment_events
               WHERE room_id = $1 AND idempotency_key = $2 AND status = 'active'""",
            target_room_id, key,
        )
        if existing:
            result = await cls._build_event_result(conn, existing, reused=True)
            return result, None, None

        # 5) ตรวจทุกอย่างให้ครบ **ก่อน** จองเลข/เขียนเงิน
        student = await conn.fetchrow(
            """SELECT S.id, S.student_no,
                      U.first_name, U.nickname, U.first_name_en
               FROM students S
               LEFT JOIN v_student_profiles U ON U.student_id = S.id
               WHERE S.id = $1 AND S.room_id = $2 AND S.deleted_at IS NULL""",
            req.student_id, target_room_id,
        )
        if not student:
            raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้องเรียน")

        account_ok = await conn.fetchval(
            """SELECT id FROM finance_accounts
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            req.wallet_account_id, target_room_id,
        )
        if not account_ok:
            raise PaymentEventAccountNotFoundError(
                "ไม่พบกระเป๋าเงินนี้ในห้อง (หรือถูกลบไปแล้ว)"
            )

        channel_snapshot: dict = {}
        if req.channel_id is not None:
            channel = await conn.fetchrow(
                """SELECT id, channel_type, label, bank_name, account_number_masked
                   FROM finance_payment_channels
                   WHERE id = $1 AND room_id = $2
                     AND is_active AND deleted_at IS NULL""",
                req.channel_id, target_room_id,
            )
            if not channel:
                raise ChannelNotFoundError(
                    "ไม่พบช่องทางชำระเงินนี้ในห้อง (หรือถูกปิดใช้งานแล้ว)"
                )
            channel_snapshot = {
                "channel_id": channel["id"],
                "name": channel["label"],
                "channel_type": channel["channel_type"],
                "bank_name": channel["bank_name"],
                # 🔒 เก็บเฉพาะเลขที่ปิดบังแล้ว — ห้าม snapshot เลขบัญชีเต็ม
                "account_no_masked": channel["account_number_masked"],
            }

        # 👤 ผู้รับเงิน: person ชนะชื่อที่ client ส่ง; ไม่มี person → ใช้ชื่อที่ส่งมา
        #    และถ้าห้องตั้ง require_receiver (ค่าเริ่มต้น = true) ต้องมีชื่อเสมอ
        receiver_person_id = req.receiver_person_id
        receiver_name = (req.receiver_name or "").strip()
        if receiver_person_id is not None:
            person = await conn.fetchrow(
                """SELECT id, display_name, roles FROM finance_people
                   WHERE id = $1 AND room_id = $2
                     AND is_active AND deleted_at IS NULL""",
                receiver_person_id, target_room_id,
            )
            if not person or "receive" not in (person["roles"] or []):
                raise ValueError(
                    "ไม่พบผู้รับเงินคนนี้ในห้อง หรือไม่ได้รับสิทธิ์รับเงิน"
                )
            receiver_name = person["display_name"]
        else:
            require_receiver = await conn.fetchval(
                "SELECT require_receiver FROM finance_settings WHERE room_id = $1",
                target_room_id,
            )
            if require_receiver is None:
                require_receiver = True  # ไม่มีแถวตั้งค่า = ใช้ค่ากลาง (ต้องระบุ)
            if require_receiver and not receiver_name:
                raise ValueError("ต้องระบุผู้รับเงินสำหรับรายการนี้")
            if not receiver_name:
                receiver_name = "—"

        # 👥 ผู้จ่าย: person (ถ้ามี) → ชื่อที่ client ส่ง → ชื่อนักเรียนจากโปรไฟล์
        payer_person_id = req.payer_person_id
        if payer_person_id is not None:
            payer_person = await conn.fetchrow(
                """SELECT id, display_name FROM finance_people
                   WHERE id = $1 AND room_id = $2
                     AND is_active AND deleted_at IS NULL""",
                payer_person_id, target_room_id,
            )
            if not payer_person:
                raise ValueError("ไม่พบผู้จ่ายเงินคนนี้ในห้อง")
            payer_name = payer_person["display_name"]
        else:
            payer_name = (req.payer_name or "").strip() or cls._display_name(student)

        # 🗓️ event_at: None → DB CURRENT_TIMESTAMP (ตอน insert); ถ้าส่งมา
        #    ต้อง tz-aware และไม่เกินอนาคต 1 วัน (พิมพ์ใบล่วงหน้าข้ามปีได้แค่พอสมควร)
        event_at_in = req.event_at
        if event_at_in is not None:
            if event_at_in.tzinfo is None:
                raise ValueError(
                    "เวลาของรายการ (event_at) ต้องระบุเขตเวลา (เช่น ...Z หรือ +07:00)"
                )
            too_far = await conn.fetchval(
                "SELECT $1::timestamptz > CURRENT_TIMESTAMP + INTERVAL '1 day'",
                event_at_in,
            )
            if too_far:
                raise ValueError(
                    "เวลาของรายการอยู่ในอนาคตเกิน 1 วัน — ตรวจสอบวันที่อีกครั้ง"
                )

        # 6) บิลเปิด/เครดิต **ใต้ล็อก**
        bills = await cls._load_preview_bills(conn, target_room_id, req.student_id)
        balance = await cls._load_credit_balance(
            conn, room_id=target_room_id, student_id=req.student_id
        )

        # 7) engine จัดสรร (pure) — error ของมัน router แปลง 400/409 ให้แล้ว
        plan = build_allocation_plan(
            bills=bills,
            amount_received_stang=to_satang(req.amount_received),
            credit_available_stang=to_satang(balance),
            use_credit=bool(req.use_credit),
            excess_action=req.excess_action,
            bill_selection=req.bill_selection,
            bill_ids=req.bill_ids,
        )
        if plan["total_applied_stang"] + plan["credit_added_stang"] <= 0:
            # event ว่าง (amount=0, ใช้เครดิตแต่ไม่มีบิลค้าง) → CHECK ของ DB จะปฏิเสธ
            # ⇒ ตอบ 400 ที่อ่านรู้เรื่องก่อน ดีกว่า 500 จาก CheckViolation
            raise ValueError(
                "ไม่มีรายการให้ทำ — ยอดรับเงินและเครดิตที่ใช้ได้รวมแล้วเป็นศูนย์"
            )

        # 8) 🔒 ล็อกบิลทั้งหมดตามลำดับ id (ไม่ใช่ลำดับที่ client ส่ง)
        await _lock_payments_in_order(
            conn, [a["payment_id"] for a in plan["allocations"]]
        )

        # 9) สร้าง event (ยังไม่มี lines) — ยอดจาก plan จะถูกเขียนทับด้วยยอดจริงข้อ 14
        excess_db = "credit" if plan["credit_added_stang"] > 0 else "none"
        event_row = await conn.fetchrow(
            """INSERT INTO finance_payment_events
                   (room_id, student_id, payer_person_id, payer_name,
                    receiver_person_id, receiver_name, wallet_account_id,
                    channel_id, channel_snapshot, amount_received, credit_used,
                    credit_added, total_applied, excess_action, note,
                    idempotency_key, event_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15,$16,
                       COALESCE($17::timestamptz, CURRENT_TIMESTAMP))
               RETURNING id, event_at""",
            target_room_id, req.student_id, payer_person_id, payer_name,
            receiver_person_id, receiver_name, req.wallet_account_id,
            req.channel_id,
            json.dumps(channel_snapshot, ensure_ascii=False),
            from_satang(plan["amount_received_stang"]),
            from_satang(plan["credit_used_stang"]),
            from_satang(plan["credit_added_stang"]),
            from_satang(plan["total_applied_stang"]),
            excess_db, req.note, key, event_at_in,
        )
        event_id = event_row["id"]
        event_at = event_row["event_at"]

        # 10) เงินสด: ต่อบิลผ่าน `_confirm_single_payment` (ทางเดียวที่ลง Dr/Cr รับเงิน)
        cash_trans_by_payment: dict[int, int] = {}
        cash_applied_stang = 0
        for alloc in plan["allocations"]:
            if alloc["source"] != "cash":
                continue
            paid = from_satang(alloc["amount_stang"])
            confirmed = await cls._confirm_single_payment(
                conn=conn, target_room_id=target_room_id,
                payment_id=alloc["payment_id"],
                paid_amount=paid,
                paid_to_account_id=req.wallet_account_id,
                slip_image_url=req.slip_image_url,
                user_name=receiver_name,
            )
            # 🔗 ผูกธุรกรรมเงินสดเข้ากับ event (ถ้าลืม = ประวัติจัดกลุ่มตาม event ไม่ครบ)
            await conn.execute(
                "UPDATE finance_transactions SET payment_event_id = $1 WHERE id = $2",
                event_id, confirmed["trans_id"],
            )
            cash_trans_by_payment[alloc["payment_id"]] = confirmed["trans_id"]
            cash_applied_stang += alloc["amount_stang"]

        # 11) เครดิต: เรียก `_apply_plan_locked` **ครั้งเดียว** ต่อ event
        credit_allocs = [a for a in plan["allocations"] if a["source"] == "credit"]
        executed_credit: dict[int, dict] = {}
        credit_used_stang = 0
        if credit_allocs:
            synthetic_plan = {
                "items": [{
                    "student_id": req.student_id,
                    "student_no": student["student_no"],
                    "student_name": payer_name,
                    # ใช้เฉพาะคำนวณ total_balance_after ของ response ที่ไม่ถูกใช้ที่นี่
                    "balance_after": round(
                        balance - from_satang(
                            sum(a["amount_stang"] for a in credit_allocs)
                        ), 2,
                    ),
                    "allocations": [
                        {
                            "payment_id": a["payment_id"],
                            "apply_amount": from_satang(a["amount_stang"]),
                            "due_date": a["due_date"],
                        }
                        for a in credit_allocs
                    ],
                }],
            }
            applied = await cls._apply_plan_locked(
                conn, target_room_id=target_room_id, plan=synthetic_plan,
                user_name=receiver_name,
                actor_identifier=actor_identifier, client_source=client_source,
            )
            for item in applied["items"]:
                for alloc in item["allocations"]:
                    pid = alloc["payment_id"]
                    # 🔗 ผูกแถว student_credits (apply) ล่าสุดของบิลนี้เข้ากับ event
                    credit_entry_id = await conn.fetchval(
                        """UPDATE student_credits SET payment_event_id = $1
                           WHERE id = (
                               SELECT id FROM student_credits
                               WHERE room_id = $2 AND student_id = $3
                                 AND entry_type = 'apply'
                                 AND student_payment_id = $4 AND deleted_at IS NULL
                               ORDER BY id DESC LIMIT 1
                           )
                           RETURNING id""",
                        event_id, target_room_id, req.student_id, pid,
                    )
                    if credit_entry_id is None:
                        raise ValueError(
                            "บันทึกการหักเครดิตไม่สมบูรณ์ — ยกเลิกรายการนี้แล้วลองใหม่"
                        )
                    executed_credit[pid] = {
                        **alloc,
                        "credit_entry_id": credit_entry_id,
                        "apply_stang": to_satang(alloc["apply_amount"]),
                    }
                    credit_used_stang += to_satang(alloc["apply_amount"])

        # 12) ส่วนเกินเป็นเครดิต (เงินสดเหลือหลังปิดบิล)
        #     ⚠️ คิดจากเงินสดที่ใช้จริง ไม่ใช่จากยอดเครดิตที่อาจถูก cap
        credit_added_stang = plan["amount_received_stang"] - cash_applied_stang
        topup = None
        if credit_added_stang > 0:
            if req.excess_action != "credit":
                raise ValueError(
                    "ยอดรับเงินเกินยอดที่ต้องใช้ — ระบบตั้งค่าไม่ให้เก็บส่วนเกินเป็นเครดิต"
                )
            topup = await cls._create_excess_credit_locked(
                conn, target_room_id=target_room_id, student_id=req.student_id,
                event_id=event_id, amount_stang=credit_added_stang,
                account_id=req.wallet_account_id, payer_name=payer_name,
                user_name=receiver_name, slip_image_url=req.slip_image_url,
                note=req.note,
                # 🔑 ต่างจาก event key: กันชนกับ unique ของ student_credits ระดับห้อง
                #    (สูงสุด 64 ตัว ⇒ ตัด 54 + ":topup" = 60)
                idempotency_key=f"{key[:54]}:topup",
            )

        # 13) บรรทัดของ event — bill / credit_apply / credit_topup
        bill_by_payment = {b["payment_id"]: b for b in bills}
        all_line_amounts_stang: List[int] = []
        for alloc in plan["allocations"]:
            pid = alloc["payment_id"]
            bill = bill_by_payment.get(pid, {})
            meta = {
                "collection_id": alloc["collection_id"],
                "title": alloc["title"],
                "student_id": req.student_id,
            }
            if alloc["source"] == "cash":
                await conn.execute(
                    """INSERT INTO finance_payment_event_lines
                           (event_id, line_kind, student_payment_id,
                            finance_transaction_id, credit_entry_id, amount,
                            bill_amount_before, bill_amount_after, meta)
                       VALUES ($1, 'bill', $2, $3, NULL, $4, $5, $6, $7::jsonb)""",
                    event_id, pid, cash_trans_by_payment[pid],
                    from_satang(alloc["amount_stang"]),
                    from_satang(alloc["bill_before_stang"]),
                    from_satang(alloc["bill_after_stang"]),
                    json.dumps({**meta, "source": "cash"}, ensure_ascii=False),
                )
                all_line_amounts_stang.append(alloc["amount_stang"])
                continue

            executed = executed_credit.get(pid)
            if not executed:
                continue  # ไม่ถูกหักจริง (cap) — ไม่มีบรรทัด ไม่มีเงิน
            before_stang = to_satang(executed["bill_remaining_before"])
            after_stang = before_stang - executed["apply_stang"]
            await conn.execute(
                """INSERT INTO finance_payment_event_lines
                       (event_id, line_kind, student_payment_id,
                        finance_transaction_id, credit_entry_id, amount,
                        bill_amount_before, bill_amount_after, meta)
                   VALUES ($1, 'credit_apply', $2, NULL, $3, $4, $5, $6, $7::jsonb)""",
                event_id, pid, executed["credit_entry_id"],
                from_satang(executed["apply_stang"]),
                from_satang(before_stang), from_satang(after_stang),
                json.dumps({**meta, "source": "credit"}, ensure_ascii=False),
            )
            all_line_amounts_stang.append(executed["apply_stang"])

        if topup is not None:
            await conn.execute(
                """INSERT INTO finance_payment_event_lines
                       (event_id, line_kind, student_payment_id,
                        finance_transaction_id, credit_entry_id, amount,
                        bill_amount_before, bill_amount_after, meta)
                   VALUES ($1, 'credit_topup', NULL, $2, $3, $4, NULL, NULL, $5::jsonb)""",
                event_id, topup["trans_id"], topup["credit_entry_id"],
                from_satang(credit_added_stang),
                json.dumps({"source": "credit", "student_id": req.student_id},
                           ensure_ascii=False),
            )

        # 14) เขียนยอดจริงกลับ event + ยืนยันสมการ (ถ้าไม่ผ่าน = bug ⇒ rollback)
        total_applied_stang = cash_applied_stang + credit_used_stang
        actual_plan = {
            "amount_received_stang": plan["amount_received_stang"],
            "credit_used_stang": credit_used_stang,
            "total_applied_stang": total_applied_stang,
            "credit_added_stang": credit_added_stang,
            "allocations": [{"amount_stang": a} for a in all_line_amounts_stang],
        }
        # assert_plan_equation ต้องการ "amount_stang" ใน allocations — เราใส่ให้แล้ว
        assert_plan_equation(actual_plan)

        await conn.execute(
            """UPDATE finance_payment_events
               SET amount_received = $1, credit_used = $2, credit_added = $3,
                   total_applied = $4, excess_action = $5
               WHERE id = $6""",
            from_satang(plan["amount_received_stang"]),
            from_satang(credit_used_stang),
            from_satang(credit_added_stang),
            from_satang(total_applied_stang),
            "credit" if credit_added_stang > 0 else "none",
            event_id,
        )

        # 🕐 issued_at อ่านจาก DB ครั้งเดียว — REC/DEP ของ event เดียวกันได้เวลาเดียวกัน
        issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")

        # 15) REC 1 ใบ — ออกเมื่อมีเงินสด **และ** มีรายการที่ปิดจริง
        #     (เครดิตล้วน/เติมเครดิตล้วนไม่มี REC; total_applied=0 ก็ออกไม่ได้)
        receipt_no = None
        receipt_doc = None
        if plan["amount_received_stang"] > 0 and total_applied_stang > 0:
            line_items = cls._build_receipt_line_items(
                plan["allocations"], executed_credit, bill_by_payment
            )
            document_meta = {
                "payer_name": payer_name,
                "receiver_name": receiver_name,
                "receiver_person_id": receiver_person_id,
                "channel": channel_snapshot,
                "event_at": event_at.isoformat() if event_at else None,
                "amount_received": from_satang(plan["amount_received_stang"]),
                "credit_used": from_satang(credit_used_stang),
                "credit_added": from_satang(credit_added_stang),
                "total_applied": from_satang(total_applied_stang),
                "amounts_in_words": baht_text(from_satang(total_applied_stang)),
            }
            issued = await cls._issue_event_receipt(
                conn,
                target_room_id=target_room_id,
                event_id=event_id,
                student_id=req.student_id,
                issued_to_name=payer_name,
                user_id=user_id,
                user_name=receiver_name,
                note=req.note,
                amount=from_satang(total_applied_stang),
                total_applied=from_satang(total_applied_stang),
                event_at=event_at,
                issued_at=issued_at_db,
                line_items=line_items,
                document_meta=document_meta,
                idempotency_key=key,
                receiver_person_id=receiver_person_id,
            )
            receipt_doc = issued["receipt"]
            receipt_no = receipt_doc["receipt_no"]

        # 16) DEP 1 ใบ + link REC↔DEP
        deposit_doc = None
        if topup is not None:
            deposit_meta = {
                "payer_name": payer_name,
                "receiver_name": receiver_name,
                "channel": channel_snapshot,
                "event_at": event_at.isoformat() if event_at else None,
                "balance_before": topup["balance_before"],
                "balance_after": topup["balance_after"],
            }
            dep = await cls._issue_event_deposit(
                conn,
                target_room_id=target_room_id,
                event_id=event_id,
                student_id=req.student_id,
                transaction_id=topup["trans_id"],
                issued_to_name=payer_name,
                user_id=user_id,
                user_name=receiver_name,
                note=req.note,
                amount=from_satang(credit_added_stang),
                event_at=event_at,
                issued_at=issued_at_db,
                document_meta=deposit_meta,
                idempotency_key=key,
                receiver_person_id=receiver_person_id,
            )
            deposit_doc = dep["receipt"]
            if receipt_doc is not None:
                await conn.execute(
                    """INSERT INTO finance_document_links
                           (room_id, from_doc_type, from_doc_id,
                            to_doc_type, to_doc_id, link_type)
                       VALUES ($1, 'receipt', $2, 'deposit', $3, 'receipt_for_deposit')
                       ON CONFLICT DO NOTHING""",
                    target_room_id, receipt_doc["id"], deposit_doc["id"],
                )

        # 17) audit — entity PAYMENT_EVENT ใน transaction เดียวกัน
        exec_time = int((time.time() - start_time) * 1000)
        await service_logger.log(
            conn=conn, action="CREATE",
            actor_identifier=actor_identifier, client_source=client_source,
            room_id=target_room_id, user_id=None,
            entity_type="PAYMENT_EVENT", entity_id=str(event_id),
            status="success",
            new_values={
                "student_id": req.student_id,
                "amount_received": from_satang(plan["amount_received_stang"]),
                "credit_used": from_satang(credit_used_stang),
                "credit_added": from_satang(credit_added_stang),
                "total_applied": from_satang(total_applied_stang),
                "receipt_no": receipt_no,
                "deposit_no": deposit_doc["receipt_no"] if deposit_doc else None,
            },
            endpoint_or_command="FinanceService.create_payment_event",
            execution_time_ms=exec_time,
        )

        # 18) server_id สำหรับแจ้ง Discord (publish หลัง commit เท่านั้น)
        room_server_id = await cls._get_room_server_id(conn, target_room_id)

        # 19) ผลลัพธ์อ่านกลับจาก DB — รูปร่างเดียวกับ replay เป๊ะ
        refreshed = await conn.fetchrow(
            "SELECT * FROM finance_payment_events WHERE id = $1", event_id
        )
        result = await cls._build_event_result(
            conn, refreshed, reused=False, warnings=plan.get("warnings")
        )

        notify_payload = cls._build_notify_payload(
            result, payer_name=payer_name, receiver_name=receiver_name,
            amount_received=from_satang(plan["amount_received_stang"]),
            receipt_no=receipt_no,
        )
        return result, notify_payload, room_server_id

    @classmethod
    def _build_receipt_line_items(
        cls, plan_allocations: List[dict], executed_credit: dict, bill_by_payment: dict,
    ) -> List[dict]:
        """รวมบรรทัดของ plan เป็น "1 บรรทัดต่อ 1 บิล" สำหรับ `line_items` ของ REC

        🔴 snapshot ต้องพอให้พิมพ์ได้เอง (P2.2 ห้าม JOIN บิลสด):
           - `bill_amount` = ยอดเต็มของบิล ณ ตอนออก (fee_collections.amount)
           - `amount_applied` = เงินสด + เครดิตที่ลงบิลนี้จริง
           - `cash_amount`/`credit_amount` แยกแหล่ง
           - `bill_remaining` = ยอดคงเหลือหลังรายการนี้
        """
        by_payment: dict[int, dict] = {}
        order: List[int] = []
        for alloc in plan_allocations:
            pid = alloc["payment_id"]
            if pid not in by_payment:
                bill = bill_by_payment.get(pid, {})
                by_payment[pid] = {
                    "collection_id": alloc["collection_id"],
                    "title": alloc["title"],
                    "bill_amount": from_satang(bill.get("bill_total_stang", 0)),
                    "amount_applied": 0.0,
                    "cash_amount": 0.0,
                    "credit_amount": 0.0,
                    "bill_remaining": None,
                }
                order.append(pid)
            entry = by_payment[pid]
            if alloc["source"] == "cash":
                entry["cash_amount"] += from_satang(alloc["amount_stang"])
                entry["amount_applied"] += from_satang(alloc["amount_stang"])
                entry["bill_remaining"] = from_satang(alloc["bill_after_stang"])
            else:
                executed = executed_credit.get(pid)
                if not executed:
                    continue
                amount = from_satang(executed["apply_stang"])
                entry["credit_amount"] += amount
                entry["amount_applied"] += amount
                entry["bill_remaining"] = round(
                    from_satang(to_satang(executed["bill_remaining_before"]))
                    - amount, 2
                )

        items = []
        for pid in order:
            entry = by_payment[pid]
            if entry["amount_applied"] <= 0:
                continue
            if entry["cash_amount"] > 0 and entry["credit_amount"] > 0:
                source = "mixed"
            elif entry["credit_amount"] > 0:
                source = "credit"
            else:
                source = "cash"
            items.append({
                "student_payment_id": pid,
                **entry,
                "source": source,
            })
        return items

    @staticmethod
    def _build_notify_payload(
        result: dict, *, payer_name: str, receiver_name: str,
        amount_received: float, receipt_no: Optional[str],
    ) -> dict:
        """payload ของ Discord — 1 event = 1 ข้อความ (ไม่เด้งต่อบิล)

        ⚠️ รวมบรรทัด cash+credit ของบิลเดียวกันเป็น **1 item** — ผู้ใช้ควรเห็น
           "ปิดบิล A 500" ครั้งเดียว ไม่ใช่สองบรรทัดที่บวกกันเอง
        """
        aggregated: dict[int, dict] = {}
        order: List[int] = []
        for alloc in result["allocations"]:
            pid = alloc["student_payment_id"]
            if pid not in aggregated:
                aggregated[pid] = {
                    "title": alloc["title"] or "รับเงิน",
                    "amount": 0.0,
                    "receipt_no": receipt_no,
                }
                order.append(pid)
            aggregated[pid]["amount"] = round(
                aggregated[pid]["amount"] + float(alloc["amount"]), 2
            )
        items = [aggregated[pid] for pid in order]
        if not items:
            items.append({
                "title": "รับเงินล่วงหน้า (ส่วนเกินเป็นเครดิต)",
                "amount": float(result["credit_added"]),
                "receipt_no": receipt_no,
            })
        return {
            "payer_name": payer_name,
            "items": items,
            "total_amount": amount_received,
            "user_name": receiver_name,
            "receipt_nos": [receipt_no] if receipt_no else None,
        }

    # ================================================================ reads
    @classmethod
    async def get_payment_event(
        cls, pool: asyncpg.Pool, *, server_id: Optional[int] = None,
        room_id: Optional[int] = None, event_id: int, user_id: int,
    ) -> dict:
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            row = await conn.fetchrow(
                """SELECT * FROM finance_payment_events
                   WHERE id = $1 AND room_id = $2""",
                event_id, target_room_id,
            )
            if not row:
                raise PaymentNotFoundError("ไม่พบรายการรับเงินนี้ในห้องของคุณ")
            lines = await cls._load_event_lines(conn, event_id)
            documents = await cls._load_event_documents(conn, event_id)
            result = cls._shape_event_result(row, lines, documents, reused=False)
            return cls._shape_event_detail(row, result, lines)

    @classmethod
    async def list_payment_events(
        cls, pool: asyncpg.Pool, *, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: int,
        date_from: Optional[date] = None, date_to: Optional[date] = None,
        student_id: Optional[int] = None, receiver_id: Optional[int] = None,
        channel_id: Optional[int] = None, q: Optional[str] = None,
    ) -> dict:
        """รายการรับเงินของห้อง — กรองด้วย **วันไทย** และเรียงใหม่→เก่า"""
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            where = ["E.room_id = $1", "E.status = 'active'"]
            params: List[object] = [target_room_id]

            if date_from is not None:
                params.append(date_from)
                where.append(
                    f"(E.event_at AT TIME ZONE 'Asia/Bangkok')::date >= ${len(params)}"
                )
            if date_to is not None:
                params.append(date_to)
                where.append(
                    f"(E.event_at AT TIME ZONE 'Asia/Bangkok')::date <= ${len(params)}"
                )
            if student_id is not None:
                params.append(student_id)
                where.append(f"E.student_id = ${len(params)}")
            if receiver_id is not None:
                params.append(receiver_id)
                where.append(f"E.receiver_person_id = ${len(params)}")
            if channel_id is not None:
                params.append(channel_id)
                where.append(f"E.channel_id = ${len(params)}")
            search = (q or "").strip()
            if search:
                params.append(f"%{search}%")
                where.append(
                    f"(E.payer_name ILIKE ${len(params)} "
                    f"OR E.reference_no ILIKE ${len(params)})"
                )

            rows = await conn.fetch(
                f"""SELECT E.*,
                           (SELECT R.receipt_no FROM finance_receipts R
                             WHERE R.payment_event_id = E.id
                               AND R.doc_type = 'receipt'
                               AND R.deleted_at IS NULL AND R.status = '{DOC_STATUS_ACTIVE}'
                             ORDER BY R.id LIMIT 1) AS receipt_no,
                           (SELECT R.receipt_no FROM finance_receipts R
                             WHERE R.payment_event_id = E.id
                               AND R.doc_type = 'deposit'
                               AND R.deleted_at IS NULL AND R.status = '{DOC_STATUS_ACTIVE}'
                             ORDER BY R.id LIMIT 1) AS deposit_no
                    FROM finance_payment_events E
                    WHERE {' AND '.join(where)}
                    ORDER BY E.event_at DESC, E.id DESC
                    LIMIT 200""",
                *params,
            )

        items = [
            {
                "event_id": r["id"],
                "student_id": r["student_id"],
                "payer_name": r["payer_name"],
                "receiver_name": r["receiver_name"],
                "amount_received": f"{float(r['amount_received']):.2f}",
                "credit_used": f"{float(r['credit_used']):.2f}",
                "credit_added": f"{float(r['credit_added']):.2f}",
                "total_applied": f"{float(r['total_applied']):.2f}",
                "event_at": r["event_at"],
                "receipt_no": r["receipt_no"],
                "deposit_no": r["deposit_no"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {"items": items}
