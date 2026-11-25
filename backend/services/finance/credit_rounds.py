"""💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว (bulk credit offset)

═══════════════════════════════════════════════════════════════════════════════
หัวใจของ package นี้
═══════════════════════════════════════════════════════════════════════════════
1 รอบ = 1 transaction = **all-or-nothing**: ล้มคนเดียว = ไม่มีใครถูกหักเลย

- 1 นักเรียน = 1 `finance_payment_events` แบบ **credit-only**
  (`amount_received=0`, `credit_used=total_applied`, `credit_added=0`,
  `excess_action='none'`) + บรรทัด `credit_apply` ต่อบิล
- **ไม่มี REC/DEP/`finance_transactions`/journal ใหม่ และไม่แตะยอดกระเป๋า** —
  เงินเข้ามาตั้งแต่ตอนเติมเครดิต (ดู `credits.py` หัวไฟล์)
- รอบผูกด้วย `reference_no` ร่วม และ idempotency key ต่อคน
  `f"{key}:{student_id}"` (unique `(room_id, idempotency_key)` ของ P1.1)

═══════════════════════════════════════════════════════════════════════════════
🔑 กติกาที่ห้ามพลาด
═══════════════════════════════════════════════════════════════════════════════
1. **ตรวจ replay ก่อนสร้าง plan** — หลังรอบแรก บิลถูกปิด/เครดิตถูกใช้ ⇒ plan ใหม่
   จะว่างเปล่า ถ้าไปดู plan ก่อนจะเข้าใจผิดว่า "ไม่มีอะไรต้องทำ" แล้วสร้างรอบซ้ำ
2. **ห้ามสร้าง event ของคนที่ `total_applied=0`** — `chk_event_not_empty` จะ
   rollback ทั้งรอบ ⇒ กรองจาก plan ใต้ล็อก (ไม่ใช่จากที่ client ส่ง) และลบ event
   ที่ยังไม่มีบรรทัดถ้ายอดจริงกลายเป็นศูนย์กลางทาง
3. **ล็อกบิลทั้งชุดตาม id ก่อนแตะคนแรก** — ล็อกทีละคนตามลำดับ request จะเกิด
   วงรอบรอ ABBA กับ `batch_confirm_payments`
4. `_apply_plan_locked` (CreditsMixin) อ่านยอดเครดิต/บิลซ้ำใต้ล็อกอยู่แล้ว ⇒
   ใช้ยอดจริงจากผลลัพธ์ของมันเขียน event/lines ไม่ใช้ยอดจาก plan
5. ใช้ `_apply_plan_locked` ตัวเดียวกับ P2.1/P3.3 — **ห้ามเรียก `apply_credit`**
   (เส้น legacy ไม่มี event) และห้ามเขียนตรรกะหักเครดิตซ้ำที่นี่
"""
import json
import time
from typing import List, Optional

import asyncpg

from core.rbac import require_permission

from .allocation import assert_plan_equation, to_satang
from .base import _lock_payments_in_order, _lock_room_money, service_logger

_MAX_STUDENTS = 100
_MIN_KEY_LEN = 8
_MAX_KEY_LEN = 64
_SKIP_REASON = "ไม่มีบิลค้างหรือเครดิตไม่พอ"


class CreditRoundConflictError(ValueError):
    """คีย์รอบเดิมถูกใช้กับชุดนักเรียนต่างกัน → router ตอบ 409 (ไม่ใช่ 400)

    🔴 แยกจาก `ValueError` ธรรมดาเพราะผู้ใช้ไม่ได้กรอกข้อมูลผิด — เขากดซ้ำจาก
       หน้าจอเดิมที่ชุดนักเรียนเปลี่ยนไปแล้ว (หรือเปิดสองแท็บ) ⇒ ต้องโหลดใหม่
    """


class CreditRoundsMixin:
    # ================================================================ entry
    @classmethod
    async def create_credit_round(
        cls, pool: asyncpg.Pool, *, target_room_id: int, req, user_id: int,
        user_name: str, client_source: str, actor_identifier: str,
    ) -> dict:
        """หักเครดิตของนักเรียน N คนปิดบิล — atomic ทั้งรอบ คืนต่อคน 1 event"""
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # 🔒 RBAC → ล็อกห้อง **ก่อน** คำสั่งเขียนใด ๆ (contract
                    #    `test_every_money_path_takes_the_room_lock` อ่านจากซอร์ส
                    #    ของเมธอดนี้ ⇒ การล็อกต้องอยู่ที่นี่ ไม่ใช่ใน helper)
                    await require_permission(
                        conn, target_room_id, user_id, "MANAGE_FINANCE"
                    )
                    await _lock_room_money(conn, target_room_id)
                    result = await cls._credit_round_locked(
                        conn, target_room_id=target_room_id, req=req, user_id=user_id,
                        user_name=user_name, client_source=client_source,
                        actor_identifier=actor_identifier, start_time=start_time,
                    )
            # 📢 ไม่ publish Discord โดยเจตนา — ไม่มีเงินเคลื่อนไหวในรอบนี้
            return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE",
                        actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        user_id=user_id,
                        entity_type="PAYMENT_EVENT", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.create_credit_round",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise

    # ================================================================ locked
    @classmethod
    async def _credit_round_locked(
        cls, conn: asyncpg.Connection, *, target_room_id: int, req, user_id: int,
        user_name: str, client_source: str, actor_identifier: str, start_time: float,
    ) -> dict:
        """เนื้อใน transaction — **caller ถือ RBAC + `_lock_room_money` มาแล้ว**"""
        # 2) ตรวจ input (Pydantic บังคับไว้แล้ว — ตรวจซ้ำเพื่อเรียก service ตรง ๆ ปลอดภัย)
        student_ids = cls._normalize_student_ids(req.student_ids)
        key = (req.idempotency_key or "").strip()
        if not (_MIN_KEY_LEN <= len(key) <= _MAX_KEY_LEN):
            raise ValueError(
                f"รหัสกันส่งซ้ำ (idempotency_key) ต้องยาว "
                f"{_MIN_KEY_LEN}–{_MAX_KEY_LEN} ตัวอักษร"
            )
        note = (req.note or "").strip() or None
        requested_reference = (req.reference_no or "").strip() or None

        # 5) 🔁 replay ก่อนสร้าง plan — ต้องเห็น "รอบที่เคยสำเร็จ" ไม่ใช่ "plan ที่ว่างเปล่า"
        #    ใช้ prefix `key:` เพราะคีย์ต่อคนคือ `f"{key}:{student_id}"`
        replay_rows = await conn.fetch(
            """SELECT id, student_id, idempotency_key, total_applied, credit_used,
                      status, reference_no
               FROM finance_payment_events
               WHERE room_id = $1
                 AND left(idempotency_key, length($2) + 1) = $2 || ':' AND status = 'active'
               ORDER BY student_id""",
            target_room_id, key,
        )
        if replay_rows:
            found = {r["idempotency_key"] for r in replay_rows}
            expected = {f"{key}:{sid}" for sid in student_ids}
            if found != expected:
                raise CreditRoundConflictError(
                    "รหัสกันส่งซ้ำนี้เคยถูกใช้กับชุดนักเรียนอื่น — "
                    "โหลดรายชื่อใหม่แล้วทำรอบใหม่ด้วยรหัสใหม่"
                )
            return await cls._build_round_replay(
                conn, target_room_id=target_room_id, rows=replay_rows,
                student_ids=student_ids, requested_reference=requested_reference,
            )

        # 6) ผู้รับ/ผู้บันทึก — person ชนะชื่อที่ client ส่ง (กฎเดียวกับ P2.1)
        receiver_person_id = req.receiver_person_id
        receiver_name = (user_name or "").strip() or "—"
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

        # 7) กระเป๋าอ้างอิงของ event (NOT NULL) — **ไม่แตะยอด** เพียงบันทึกว่าอ้างถึงไหน
        wallet_account_id = await cls._resolve_round_wallet(
            conn, target_room_id=target_room_id, requested=req.wallet_account_id,
        )

        # 8) plan ใต้ล็อก — ตัวเดียวกับ preview (สัญญา "สิ่งที่เห็น = สิ่งที่ทำ")
        plan = await cls._build_plan_for_students(
            conn, target_room_id=target_room_id, student_ids=student_ids,
        )
        student_names = {
            int(item["student_id"]): item.get("student_name") or "" for item in plan["items"]
        }

        # 9) ล็อกบิลทั้งหมดตาม id ที่เรียงแล้ว **ก่อน** แตะคนแรก
        bill_ids = [a["payment_id"] for item in plan["items"] for a in item["allocations"]]
        await _lock_payments_in_order(conn, bill_ids)

        # 10) ต่อคนตามลำดับที่ client ส่ง
        events: List[dict] = []
        skipped: List[dict] = []
        event_ids: List[int] = []
        total_applied = 0.0

        for item in plan["items"]:
            student_id = int(item["student_id"])
            if not item["allocations"]:
                skipped.append({
                    "student_id": student_id,
                    "student_name": student_names.get(student_id, ""),
                    "reason": _SKIP_REASON,
                })
                continue

            planned_total = round(float(item["total_applied"]), 2)
            event_row = await conn.fetchrow(
                """INSERT INTO finance_payment_events
                       (room_id, student_id, payer_name, receiver_person_id,
                        receiver_name, wallet_account_id, amount_received,
                        credit_used, credit_added, total_applied, excess_action,
                        reference_no, note, idempotency_key, event_at)
                   VALUES ($1, $2, 'ใช้เครดิต', $3, $4, $5, 0, $6, 0, $6, 'none',
                           $7, $8, $9, CURRENT_TIMESTAMP)
                   RETURNING id""",
                target_room_id, student_id, receiver_person_id, receiver_name,
                wallet_account_id, planned_total, requested_reference, note,
                f"{key}:{student_id}",
            )
            event_id = int(event_row["id"])

            executed = await cls._apply_plan_locked(
                conn, target_room_id=target_room_id,
                plan={"items": [item]}, user_name=receiver_name,
                actor_identifier=actor_identifier, client_source=client_source,
                payment_event_id=event_id,
            )
            actual = executed["items"][0] if executed["items"] else None
            actual_total = round(float(actual["total_applied"]), 2) if actual else 0.0

            # ⚖️ ยอดจริงเป็นศูนย์ (บิลถูกปิดไปก่อนหน้า / เครดิตถูกใช้ไปแล้ว)
            #    ⇒ event นี้ยังไม่มีบรรทัด/เอกสารอ้างถึง ลบได้อย่างปลอดภัย
            if actual is None or actual_total <= 0:
                await conn.execute(
                    "DELETE FROM finance_payment_events WHERE id = $1", event_id
                )
                skipped.append({
                    "student_id": student_id,
                    "student_name": student_names.get(student_id, ""),
                    "reason": _SKIP_REASON,
                })
                continue

            await conn.execute(
                """UPDATE finance_payment_events
                   SET credit_used = $1, total_applied = $1
                   WHERE id = $2""",
                actual_total, event_id,
            )

            line_amounts_stang: List[int] = []
            credit_entry_ids: List[int] = []
            for alloc in actual["allocations"]:
                apply_amount = round(float(alloc["apply_amount"]), 2)
                before = round(float(alloc["bill_remaining_before"]), 2)
                after = round(before - apply_amount, 2)
                credit_entry_id = alloc.get("credit_entry_id")
                if credit_entry_id is None:
                    raise ValueError(
                        "บันทึกการหักเครดิตไม่สมบูรณ์ — ยกเลิกรอบนี้แล้วลองใหม่"
                    )
                await conn.execute(
                    """INSERT INTO finance_payment_event_lines
                           (event_id, line_kind, student_payment_id,
                            finance_transaction_id, credit_entry_id, amount,
                            bill_amount_before, bill_amount_after, meta)
                       VALUES ($1, 'credit_apply', $2, NULL, $3, $4, $5, $6, $7::jsonb)""",
                    event_id, alloc["payment_id"], credit_entry_id,
                    apply_amount, before, after,
                    cls._round_line_meta(
                        student_id=student_id, alloc=alloc,
                    ),
                )
                line_amounts_stang.append(to_satang(apply_amount))
                credit_entry_ids.append(int(credit_entry_id))

            # 11) สมการของ event นี้: 0 + credit_used = total_applied + 0
            assert_plan_equation({
                "amount_received_stang": 0,
                "credit_used_stang": to_satang(actual_total),
                "total_applied_stang": to_satang(actual_total),
                "credit_added_stang": 0,
                "allocations": [{"amount_stang": s} for s in line_amounts_stang],
            })

            events.append({
                "student_id": student_id,
                "student_name": student_names.get(student_id, ""),
                "event_id": event_id,
                "total_applied": actual_total,
                "credit_used": actual_total,
                "balance_after": round(float(actual["balance_after"]), 2),
                "credit_entry_ids": credit_entry_ids,
            })
            event_ids.append(event_id)
            total_applied = round(total_applied + actual_total, 2)

        if not events:
            raise ValueError("ไม่มีนักเรียนคนใดมีบิลค้างให้หักเครดิตในรอบนี้")

        # 12) audit ระดับรอบ 1 ครั้ง — core log ต่อแถวเครดิตอยู่ใน `_apply_plan_locked`
        await service_logger.log(
            conn=conn, action="UPDATE",
            actor_identifier=actor_identifier, client_source=client_source,
            room_id=target_room_id, user_id=user_id,
            entity_type="PAYMENT_EVENT", entity_id=str(event_ids[0]),
            status="success",
            new_values={
                "reference_no": requested_reference,
                "student_count": len(events),
                "total_applied": f"{total_applied:.2f}",
                "event_ids": event_ids,
            },
            endpoint_or_command="FinanceService.create_credit_round",
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

        # 13) คืนผล — `total_balance_after` จาก **ทุกคนใน plan** (รวม skipped)
        return {
            "reused": False,
            "reference_no": requested_reference,
            "events": events,
            "skipped": skipped,
            "total_applied": total_applied,
            "total_balance_after": round(float(plan["total_balance_after"]), 2),
        }

    # ================================================================ replay
    @classmethod
    async def _build_round_replay(
        cls, conn: asyncpg.Connection, *, target_room_id: int, rows: List[asyncpg.Record],
        student_ids: List[int], requested_reference: Optional[str],
    ) -> dict:
        """คืนผลเดิมของรอบนี้ (ไม่เขียนอะไรเลย) — `reused=true`"""
        event_ids = [int(r["id"]) for r in rows]
        line_rows = await conn.fetch(
            """SELECT L.event_id, L.credit_entry_id, C.balance_after
               FROM finance_payment_event_lines L
               LEFT JOIN student_credits C ON C.id = L.credit_entry_id
               WHERE L.event_id = ANY($1::bigint[]) AND L.line_kind = 'credit_apply'
               ORDER BY L.event_id, L.id""",
            event_ids,
        )
        entries_by_event: dict[int, dict] = {}
        for row in line_rows:
            bucket = entries_by_event.setdefault(
                int(row["event_id"]), {"ids": [], "balance_after": 0.0}
            )
            bucket["ids"].append(int(row["credit_entry_id"]))
            # แถวสุดท้ายของ event = ยอดคงเหลือหลังหักครบของคนนั้น
            bucket["balance_after"] = round(float(row["balance_after"] or 0), 2)

        students = await cls._load_students_in_room(
            conn, target_room_id=target_room_id, student_ids=student_ids,
        )
        by_student = {int(r["student_id"]): r for r in rows}

        events: List[dict] = []
        skipped: List[dict] = []
        total_applied = 0.0
        total_balance_after = 0.0
        stored_reference: Optional[str] = None

        for sid in student_ids:
            name = (students.get(sid) or {}).get("display_name", "")
            row = by_student.get(sid)
            if row is None:
                skipped.append({
                    "student_id": sid, "student_name": name, "reason": _SKIP_REASON,
                })
            else:
                bucket = entries_by_event.get(int(row["id"]), {"ids": [], "balance_after": 0.0})
                applied = round(float(row["total_applied"]), 2)
                events.append({
                    "student_id": sid,
                    "student_name": name,
                    "event_id": int(row["id"]),
                    "total_applied": applied,
                    "credit_used": round(float(row["credit_used"]), 2),
                    "balance_after": bucket["balance_after"],
                    "credit_entry_ids": bucket["ids"],
                })
                total_applied = round(total_applied + applied, 2)
                if stored_reference is None and row["reference_no"]:
                    stored_reference = row["reference_no"]
            # ยอดคงเหลือปัจจุบันของทุกคน (รวม skipped) — ตรงกับความหมายของ fresh path
            total_balance_after = round(
                total_balance_after + await cls._load_credit_balance(
                    conn, room_id=target_room_id, student_id=sid,
                ),
                2,
            )

        return {
            "reused": True,
            "reference_no": stored_reference or requested_reference,
            "events": events,
            "skipped": skipped,
            "total_applied": total_applied,
            "total_balance_after": total_balance_after,
        }

    # ================================================================ helpers
    @staticmethod
    def _normalize_student_ids(raw: List[int]) -> List[int]:
        """ตรวจ 1–100 คน ไม่ซ้ำ — รักษาลำดับที่ client ส่ง"""
        unique: List[int] = []
        seen: set[int] = set()
        for value in raw or []:
            sid = int(value)
            if sid in seen:
                raise ValueError("มีนักเรียนซ้ำในรอบเดียวกัน — เลือกได้คนละหนึ่งครั้ง")
            seen.add(sid)
            unique.append(sid)
        if not unique:
            raise ValueError("กรุณาเลือกนักเรียนอย่างน้อย 1 คน")
        if len(unique) > _MAX_STUDENTS:
            raise ValueError(f"หักเครดิตได้ครั้งละไม่เกิน {_MAX_STUDENTS} คน")
        return unique

    @classmethod
    async def _resolve_round_wallet(
        cls, conn: asyncpg.Connection, *, target_room_id: int,
        requested: Optional[int],
    ) -> int:
        """กระเป๋าอ้างอิงของ event — primary cash → cash id น้อยสุด → 400

        🔴 **ไม่แตะ `balance`** — เครดิตไม่ใช่เงินสด การปรับยอดที่นี่จะทำให้เงินงอก
        """
        if requested is not None:
            ok = await conn.fetchval(
                """SELECT id FROM finance_accounts
                   WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                requested, target_room_id,
            )
            if not ok:
                raise ValueError("ไม่พบกระเป๋าเงินนี้ในห้อง (หรือถูกลบไปแล้ว)")
            return int(ok)

        primary = await conn.fetchval(
            """SELECT id FROM finance_accounts
               WHERE room_id = $1 AND is_primary AND account_kind = 'cash'
                 AND deleted_at IS NULL
               ORDER BY id LIMIT 1""",
            target_room_id,
        )
        if primary is not None:
            return int(primary)

        fallback = await conn.fetchval(
            """SELECT id FROM finance_accounts
               WHERE room_id = $1 AND account_kind = 'cash' AND deleted_at IS NULL
               ORDER BY id LIMIT 1""",
            target_room_id,
        )
        if fallback is None:
            raise ValueError(
                "ยังไม่มีกระเป๋าเงินสดในห้อง — สร้างกระเป๋าเงินก่อนจึงจะหักเครดิตได้"
            )
        return int(fallback)

    @staticmethod
    def _round_line_meta(*, student_id: int, alloc: dict) -> str:
        """meta ของบรรทัด `credit_apply` — รูปเดียวกับ P2.1 (`source='credit'`)"""
        return json.dumps(
            {
                "collection_id": alloc.get("collection_id"),
                "title": alloc.get("title"),
                "source": "credit",
                "student_id": student_id,
            },
            ensure_ascii=False,
        )
