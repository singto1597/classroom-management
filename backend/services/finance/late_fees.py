"""⏰ ค่าปรับจ่ายล่าช้าแบบอัตโนมัติ (Phase 6.5)

═══════════════════════════════════════════════════════════════════════════════
🎯 หลักการ
═══════════════════════════════════════════════════════════════════════════════
1. **นโยบายอยู่ที่แคมเปญ ไม่ใช่ที่ระบบ** — `fee_collections.late_fee_mode`
   (`none`/`fixed`/`percent`) + `late_fee_amount` + `late_fee_grace_days`
   ⇒ ครูกำหนดเองได้ต่อโปรเจกต์ และโปรเจกต์เดิมทั้งหมดเป็น `none` (ไม่เปลี่ยนพฤติกรรม)
2. **ออกค่าปรับผ่านเครื่องจักรเดิมทั้งหมด** — โปรเจกต์ซ่อน (`collection_kind='fine'`)
   + บิล + accrual (Dr 11002 / Cr 49001) + INV- 1 ใบ/บิล + แจ้งเตือนในแอป
   ⇒ ค่าปรับล่าช้าใช้ระบบชำระเงิน/เครดิต/ยกเว้น/คืนเงินเดิมได้ทันที ไม่มีทางรับเงินที่สอง
3. **1 บิลต้นทาง = 1 ค่าปรับล่าช้า ตลอดชีพ** — unique index `uq_fines_late_fee_source`
   (migration 0011) ⇒ worker รันซ้ำ/หลายรอบ/หลาย replica ไม่สร้างซ้ำ
   ⚠️ ถ้าครูยกเลิกค่าปรับที่ระบบออกไปแล้ว **ระบบจะไม่ออกใหม่** (ต้องออกด้วยมือ)
      — เงื่อนไขกันซ้ำใช้ index แบบไม่มี `status` เพื่อไม่ให้เกิดลูป "ยกเลิกแล้วออกใหม่ทุกวัน"
4. **ยอดคิดจากยอดคงเหลือ ณ วันที่ออก** ไม่ใช่ยอดเต็มของบิล:
   `percent` = `%` ของ `FC.amount - paid_amount` · `fixed` = จำนวนคงที่
   ⇒ จ่ายไปบางส่วนแล้วค่าปรับไม่เกินยอดที่ยังค้าง
5. **เงื่อนไขเวลา**: `due_date + grace_days < วันนี้` (ผ่อนผันเต็มจำนวนวันแล้ว)
   ⇒ grace 0 = ปรับเมื่อเลยกำหนด 1 วันเต็ม ไม่ใช่ตอนเที่ยงคืนของวันครบกำหนด

🧾 ผู้ทำรายการใน audit = "ระบบ (ค่าปรับล่าช้าอัตโนมัติ)" และ `fines.auto_late_fee=TRUE`
   ⇒ แยกออกจากค่าปรับที่ครูออกได้ในรายงาน/หน้าจอ
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import asyncpg

from services.action_service import ActionService
from services.notification_service import notify_user

from .base import _lock_room_money, service_logger
from .constants import (
    COLLECTION_KIND_FINE,
    COLLECTION_KIND_PROJECT,
    FINE_STATUS_ISSUED,
    LATE_FEE_DUE_DAYS,
    LATE_FEE_FINE_TYPE_NAME,
    LATE_FEE_MODE_FIXED,
    LATE_FEE_MODE_PERCENT,
)

# ผู้ทำรายการของค่าปรับที่ระบบสร้าง (แยกจากชื่อครูใน audit log)
SYSTEM_ACTOR = "ระบบ (ค่าปรับล่าช้าอัตโนมัติ)"

# ยอดเล็กกว่านี้ถือว่าเป็นศูนย์ — ตรงกับ _EPS ของโมดูลการเงิน
_EPS = 0.005


class LateFeesMixin:
    # ─────────────────────────────────────────────────────────────────────────
    # อ่าน/คำนวณ (ไม่มี side effect — เทสต์เรียกตรงได้)
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    async def _collect_late_fee_candidates(
        cls,
        conn: asyncpg.Connection,
        *,
        as_of: date,
        room_id: Optional[int] = None,
    ) -> list:
        """บิลเปิดที่เลยกำหนด + ผ่อนผันครบแล้ว + ยังไม่มีค่าปรับล่าช้า

        ⚠️ `NOT EXISTS (... fines.source_payment_id ...)` เป็นการกรองเพื่อ **ลดงาน**
           เท่านั้น — ด่านกันซ้ำจริงคือ unique index (ระหว่างสอง worker ไม่มีใครเห็นกัน)
        """
        # $1 = as_of · $2 = eps · $3 = kind · ($4 = room_id ถ้าระบุ)
        params: list = [as_of, _EPS, COLLECTION_KIND_PROJECT]
        room_clause = ""
        if room_id is not None:
            params.append(room_id)
            room_clause = f"AND FC.room_id = ${len(params)}"

        return await conn.fetch(
            f"""
            SELECT FC.room_id,
                   SP.id AS payment_id,
                   SP.student_id,
                   S.user_id,
                   S.student_no,
                   FC.id AS collection_id,
                   FC.title,
                   FC.amount,
                   FC.due_date,
                   FC.late_fee_mode,
                   FC.late_fee_amount,
                   FC.late_fee_grace_days,
                   COALESCE(SP.paid_amount, 0) AS paid_amount,
                   (FC.amount - COALESCE(SP.paid_amount, 0)) AS outstanding
            FROM student_payments SP
            JOIN fee_collections FC ON FC.id = SP.collection_id
            JOIN students S ON S.id = SP.student_id AND S.deleted_at IS NULL
            WHERE {cls._open_bill_predicate()}
              AND FC.collection_kind = $3
              AND FC.late_fee_mode <> 'none'
              AND FC.due_date IS NOT NULL
              AND FC.due_date + (FC.late_fee_grace_days || ' days')::interval < $1::date
              AND (FC.amount - COALESCE(SP.paid_amount, 0)) > $2
              AND NOT EXISTS (
                    SELECT 1 FROM fines F
                     WHERE F.source_payment_id = SP.id AND F.deleted_at IS NULL
              )
              {room_clause}
            ORDER BY FC.room_id, S.student_no, SP.id
            """,
            *params,
        )

    @staticmethod
    def _compute_late_fee_amount(row) -> float:
        """ยอดค่าปรับของบิลนี้ (0 = ไม่ต้องออก) — ใช้ยอดคงเหลือเป็นฐานของ `percent`"""
        outstanding = round(float(row["outstanding"]), 2)
        if outstanding <= _EPS:
            return 0.0
        rate = float(row["late_fee_amount"] or 0)
        if row["late_fee_mode"] == LATE_FEE_MODE_FIXED:
            amount = rate
        elif row["late_fee_mode"] == LATE_FEE_MODE_PERCENT:
            amount = outstanding * rate / 100.0
        else:
            return 0.0
        amount = round(min(amount, outstanding), 2)
        return amount if amount > _EPS else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # ออกจริง — เรียกจาก worker วันละครั้ง (ปลอดภัยต่อการเรียกซ้ำ)
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    async def apply_late_fees(
        cls,
        pool: asyncpg.Pool,
        *,
        as_of: date,
        room_id: Optional[int] = None,
    ) -> dict:
        """ออกค่าปรับล่าช้าให้ทุกบิลที่เข้าเงื่อนไขของวัน `as_of`

        🧱 **ทีละห้องใน transaction ของตัวเอง** — ห้องที่ข้อมูลเพี้ยน (เช่น ledger
           ชนกัน) ต้องไม่ทำให้ห้องอื่นไม่ได้ออกค่าปรับเลย · ภายในห้องใช้ savepoint
           ต่อบิล เพื่อให้บิลเดียวล้ม (เช่นแพ้ unique index) ไม่ล้มทั้งห้อง

        คืนสถิติ: `issued` / `skipped` / `total_amount` / `rooms`
        """
        stats = {
            "as_of": as_of.isoformat(),
            "issued": 0,
            "skipped": 0,
            "total_amount": 0.0,
            "rooms": 0,
        }

        async with pool.acquire() as conn:
            candidates = await cls._collect_late_fee_candidates(
                conn, as_of=as_of, room_id=room_id
            )
            if not candidates:
                return stats

            by_room: dict[int, list] = {}
            for row in candidates:
                by_room.setdefault(int(row["room_id"]), []).append(row)
            stats["rooms"] = len(by_room)

            for rid, rows in by_room.items():
                issued_rows: list = []
                room_total = 0.0
                async with conn.transaction():
                    # 🔒 คำสั่งแรกใน transaction ของห้องเสมอ (protocol ทั้งระบบ)
                    await _lock_room_money(conn, rid)
                    due_date = as_of + timedelta(days=LATE_FEE_DUE_DAYS)
                    for row in rows:
                        amount = cls._compute_late_fee_amount(row)
                        if amount <= 0:
                            stats["skipped"] += 1
                            continue
                        try:
                            async with conn.transaction():
                                await cls._issue_one_late_fee(
                                    conn,
                                    row=row,
                                    amount=amount,
                                    as_of=as_of,
                                    due_date=due_date,
                                )
                        except asyncpg.UniqueViolationError:
                            # ⚔️ แพ้การแข่งกับ worker อีกตัว/รอบก่อน — ถือว่าออกแล้ว
                            stats["skipped"] += 1
                            continue
                        stats["issued"] += 1
                        stats["total_amount"] = round(
                            stats["total_amount"] + amount, 2
                        )
                        room_total = round(room_total + amount, 2)
                        issued_rows.append(row)

                    if issued_rows:
                        server_id = await cls._get_room_server_id(conn, rid)
                    else:
                        server_id = None

                # 📢 publish หลัง commit เท่านั้น (ยอดต่อห้อง ไม่ใช่ยอดรวมทุกห้อง)
                if server_id and issued_rows:
                    await ActionService.notify_fines_issued(
                        server_id,
                        fine_type_name=LATE_FEE_FINE_TYPE_NAME,
                        student_count=len(issued_rows),
                        total_amount=room_total,
                        due_date=due_date,
                        user_name=SYSTEM_ACTOR,
                    )

        return stats

    @classmethod
    async def _issue_one_late_fee(
        cls,
        conn: asyncpg.Connection,
        *,
        row,
        amount: float,
        as_of: date,
        due_date: date,
    ) -> None:
        """สร้างค่าปรับล่าช้า 1 ใบ (โปรเจกต์ซ่อน + บิล + accrual + INV- + แจ้งเตือน)

        ⚠️ ผู้เรียกต้องถือ `_lock_room_money` และอยู่ภายใน transaction (หรือ savepoint)
        """
        room_id = int(row["room_id"])
        student_id = int(row["student_id"])
        source_payment_id = int(row["payment_id"])
        reason = (
            f"ชำระล่าช้าเกินกำหนด · {row['title']} "
            f"(ครบกำหนด {row['due_date'].isoformat()})"
        )
        title = f"{LATE_FEE_FINE_TYPE_NAME} · {row['title']}"

        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, collection_kind)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            room_id, title, amount, due_date, COLLECTION_KIND_FINE,
        )
        payment_ids = await cls._create_bills_with_accrual(
            conn,
            room_id=room_id,
            collection_id=collection_id,
            student_ids=[student_id],
            amount=amount,
            collection_kind=COLLECTION_KIND_FINE,
            recorded_by=SYSTEM_ACTOR,
            metadata={"late_fee_source_payment_id": source_payment_id},
        )
        payment_id = payment_ids[0]

        fine_id = await conn.fetchval(
            """INSERT INTO fines
                   (room_id, fine_type_name, student_id, hidden_collection_id,
                    student_payment_id, incident_date, due_date, reason,
                    original_amount, amount, status, source_payment_id,
                    auto_late_fee, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,TRUE,NULL)
               RETURNING id""",
            room_id, LATE_FEE_FINE_TYPE_NAME, student_id, collection_id,
            payment_id, as_of, due_date, reason, amount, amount,
            FINE_STATUS_ISSUED, source_payment_id,
        )
        # ⚠️ `user_id=None` — ใบนี้ "ระบบ" เป็นผู้ออก ไม่มี user จริงให้ FK ชี้
        #    (ส่ง 0 จะชน FK `finance_receipts_issued_by_fkey`)
        inv = await cls._issue_fine_invoice(
            conn, room_id=room_id, payment_id=payment_id, fine_id=fine_id,
            fine_type_name=LATE_FEE_FINE_TYPE_NAME, incident_date=as_of,
            due_date=due_date, reason=reason, amount=amount,
            user_id=None, user_name=SYSTEM_ACTOR, issued_at_db=None,
        )
        await conn.execute(
            "UPDATE fines SET invoice_receipt_id = $1 WHERE id = $2",
            inv["id"], fine_id,
        )

        # 🔔 แจ้งเจ้าของบิล (ถ้าผูกบัญชี) — ระบบเป็นผู้ออก จึงไม่มี "ผู้ขอ" ให้ยกเว้น
        if row["user_id"]:
            await notify_user(
                conn, room_id=room_id, user_id=int(row["user_id"]),
                group_type="finance", type="fine_issued",
                title=f"มีค่าปรับจ่ายล่าช้า {amount:,.2f} บาท",
                body=f"{row['title']} · {reason}",
                entity_type="fine", entity_id=fine_id,
                url=f"/finance/fines/{fine_id}",
            )

        await service_logger.log(
            conn=conn, action="CREATE", actor_identifier=SYSTEM_ACTOR,
            client_source="SYSTEM", room_id=room_id, user_id=None,
            entity_type="FINE", entity_id=str(fine_id), status="success",
            new_values={
                "auto_late_fee": True,
                "source_payment_id": source_payment_id,
                "collection_id": row["collection_id"],
                "amount": amount,
                "late_fee_mode": row["late_fee_mode"],
                "late_fee_rate": float(row["late_fee_amount"] or 0),
                "invoice_no": inv["receipt_no"],
            },
            endpoint_or_command="FinanceService.apply_late_fees",
            execution_time_ms=0,
        )
