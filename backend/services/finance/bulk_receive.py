"""📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว (bulk receive)

═══════════════════════════════════════════════════════════════════════════════
หัวใจของ package นี้
═══════════════════════════════════════════════════════════════════════════════
1 คำขอ = 1 transaction = **all-or-nothing**: ถ้านักเรียนคนใดล้ม (บิลถูกปิด/ยอดผิด)
**ไม่มีใครถูกบันทึกเลย** — ไม่มี event/REC/DEP/transaction/journal/เลขใบเสร็จค้าง

- 1 นักเรียน = 1 `finance_payment_event` + REC/DEP ของตัวเอง (ไม่ยุบข้ามคน)
- ทุก event ในรอบใช้ `reference_no` เดียว และ `event_at` เดียว (ปี พ.ศ. เดียวกัน)
- แจ้ง Discord **ครั้งเดียวหลัง commit** และ replay ไม่แจ้ง

🔴 กฎเหล็ก: **ห้ามเรียก `create_payment_event`** — มันเปิด transaction เอง
   ต้องเรียก `_commit_payment_event_locked` (payment_events.py) ในลูปแทน

🔁 idempotency: ต่อคนใช้คีย์อนุพันธ์ `f"{bulk_key[:48]}:{student_id}"`
   (unique `(room_id, idempotency_key)` ยังบังคับที่ DB; bulk key เดียวใช้ทุก event
   ไม่ได้ — จะชนตั้งแต่แถวที่ 2) · replay ตรวจ `reference_no` + item keys ใต้
   `_lock_room_money` — schema ไม่มีตาราง bulk (รายงานเป็นช่องว่าง)
"""
import time
from decimal import Decimal
from typing import List, Optional

import asyncpg

from core.rbac import require_permission
from models.finance_schemas import PaymentEventCreate
from services.action_service import ActionService

from .allocation import AllocationError, ChannelNotFoundError
from .base import _lock_room_money, service_logger
from .payment_events import PaymentEventAccountNotFoundError


class BulkPaymentFailure(ValueError):
    """ข้อผิดพลาดของ bulk — router แปลเป็น 400/409

    - `student_id` ไม่ใช่ None ⇒ router ตอบ detail object
      `{"code": "BULK_ITEM_FAILED", "message", "student_id", "item_code"}`
      (หน้าจอไฮไลต์แถวนั้นได้)
    - `student_id` เป็น None ⇒ validation ก่อนเขียน ⇒ detail string
    """

    def __init__(
        self, message: str, *, item_code: str = "BULK_ITEM_FAILED",
        status_code: int = 400, student_id: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.item_code = item_code
        self.status_code = status_code
        self.student_id = student_id


# บิลที่ถูกปิด/เปลี่ยนระหว่างทาง = 409 (ผู้ใช้ควรโหลดใหม่) · อื่น ๆ = 400
_ITEM_409_CODES = {"BILL_NOT_OPEN", "BILL_CHANGED"}


class BulkReceiveMixin:
    # ================================================================ entry
    @classmethod
    async def create_bulk_payment_events(
        cls, pool: asyncpg.Pool, *, server_id: Optional[int] = None,
        room_id: Optional[int] = None, req, user_id: int,
        client_source: str, actor_identifier: str,
    ) -> dict:
        """รับเงิน N คน → N events (+REC/DEP ต่อคน) ใน transaction เดียว"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                async with conn.transaction():
                    result, notify_payload, room_server_id = await cls._bulk_locked(
                        conn, target_room_id=target_room_id, req=req,
                        user_id=user_id, client_source=client_source,
                        actor_identifier=actor_identifier, start_time=start_time,
                    )

            # 📢 notify **หลัง commit เท่านั้น** ครั้งเดียว — replay คืน None
            if notify_payload and room_server_id:
                await ActionService.notify_payments_confirmed(
                    server_id=room_server_id,
                    payer_name=notify_payload["payer_name"],
                    items=notify_payload["items"],
                    total_amount=notify_payload["total_amount"],
                    user_name=notify_payload["user_name"],
                    receipt_nos=notify_payload.get("receipt_nos") or None,
                )
            return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=None,
                        entity_type="PAYMENT_EVENT_BULK", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.create_bulk_payment_events",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ================================================================ locked
    @classmethod
    async def _bulk_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, req, user_id: int,
        client_source: str, actor_identifier: str, start_time: float,
    ):
        """เนื้อใน transaction — คืน `(result, notify_payload, room_server_id)`

        ลำดับ **ห้ามสลับ**: RBAC → `_lock_room_money` → อ่าน/ตรวจทั้งหมด →
        เขียนต่อคน (`_commit_payment_event_locked`) → audit bulk → server_id
        """
        # 2) RBAC
        await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

        # 3) 🔒 ล็อกห้องก่อนแตะข้อมูลใด ๆ — protocol เดียวกันทั้งระบบ
        await _lock_room_money(conn, target_room_id)

        # 4) dedupe student_id รักษาลำดับ — ซ้ำ = 400 ก่อนเขียนอะไรเลย
        student_ids: List[int] = []
        seen: set[int] = set()
        for item in req.items:
            if item.student_id in seen:
                raise BulkPaymentFailure(
                    "มีนักเรียนซ้ำในรอบเดียวกัน — เลือกได้คนละหนึ่งครั้ง",
                    item_code="DUPLICATE_STUDENT", status_code=400,
                )
            seen.add(item.student_id)
            student_ids.append(item.student_id)

        # 5) ขอบเขต (Pydantic บังคับแล้ว — ตรวจซ้ำเพื่อเรียก service ตรง ๆ ให้ปลอดภัย)
        if not student_ids:
            raise BulkPaymentFailure(
                "ต้องมีนักเรียนอย่างน้อย 1 คน", item_code="TOO_MANY_ITEMS",
            )
        if len(student_ids) > 100:
            raise BulkPaymentFailure(
                "รับเงินได้ครั้งละไม่เกิน 100 คน", item_code="TOO_MANY_ITEMS",
            )
        reference_no = (req.reference_no or "").strip()
        if not reference_no or len(reference_no) > 64:
            raise BulkPaymentFailure(
                "เลขที่รับเงินต้องมีความยาว 1–64 ตัวอักษร",
                item_code="INVALID_REFERENCE_NO",
            )
        bulk_key = (req.idempotency_key or "").strip()
        if not (8 <= len(bulk_key) <= 64):
            raise BulkPaymentFailure(
                "รหัสกันส่งซ้ำ (idempotency_key) ต้องยาว 8–64 ตัวอักษร",
                item_code="INVALID_IDEMPOTENCY_KEY",
            )
        for item in req.items:
            # event ว่างไม่ผ่าน CHECK ของ DB (`total_applied + credit_added > 0`)
            # ⇒ ปฏิเสธที่อ่านรู้เรื่องก่อนเริ่มเขียน ดีกว่า 500 จาก CheckViolation
            if item.amount_received == 0 and not item.use_credit:
                raise BulkPaymentFailure(
                    "นักเรียนคนหนึ่งมียอดรับเงิน 0 และไม่ได้ใช้เครดิต — "
                    "ถอดออกหรือใส่ยอดก่อนบันทึก",
                    item_code="INVALID_AMOUNT", status_code=400,
                )

        # 6) 🔁 idempotency/reference **อ่านก่อนเขียน** ใต้ล็อกห้อง
        item_keys = [f"{bulk_key[:48]}:{sid}" for sid in student_ids]
        expected = set(item_keys)
        rows = await conn.fetch(
            """SELECT id, idempotency_key, reference_no, status
               FROM finance_payment_events
               WHERE room_id = $1
                 AND (reference_no = $2 OR idempotency_key = ANY($3::text[]))
               ORDER BY id""",
            target_room_id, reference_no, item_keys,
        )
        by_key = {r["idempotency_key"]: r for r in rows
                  if r["idempotency_key"] in expected}
        key_rows = list(by_key.values())
        ref_rows = [r for r in rows if r["reference_no"] == reference_no]

        full_replay = (
            len(key_rows) == len(expected)
            and len(ref_rows) == len(expected)
            and all(r["status"] == "active" for r in key_rows)
        )
        if full_replay:
            return await cls._build_bulk_replay(
                conn, target_room_id=target_room_id, student_ids=student_ids,
                item_keys=item_keys, reference_no=reference_no,
            )

        if key_rows:
            if any(r["reference_no"] != reference_no for r in key_rows):
                raise BulkPaymentFailure(
                    "รหัสกันส่งซ้ำนี้เคยถูกใช้กับเลขที่รับเงินอื่น — "
                    "กรุณาทำรายการใหม่ด้วยรหัสใหม่",
                    item_code="IDEMPOTENCY_KEY_CONFLICT", status_code=409,
                )
            if len(key_rows) == len(expected) and any(
                r["status"] != "active" for r in key_rows
            ):
                raise BulkPaymentFailure(
                    "รายการรับเงินรอบนี้ถูกยกเลิกไปแล้ว — ทำรายการใหม่ด้วยรหัสใหม่",
                    item_code="IDEMPOTENCY_KEY_CONFLICT", status_code=409,
                )
            raise BulkPaymentFailure(
                "เลขที่รับเงินนี้ถูกบันทึกไปแล้วบางส่วนและไม่ตรงกับรอบเดิม — "
                "ไม่บันทึกซ้ำ",
                item_code="REFERENCE_NO_CONFLICT", status_code=409,
            )
        if ref_rows:
            raise BulkPaymentFailure(
                "เลขที่รับเงินนี้ถูกใช้ไปแล้วด้วยรหัสอื่น — "
                "ใช้เลขที่ใหม่ หรือกดซ้ำจากรอบเดิม",
                item_code="REFERENCE_NO_CONFLICT", status_code=409,
            )

        # 7) ตรวจ shared (กระเป๋า/ช่องทาง/ผู้รับ) + ชื่อนักเรียน **ก่อนเขียน**
        account_ok = await conn.fetchval(
            """SELECT id FROM finance_accounts
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            req.wallet_account_id, target_room_id,
        )
        if not account_ok:
            raise PaymentEventAccountNotFoundError(
                "ไม่พบกระเป๋าเงินนี้ในห้อง (หรือถูกลบไปแล้ว)"
            )
        if req.channel_id is not None:
            channel_ok = await conn.fetchval(
                """SELECT id FROM finance_payment_channels
                   WHERE id = $1 AND room_id = $2
                     AND is_active AND deleted_at IS NULL""",
                req.channel_id, target_room_id,
            )
            if not channel_ok:
                raise ChannelNotFoundError(
                    "ไม่พบช่องทางชำระเงินนี้ในห้อง (หรือถูกปิดใช้งานแล้ว)"
                )

        # 👤 ผู้รับเงิน: person ชนะชื่อที่ client ส่ง (กฎเดียวกับ P2.1)
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
                raise BulkPaymentFailure(
                    "ไม่พบผู้รับเงินคนนี้ในห้อง หรือไม่ได้รับสิทธิ์รับเงิน",
                    item_code="INVALID_RECEIVER", status_code=400,
                )
            receiver_name = person["display_name"]
        else:
            require_receiver = await conn.fetchval(
                "SELECT require_receiver FROM finance_settings WHERE room_id = $1",
                target_room_id,
            )
            if require_receiver is None:
                require_receiver = True
            if require_receiver and not receiver_name:
                raise BulkPaymentFailure(
                    "ต้องระบุผู้รับเงินสำหรับรายการนี้",
                    item_code="INVALID_RECEIVER", status_code=400,
                )
            if not receiver_name:
                receiver_name = "—"

        student_rows = await conn.fetch(
            """SELECT S.id, S.student_no,
                      U.prefix, U.first_name, U.last_name, U.first_name_en, U.last_name_en
               FROM students S
               LEFT JOIN v_student_profiles U ON U.student_id = S.id
               WHERE S.id = ANY($1::bigint[]) AND S.room_id = $2
                 AND S.deleted_at IS NULL""",
            student_ids, target_room_id,
        )
        by_student = {r["id"]: r for r in student_rows}
        missing = [sid for sid in student_ids if sid not in by_student]
        if missing:
            raise BulkPaymentFailure(
                "ไม่พบนักเรียนบางคนในห้องเรียน — โหลดรายชื่อใหม่แล้วลองอีกครั้ง",
                item_code="STUDENT_NOT_FOUND", status_code=404,
                student_id=missing[0],
            )
        student_names = {
            sid: cls._display_name(by_student[sid]) for sid in student_ids
        }

        # 8) event_at เดียวทั้งรอบ — DB NOW ครั้งเดียว ⇒ ปี พ.ศ. เดียวกันแม้ข้ามเที่ยงคืน
        issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        event_at = req.event_at or issued_at_db

        # 9) ต่อ item ตามลำดับ — ห้าม notify ในลูป
        events_payload: List[dict] = []
        event_ids: List[int] = []
        receipt_nos: List[str] = []
        notify_items: List[dict] = []
        total_received = Decimal("0")

        for item in req.items:
            item_key = f"{bulk_key[:48]}:{item.student_id}"
            item_req = PaymentEventCreate(
                idempotency_key=item_key,
                student_id=item.student_id,
                wallet_account_id=req.wallet_account_id,
                payer_name=None,
                payer_person_id=None,
                receiver_person_id=receiver_person_id,
                receiver_name=receiver_name,
                channel_id=req.channel_id,
                amount_received=Decimal(item.amount_received),
                use_credit=item.use_credit,
                excess_action=item.excess_action,
                bill_selection="auto",
                bill_ids=[],
                note=item.note or req.note,
                event_at=event_at,
                slip_image_url=None,
            )
            try:
                event_result, _ = await cls._commit_payment_event_locked(
                    conn, target_room_id=target_room_id, req=item_req,
                    user_id=user_id, client_source=client_source,
                    actor_identifier=actor_identifier, start_time=None,
                    reference_no=reference_no,
                )
            except AllocationError as e:
                raise BulkPaymentFailure(
                    str(e), item_code=e.code,
                    status_code=409 if e.code in _ITEM_409_CODES else 400,
                    student_id=item.student_id,
                ) from e
            except asyncpg.UniqueViolationError as e:
                # แข่งกับคำขออื่น (unique idem key / line ของบิล) — rollback ทั้งรอบ
                raise BulkPaymentFailure(
                    "รายการนี้ถูกบันทึกซ้ำจากอีกหน้าจอ — "
                    "โหลดใหม่แล้วตรวจสอบก่อนกดยืนยัน",
                    item_code="IDEMPOTENCY_KEY_CONFLICT", status_code=409,
                    student_id=item.student_id,
                ) from e
            except asyncpg.CheckViolationError as e:
                raise BulkPaymentFailure(
                    "ยอดของรายการไม่สมดุล — ตรวจสอบยอดอีกครั้ง",
                    item_code="INVALID_AMOUNT", status_code=400,
                    student_id=item.student_id,
                ) from e
            except ValueError as e:
                # payment_events core ใช้ ValueError สำหรับข้อมูลที่ผิดแบบธุรกิจ
                raise BulkPaymentFailure(
                    str(e), item_code="INVALID_AMOUNT", status_code=400,
                    student_id=item.student_id,
                ) from e

            name = student_names[item.student_id]
            events_payload.append({
                "student_id": item.student_id,
                "student_name": name,
                "event": event_result,
            })
            event_ids.append(event_result["event_id"])
            if event_result["receipt_no"]:
                receipt_nos.append(event_result["receipt_no"])

            cash = Decimal(event_result["amount_received"])
            total_received += cash
            n_bills = len(event_result["allocations"])
            notify_items.append({
                "title": (
                    f"{name} — {n_bills} บิล" if n_bills
                    else f"{name} — รับเงินล่วงหน้า"
                ),
                "amount": float(cash),
                "receipt_no": event_result["receipt_no"],
            })

        # 10) audit ระดับ bulk 1 ครั้ง (core ยัง log PAYMENT_EVENT ต่อคนตามเดิม)
        await service_logger.log(
            conn=conn, action="CREATE",
            actor_identifier=actor_identifier, client_source=client_source,
            room_id=target_room_id, user_id=None,
            entity_type="PAYMENT_EVENT_BULK", entity_id=reference_no,
            status="success",
            new_values={
                "reference_no": reference_no,
                "student_ids": student_ids,
                "event_ids": event_ids,
                "receipt_nos": receipt_nos,
                "amount_total": f"{total_received:.2f}",
            },
            endpoint_or_command="FinanceService.create_bulk_payment_events",
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

        # 11) server_id ก่อนออก transaction — publish หลัง commit เท่านั้น
        room_server_id = await cls._get_room_server_id(conn, target_room_id)

        result = {
            "status": "success",
            "message": f"บันทึกรับเงิน {len(events_payload)} คน เรียบร้อย",
            "reference_no": reference_no,
            "events": events_payload,
            "total_amount_received": f"{total_received:.2f}",
            "reused": False,
        }
        notify_payload = {
            "payer_name": f"นักเรียน {len(events_payload)} คน",
            "items": notify_items,
            "total_amount": float(total_received),
            "user_name": receiver_name,
            "receipt_nos": receipt_nos,
        }
        return result, notify_payload, room_server_id

    # ================================================================ replay
    @classmethod
    async def _build_bulk_replay(
        cls, conn: asyncpg.Connection, *, target_room_id: int,
        student_ids: List[int], item_keys: List[str], reference_no: str,
    ):
        """คืนผลเดิมของรอบนี้ (ไม่เขียน/ไม่ notify) — `reused=true` ทุก event"""
        rows = await conn.fetch(
            """SELECT * FROM finance_payment_events
               WHERE room_id = $1 AND idempotency_key = ANY($2::text[])""",
            target_room_id, item_keys,
        )
        by_key = {r["idempotency_key"]: r for r in rows}

        student_rows = await conn.fetch(
            """SELECT S.id, S.student_no,
                      U.prefix, U.first_name, U.last_name, U.first_name_en, U.last_name_en
               FROM students S
               LEFT JOIN v_student_profiles U ON U.student_id = S.id
               WHERE S.id = ANY($1::bigint[]) AND S.room_id = $2""",
            student_ids, target_room_id,
        )
        by_student = {r["id"]: r for r in student_rows}

        events_payload: List[dict] = []
        total_received = Decimal("0")
        for sid, ikey in zip(student_ids, item_keys):
            row = by_key[ikey]
            event_result = await cls._build_event_result(conn, row, reused=True)
            events_payload.append({
                "student_id": sid,
                "student_name": (
                    cls._display_name(by_student[sid])
                    if sid in by_student else ""
                ),
                "event": event_result,
            })
            total_received += Decimal(str(row["amount_received"]))

        result = {
            "status": "success",
            "message": "รายการรับเงินรอบนี้เคยบันทึกแล้ว — แสดงผลเดิม",
            "reference_no": reference_no,
            "events": events_payload,
            "total_amount_received": f"{total_received:.2f}",
            "reused": True,
        }
        return result, None, None
