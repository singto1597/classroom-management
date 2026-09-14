"""ตัวช่วยพื้นฐานที่ Finance service อื่นใช้ร่วมกัน (resolve room / actor / server_id)"""
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
)
from .helpers import (
    _naive_thai_dt, _clamp_to_cutoff, _ExportPeriodView, _resolve_inclusive_period,
    _legacy_id_from_journal,
)

service_logger = AuditLogger(service_name="FINANCE")

# 🔒 namespace ของ **advisory lock ระดับห้อง** ที่ทุกเส้นทางเงินต้องยึดเป็นอย่างแรก
#
# ⚠️ ต้องมี namespace เดียวทั้งระบบ — ถ้าสองเส้นทางใช้ namespace ต่างกัน มันจะไม่เห็นกัน
#    แล้ว protocol ทั้งหมดก็เป็นโมฆะ (เหมือนล็อกคนละดอก)
#    ค่าเดิมมาจาก receipts.py (`_ISSUE_LOCK_NAMESPACE`) — คงตัวเลขเดิมไว้เพื่อไม่ให้
#    พฤติกรรมของ advisory lock ที่ deploy อยู่เปลี่ยนความหมายกลางทาง
#    (0x52454350 = 'RECP' — อ่านออกว่าเป็นของงานเอกสาร/การเงิน)
#
# 📐 ลายเซ็น `pg_advisory_xact_lock(key1 int4, key2 int4)`: key1 = namespace, key2 = room_id
#    ⇒ คนละห้องได้ล็อกคนละดอก ไม่บล็อกกัน (ห้องอื่นทำงานขนานได้ตามปกติ)
_MONEY_LOCK_NAMESPACE = 0x52454350


async def _lock_room_money(conn: asyncpg.Connection, room_id: int) -> None:
    """🔒 ยึด advisory lock ของห้อง — **ต้องเป็นคำสั่งแรกใน transaction ของทุกเส้นทางที่แตะเงิน**

    ⚠️ เรียกซ้ำใน transaction เดียวกันไม่บล็อก (advisory lock เป็นแบบ re-entrant ต่อ session)
       ⇒ batch ที่เรียกในลูปจึงได้ล็อกครั้งเดียวที่ item แรก แล้วถือไปจน commit

    ─────────────────────────────────────────────────────────────────────────────
    🎯 ทำไมต้องมี (deadlock 40P01 → 500 ที่ผู้ใช้เห็น)
    ─────────────────────────────────────────────────────────────────────────────
    ก่อนหน้านี้แต่ละเส้นทางยึด "หลายทรัพยากร" ในลำดับของตัวเอง ⇒ เกิดวงรอบรอ ABBA
    ที่ **พิสูจน์ได้จากโค้ด** 3 วง (ไม่ใช่ทฤษฎี):

      1) `student_payments` ↔ `finance_accounts`
         - รับเงิน (`_confirm_single_payment`) : SP → ACC
         - ยกเลิก (`revert_transaction`)        : ACC → SP
      2) `finance_transactions` ↔ `student_payments`
         - ออกใบเสร็จ (`_load_payment`) : SP แล้ว INSERT `finance_receipts` ที่อ้าง FK
           `legacy_transaction_id` ⇒ Postgres ได้ **KEY SHARE บนแถว FT** ⇒ SP → FT
         - ยกเลิก (`revert_transaction`) : FT (`FOR UPDATE`) → SP ⇒ FT → SP
      3) `finance_accounts` กับตัวเอง ใน `transfer_money`
         - ยึด `from` (FOR UPDATE) แล้วค่อยยึด `to` ⇒ ลำดับขึ้นกับ **ทิศทางที่ผู้ใช้ส่ง**
         - โอนสองรายการทิศตรงข้ามบนบัญชีคู่เดียวกัน = วงรอบรอทันที
         (และ `revert_transaction` ยังล็อกกลุ่มโอนโดย **ไม่มี ORDER BY** ⇒ ลำดับขึ้นกับ plan)

    วิธีแก้: บังคับให้ทุกเส้นทางยึด **ล็อกของห้องก่อน** แล้วค่อยแตะแถวใด ๆ
    ⇒ ไม่มีทางเกิดวงรอบ เพราะภายในห้องเดียวจะมี transaction ที่ถือล็อกอยู่ได้ทีละหนึ่ง
       และมันไม่เคยถือ row lock ค้างไว้ขณะ "รอ" advisory lock (เพราะยึด advisory เป็นอย่างแรก)

    ⚠️ เงื่อนไขที่ทำให้ protocol นี้ใช้ได้จริง: **ทุก** เส้นทางที่แตะเงินต้องเรียกฟังก์ชันนี้
       ถ้ามีเส้นทางเดียวที่ลืม มันจะยัง interleave กับที่เหลือได้ ⇒ ต้องมีเทสต์กันการถอยกลับ
       (`test_finance_money_lock.py` มีทั้งเทสต์เชิงพฤติกรรมและเทสต์เชิงโครงสร้าง)
    """
    await conn.execute(
        "SELECT pg_advisory_xact_lock($1, $2)", _MONEY_LOCK_NAMESPACE, room_id
    )


async def _lock_payments_in_order(conn: asyncpg.Connection, payment_ids: List[int]) -> None:
    """🔒 ล็อกแถว `student_payments` ทั้งชุด **ตามลำดับ id เสมอ** ก่อนเข้าลูปทำงาน

    ⚠️ ปัญหาที่มันแก้ (deadlock 40P01 → 500 + ทั้งชุด rollback):
       เส้นทางที่ **ล็อกบิลหลายใบ** มีสองทาง — รับเงินรวบยอด (`batch_confirm_payments`)
       และออกเอกสารรวบยอด (`issue_receipts_batch`) — และทั้งคู่ล็อก **ตามลำดับที่ผู้ใช้ส่งมา**
       ⇒ สองคำขอของห้องเดียวกันที่ส่งบิลชุดเดียวกัน "สลับลำดับกัน" (A: P1→P2, B: P2→P1)
         จะวนรอกันทันที: A ยึด P1 รอ P2 ขณะที่ B ยึด P2 รอ P1
       Postgres ฆ่าฝั่งหนึ่งด้วย DeadlockDetectedError ซึ่ง router ไม่ได้แปลง ⇒ 500
       และถ้าฝั่งที่แพ้เป็น batch เอกสาร/การรับเงิน **ทั้งชุดถูก rollback**

    🔒 บังคับลำดับอย่างไร: ล็อกให้ครบ **ก่อน** เข้าลูป ⇒ การล็อกซ้ำรายใบในลูป
       (เช่น `FOR UPDATE OF SP` ใน `_load_payment`) เป็นการล็อกซ้ำใน transaction เดียวกัน
       ซึ่งไม่บล็อก ⇒ ไม่มีจุด "รอ" กลางลูปที่ทำให้ลำดับขึ้นกับ request อีก

    🧠 ทำไมล็อกทีละแถวในลูป Python ไม่ใช่ `SELECT ... ORDER BY id FOR UPDATE` คำสั่งเดียว:
       เอกสาร Postgres ระบุว่าเมื่อมี `ORDER BY` คู่กับ locking clause การเรียงเกิดก่อนการล็อก
       แต่ก็เตือนว่าผลลัพธ์อาจ "ดูสลับที่" ได้ ⇒ พฤติกรรมจริงขึ้นกับ plan
       การล็อกทีละแถวตาม `sorted()` เป็นลำดับที่ **อ่านโค้ดแล้วพิสูจน์ได้ทันที** ไม่ต้องพึ่ง planner
       ราคาที่จ่ายคือ round-trip เพิ่มใบละ 1 ครั้ง ซึ่งน้อยมากเทียบกับงานต่อใบในลูป (≥5 query)

    🔗 หน้าที่ของตัวนี้ **เปลี่ยนไปแล้ว** ตั้งแต่มี `_lock_room_money`:
       การกันวงรอบรอ ABBA ทั้งคลาสเป็นหน้าที่ของ `_lock_room_money` (advisory lock ต่อห้อง
       ซึ่งเรียกเป็นอย่างแรกในทุกเส้นทางที่แตะเงิน) ส่วนตัวนี้ทำหน้าที่เสริมเฉพาะทาง คือ
       จัดลำดับการล็อก **หลายบิลในลูปเดียว** ให้อ่านแล้วพิสูจน์ได้ ⇒ ยังต้องคงไว้
       (ที่ล็อกซ้ำรายใบในลูปเป็นการล็อกซ้ำใน transaction เดียวกัน ซึ่งไม่บล็อก)
    """
    ids = sorted({int(p) for p in payment_ids if p is not None})
    for pid in ids:
        await conn.fetchval("SELECT id FROM student_payments WHERE id = $1 FOR UPDATE", pid)


class BaseMixin:
    @staticmethod
    def _extract_req_data(req) -> dict:
        if isinstance(req, dict):
            return req
        # 🚀 Pydantic v2 ต้องใช้ model_dump() (dict() ถูกลบใน v3) — ตรงตามกฎ CLAUDE.md
        if hasattr(req, 'model_dump') and callable(req.model_dump):
            return req.model_dump()
        if hasattr(req, 'dict') and callable(req.dict):
            return req.dict()
        try:
            return vars(req)
        except Exception:
            return {"raw_data": str(req)}

    @staticmethod
    def _finance_actor(req) -> str:
        n = getattr(req, "user_name", None)
        if n is not None and str(n).strip():
            return str(n).strip()[:200]
        return "—"

    @staticmethod
    async def _get_room_server_id(conn: asyncpg.Connection, room_id: int) -> Optional[int]:
        """ดึง server_id ของห้อง (ใช้ publish ไป Discord) — คืน None ถ้าห้องยังไม่ผูก Discord"""
        return await conn.fetchval(
            "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL",
            room_id,
        )

    @staticmethod
    def _period_start(
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
    ) -> Optional[date]:
        """จุดเริ่มต้นของช่วงเวลาที่ถูกขอ → ใช้ตัดสินใจ Route ไป legacy หรือ v2.

        - month/year: วันที่ 1 ของเดือน
        - start_date: ตัวมันเอง (หรือจุดเริ่มต้นของช่วง)
        - ไม่ระบุเลย: ใช้จุดเริ่มต้นของเดือนปัจจุบัน (ทำนองเดียวกับ legacy fallback)
        คืน None ไม่มีทางเกิดขึ้นจริง (เดือนปัจจุบันมีจุดเริ่มเสมอ) แต่ใส่เผื่อ type safety.
        """
        if month is not None and year is not None:
            return date(year, month, 1)
        if start_date is not None:
            return start_date
        # ไม่มีตัวกรองช่วงเวลา → default เป็นเดือนปัจจุบัน (ตรงกับ logic เดิมของ get_summary)
        today = datetime.now(THAI_TZ).date()
        return date(today.year, today.month, 1)

    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: 
                raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id")

    @classmethod
    async def get_active_students(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id, S.student_no, U.first_name, U.last_name, U.nickname,
                           U.first_name_en, U.last_name_en, U.nickname_en
                    FROM students S
                    LEFT JOIN users U ON S.user_id = U.id
                    WHERE S.room_id = $1 AND S.status = 'active' AND S.deleted_at IS NULL
                    ORDER BY S.student_no ASC
                """, target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="success",
                    endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
