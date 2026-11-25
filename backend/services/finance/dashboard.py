"""📊 [FIN-V2 / P6.4] เงินของห้อง "ตอนนี้" (money ownership) — snapshot ปัจจุบัน

═══════════════════════════════════════════════════════════════════════════════
🎯 ตอบคำถามหลักของผู้ใช้ในหน้าเดียว: "ห้องมีเงินของตัวเองเท่าไหร่"
═══════════════════════════════════════════════════════════════════════════════
    เงินสดในกระเป๋า + เงินที่ผู้รับถืออยู่ = เงินสดรวม (total_cash)
    เงินสดรวม − เครดิตที่ห้องติดค้างนักเรียน = เงินของห้อง (net_room_money)

⚠️ **คนละความหมายกับ `/finance/summary`** — ตัวนั้นคิดตาม "งวดเดือน" และสลับ
   legacy/v2 ตาม CUTOFF_DATE ⇒ ห้ามยัดรวมกัน (ดูบันทึกการตัดสินใจข้อ 1 ของ brief)
   endpoint นี้เป็น snapshot ของ **บัดนี้** ไม่รับ month/year

🔴 กติกาสำคัญ
   1. `require_member` (ไม่ใช่ MANAGE_FINANCE) — แดชบอร์ดเปิดให้สมาชิกดูเพื่อความโปร่งใส
      ของกองทุนห้อง และข้อมูลที่ให้ไม่ลึกไปกว่าที่ `/finance/accounts` ให้อยู่แล้ว
   2. **ไม่ clamp** ค่าติดลบ — `net_room_money < 0` แปลว่าเครดิตเกินเงินสด (ข้อมูลผิด)
      ต้องเห็นบนจอ ไม่ใช่ซ่อน
   3. เครดิตคิดจาก `balance_after` ของแถวล่าสุดต่อคน **ห้าม `SUM(amount)`** — ตาราง
      `student_credits` เป็น append-only ledger ที่มีแถว `reverse` ปนอยู่
      (ดู `credits.py::_load_credit_balance`)
   4. ยอดค้างรับใช้ predicate + สูตร 3 พจน์เดียวกับ `get_receivables_aging` (P6.2)
      ⇒ `receivable_total` ต้องตรงกับ aging `grand_total` เป๊ะ
   5. อ่านทุกตัวใน transaction เดียว (repeatable read, read-only) เพื่อให้ตัวเลขทุกตัว
      มาจาก moment เดียวกัน — ไม่งั้นยอดกระเป๋ากับยอดค้างที่ต่างวินาทีอาจทำให้สมการดูผิด

📌 ไฟล์นี้อ่านอย่างเดียว — **ไม่มี journal, ไม่ยึด advisory lock** (ไม่เขียนเงิน)
   audit log เขียน **หลัง** ออกจาก read-only transaction (การ INSERT ใน read-only
   transaction จะล้มทันที)
"""
from __future__ import annotations

from typing import Optional

import asyncpg

from core.rbac import require_member

from .base import service_logger

_EPS = 0.005

# 🧭 ทางลัดบนแดชบอร์ด — **backend กำหนดว่ามีอะไรบ้าง** (อนาคตอาจกรองตามสิทธิ์/ลำดับ)
#    ส่วน FE ถือ route เพราะ backend ไม่ควรรู้ URL ของ SPA ⇒ action ที่ FE ไม่รู้จักถูกข้าม
QUICK_ACTIONS: tuple[str, ...] = ("receive", "expense", "income", "handover", "report")


class DashboardMixin:
    @classmethod
    async def get_money_ownership(
        cls, pool: asyncpg.Pool, *,
        client_source: str = "WEB_APP",
        actor_identifier: str = "system",
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """คืนยอดเงินของห้อง ณ ปัจจุบัน (อ่านอย่างเดียว, transaction เดียว)"""
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)

            async with conn.transaction(isolation="repeatable_read", readonly=True):
                # (a) กระเป๋าทั่วไป vs เงินที่ผู้รับถือ
                #     ⚠️ `is_custody` เป็น NOT NULL DEFAULT FALSE ⇒ ไม่ต้อง COALESCE
                #        (และห้าม COALESCE เพราะจะทำให้ planner ไม่ใช้ partial index)
                acc = await conn.fetchrow(
                    """
                    SELECT
                      COALESCE(SUM(A.balance) FILTER (WHERE NOT A.is_custody), 0) AS room_wallets,
                      COALESCE(SUM(A.balance) FILTER (WHERE A.is_custody), 0)     AS custody_held
                    FROM finance_accounts A
                    WHERE A.room_id = $1 AND A.deleted_at IS NULL
                    """,
                    target_room_id,
                )

                # (b) เครดิตติดค้างนักเรียน = `balance_after` ของแถวล่าสุดต่อคน
                credit_liability = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(L.balance_after), 0)
                    FROM (
                      SELECT DISTINCT ON (student_id) balance_after
                      FROM student_credits
                      WHERE room_id = $1 AND deleted_at IS NULL
                      ORDER BY student_id, id DESC
                    ) L
                    """,
                    target_room_id,
                )

                # (c) ยอดค้างรับ — สูตร 3 พจน์เดียวกับ aging (P6.2)
                #     ⚠️ `_open_bill_predicate()` อ้าง alias `SP`/`FC` ตรง ๆ
                receivable_total = await conn.fetchval(
                    f"""
                    SELECT COALESCE(SUM(
                             FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)
                           ), 0)
                    FROM student_payments SP
                    JOIN fee_collections FC ON FC.id = SP.collection_id
                    WHERE FC.room_id = $1
                      AND {cls._open_bill_predicate()}
                      AND (FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)) > {_EPS}
                    """,
                    target_room_id,
                )

                # (d) เงินที่ผู้รับแต่ละคนถือ — เฉพาะ custodial account ที่มีเจ้าของ
                #     (นิยาม "ผู้รับถือเงิน" ที่ตรวจสอบได้จากบัญชี ไม่ใช่เดาจากชื่อใน event)
                receivers = await conn.fetch(
                    """
                    SELECT A.owner_person_id AS receiver_id,
                           COALESCE(P.display_name, 'ไม่ระบุชื่อ') AS name,
                           A.balance AS held
                    FROM finance_accounts A
                    LEFT JOIN finance_people P
                           ON P.id = A.owner_person_id AND P.deleted_at IS NULL
                    WHERE A.room_id = $1 AND A.deleted_at IS NULL
                      AND A.is_custody AND A.owner_person_id IS NOT NULL
                    ORDER BY A.balance DESC, A.id ASC
                    """,
                    target_room_id,
                )

            # 🔢 Decimal จาก asyncpg → float() ก่อนคำนวณ/ปัด (กติกา repo)
            room_wallets = round(float(acc["room_wallets"] or 0), 2)
            custody_held = round(float(acc["custody_held"] or 0), 2)
            total_cash = round(room_wallets + custody_held, 2)
            credit_liab = round(float(credit_liability or 0), 2)
            receivable = round(float(receivable_total or 0), 2)
            # 🔴 ไม่ clamp — ติดลบคือสัญญาณว่าข้อมูลผิด ต้องเห็นบนจอ
            net_room_money = round(total_cash - credit_liab, 2)

            result = {
                "room_wallets": room_wallets,
                "custody_held": custody_held,
                "total_cash": total_cash,
                "credit_liability": credit_liab,
                "receivable_total": receivable,
                "net_room_money": net_room_money,
                "by_receiver": [
                    {
                        "receiver_id": int(r["receiver_id"]),
                        "name": r["name"],
                        "held": round(float(r["held"] or 0), 2),
                    }
                    for r in receivers
                ],
                "quick_actions": list(QUICK_ACTIONS),
            }

            # ⚠️ audit log **นอก** read-only transaction — INSERT ในนั้นจะล้มทันที
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                entity_type="MONEY_OWNERSHIP", entity_id=str(target_room_id),
                status="success",
                endpoint_or_command="FinanceService.get_money_ownership",
            )
        return result
