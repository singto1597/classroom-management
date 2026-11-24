"""🧾 เรียกเก็บเงินเองรายบุคคล — ครูกำหนดยอดต่อคนเองได้ในคำขอเดียว (Phase 6.5)

═══════════════════════════════════════════════════════════════════════════════
🎯 ใช้เมื่อไหร่
═══════════════════════════════════════════════════════════════════════════════
แคมเปญปกติมี **ยอดเดียวทั้งห้อง** (`fee_collections.amount`) — แต่ของจริงมักมี
"เก็บเฉพาะบางคน · คนละยอด" เช่น ค่าหนังสือที่เหลือ ยอดค้างเก่า ยอดต่างกันตามจำนวนชิ้น
⇒ endpoint นี้ให้ส่ง `items = [{student_id, amount, note}]` ครั้งเดียว

🧱 กลไก: 1 รายการ = 1 แคมเปญซ่อนรายคน (`collection_kind='project'`)
   - ใช้ยอดที่ **นักเรียนแต่ละคน** เพื่อให้ทุก query AR เดิม (`FC.amount - paid_amount`)
     ทำงานถูกต้องโดยไม่ต้องแก้ทั้งระบบ
   - ยังเป็น kind `project` (ไม่ใช่ `fine`) ⇒ ลง Dr 11001 / Cr รายได้ห้องปกติ
     และใช้ระบบชำระเงิน/ใบเสร็จ/เครดิตเดิมได้ครบ
   - แคมเปญที่เกิดจากที่นี่มี `idempotency_key` และตัวเลข/ข้อมูลจะโชว์ในลิสต์
     โปรเจกต์เก็บเงินตามปกติ (ครูเห็นความคืบหน้ารายคน)

🔁 กันกดซ้ำ: `idempotency_key` บังคับ (≥ 8 ตัวอักษร) และใช้ต่อแถวเป็น
   `"{key}:{student_id}"` ⇒ ยิงซ้ำด้วยคีย์เดิมได้ผลเดิม ไม่สร้างบิลซ้ำ
   (partial unique index `uq_fee_collections_idempotency`)
"""
from __future__ import annotations

import time
from typing import List

import asyncpg

from core.rbac import require_permission
from services.notification_service import notify_user

from .base import _lock_room_money, service_logger
from .constants import COLLECTION_KIND_PROJECT

# ยอดขั้นต่ำที่ถือว่าเป็นตัวเลขจริง (ตรงกับ _EPS ของโมดูลการเงิน)
_EPS = 0.005


class CustomChargesMixin:
    @classmethod
    async def create_custom_charges(
        cls,
        pool: asyncpg.Pool,
        *,
        room_id: int,
        req,
        user_id: int,
        client_source: str,
        actor_identifier: str,
    ) -> dict:
        """สร้างรายการเรียกเก็บเองหลายคน (ยอดต่างกันได้) ในคำขอเดียว

        คืน `{"status", "message", "collections": [...], "total_amount", "created"}`
        — `created = False` เมื่อคีย์ซ้ำ (คืนของเดิม ไม่สร้างใหม่)
        """
        start_time = time.time()

        async with pool.acquire() as conn:
            async with conn.transaction():
                await require_permission(conn, room_id, user_id, "MANAGE_FINANCE")
                # 🔒 คำสั่งแรกที่แตะเงินของห้อง = ยึด advisory lock (protocol ทั้งระบบ)
                await _lock_room_money(conn, room_id)

                # 🧮 รวมรายการซ้ำต่อคน + ตรวจยอด + ตรวจว่านักเรียนอยู่ในห้องจริง
                wanted: dict[int, dict] = {}
                for item in req.items:
                    sid = int(item.student_id)
                    amount = round(float(item.amount), 2)
                    if amount <= _EPS:
                        raise ValueError("ยอดที่เรียกเก็บต้องมากกว่า 0 บาท")
                    if sid in wanted:
                        # แถวซ้ำในคำขอเดียว — รวมยอดไว้ในรายการเดียว (ไม่สร้างสองบิล)
                        wanted[sid]["amount"] = round(wanted[sid]["amount"] + amount, 2)
                        continue
                    wanted[sid] = {
                        "student_id": sid,
                        "amount": amount,
                        "note": item.note,
                    }
                if not wanted:
                    raise ValueError("ต้องเลือกนักเรียนอย่างน้อย 1 คน")

                valid = await conn.fetch(
                    """SELECT id, user_id FROM students
                       WHERE room_id = $1 AND id = ANY($2::int[])
                         AND status = 'active' AND deleted_at IS NULL""",
                    room_id, list(wanted.keys()),
                )
                valid_map = {int(r["id"]): r["user_id"] for r in valid}
                missing = [sid for sid in wanted if sid not in valid_map]
                if missing:
                    raise ValueError("มีนักเรียนที่ไม่อยู่ในห้องนี้หรือไม่ active อยู่ในรายการ")

                collections: List[dict] = []
                created_count = 0
                total_amount = 0.0

                for sid, item in wanted.items():
                    row_key = f"{req.idempotency_key}:{sid}"
                    amount = item["amount"]
                    note = item["note"]
                    title = f"{req.title} · {note}" if note else req.title

                    collection_id = await conn.fetchval(
                        """INSERT INTO fee_collections
                               (room_id, title, amount, due_date, collection_kind,
                                idempotency_key)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT DO NOTHING
                           RETURNING id""",
                        room_id, title, amount, req.due_date,
                        COLLECTION_KIND_PROJECT, row_key,
                    )

                    if collection_id is None:
                        # 🔁 คีย์เดิมยิงซ้ำ — คืนแถวที่มีอยู่ ไม่สร้างบิลเพิ่ม
                        existing = await conn.fetchrow(
                            """SELECT id, title, amount FROM fee_collections
                               WHERE room_id = $1 AND idempotency_key = $2
                                 AND deleted_at IS NULL""",
                            room_id, row_key,
                        )
                        if existing is None:
                            # แพ้การแข่งกับคำขออื่นที่ยังไม่ commit — ถือว่าสำเร็จแบบไม่รู้ยอด
                            continue
                        collections.append({
                            "collection_id": int(existing["id"]),
                            "student_id": sid,
                            "amount": float(existing["amount"]),
                            "reused": True,
                        })
                        continue

                    payment_ids = await cls._create_bills_with_accrual(
                        conn,
                        room_id=room_id,
                        collection_id=collection_id,
                        student_ids=[sid],
                        amount=amount,
                        collection_kind=COLLECTION_KIND_PROJECT,
                        recorded_by=actor_identifier,
                        metadata={
                            "custom_charge_key": req.idempotency_key,
                            "custom_charge_note": note,
                        },
                    )

                    if valid_map.get(sid):
                        await notify_user(
                            conn, room_id=room_id, user_id=int(valid_map[sid]),
                            group_type="finance", type="collection_created",
                            title=f"มีรายการเรียกเก็บเงิน {amount:,.2f} บาท",
                            body=f"{title} · กำหนดชำระ {req.due_date.isoformat()}",
                            entity_type="fee_collection", entity_id=collection_id,
                            url="/finance/my-debts",
                        )

                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=room_id, user_id=user_id,
                        entity_type="FEE_COLLECTION", entity_id=str(collection_id),
                        status="success",
                        new_values={
                            "title": title,
                            "amount": amount,
                            "due_date": req.due_date.isoformat(),
                            "student_id": sid,
                            "idempotency_key": row_key,
                            "payment_ids": payment_ids,
                            "custom_charge": True,
                        },
                        endpoint_or_command="FinanceService.create_custom_charges",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                    created_count += 1
                    total_amount = round(total_amount + amount, 2)
                    collections.append({
                        "collection_id": int(collection_id),
                        "student_id": sid,
                        "amount": amount,
                        "reused": False,
                    })

        return {
            "status": "success",
            "message": (
                f"เรียกเก็บเองสำเร็จ {created_count} รายการ รวม {total_amount:,.2f} บาท"
                if created_count else "รายการนี้ถูกสร้างไปแล้ว (คีย์ซ้ำ) — ไม่ได้สร้างเพิ่ม"
            ),
            "collections": collections,
            "total_amount": total_amount,
            "created": created_count > 0,
        }
