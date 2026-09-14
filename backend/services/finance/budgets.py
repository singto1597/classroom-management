"""งบประมาณรายหมวด/รายงวด (finance_budgets) — F2

═══════════════════════════════════════════════════════════════════════════════
[ERA ROUTING] อ่าน `finance_transactions` เป็นหลัก — **ตรงข้ามกับ F1 โดยเจตนา**
═══════════════════════════════════════════════════════════════════════════════
F1 (งบการเงิน)  อ่าน `journal_lines` ล้วน แล้ว **clamp** ที่ CUTOFF_DATE
F2 (งบประมาณ)   อ่าน `finance_transactions` ล้วน แล้ว **ไม่ clamp**

เหตุผลที่อ่านตารางนี้แล้วไม่นับซ้ำ ทั้งที่ dual-write เขียนสองที่:

1. `finance_transactions` **ไม่ใช่ตาราง legacy-only** — มันคือ mirror ที่ครบทั้งสองยุค
   `add_transaction` / `transfer_money` / `_confirm_single_payment` เขียนทั้งแถว legacy
   **และ** journal ใน `conn.transaction()` เดียวกัน
   (ยืนยันด้วย `grep -rn "INSERT INTO finance_transactions" backend/` → มี 3 จุดในโปรดักชัน
    ทั้งสาม dual-write ครบ ไม่มีรู)
2. `revert_transaction` mark **ทั้งสองฝั่ง** พร้อมกัน (`deleted_at = NOW()` คู่กับ `status='voided'`)
   ⇒ เงื่อนไข `deleted_at IS NULL` ฝั่ง legacy สอดคล้องกับฝั่ง journal อยู่แล้ว
   ⇒ **อ่านทั้งสองฝั่ง = นับซ้ำเป็น 2 เท่า** (มีเทสต์บังคับพิสูจน์ `used == Y` ไม่ใช่ `2Y`)
3. ช่วงก่อน cutoff มีแถว legacy อยู่แล้ว ช่วงหลัง dual-write ใส่ให้ คร่อมเส้นก็ไม่มีรู
   ⇒ **ไม่ต้อง clamp** (ต่างจาก F1 ที่ journal ไม่มีข้อมูลยุค legacy ให้อ่านเลย)
4. `opening_balance` และ `adjustment` ของ reconcile **ไม่มีแถวในตารางนี้** → ถูกตัดออกเอง
   โดยธรรมชาติ (ถูกต้อง เพราะไม่ใช่การใช้จ่ายจริง)

⚠️ **ห้าม refactor ให้ F1 กับ F2 ใช้ helper ร่วมกัน** — era assumption คนละขั้ว
   ยุบรวมเมื่อไหร่จะได้ assumption ผิดติดไปด้วยกันทั้งคู่
"""
import asyncpg
import time
from datetime import date, timedelta
from typing import List, Optional, Tuple

from core.exceptions import RoomNotFoundError
from core.rbac import require_permission, require_member

from .base import _lock_room_money, service_logger


def _last_day_of_month(d: date) -> date:
    """วันสุดท้ายของเดือนที่ d อยู่ — ใช้ตัดสินว่า range หนึ่ง ๆ คือ 'รายเดือน' หรือไม่."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


# =====================================================================================
# [TIMEZONE] นิพจน์ขอบเขตวันไทยสำหรับ query ของงบประมาณ
# =====================================================================================
# ขอบเขตวันไทยเทียบกับคอลัมน์คนละชนิดกัน จึงต้องมี 2 รูป (ดู helpers บล็อก [TIMEZONE]):
#
#   (ก) `finance_transactions.created_at` = TIMESTAMP **naive ที่เก็บเวลา UTC**
#       → `AT TIME ZONE 'Asia/Bangkok' AT TIME ZONE 'UTC'` = "ต้นวันไทย เขียนเป็น UTC wall-clock"
#         ซึ่งเทียบกับคอลัมน์ได้ตรง ๆ และ **ยังใช้ index ของ created_at ได้** เพราะเป็น
#         การเทียบช่วงบนคอลัมน์เปล่า (ไม่ห่อฟังก์ชันไว้ฝั่งคอลัมน์)
#       → ห้ามใช้ `T.created_at::date` เด็ดขาด: นั่นให้ "วันที่แบบ UTC" ซึ่งเป็นคนละปฏิทิน
#         กับเวลาไทย รายการที่บันทึก 00:00–07:00 น. ไทยจะถูกนับเป็นวันก่อนหน้า
#         ⇒ งบรายเดือนกินรายจ่ายข้ามเดือนเงียบ ๆ
#
#   (ข) `journal_entries.transaction_date` = TIMESTAMPTZ (aware)
#       → `AT TIME ZONE 'Asia/Bangkok'` ตัวเดียวพอ ได้ timestamptz ต้นวันไทยตรง ๆ
#
# ⚠️ `AT TIME ZONE 'Asia/Bangkok'` ในนิพจน์ SQL **ไม่ใช่**การแก้ TimeZone ของ Postgres
#    (ไม่แตะ session/DB setting) — เป็นการแปลงรายนิพจน์ ซึ่งคนละเรื่องกับข้อห้ามของผู้ใช้
#
# 💡 ทำไมขอบเขตมาจาก "คอลัมน์ของ B" แทนที่จะ unwrap ฝั่ง parameter แบบที่อื่น:
#    เพราะใน `get_budget_overview` แต่ละงบมีช่วงของตัวเอง (ต้อง clamp ด้วย GREATEST/LEAST
#    กับช่วงที่ผู้ใช้กรอง) ⇒ ไม่มีค่า param เดียวให้ unwrap ได้ ต้องคำนวณในนิพจน์
#    ผลลัพธ์เทียบเท่า `_thai_day_start`/`_thai_next_day_start` เป๊ะ
#    และใช้ขอบบนแบบ **half-open `<`** เพื่อไม่ให้รายการวินาทีสุดท้ายของวันหลุด
_LEGACY_LO = "((GREATEST(B.start_date, $2)::timestamp) AT TIME ZONE 'Asia/Bangkok' AT TIME ZONE 'UTC')"
_LEGACY_HI = "(((LEAST(B.end_date, $3) + 1)::timestamp) AT TIME ZONE 'Asia/Bangkok' AT TIME ZONE 'UTC')"
_JOURNAL_LO = "((GREATEST(B.start_date, $2)::timestamp) AT TIME ZONE 'Asia/Bangkok')"
_JOURNAL_HI = "(((LEAST(B.end_date, $3) + 1)::timestamp) AT TIME ZONE 'Asia/Bangkok')"


# คอลัมน์ที่อนุญาตให้ PATCH แก้ได้ (whitelist — กัน client ยัด `room_id`/`deleted_at` เข้ามา)
_BUDGET_PATCHABLE = ("amount", "start_date", "end_date", "note")


class BudgetsMixin:
    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _derive_period(start: date, end: date) -> Tuple[str, int, Optional[int]]:
        """แปลงช่วงวันที่ materialized → (period_type, period_year, period_month).

        [DESIGN] derive จาก `start_date`/`end_date` **เสมอ** ไม่รับจาก client
        ⇒ เป็นไปไม่ได้ที่ป้าย "ก.ย. 2569" จะขัดกับตัวเลขที่คิดจากช่วงจริง
          (ถ้ารับจาก client แล้วมีคน PATCH วันที่ทีหลัง ป้ายจะค้างอยู่ที่เดือนเดิมเงียบ ๆ)
        """
        if start.day == 1:
            if end == _last_day_of_month(start):
                return "monthly", start.year, start.month
            if start.month == 1 and end == date(start.year, 12, 31):
                return "yearly", start.year, None
        return "custom", start.year, None

    @staticmethod
    def _to_float(v) -> float:
        """DECIMAL กลับมาจาก asyncpg เป็น `Decimal` — cast ก่อนบวกลบเสมอ (กฎ CLAUDE.md)."""
        return float(v) if v is not None else 0.0

    @classmethod
    def _shape_budget_item(cls, row) -> dict:
        """แถวดิบจาก overview → dict ที่คำนวณ derived fields ให้ครบ"""
        amount = cls._to_float(row["amount"])
        used = cls._to_float(row["used"])
        remaining = amount - used
        usage_pct = round(used / amount * 100, 2) if amount else None
        return {
            "budget_id": row["budget_id"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "category_type": row["category_type"],
            "amount": amount,
            "used": used,
            "remaining": remaining,
            "usage_pct": usage_pct,
            # 💡 ใช้เท่างบพอดีไม่นับว่าเกิน — ไม่งั้นงบที่พอดีจะขึ้นเตือนสีแดงทั้งที่ยังไม่เกิน
            "is_over": used > amount,
            "is_near": usage_pct is not None and 80 <= usage_pct <= 100,
            "period_start": row["start_date"],
            "period_end": row["end_date"],
            "period_type": row["period_type"],
            "note": row["note"],
        }

    # ------------------------------------------------------------------ สร้าง
    @classmethod
    async def create_budget(
        cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ การตั้งงบคือการกำหนดกรอบการใช้เงิน = การเขียน ต้องมี MANAGE_FINANCE
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)

                    if req.end_date < req.start_date:
                        raise ValueError("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")

                    cat = await conn.fetchrow(
                        "SELECT id FROM finance_categories WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        req.category_id, target_room_id,
                    )
                    if not cat:
                        raise ValueError("ไม่พบหมวดหมู่นี้ในห้องของคุณ")

                    period_type, period_year, period_month = cls._derive_period(req.start_date, req.end_date)

                    try:
                        new_id = await conn.fetchval(
                            """INSERT INTO finance_budgets
                                   (room_id, category_id, period_type, period_year, period_month,
                                    start_date, end_date, amount, note, created_by)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id""",
                            target_room_id, req.category_id, period_type, period_year, period_month,
                            req.start_date, req.end_date, req.amount, req.note, user_id,
                        )
                    except asyncpg.UniqueViolationError:
                        # partial unique index (room_id, category_id, start_date, end_date)
                        # WHERE deleted_at IS NULL → แปลงเป็น 400 ที่อ่านรู้เรื่อง ไม่ใช่ 500
                        raise ValueError("มีงบประมาณของหมวดนี้ในช่วงเวลานี้อยู่แล้ว")

                    new_values = cls._extract_req_data(req)
                    new_values["budget_id"] = new_id
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", entity_id=str(new_id),
                        status="success", new_values=new_values,
                        endpoint_or_command="FinanceService.create_budget", execution_time_ms=exec_time,
                    )
                return {"status": "success", "message": f"ตั้งงบประมาณแล้ว (id: {new_id})"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.create_budget",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # -------------------------------------------------------------------- อ่าน
    @classmethod
    async def get_budgets(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        category_type: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> List[dict]:
        """รายการงบของห้อง — กรองแบบ **overlap** กับช่วงที่ขอ (ไม่ใช่ containment).

        งบที่คร่อมขอบช่วงต้องโผล่ ไม่งั้นผู้ใช้กรองเดือนเดียวจะไม่เห็นงบภาคเรียน
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น
                await require_member(conn, target_room_id, user_id)

                where = "WHERE B.room_id = $1 AND B.deleted_at IS NULL"
                params: List = [target_room_id]
                idx = 2
                if start_date is not None:
                    where += f" AND B.end_date >= ${idx}"
                    params.append(start_date); idx += 1
                if end_date is not None:
                    where += f" AND B.start_date <= ${idx}"
                    params.append(end_date); idx += 1
                if category_type:
                    where += f" AND C.category_type = ${idx}"
                    params.append(category_type); idx += 1

                rows = await conn.fetch(f"""
                    SELECT B.id, B.category_id, C.category_name, C.category_type,
                           B.period_type, B.period_year, B.period_month,
                           B.start_date, B.end_date, B.amount, B.note,
                           U.first_name || ' ' || U.last_name AS created_by_name,
                           B.created_at
                    FROM finance_budgets B
                    JOIN finance_categories C ON C.id = B.category_id
                    LEFT JOIN users U ON U.id = B.created_by
                    {where}
                    ORDER BY B.start_date DESC, B.id DESC
                    LIMIT 200
                """, *params)

                result = []
                for r in rows:
                    d = dict(r)
                    d["amount"] = cls._to_float(d.get("amount"))
                    result.append(d)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_BUDGET", status="success",
                    endpoint_or_command="FinanceService.get_budgets", execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_BUDGET", status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.get_budgets",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # -------------------------------------------------------------------- แก้
    @classmethod
    async def update_budget(
        cls, pool: asyncpg.Pool, budget_id: int, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)

                    # 🔒 FOR UPDATE — อ่านค่าที่จะนำไป UPDATE ต้องล็อกแถว (เคสในกฎ backend เป๊ะ)
                    old_row = await conn.fetchrow(
                        "SELECT * FROM finance_budgets WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        budget_id, target_room_id,
                    )
                    if not old_row:
                        raise RoomNotFoundError("ไม่พบงบประมาณนี้")
                    old_values = dict(old_row)

                    data = {
                        k: v for k, v in req.model_dump(exclude_unset=True).items()
                        if k in _BUDGET_PATCHABLE
                    }

                    # ช่วงที่มีผลจริง "หลังแก้" — ส่งมาแค่ตัวเดียวต้องเทียบกับค่าที่มีอยู่
                    eff_start = data.get("start_date", old_row["start_date"])
                    eff_end = data.get("end_date", old_row["end_date"])
                    if eff_end < eff_start:
                        raise ValueError("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")

                    set_parts = []
                    params: List = []
                    idx = 1
                    for col in _BUDGET_PATCHABLE:
                        if col in data:
                            set_parts.append(f"{col} = ${idx}")
                            params.append(data[col]); idx += 1

                    # period_* ต้อง derive ใหม่ทุกครั้ง เพราะช่วงอาจเปลี่ยน (= ป้ายต้องไม่ค้างเดือนเดิม)
                    period_type, period_year, period_month = cls._derive_period(eff_start, eff_end)
                    set_parts += [f"period_type = ${idx}"]; params.append(period_type); idx += 1
                    set_parts += [f"period_year = ${idx}"]; params.append(period_year); idx += 1
                    set_parts += [f"period_month = ${idx}"]; params.append(period_month); idx += 1
                    set_parts.append("updated_at = NOW()")

                    budget_ph = idx; params.append(budget_id); idx += 1
                    room_ph = idx; params.append(target_room_id)

                    try:
                        res = await conn.execute(
                            f"""UPDATE finance_budgets SET {', '.join(set_parts)}
                                WHERE id = ${budget_ph} AND room_id = ${room_ph} AND deleted_at IS NULL""",
                            *params,
                        )
                    except asyncpg.UniqueViolationError:
                        raise ValueError("มีงบประมาณของหมวดนี้ในช่วงเวลานี้อยู่แล้ว")
                    if res == "UPDATE 0":
                        raise RoomNotFoundError("ไม่พบงบประมาณนี้")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", entity_id=str(budget_id),
                        status="success", old_values=old_values, new_values=cls._extract_req_data(req),
                        endpoint_or_command="FinanceService.update_budget", execution_time_ms=exec_time,
                    )
                return {"status": "success", "message": "อัปเดตงบประมาณสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", entity_id=str(budget_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_budget", execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # -------------------------------------------------------------------- ลบ
    @classmethod
    async def delete_budget(
        cls, pool: asyncpg.Pool, budget_id: int, user_id: int, client_source: str,
        actor_identifier: str, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """**soft delete** — `UPDATE ... SET deleted_at = NOW()`.

        ⚠️ ห้ามลอก `delete_category` (hard delete) — กฎโปรเจกต์บังคับ soft delete สำหรับ
        ข้อมูลสำคัญ และงบประมาณที่ถูกลบต้องตรวจย้อนได้ว่าเคยมีอยู่ (audit + แถวยังอยู่)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ (protocol เดียวกันทั้งระบบ — ดู `_lock_room_money`)
                    await _lock_room_money(conn, target_room_id)

                    old_row = await conn.fetchrow(
                        "SELECT * FROM finance_budgets WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        budget_id, target_room_id,
                    )
                    if not old_row:
                        raise RoomNotFoundError("ไม่พบงบประมาณนี้")
                    old_values = dict(old_row)

                    res = await conn.execute(
                        """UPDATE finance_budgets SET deleted_at = NOW(), updated_at = NOW()
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                        budget_id, target_room_id,
                    )
                    if res == "UPDATE 0":
                        raise RoomNotFoundError("ไม่พบงบประมาณนี้")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", entity_id=str(budget_id),
                        status="success", old_values=old_values,
                        endpoint_or_command="FinanceService.delete_budget", execution_time_ms=exec_time,
                    )
                return {"status": "success", "message": "ลบงบประมาณสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_BUDGET", entity_id=str(budget_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_budget", execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ------------------------------------------------------------------ ภาพรวม
    @classmethod
    async def get_budget_overview(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        start_date: date, end_date: date,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> dict:
        """งบทุกใบที่ **overlap** ช่วงที่ขอ + ยอดใช้จริง **ในช่วงของแต่ละงบเอง**.

        query เดียวด้วย `LEFT JOIN LATERAL` — งบแต่ละใบมีช่วงของตัวเอง จึง clamp ด้วย
        `GREATEST`/`LEAST` กับช่วงที่ผู้ใช้กรอง แล้ววัดยอดเฉพาะส่วนที่ทับกัน
        (ถ้าแยก query ต่อใบจะกลายเป็น N+1 และหน้าจอช้าทันทีที่มีงบหลายสิบใบ)

        "ใช้ไป" = ผลรวม 2 ส่วนที่เป็น **disjoint กันจริง** (ดูรายละเอียดที่คอมเมนต์ใน SQL):
          (ก) แถว legacy ที่ **ผูกหมวด** — ครอบทั้งรายรับที่บันทึกมือและรายจ่าย
          (ข) รายรับจาก `student_payments` — แถว legacy ของการรับเงิน **ไม่มี category_id**
              ⇒ query (ก) มองไม่เห็น ต้องเสริมจาก journal ขาเครดิตของ ledger ที่ map กับหมวดนี้
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if end_date < start_date:
                    raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")

                rows = await conn.fetch(f"""
                    SELECT B.id AS budget_id, B.category_id, C.category_name, C.category_type,
                           B.amount, B.start_date, B.end_date, B.period_type, B.note,
                           COALESCE(U.used, 0) AS used
                    FROM finance_budgets B
                    JOIN finance_categories C ON C.id = B.category_id
                    LEFT JOIN LATERAL (
                        SELECT (
                            -- (ก) รายการที่ผูกหมวด — อ่าน legacy mirror อย่างเดียว (ดูคอมเมนต์หัวไฟล์)
                            --     `transaction_type = C.category_type` ทำให้หมวดเป็นตัวกำหนดประเภทเอง
                            --     (add_transaction บังคับไว้แล้ว) ⇒ ไม่ต้องส่ง type เป็น param
                            COALESCE((
                                SELECT SUM(T.amount)
                                FROM finance_transactions T
                                WHERE T.room_id = B.room_id
                                  AND T.category_id = B.category_id
                                  AND T.transaction_type = C.category_type
                                  -- ตัดขาโอนเงินทั้งสองขา: ไม่ใช่การใช้จ่าย/รายรับจริง
                                  AND T.transfer_group_id IS NULL
                                  AND T.deleted_at IS NULL
                                  AND T.created_at >= {_LEGACY_LO}
                                  AND T.created_at <  {_LEGACY_HI}
                            ), 0)
                            +
                            -- (ข) รายรับจาก student_payments
                            --     ⚠️ เดิมแผนเขียนว่า `SUM(L.credit - L.debit)` เฉย ๆ ซึ่ง **ผิด**:
                            --     entry ของการรับเงินมี 2 บรรทัด (Dr สินทรัพย์ / Cr รายได้)
                            --     ⇒ ผลรวมทั้งใบหักลบกันได้ 0 เสมอ ต้องกรองเอาเฉพาะบรรทัดรายได้
                            COALESCE((
                                SELECT SUM(L.credit - L.debit)
                                FROM journal_lines L
                                JOIN journal_entries JE ON L.journal_entry_id = JE.id
                                JOIN accounting_ledgers AL ON AL.id = L.ledger_id
                                WHERE JE.room_id = B.room_id
                                  -- 🔴 [F4] ต้องมี 'student_credit_apply' ด้วย ไม่งั้น **ยอดหายเงียบ**:
                                  --    รายได้ที่เกิดจากการหักเครดิตไปปิดบิลจะไม่ถูกนับเข้างบเลย
                                  --    และไม่มีอะไรฟ้อง (ยอดต่ำกว่าจริงเฉย ๆ) — เป็นกับดักตระกูล
                                  --    เดียวกับ `--api-timeout` ที่ต้องแก้สองที่พร้อมกัน
                                  --
                                  --    🚫 **ห้ามเพิ่ม 'student_credit_topup'** — นั่นคือการย้าย
                                  --    สินทรัพย์ ↔ หนี้สิน ยังไม่ใช่รายได้ (ไม่มีขา revenue เลย
                                  --    ⇒ `AL.account_type = 'revenue'` ข้างล่างกรองออกให้อยู่แล้ว
                                  --    แต่ใส่ไว้จะทำให้อ่านโค้ดแล้วเข้าใจผิดว่ามันนับเป็นรายได้)
                                  AND JE.reference_type IN ('student_payment', 'student_credit_apply')
                                  AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                                  AND AL.account_type = 'revenue'
                                  -- ผูกกับ "หมวด" ไม่ใช่ "ชื่อ ledger" ⇒ งบของหมวดอื่นไม่โดนเหมารวม
                                  AND AL.legacy_category_id = B.category_id
                                  AND JE.transaction_date >= {_JOURNAL_LO}
                                  AND JE.transaction_date <  {_JOURNAL_HI}
                            ), 0)
                        ) AS used
                    ) U ON TRUE
                    WHERE B.room_id = $1 AND B.deleted_at IS NULL
                      AND B.start_date <= $3 AND B.end_date >= $2      -- overlap กับช่วงที่กรอง
                    ORDER BY C.category_type, C.category_name, B.start_date
                """, target_room_id, start_date, end_date)

                items = [cls._shape_budget_item(r) for r in rows]
                result = {
                    "start_date": start_date,
                    "end_date": end_date,
                    "items": items,
                    "total_budget": round(sum(i["amount"] for i in items), 2),
                    "total_used": round(sum(i["used"] for i in items), 2),
                    "over_count": sum(1 for i in items if i["is_over"]),
                    "warning_count": sum(1 for i in items if i["is_near"]),
                }

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_BUDGET", status="success",
                    endpoint_or_command="FinanceService.get_budget_overview", execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_BUDGET", status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.get_budget_overview",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
