"""[F5] ชุดเอกสาร (Document Batch) — จัดกลุ่มเอกสารเพื่อยุบการแสดงผลในทะเบียน

═══════════════════════════════════════════════════════════════════════════════
"ชุด" คืออะไร และ **ไม่ใช่อะไร**
═══════════════════════════════════════════════════════════════════════════════
ชุด = กลุ่มของใบเสร็จ/ใบแจ้งหนี้ที่ "ออกพร้อมกันในรอบเดียว" หรือที่ผู้ใช้จับกลุ่มทีหลัง
ใช้เพื่อ (ก) ยุบการแสดงผลในทะเบียนเอกสาร (ข) ติ๊กครั้งเดียวได้เอกสารทั้งชุดไปรวม PDF

🔴 **ชุดไม่ใช่เอกสารทางบัญชี** ⇒
    - ไม่มีเลขรันของตัวเอง (ใช้ `id`) และ **ไม่กินเลขเอกสาร** ⇒ ไม่แตะ `receipt_sequences` เลย
      การเพิ่ม doc_type ใหม่เข้าไปในตารางนั้นจะต้องมี upsert สำเนาที่ 4 ซึ่ง
      `receipts.py` เขียนเตือนไว้ว่าห้ามทำ — ชุดจึงเลี่ยงปัญหานั้นทั้งหมด
    - ไม่มีสถานะ void ของตัวเอง — "ยุบชุด" = soft delete (แถวชุดหายไป เอกสารไม่หาย)
    - **ใบที่ถูกยกเลิกยังคงเป็นสมาชิกของชุด** ไม่ถูกถอดออก: ชุดคือบันทึกประวัติว่า
      "ออกพร้อมกัน" การถอดสมาชิกคือการเขียนประวัติใหม่ และชื่อชุดที่หน้าจอประกอบว่า
      "20 ใบ" จะกลายเป็นคำโกหก ⇒ หน้าจอใช้ `voided_count` บอกความจริงแทน
      ("แสดง 12 จาก 20 ใบ · ยกเลิก 3") — ด้วยเหตุนี้ `transactions.revert_transaction`
      **ไม่ต้องแก้อะไรเลย**

═══════════════════════════════════════════════════════════════════════════════
ทำไม `get_receipts` ยังคืน "แบน" ไม่คืนโครงสร้างซ้อน
═══════════════════════════════════════════════════════════════════════════════
`get_receipts` เติมแค่ 4 ฟิลด์ (`batch_id`/`batch_title`/`batch_size`/`batch_voided_count`)
แล้วให้ frontend จัดกลุ่มเอง เพราะ
  1. `LIMIT 500` + ตัวกรองวันที่คือสัญญาที่หน้าจอพึ่งอยู่ — ชุดที่สมาชิกบางส่วนหลุดช่วงกรอง
     จะดูเหมือน "มีไม่ครบ" โดยที่ผู้ใช้ไม่มีทางรู้ว่าขาด
  2. `ReceiptList.vue` ตัด `selectedNos` ที่หลุดตัวกรองทิ้งอยู่แล้ว ⇒ การจัดกลุ่มฝั่ง client
     ใช้ข้อมูลชุดเดียวกับ checkbox **ไม่มีทางที่สองสิ่งจะไม่ตรงกัน**
  3. จัดกลุ่ม ≤500 แถวในหน่วยความจำเบราว์เซอร์ = ฟรี ไม่ต้องมี request ที่สอง

⚠️ `batch_size` ต้องมาจาก **คำขอที่สอง** (`_load_batch_counts`) ไม่ใช่
   `COUNT(*) OVER (PARTITION BY batch_id)` — window function นับเฉพาะแถวที่รอด `WHERE`
   ⇒ จะโกหกทันทีที่ตัวกรองวันที่ตัดสมาชิกบางส่วนออก (มีเทสต์ปิดไว้)
"""
import asyncpg
import time
from typing import Dict, List, Optional

from core.exceptions import RoomNotFoundError
from core.rbac import require_permission, require_member

from .base import _lock_room_money, service_logger
from .constants import (
    AUTO_BATCH_MIN, BATCH_RECEIPTS_MAX,
    BATCH_SOURCE_AUTO, BATCH_SOURCE_MANUAL, BATCH_SOURCE_ROOM,
)
from .helpers import _as_utc
from .receipts import _DOC_DATE, _RECEIPT_COLUMNS

# 🚧 เพดานจำนวนชุดที่หน้าทะเบียนโหลด — เท่ากับ LIMIT ของ `get_receipts` โดยเจตนา
_BATCH_LIST_LIMIT = 500

# 🔒 allowlist ของคอลัมน์ที่ PATCH ได้ — **ห้ามต่อชื่อคอลัมน์ที่ client ส่งมาเข้า SQL ตรง ๆ**
#    (เป็นช่องทาง SQL injection ที่ classic ที่สุด) ท่ามาตรฐานของ repo อยู่ที่
#    `budgets.py:_BUDGET_PATCHABLE` — ที่นี่ทำแบบเดียวกัน และ **ไม่รวม `source`/`room_id`/
#    `deleted_at`** เพราะเป็นfield ที่ระบบเป็นเจ้าของ ไม่ใช่ผู้ใช้
_BATCH_PATCHABLE = ("title", "note")


async def attach_issuance_batch(
    conn: asyncpg.Connection, *, room_id: int, receipt_ids: List[int],
    source: str, user_id: Optional[int], user_name: Optional[str],
) -> Optional[int]:
    """จัดชุดให้เอกสารที่เพิ่งออกในรอบนี้ — คืน `batch_id` หรือ `None` ถ้าไม่เข้าเกณฑ์

    🔴 **เรียกจากใน transaction ของการออกเอกสารเท่านั้น** — ชุดต้องเกิดพร้อมเอกสาร
       ไม่มี background job/cron (ถ้าชุดเกิดทีหลัง เอกสารที่ออกไปแล้วจะล่องลอยชั่วขณะ
       และถ้า process ตายกลางทางจะไม่มีใครมาปิดให้)

    🔴 **ผู้เรียกต้องยึด `_lock_room_money` มาก่อนแล้ว** — ฟังก์ชันนี้ไม่ยึดล็อกเอง
       (ยึดซ้ำจะไม่บล็อกก็จริง เพราะเป็น `pg_advisory_xact_lock` แบบ re-entrant
        แต่การยึดที่นี่ทำให้อ่านไม่ออกว่าใครเป็นเจ้าของล็อก)

    ⚠️ **ผู้เรียกต้องส่งเฉพาะ id ของใบที่ "ออกใหม่จริง"** (`reused == False`) — ใบที่ถูก
       reuse คือใบที่ออกไปก่อนหน้านี้แล้ว การลากมันเข้าชุดใหม่จะทำให้ชุดเดียวมีใบที่
       "ออกคนละเวลา" ปนอยู่ และกดออกซ้ำหลายรอบจะได้ชุดใหญ่ขึ้นเรื่อย ๆ โดยไม่มีเหตุผล
       ⇒ ตรรกะ "กรอง reused" อยู่ที่ผู้เรียก ไม่ใช่ที่นี่ (ดู `issue_receipts_batch`)

    ⚠️ **ไม่แตะ `_issue_one` เลย** — การผูกชุดทำด้วย `UPDATE` ทีหลัง ไม่ใช่เพิ่ม kwarg
       เข้า hot path ที่เทสต์เชิงโครงสร้างผูกพันอยู่ (เหตุผลอยู่ในแผน F5)
    """
    if len(receipt_ids) < AUTO_BATCH_MIN:
        return None

    batch_id = await conn.fetchval(
        """INSERT INTO finance_receipt_batches (room_id, title, source, created_by, created_by_name)
           VALUES ($1, NULL, $2, $3, $4) RETURNING id""",
        # 📛 `title = NULL` โดยเจตนา — หน้าจอประกอบชื่อแสดงเอง ("ชุดใบเสร็จ 20 ใบ · วันที่")
        #    🔴 ห้ามเก็บสตริงที่ประกอบแล้วลง DB: มันจะกลายเป็น snapshot ที่ **โกหก** ทันที
        #       ที่มีใบถูกยกเลิก (ยังเขียนว่า "20 ใบ" ทั้งที่เหลือ 17) — ต่างจากชื่อเอกสาร
        #       ที่ต้อง snapshot เพราะเป็นข้อความทางกฎหมาย
        room_id, source, user_id, user_name,
    )
    # ⚠️ `deleted_at IS NULL` กันไม่ให้ลากใบที่ถูกลบกลับเข้าชุด (ไม่ควรเกิดในทางปกติ
    #    แต่การ UPDATE ที่ไม่มีเงื่อนไขนี้จะ " ressurect" ใบที่ถูก soft delete เงียบ ๆ)
    await conn.execute(
        """UPDATE finance_receipts SET batch_id = $1
           WHERE room_id = $2 AND id = ANY($3::int[]) AND deleted_at IS NULL""",
        batch_id, room_id, receipt_ids,
    )
    return batch_id


class ReceiptBatchesMixin:
    # =================================================================
    # ตัวช่วยอ่าน (ไม่เขียนอะไร)
    # =================================================================
    @staticmethod
    def _shape_batch(row) -> dict:
        """แถวชุด → dict สำหรับ response (cast Decimal → float ตามกฎของ repo)"""
        d = dict(row)
        for key in ("total_amount",):
            if d.get(key) is not None:
                d[key] = float(d[key])
        for key in ("active_count", "voided_count"):
            if d.get(key) is not None:
                d[key] = int(d[key])
        for key in ("created_at", "updated_at", "first_doc_at", "last_doc_at"):
            d[key] = _as_utc(d.get(key))
        return d

    @classmethod
    async def _load_batch_row(cls, conn: asyncpg.Connection, *, room_id: int, batch_id: int):
        """โหลดชุดที่ยังไม่ถูกลบ **ของห้องนี้** — ไม่พบ = 404

        ⚠️ กรอง `room_id` ด้วยเสมอ ไม่ใช่แค่ `id` — ไม่งั้นชุดของห้องอื่นจะถูกอ่าน/แก้ได้
           ด้วยการเดา id (composite FK กันได้แค่ตอน **เขียน** `batch_id` ของใบเสร็จ)
        """
        row = await conn.fetchrow(
            """SELECT id, room_id, title, source, note, created_by, created_by_name,
                      created_at, updated_at
               FROM finance_receipt_batches
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            batch_id, room_id,
        )
        if row is None:
            raise RoomNotFoundError("ไม่พบชุดเอกสารนี้ในห้อง (อาจถูกยุบไปแล้ว)")
        return row

    @staticmethod
    async def _resolve_receipt_ids(
        conn: asyncpg.Connection, *, room_id: int, receipt_nos: List[str]
    ) -> List[int]:
        """เลขที่เอกสาร → id ของแถวในห้องนี้ (คงลำดับที่ผู้ใช้ส่งมา) — เลขที่หายไป = 404

        🔴 **ห้ามข้ามเลขที่ไม่พบแบบเงียบ ๆ**: ชุดที่ขาดสมาชิกไปหนึ่งใบหน้าตาเหมือนชุดที่
           ถูกต้อง ⇒ ครูกด "โหลดทั้งชุด" แล้วแจกเอกสารไม่ครบโดยไม่มีทางรู้
           (เหตุผลเดียวกับ `render_documents_pdf`)
        ⚠️ รับเฉพาะใบที่ยัง `active` + ไม่ถูกลบ — ใบที่ถูกยกเลิกแล้ว **ไม่ควรถูกจัดเข้าชุดใหม่**
           (แต่ใบที่ถูกยกเลิกระหว่างที่เป็นสมาชิกอยู่แล้วจะยังอยู่ต่อ — คนละกรณีกัน)
        """
        if not receipt_nos:
            raise ValueError("ต้องเลือกเอกสารอย่างน้อย 1 ฉบับ")
        unique_nos = list(dict.fromkeys(receipt_nos))
        if len(unique_nos) > BATCH_RECEIPTS_MAX:
            raise ValueError(
                f"จัดชุดได้ครั้งละไม่เกิน {BATCH_RECEIPTS_MAX} ฉบับ "
                f"(เลือกมา {len(unique_nos)} ฉบับ)"
            )
        rows = await conn.fetch(
            """SELECT id, receipt_no FROM finance_receipts
               WHERE room_id = $1 AND receipt_no = ANY($2::text[])
                 AND deleted_at IS NULL AND status = 'active'""",
            room_id, unique_nos,
        )
        by_no = {r["receipt_no"]: r["id"] for r in rows}
        missing = [n for n in unique_nos if n not in by_no]
        if missing:
            raise RoomNotFoundError("ไม่พบเอกสารเลขที่ " + ", ".join(missing) + " ในห้องนี้")
        # เรียงตามลำดับที่ผู้ใช้เห็น ไม่ใช่ตามที่ DB คืน (array_agg ใน idempotency check
        # ของ `create_receipt_batch` เรียงตาม id อยู่แล้ว ⇒ สองที่จะตรงกันเสมอ)
        return [by_no[n] for n in unique_nos]

    @staticmethod
    async def _load_batch_counts(
        conn: asyncpg.Connection, *, room_id: int, batch_ids: List[int]
    ) -> Dict[int, dict]:
        """ขนาดจริงของแต่ละชุด — **ไม่ขึ้นกับตัวกรองของหน้าจอ** (ดูเหตุผลบนหัวไฟล์)

        คืน {batch_id: {"batch_size": int, "batch_voided_count": int}} โดยนับ
        **สมาชิกทั้งหมดของชุด** ไม่ใช่เฉพาะแถวที่รอด `WHERE` ของ `get_receipts`
        """
        wanted = [b for b in dict.fromkeys(batch_ids) if b is not None]
        if not wanted:
            return {}
        rows = await conn.fetch(
            """SELECT batch_id,
                      COUNT(*) FILTER (WHERE deleted_at IS NULL AND status = 'active') AS active_cnt,
                      COUNT(*) FILTER (WHERE deleted_at IS NOT NULL OR status <> 'active') AS voided_cnt
               FROM finance_receipts
               WHERE room_id = $1 AND batch_id = ANY($2::int[])
               GROUP BY batch_id""",
            room_id, wanted,
        )
        # `batch_size` = ขนาด **ทั้งชุด** = ใบที่ยัง active + ใบที่ถูกยกเลิก/ลบ
        #    ⇒ `batch_size - batch_voided_count` = จำนวนที่หน้าจอควรแสดงเมื่อไม่กรองอะไร
        return {
            r["batch_id"]: {
                "batch_size": int(r["active_cnt"]) + int(r["voided_cnt"]),
                "batch_voided_count": int(r["voided_cnt"]),
            }
            for r in rows
        }

    @classmethod
    async def _load_batch_summary(cls, conn: asyncpg.Connection, *, room_id: int, batch_id: int) -> dict:
        """ชุดเดียว + ยอด/จำนวนสมาชิก (ใช้ตอบหลังเขียน)"""
        row = await conn.fetchrow(
            f"""SELECT B.id, B.room_id, B.title, B.source, B.note, B.created_by, B.created_by_name,
                       B.created_at, B.updated_at,
                       COUNT(R.id) FILTER (WHERE R.deleted_at IS NULL AND R.status = 'active')
                           AS active_count,
                       COUNT(R.id) FILTER (WHERE R.deleted_at IS NOT NULL OR R.status <> 'active')
                           AS voided_count,
                       COALESCE(SUM(R.amount) FILTER (
                           WHERE R.deleted_at IS NULL AND R.status = 'active'), 0) AS total_amount,
                       MIN({_DOC_DATE}) AS first_doc_at,
                       MAX({_DOC_DATE}) AS last_doc_at
                FROM finance_receipt_batches B
                LEFT JOIN finance_receipts R ON R.batch_id = B.id
                WHERE B.id = $1 AND B.room_id = $2 AND B.deleted_at IS NULL
                GROUP BY B.id""",
            batch_id, room_id,
        )
        if row is None:
            raise RoomNotFoundError("ไม่พบชุดเอกสารนี้ในห้อง (อาจถูกยุบไปแล้ว)")
        d = cls._shape_batch(row)
        # `batch_size` (ทั้งชุด รวมใบที่ถูกยกเลิก) ให้ตรงความหมายเดียวกับที่ `get_receipts` คืน
        d["batch_size"] = d["active_count"] + d["voided_count"]
        return d

    # =================================================================
    # อ่าน
    # =================================================================
    @classmethod
    async def get_receipt_batches(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[dict]:
        """ชุดเอกสารทั้งหมดของห้อง (ใหม่สุดก่อน) — **ซ่อนชุดที่ไม่มีสมาชิก active เหลืออยู่**

        ⚠️ ชุดที่สมาชิกทุกใบถูกยกเลิก/ลบ จะไม่มีแถวไหนในทะเบียนอ้างถึง ⇒ ถ้าไม่กรองออก
           ครูจะเห็น "ชุดเปล่า" ที่กดเข้าไปแล้วว่าง ซึ่งอ่านไม่ออกว่าเกิดอะไรขึ้น
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch(
                    f"""SELECT B.id, B.room_id, B.title, B.source, B.note,
                               B.created_by, B.created_by_name, B.created_at, B.updated_at,
                               COUNT(R.id) FILTER (
                                   WHERE R.deleted_at IS NULL AND R.status = 'active') AS active_count,
                               COUNT(R.id) FILTER (
                                   WHERE R.deleted_at IS NOT NULL OR R.status <> 'active')
                                   AS voided_count,
                               COALESCE(SUM(R.amount) FILTER (
                                   WHERE R.deleted_at IS NULL AND R.status = 'active'), 0)
                                   AS total_amount,
                               MIN({_DOC_DATE}) AS first_doc_at,
                               MAX({_DOC_DATE}) AS last_doc_at
                        FROM finance_receipt_batches B
                        LEFT JOIN finance_receipts R ON R.batch_id = B.id
                        WHERE B.room_id = $1 AND B.deleted_at IS NULL
                        GROUP BY B.id
                        HAVING COUNT(R.id) FILTER (
                                   WHERE R.deleted_at IS NULL AND R.status = 'active') > 0
                        ORDER BY MAX({_DOC_DATE}) DESC NULLS LAST, B.id DESC
                        LIMIT {_BATCH_LIST_LIMIT}""",
                    target_room_id,
                )
                result = []
                for r in rows:
                    d = cls._shape_batch(r)
                    d["batch_size"] = d["active_count"] + d["voided_count"]
                    result.append(d)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT_BATCH", status="success",
                    new_values={"count": len(result)},
                    endpoint_or_command="FinanceService.get_receipt_batches",
                    execution_time_ms=exec_time,
                )
            return result
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                endpoint="FinanceService.get_receipt_batches", error=e, start_time=start_time,
            )
            raise e

    @classmethod
    async def get_receipt_batch_detail(
        cls, pool: asyncpg.Pool, batch_id: int, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ชุด + เอกสารทุกใบในชุด (**รวมใบที่ถูกยกเลิก** โดยเจตนา)

        ⚠️ ไม่กรอง `status`/`deleted_at` ของใบ: ถ้ากรอง จำนวนที่หน้ารายละเอียดแสดงจะไม่ตรง
           กับ `voided_count` ที่ทะเบียนบอก ⇒ ผู้ใช้เห็น "ยกเลิก 3" แต่กางออกมานับได้แค่ 17
           (แถวที่ถูกยกเลิกมี `status` ติดมาด้วย ⇒ หน้าจอประทับป้าย "ยกเลิก" เองได้)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)
                batch = await cls._load_batch_summary(
                    conn, room_id=target_room_id, batch_id=batch_id
                )
                # 🔴 SELECT list ต้องมีคอลัมน์ครบทุกตัวที่ `_shape_receipt_detail` อ่าน
                #    (ชุดเดียวกับ `get_receipt`/`render_documents_pdf`) และ **ต้องส่งผ่าน
                #    ตัวจัดรูปตัวเดียวกัน** — ถ้าที่นี่เรียก `_shape_receipt` เปล่า ๆ
                #    หน้ารายละเอียดชุดจะขาด `collection_title`/`collection_amount`/
                #    `student_no`/`room_name` โดยไม่มีอะไรฟ้อง (response_model ตัดเงียบ)
                rows = await conn.fetch(
                    f"""SELECT {_RECEIPT_COLUMNS}, R.line_items,
                               FC.title AS collection_title, FC.amount AS collection_amount,
                               FC.due_date AS collection_due_date,
                               S.student_no, R2.room_name, R2.room_code
                        FROM finance_receipts R
                        LEFT JOIN fee_collections FC ON R.collection_id = FC.id
                        LEFT JOIN students S ON R.student_id = S.id
                        JOIN rooms R2 ON R.room_id = R2.id
                        WHERE R.room_id = $1 AND R.batch_id = $2
                        ORDER BY {_DOC_DATE} DESC, R.id DESC""",
                    target_room_id, batch_id,
                )
                receipts = [cls._shape_receipt_detail(r) for r in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT_BATCH", entity_id=str(batch_id), status="success",
                    new_values={"count": len(receipts)},
                    endpoint_or_command="FinanceService.get_receipt_batch_detail",
                    execution_time_ms=exec_time,
                )
            return {"batch": batch, "receipts": receipts}
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="VIEW", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                entity_id=str(batch_id),
                endpoint="FinanceService.get_receipt_batch_detail", error=e, start_time=start_time,
            )
            raise e

    # =================================================================
    # เขียน
    # =================================================================
    @classmethod
    async def create_receipt_batch(
        cls, pool: asyncpg.Pool, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """สร้างชุดจากเลขที่เอกสารที่เลือก — **idempotent ด้วย "เซตของสมาชิก"**

        🔑 กดปุ่มเดิมซ้ำ (double-click / retry หลัง timeout) ต้องไม่สร้างชุดซ้ำ:
           ถ้าเซตของเลขที่ส่งมา **เท่ากับ** สมาชิก active ของชุด manual ที่มีอยู่แล้ว
           → คืนชุดนั้นพร้อม `created: false` ไม่เขียนอะไรเลย

           เกณฑ์นี้ใช้ได้เพราะ "ผลลัพธ์ที่ต้องการ" คือเซตของสมาชิก ไม่ใช่ "เหตุการณ์ที่เกิด"
           ⇒ ไม่ต้องมี `idempotency_key` จาก client แบบ `top_up_credit`
           (ที่นั่นกดซ้ำสร้างธุรกรรมใหม่จริง ๆ จึงต้องมีคีย์)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    # 🔒 ล็อกห้องเป็นคำสั่งแรก — ทำให้คำขอซ้ำสองอัน serialize กันจริง
                    #    (ถ้าไม่ล็อก สองคำขอที่มาพร้อมกันจะ "ไม่เห็น" ชุดของกันและกัน
                    #     แล้วสร้างชุดซ้ำสองชุด ทั้งที่เช็ค idempotency ไว้แล้ว)
                    await _lock_room_money(conn, target_room_id)

                    receipt_ids = await cls._resolve_receipt_ids(
                        conn, room_id=target_room_id, receipt_nos=req.receipt_nos
                    )
                    sorted_ids = sorted(receipt_ids)

                    # 🔁 มีชุด manual ที่มีสมาชิกชุดเดียวกันเป๊ะอยู่แล้วหรือยัง
                    #    ⚠️ เทียบด้วย `array_agg(... ORDER BY id)` — ชุดที่ไม่มีสมาชิก
                    #       จะได้ NULL ⇒ `NULL = $2` เป็น NULL (ไม่ match) ถูกต้องแล้ว
                    existing_id = await conn.fetchval(
                        """SELECT B.id FROM finance_receipt_batches B
                           WHERE B.room_id = $1 AND B.source = $2 AND B.deleted_at IS NULL
                             AND (SELECT array_agg(R.id ORDER BY R.id) FROM finance_receipts R
                                  WHERE R.batch_id = B.id AND R.deleted_at IS NULL
                                    AND R.status = 'active') = $3::int[]
                           ORDER BY B.id LIMIT 1""",
                        target_room_id, BATCH_SOURCE_MANUAL, sorted_ids,
                    )
                    if existing_id is not None:
                        batch = await cls._load_batch_summary(
                            conn, room_id=target_room_id, batch_id=existing_id
                        )
                        return {"batch": batch, "created": False}

                    batch_id = await conn.fetchval(
                        """INSERT INTO finance_receipt_batches
                               (room_id, title, source, note, created_by, created_by_name)
                           VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                        target_room_id, req.title, BATCH_SOURCE_MANUAL, req.note,
                        user_id, req.user_name or "—",
                    )
                    # ⚠️ UPDATE เดียวจบทั้ง "เพิ่มเข้า" และ "ย้ายออกจากชุดเดิม" — เพราะ `batch_id`
                    #    เป็นคอลัมน์เดียว ใบที่เคยอยู่ชุดอื่นจะถูกย้ายมาเงียบ ๆ ซึ่งเป็นพฤติกรรม
                    #    ที่ต้องการ (1 ใบอยู่ได้ชุดเดียว) แต่ต้องบอกในข้อความ API ด้วย
                    await conn.execute(
                        """UPDATE finance_receipts SET batch_id = $1
                           WHERE room_id = $2 AND id = ANY($3::int[]) AND deleted_at IS NULL""",
                        batch_id, target_room_id, receipt_ids,
                    )
                    batch = await cls._load_batch_summary(
                        conn, room_id=target_room_id, batch_id=batch_id
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT_BATCH", entity_id=str(batch_id),
                        status="success",
                        new_values={
                            "receipt_nos": list(req.receipt_nos),
                            "count": len(receipt_ids),
                            "title": req.title,
                            "source": BATCH_SOURCE_MANUAL,
                        },
                        endpoint_or_command="FinanceService.create_receipt_batch",
                        execution_time_ms=exec_time,
                    )
            return {"batch": batch, "created": True}
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="CREATE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                endpoint="FinanceService.create_receipt_batch", error=e, start_time=start_time,
            )
            raise e

    @classmethod
    async def set_batch_receipts(
        cls, pool: asyncpg.Pool, batch_id: int, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """**ตั้งสมาชิกทั้งชุด** = เพิ่มและถอดในคำขอเดียว (idempotent โดยธรรมชาติ)

        ใบที่เคยเป็นสมาชิกแต่หายไปจากลิสต์ → `batch_id = NULL` (ถูกถอดออก)
        ⚠️ ถ้าต้องการ "ถอดทั้งหมด" ให้ใช้ DELETE (ยุบชุด) — ส่งลิสต์ว่างมาจะได้ 400
           เพราะชุดที่ไม่มีสมาชิกเป็นสถานะที่ไม่มีประโยชน์และทำให้หน้าจอสับสน
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    await cls._load_batch_row(conn, room_id=target_room_id, batch_id=batch_id)
                    receipt_ids = await cls._resolve_receipt_ids(
                        conn, room_id=target_room_id, receipt_nos=req.receipt_nos
                    )
                    old_ids = await conn.fetch(
                        """SELECT id FROM finance_receipts
                           WHERE room_id = $1 AND batch_id = $2 ORDER BY id""",
                        target_room_id, batch_id,
                    )
                    # 1) ถอดใบที่ไม่อยู่ในลิสต์ใหม่ (รวมใบที่ถูกลบ/ยกเลิกไปแล้วด้วย —
                    #    ไม่ต้องแตะ เพราะไม่มีทางกลับมาเป็นสมาชิก active)
                    await conn.execute(
                        """UPDATE finance_receipts SET batch_id = NULL
                           WHERE room_id = $1 AND batch_id = $2 AND deleted_at IS NULL
                             AND NOT (id = ANY($3::int[]))""",
                        target_room_id, batch_id, receipt_ids,
                    )
                    # 2) ย้ายใบในลิสต์เข้าชุดนี้ (ถ้าอยู่ชุดอื่นมาก็ย้ายมา)
                    await conn.execute(
                        """UPDATE finance_receipts SET batch_id = $1
                           WHERE room_id = $2 AND id = ANY($3::int[]) AND deleted_at IS NULL""",
                        batch_id, target_room_id, receipt_ids,
                    )
                    batch = await cls._load_batch_summary(
                        conn, room_id=target_room_id, batch_id=batch_id
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT_BATCH", entity_id=str(batch_id),
                        status="success",
                        old_values={"receipt_ids": [r["id"] for r in old_ids]},
                        new_values={"receipt_nos": list(req.receipt_nos), "receipt_ids": receipt_ids},
                        endpoint_or_command="FinanceService.set_batch_receipts",
                        execution_time_ms=exec_time,
                    )
            return {"batch": batch, "created": False}
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="UPDATE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                entity_id=str(batch_id),
                endpoint="FinanceService.set_batch_receipts", error=e, start_time=start_time,
            )
            raise e

    @classmethod
    async def update_receipt_batch(
        cls, pool: asyncpg.Pool, batch_id: int, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """เปลี่ยนชื่อ/โน้ตของชุด (PATCH — ส่งมาเฉพาะฟิลด์ที่ต้องการแก้)

        ⚠️ `title` ตั้งเป็น `None` ได้ = กลับไปใช้ชื่อที่หน้าจอประกอบเอง (ส่ง `null` มาชัด ๆ)
           ต่างจาก "ไม่ส่งมา" ซึ่งหมายถึง "ไม่แก้" — พฤติกรรมนี้มาจาก `exclude_unset=True`
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    # 🔒 `FOR UPDATE` — อ่านค่าที่จะลง `old_values` ต้องล็อกแถวก่อน
                    #    (กฎ backend: อ่านแล้วเอาไป UPDATE ต้องล็อก) และการล็อกยังกัน
                    #    สองคำขอที่แก้ชุดเดียวกันพร้อมกันเขียนทับกันแบบอ่านไม่ออก
                    old = await conn.fetchrow(
                        """SELECT title, note FROM finance_receipt_batches
                           WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE""",
                        batch_id, target_room_id,
                    )
                    if old is None:
                        raise RoomNotFoundError("ไม่พบชุดเอกสารนี้ในห้อง (อาจถูกยุบไปแล้ว)")

                    data = {
                        k: v for k, v in req.model_dump(exclude_unset=True).items()
                        if k in _BATCH_PATCHABLE
                    }
                    if not data:
                        raise ValueError("ไม่มีฟิลด์ที่จะแก้ไข")

                    set_parts, params, idx = [], [], 1
                    for col in _BATCH_PATCHABLE:          # เรียงตาม allowlist = SQL คงที่ทุกรอบ
                        if col in data:
                            set_parts.append(f"{col} = ${idx}")
                            params.append(data[col]); idx += 1
                    batch_ph = idx; params.append(batch_id); idx += 1
                    room_ph = idx; params.append(target_room_id)
                    await conn.execute(
                        f"""UPDATE finance_receipt_batches
                            SET {', '.join(set_parts)}, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ${batch_ph} AND room_id = ${room_ph} AND deleted_at IS NULL""",
                        *params,
                    )
                    batch = await cls._load_batch_summary(
                        conn, room_id=target_room_id, batch_id=batch_id
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT_BATCH", entity_id=str(batch_id),
                        status="success",
                        old_values={k: old[k] for k in data},
                        new_values=data,
                        endpoint_or_command="FinanceService.update_receipt_batch",
                        execution_time_ms=exec_time,
                    )
            return {"batch": batch, "created": False}
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="UPDATE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                entity_id=str(batch_id),
                endpoint="FinanceService.update_receipt_batch", error=e, start_time=start_time,
            )
            raise e

    @classmethod
    async def delete_receipt_batch(
        cls, pool: asyncpg.Pool, batch_id: int, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ยุบชุด = **ถอดสมาชิกออกทั้งหมด + soft delete ตัวชุด** (เอกสารไม่ถูกแตะเลย)

        🔴 ลำดับสำคัญ: ถอดสมาชิก **ก่อน** soft delete ชุด — ถ้าสลับกัน คำขอที่จะ retry
           จะหาไม่เจอชุด (deleted_at แล้ว) ⇒ เหลือใบที่ยังชี้ `batch_id` ที่ชี้ชุดที่ถูกลบ
           ค้างอยู่ = ข้อมูลขัดกันเองที่ไม่มีอะไรฟ้อง (FK ยังผ่านเพราะแถวยังอยู่)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    await _lock_room_money(conn, target_room_id)

                    old = await cls._load_batch_row(conn, room_id=target_room_id, batch_id=batch_id)
                    # ⚠️ **ไม่กรอง `deleted_at`** ของใบ: ใบที่ถูกลบไปแล้วก็ต้องถูกปลด
                    #    `batch_id` ด้วย ไม่งั้นมันจะยังนับเป็นสมาชิกของชุดที่ถูกลบ
                    #    (และวันหนึ่งถ้ามีการกู้คืนใบนั้น มันจะโผล่มาในชุดที่ครูคิดว่ายุบไปแล้ว)
                    members = await conn.fetch(
                        """SELECT id FROM finance_receipts
                           WHERE room_id = $1 AND batch_id = $2 ORDER BY id""",
                        target_room_id, batch_id,
                    )
                    await conn.execute(
                        "UPDATE finance_receipts SET batch_id = NULL WHERE room_id = $1 AND batch_id = $2",
                        target_room_id, batch_id,
                    )
                    await conn.execute(
                        """UPDATE finance_receipt_batches
                           SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                           WHERE id = $1 AND room_id = $2""",
                        batch_id, target_room_id,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT_BATCH", entity_id=str(batch_id),
                        status="success",
                        old_values={
                            "title": old["title"], "source": old["source"],
                            "receipt_ids": [r["id"] for r in members],
                        },
                        endpoint_or_command="FinanceService.delete_receipt_batch",
                        execution_time_ms=exec_time,
                    )
            # คืน "จำนวนใบที่ถูกปลด" ให้ผู้ใช้ยืนยันผลได้ (ชุดถูกลบแล้ว ⇒ ไม่มี summary ให้คืน)
            return {"batch_id": batch_id, "detached_count": len(members)}
        except Exception as e:
            await cls._log_batch_failure(
                pool, action="DELETE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=target_room_id, user_id=user_id,
                entity_id=str(batch_id),
                endpoint="FinanceService.delete_receipt_batch", error=e, start_time=start_time,
            )
            raise e

    # =================================================================
    # บันทึกความล้มเหลว
    # =================================================================
    @staticmethod
    async def _log_batch_failure(
        pool: asyncpg.Pool, *, action: str, actor_identifier: str, client_source: str,
        room_id: Optional[int], user_id: Optional[int], endpoint: str, error: Exception,
        start_time: float, entity_id: Optional[str] = None,
    ) -> None:
        """เขียน audit `status="failed"` บน connection ใหม่ — **ห้ามให้มันกลบ error เดิม**

        ⚠️ ต้อง acquire connection ใหม่ เพราะ transaction เดิมอาจอยู่ในสภาพ abort
           (กฎเดียวกับ `top_up_credit`)
        """
        exec_time = int((time.time() - start_time) * 1000)
        try:
            async with pool.acquire() as log_conn:
                await service_logger.log(
                    conn=log_conn, action=action, actor_identifier=actor_identifier,
                    client_source=client_source, room_id=room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT_BATCH", entity_id=entity_id,
                    status="failed", error_detail=str(error),
                    endpoint_or_command=endpoint, execution_time_ms=exec_time,
                )
        except Exception:
            pass
