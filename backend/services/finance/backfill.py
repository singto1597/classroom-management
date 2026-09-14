"""[BACKFILL] สร้าง journal ย้อนหลังให้แถว legacy ที่ตกหล่นจาก dual-write

## ปัญหาที่ไฟล์นี้แก้

`finance_transactions` (single-entry) และ `journal_entries` (double-entry) ถูกเขียนคู่กัน
ใน transaction เดียวกัน (dual-write) ตั้งแต่ `CUTOFF_DATE = 2026-09-01` เป็นต้นมา
แต่มีแถว legacy กลุ่มหนึ่งที่ **ไม่มี journal คู่กัน** เกิดขึ้นได้ 2 ทาง:

1. **ช่วงเปลี่ยนผ่าน** — แถวที่ถูกบันทึกในช่วงเวลาสั้น ๆ หลังเที่ยงคืนไทยของวันที่ 1 ก.ย.
   ก่อนที่โค้ด dual-write จะขึ้นจริง (แถวถูกเขียนลง legacy แล้ว แต่โค้ดตอนนั้นยังไม่เขียน journal)
2. **รอยรั่วที่ปิดไปแล้ว** — `_confirm_single_payment` เคย `pass` (ข้าม dual-write เงียบ ๆ)
   เมื่อห้องยังไม่มี ledger รายได้ ก่อนจะถูกปิดด้วย FIX A (`_find_or_create_default_income_category`)
   ⇒ การรับชำระเงินของห้องกลุ่มนั้นลง legacy แต่ไม่มี journal

**ผลที่ผู้ใช้เห็น:** ผู้อ่านสองฝั่งแบ่งงานกันตาม "วันที่ไทย" — ฝั่ง legacy รับเฉพาะวันที่ไทย
ก่อนเส้นตัด และฝั่ง journal รับตั้งแต่วันที่ไทยของเส้นตัดเป็นต้นไป ⇒ แถวกลุ่มนี้
**ไม่มีผู้อ่านฝั่งใดรับเลย** ทั้งที่ข้อมูลยังอยู่ใน DB ครบ ⇒ หายจากหน้าประวัติ และไม่โผล่ในงบการเงิน

## หลักการที่ยึด (อ่านก่อนแก้)

- **แตะเฉพาะแถวที่ "วันที่ไทย" >= CUTOFF_DATE เท่านั้น** — แถวก่อนเส้นตัด *ไม่มี* journal โดยเจตนา
  (dual-write ยังไม่เริ่ม) ถ้าไปสร้างให้จะ **เพิ่มข้อมูลเข้างบการเงินที่ไม่มีมาก่อน** ⇒ งบทดลอง/
  งบดุลเพี้ยนทันที เพราะงบเหล่านั้นอ่าน `journal_lines` เป็นแหล่งเดียว
- **ข้ามแถวที่ `deleted_at IS NOT NULL`** — แถวนั้นถูก revert ไปแล้ว (ยอดเงินถูกคืนกลับแล้ว)
  ถ้าสร้าง journal ให้ journal จะมีสถานะ `posted` ⇒ **ผู้อ่านฝั่ง v2 จะคืนรายการผีกลับมา**
- **idempotent โดยโครงสร้าง** — หาแถวที่ยังไม่มี journal คู่แล้วเท่านั้น ⇒ รันซ้ำไม่สร้างซ้ำ
- **จับกลุ่ม transfer ก่อน** — เงินโอน 1 ครั้ง = แถว legacy 2 แถว แต่ journal มีใบเดียว
  ⇒ ต้องสร้างใบเดียว ไม่ใช่สองใบ (ไม่งั้นนับซ้ำ)
- **metadata ต้องเป็นคีย์ชุดเดียวกับ dual-write ปกติ** (`legacy_transaction_id` /
  `transfer_group_id` / `student_payment_id`) ไม่งั้น `revert_transaction` จะ void journal
  ที่ backfill มาให้ไม่ได้ ⇒ กลายเป็นรายการที่ยกเลิกไม่ได้
- **`transaction_date` ต้องเป็นเวลาที่เงินเคลื่อนไหวจริง** ไม่ใช่ NOW() ไม่งั้นรายการย้อนหลัง
  ไปกองที่วันนี้ และเดือนที่แล้วก็ยังขาดรายการอยู่ดี
- **dry-run เป็นค่าเริ่มต้น** และทำใน transaction ที่ `rollback()` ทิ้ง ⇒ การจำลองตรงกับของจริง
  แม้แต่ ledger ที่ต้อง auto-provision ก็ถูกนับรวมในรายงาน

## ความสัมพันธ์กับ `reconcile_balances`

คนละเรื่องกัน: `reconcile` แก้ **ผลต่างของยอดคงเหลือ** (`finance_accounts.balance` vs asset ledger)
ส่วนไฟล์นี้แก้ **แถวที่ขาด journal ทั้งใบ** ใช้ด้วยกันได้ — แนะนำรัน `reconcile_finance.py`
ตามหลัง backfill เพื่อยืนยันว่ายอดคงเหลือยังตรงกัน
"""
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import asyncpg

from .constants import CUTOFF_DATE, THAI_TZ, DEFAULT_INCOME_CATEGORIES
from .helpers import _as_utc, _thai_day_start
from .base import _lock_room_money, service_logger

# จำนวนเงินที่ยอมรับว่า "สองขาเท่ากัน" (บาท) — ครึ่งสตางค์ กัน binary noise ของ float
_AMOUNT_EPS = 0.005

# prefix ที่ `transfer_money` ใส่ให้แถว legacy ขาออก — ต้องถอดออกก่อนใช้เป็น description ของ journal
_TRANSFER_OUT_PREFIX = "โอนออก: "

# ป้ายชื่อชนิด journal ที่จะสร้าง — ใช้ในรายงาน/หน้าจอ
KIND_MANUAL = "manual_transaction"
KIND_PAYMENT = "student_payment"
KIND_TRANSFER = "transfer"

KIND_LABELS = {
    KIND_MANUAL: "รายการทั่วไป",
    KIND_PAYMENT: "รับชำระเงินนักเรียน",
    KIND_TRANSFER: "โอนเงินระหว่างบัญชี",
}


def _fmt_thai(dt: Optional[datetime]) -> str:
    """แสดง instant เป็นเวลาไทยแบบอ่านง่าย (ใช้ในรายงานเท่านั้น)."""
    if dt is None:
        return "—"
    return dt.astimezone(THAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


class BackfillMixin:
    # ------------------------------------------------------------------ อ่าน
    @classmethod
    async def _fetch_backfill_candidates(cls, conn: asyncpg.Connection, room_id: int) -> List[dict]:
        """แถว legacy ที่ **"วันที่ไทย" >= CUTOFF_DATE**, ยังไม่ถูกลบ และ **ยังไม่มี journal คู่กัน**.

        [TIMEZONE] `T.created_at` เป็น TIMESTAMP (naive) ที่เก็บเวลา UTC ⇒ unwrap ฝั่ง parameter
        ด้วย `AT TIME ZONE 'UTC'` แล้วเทียบกับต้นวันไทยของเส้นตัด (ท่าเดียวกับ `transactions.py`)
        ห้ามใช้ `DATE(T.created_at)` — จะได้ปฏิทิน UTC ซึ่งเป็นคนละใบกับที่ใช้แบ่งยุค

        [IDEMPOTENT] เงื่อนไข `NOT EXISTS` นับ journal **ทุกสถานะ** (รวม voided/deleted)
        ⇒ ถ้าแถวนี้เคยถูก dual-write ไปแล้วแม้จะถูก revert ทีหลัง ก็จะไม่ถูกสร้างซ้ำ
        (แถวที่ถูก revert ถูกตัดออกด้วย `T.deleted_at IS NULL` อยู่แล้ว — สองเงื่อนไขเสริมกัน)
        """
        return await conn.fetch(
            """
            SELECT T.id, T.account_id, T.category_id, T.amount, T.description,
                   T.transaction_type, T.slip_image_url, T.transfer_group_id,
                   T.student_payment_id, T.recorded_by, T.created_at
            FROM finance_transactions T
            WHERE T.room_id = $1
              AND T.deleted_at IS NULL
              AND T.created_at >= ($2::timestamptz AT TIME ZONE 'UTC')
              AND NOT EXISTS (
                  SELECT 1 FROM journal_entries JE
                  WHERE JE.room_id = T.room_id
                    AND (
                        JE.metadata->>'legacy_transaction_id' = T.id::text
                        OR (T.transfer_group_id IS NOT NULL
                            AND JE.metadata->>'transfer_group_id' = T.transfer_group_id::text)
                    )
              )
            ORDER BY T.created_at ASC, T.id ASC
            """,
            room_id, _thai_day_start(CUTOFF_DATE),
        )

    @classmethod
    async def _ledger_names(cls, conn: asyncpg.Connection, ledger_ids: List[int]) -> Dict[int, str]:
        """map ledger_id → 'account_code ชื่อบัญชี' สำหรับแสดงในรายงาน (อ่านล้วน)."""
        ids = sorted({int(i) for i in ledger_ids if i is not None})
        if not ids:
            return {}
        rows = await conn.fetch(
            "SELECT id, account_code, account_name FROM accounting_ledgers WHERE id = ANY($1::int[])",
            ids,
        )
        return {r["id"]: f"{r['account_code']} {r['account_name']}" for r in rows}

    # --------------------------------------------------------------- วางแผน
    @classmethod
    async def _count_prior_adjustments(cls, conn: asyncpg.Connection, room_id: int) -> int:
        """นับ journal ปรับปรุงยอด (`reconcile_balances`) ที่ยังไม่ถูก void ของห้องนี้.

        ⚠️ **อันตรายที่ต้องรายงาน ไม่ใช่ปล่อยผ่าน**: `reconcile_balances` แก้ "ผลต่างของยอดคงเหลือ"
        ด้วยการออก journal `Dr สินทรัพย์ / Cr ทุน 3001` — ซึ่งแก้ **ผลต่างตัวเดียวกับ** ที่ backfill
        กำลังจะแก้อีกทาง (แถวที่ตกหล่นคือสาเหตุที่ยอดบัญชีคู่ขาดไป ⇒ มักเป็นตัวที่ทำให้เกิดผลต่างนั้น)

        ถ้าห้องนั้นเคยถูกรัน reconcile --apply ไปก่อน ⇒ สินทรัพย์ถูกปรับขึ้นไปแล้วรอบหนึ่ง
        พอ backfill เพิ่มการเคลื่อนไหวจริงเข้าไปอีก ⇒ **ยอดสินทรัพย์เบิ้ล** (ledger = 2 เท่า ของ legacy)

        ตรวจไม่เจอด้วยเงื่อนไข `NOT EXISTS` ปกติ เพราะ journal ปรับปรุงยอด **ไม่มี**
        `legacy_transaction_id` ให้อ้างอิง (มันเป็นค่าระดับ "บัญชี" ไม่ใช่ระดับ "รายการ")

        ⇒ คำตอบคือ **รายงานให้ผู้ใช้รู้** แล้วให้รัน `reconcile_finance.py` ซ้ำหลัง backfill
        (รอบสองจะเห็น ledger เกิน legacy แล้วออกรายการปรับปรุง "ทางกลับ" ให้เอง — ฝั่งรายได้
        ไม่ถูกแตะ จึงได้ยอดถูกทั้งสองฝั่ง)
        """
        return await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'adjustment'
                 AND deleted_at IS NULL AND status <> 'voided'""",
            room_id,
        )

    @classmethod
    async def _plan_one_manual(
        cls, conn: asyncpg.Connection, room_id: int, row: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """แถว legacy ที่ไม่ใช่โอนเงิน/รับชำระ → journal 2 บรรทัดตาม `transaction_type`."""
        if row["account_id"] is None:
            return None, {"legacy_id": row["id"], "reason": "บัญชีสินทรัพย์ถูกลบไปแล้ว (account_id = NULL)"}
        if row["category_id"] is None:
            return None, {"legacy_id": row["id"], "reason": "ไม่มีหมวดหมู่ (category_id = NULL)"}
        if row["transaction_type"] not in ("income", "expense"):
            return None, {
                "legacy_id": row["id"],
                "reason": f"transaction_type ไม่ใช่ income/expense (ได้ {row['transaction_type']!r})",
            }

        asset_ledger_id = await cls._resolve_asset_ledger(conn, room_id, row["account_id"])
        category_ledger_id = await cls._resolve_category_ledger(
            conn, room_id, row["category_id"], row["transaction_type"]
        )
        amount = float(row["amount"])
        if row["transaction_type"] == "income":
            lines = [
                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"รับเงินเข้าบัญชี: {row['account_id']}"},
                {"ledger_id": category_ledger_id, "debit": 0, "credit": amount,
                 "line_description": f"รายได้: {row['description']}"},
            ]
        else:
            lines = [
                {"ledger_id": category_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"ค่าใช้จ่าย: {row['description']}"},
                {"ledger_id": asset_ledger_id, "debit": 0, "credit": amount,
                 "line_description": f"เงินออกจากบัญชี: {row['account_id']}"},
            ]
        return {
            "kind": KIND_MANUAL,
            "legacy_ids": [row["id"]],
            "group_id": None,
            "amount": amount,
            "occurred_at": _as_utc(row["created_at"]),
            "description": row["description"],
            "reference_type": "manual_transaction",
            "reference_id": str(row["id"]),
            "recorded_by": row["recorded_by"],
            "slip_image_url": row["slip_image_url"],
            "metadata": {"legacy_transaction_id": row["id"]},
            "lines": lines,
        }, None

    @classmethod
    async def _plan_one_payment(
        cls, conn: asyncpg.Connection, room_id: int, row: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """แถว legacy ของการรับชำระเงิน → Dr สินทรัพย์ / Cr รายได้ 'เก็บเงินห้องปกติ'.

        ลอตรรกะจาก `_confirm_single_payment` เป๊ะ ๆ รวม FIX A (หา/สร้างหมวดรายได้ค่าเริ่มต้น)
        เพื่อให้ขาเครดิตลง ledger ตัวเดียวกับที่ dual-write ปกติใช้
        """
        if row["account_id"] is None:
            return None, {"legacy_id": row["id"], "reason": "บัญชีรับเงินถูกลบไปแล้ว (account_id = NULL)"}

        asset_ledger_id = await cls._resolve_asset_ledger(conn, room_id, row["account_id"])
        revenue_ledger_id = await cls._find_revenue_ledger_by_name(
            conn, room_id, account_name=DEFAULT_INCOME_CATEGORIES[0]
        )
        if revenue_ledger_id is None:
            legacy_cat_id = await cls._find_or_create_default_income_category(conn, room_id)
            if legacy_cat_id:
                revenue_ledger_id = await cls._resolve_category_ledger(conn, room_id, legacy_cat_id, "income")
        if revenue_ledger_id is None:
            return None, {
                "legacy_id": row["id"],
                "reason": f"หา/สร้าง ledger รายได้ '{DEFAULT_INCOME_CATEGORIES[0]}' ไม่ได้",
            }

        amount = float(row["amount"])
        return {
            "kind": KIND_PAYMENT,
            "legacy_ids": [row["id"]],
            "group_id": None,
            "amount": amount,
            "occurred_at": _as_utc(row["created_at"]),
            "description": row["description"],
            "reference_type": "student_payment",
            "reference_id": str(row["student_payment_id"]),
            "recorded_by": row["recorded_by"],
            "slip_image_url": row["slip_image_url"],
            "metadata": {
                "student_payment_id": row["student_payment_id"],
                "legacy_transaction_id": row["id"],
            },
            "lines": [
                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                 "line_description": f"รับเงินจากนักเรียน (student_payment #{row['student_payment_id']})"},
                {"ledger_id": revenue_ledger_id, "debit": 0, "credit": amount,
                 "line_description": f"รายได้: {row['description']}"},
            ],
        }, None

    @classmethod
    async def _plan_one_transfer(
        cls, conn: asyncpg.Connection, room_id: int, group_id: int, legs: List[dict]
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """กลุ่มโอนเงิน → journal **ใบเดียว** (Dr ปลายทาง / Cr ต้นทาง) จากแถว legacy 2 ขา.

        ⚠️ 1 กลุ่ม = 1 journal ห้ามสร้างแยกขา ไม่งั้นยอดโอนถูกนับซ้ำในงบการเงิน
        """
        outs = [t for t in legs if t["transaction_type"] == "expense"]
        ins = [t for t in legs if t["transaction_type"] == "income"]
        if len(outs) != 1 or len(ins) != 1:
            return None, {
                "group_id": group_id,
                "reason": f"กลุ่มโอนเงินมีขาไม่ครบ 2 ขา (expense={len(outs)}, income={len(ins)})",
            }
        out_leg, in_leg = outs[0], ins[0]
        if abs(float(out_leg["amount"]) - float(in_leg["amount"])) >= _AMOUNT_EPS:
            return None, {
                "group_id": group_id,
                "reason": (
                    f"สองขาของการโอนมีจำนวนเงินไม่เท่ากัน "
                    f"(ออก {float(out_leg['amount']):,.2f} / เข้า {float(in_leg['amount']):,.2f})"
                ),
            }
        if out_leg["account_id"] is None or in_leg["account_id"] is None:
            return None, {"group_id": group_id, "reason": "บัญชีต้นทาง/ปลายทางถูกลบไปแล้ว (account_id = NULL)"}

        ledger_from = await cls._resolve_asset_ledger(conn, room_id, out_leg["account_id"])
        ledger_to = await cls._resolve_asset_ledger(conn, room_id, in_leg["account_id"])
        amount = float(out_leg["amount"])
        # 💡 ถอด prefix "โอนออก: " ที่ `transfer_money` ใส่ให้แถว legacy ออก แล้วใช้ข้อความดิบ
        # ⇒ ได้ description ตัวเดียวกับที่ dual-write สดเขียน (`description=req.description or "Transfer"`)
        # ⇒ journal ที่ backfill กับที่เขียนสดแยกกันไม่ออกใน UI/export
        desc = out_leg["description"] or ""
        if desc.startswith(_TRANSFER_OUT_PREFIX):
            desc = desc[len(_TRANSFER_OUT_PREFIX):].strip()
        return {
            "kind": KIND_TRANSFER,
            "legacy_ids": [out_leg["id"], in_leg["id"]],
            "group_id": group_id,
            "amount": amount,
            # ทั้งสองขาถูก INSERT ใน transaction เดียวกัน ⇒ created_at เท่ากันเป๊ะ
            # ใช้ค่าที่น้อยที่สุดเพื่อให้ผลซ้ำได้เสมอ (deterministic)
            "occurred_at": _as_utc(min(out_leg["created_at"], in_leg["created_at"])),
            "description": desc or "Transfer",
            "reference_type": "transfer",
            "reference_id": str(group_id),
            "recorded_by": out_leg["recorded_by"],
            "slip_image_url": out_leg["slip_image_url"],
            "metadata": {
                "transfer_group_id": group_id,
                "legacy_transaction_id": out_leg["id"],
                "legacy_transaction_ids": [out_leg["id"], in_leg["id"]],
            },
            "lines": [
                {"ledger_id": ledger_to, "debit": amount, "credit": 0,
                 "line_description": f"รับโอนเข้าบัญชี: {in_leg['account_id']}"},
                {"ledger_id": ledger_from, "debit": 0, "credit": amount,
                 "line_description": f"โอนออกจากบัญชี: {out_leg['account_id']}"},
            ],
        }, None

    @classmethod
    async def _plan_backfill_journals(
        cls, conn: asyncpg.Connection, room_id: int, rows: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """แปลงแถว legacy ที่ตกหล่น → แผนการสร้าง journal (ยังไม่เขียน) + รายการที่ข้าม.

        ⚠️ ฟังก์ชันนี้ **อาจสร้าง ledger ใหม่** (auto-provision ผ่าน `_resolve_*_ledger`)
        จึงต้องถูกเรียกภายใน transaction ที่ผู้เรียกรู้ตัว (dry-run = rollback ทิ้ง)
        """
        plans: List[dict] = []
        skipped: List[dict] = []

        # จับกลุ่มโอนเงินก่อน — 1 กลุ่ม = 1 journal
        transfer_groups: Dict[int, List[dict]] = {}
        for r in rows:
            if r["transfer_group_id"] is not None:
                transfer_groups.setdefault(r["transfer_group_id"], []).append(r)
                continue
            try:
                if r["student_payment_id"] is not None:
                    plan, skip = await cls._plan_one_payment(conn, room_id, r)
                else:
                    plan, skip = await cls._plan_one_manual(conn, room_id, r)
            except ValueError as e:
                # `_resolve_*_ledger` raise เมื่อแถว legacy ต้นทางถูกลบจริง (ไม่ใช่แค่ NULL)
                # ⇒ รายงานเป็น "ข้าม" ไม่ใช่ล้มทั้งสคริปต์ เพราะแถวอื่นยัง backfill ได้
                skipped.append({"legacy_id": r["id"], "reason": str(e)})
                continue
            if plan:
                plans.append(plan)
            if skip:
                skipped.append(skip)

        for group_id, legs in transfer_groups.items():
            try:
                plan, skip = await cls._plan_one_transfer(conn, room_id, group_id, legs)
            except ValueError as e:
                skipped.append({"group_id": group_id, "reason": str(e)})
                continue
            if plan:
                plans.append(plan)
            if skip:
                skipped.append(skip)

        # 🛡️ ตรวจ Dr == Cr ก่อนเขียน — journal ที่ไม่สมดุลจะทำให้งบทดลองเพี้ยนถาวร
        balanced: List[dict] = []
        for p in plans:
            dr = round(sum(float(ln["debit"]) for ln in p["lines"]), 4)
            cr = round(sum(float(ln["credit"]) for ln in p["lines"]), 4)
            if abs(dr - cr) >= 0.005 or dr <= 0:
                skipped.append({
                    "legacy_id": p["legacy_ids"][0] if p["legacy_ids"] else None,
                    "group_id": p["group_id"],
                    "reason": f"ยอดเดบิต/เครดิตไม่สมดุล (Dr {dr:,.4f} / Cr {cr:,.4f})",
                })
                continue
            balanced.append(p)

        # เติมชื่อ ledger ไว้ให้รายงานอ่านออก (ไม่กระทบการเขียน)
        names = await cls._ledger_names(conn, [ln["ledger_id"] for p in balanced for ln in p["lines"]])
        for p in balanced:
            for ln in p["lines"]:
                ln["ledger_label"] = names.get(ln["ledger_id"], f"ledger #{ln['ledger_id']}")

        # เรียงตามเวลาที่เกิดจริง เพื่อให้ลำดับการสร้างอ่านรู้เรื่อง
        balanced.sort(key=lambda p: (p["occurred_at"], p["reference_id"]))
        return balanced, skipped

    # ---------------------------------------------------------------- เขียน
    @classmethod
    async def _write_backfill_journals(
        cls, conn: asyncpg.Connection, room_id: int, plans: List[dict]
    ) -> List[str]:
        """เขียน journal ตามแผน + ติด provenance ใน metadata. คืน list ของ journal UUID."""
        created: List[str] = []
        for p in plans:
            entry_id = await cls._insert_journal_entry(
                conn, room_id,
                reference_type=p["reference_type"],
                reference_id=p["reference_id"],
                description=p["description"],
                slip_image_url=p["slip_image_url"],
                recorded_by=p["recorded_by"],
                metadata={
                    **p["metadata"],
                    # 🔖 รอยประทับ: แถวนี้สร้างโดยสคริปต์ backfill ไม่ใช่ dual-write สด
                    # ⇒ ใช้ตามรอย/ตรวจสอบย้อนหลังได้ และเป็นเงื่อนไขให้ query เฉพาะของที่ backfill
                    #    (เช่น `WHERE metadata->>'backfilled' = 'true'`) หากต้องย้อนกลับด้วยมือ
                    "backfilled": True,
                    "backfill_source": "backfill_missing_journals",
                    "backfill_legacy_ids": p["legacy_ids"],
                },
                lines=[
                    {"ledger_id": ln["ledger_id"], "debit": ln["debit"],
                     "credit": ln["credit"], "line_description": ln["line_description"]}
                    for ln in p["lines"]
                ],
                transaction_date=p["occurred_at"],
            )
            created.append(str(entry_id))
        return created

    # ------------------------------------------------------------- entry point
    @classmethod
    async def backfill_missing_journals(
        cls,
        pool: asyncpg.Pool,
        *,
        room_id: Optional[int] = None,
        server_id: Optional[int] = None,
        apply: bool = False,
    ) -> dict:
        """สร้าง journal ย้อนหลังให้แถว legacy ที่ตกหล่นจาก dual-write (ops tool).

        - `apply=False` (ค่าเริ่มต้น) = dry-run: วางแผนครบทุกขั้น (รวม ledger ที่ต้อง provision)
          แล้ว **rollback ทิ้ง** ⇒ รายงานตรงกับสิ่งที่จะเกิดขึ้นจริงโดยไม่เขียนอะไรลง DB
        - `apply=True` = เขียนจริงทั้งห้องใน **transaction เดียว** พร้อม audit log
          ⇒ ห้องใดห้องหนึ่งพลาด = ไม่มีอะไรถูกเขียนครึ่งทาง

        ⚠️ Ops tool — ไม่ได้ล็อก **แถว** legacy ระหว่างวางแผน แนะนำให้รันช่วงที่ไม่มีรายการสด
        (เหมือน `reconcile_balances`) แต่ยึด advisory lock ของห้องไว้ ⇒ ถ้ารันระหว่างที่มี
        รายการสด มันจะรอจนเส้นทางเงินปล่อยล็อก แทนที่จะวางแผนบนยอดที่กำลังขยับ

        คืน dict รายงาน (ตัวเลขเป็น float, journal id เป็น str)
        """
        start_time = time.time()
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            room_name = await conn.fetchval(
                "SELECT room_name FROM rooms WHERE id = $1", resolved_room_id
            )

            tx = conn.transaction()
            await tx.start()
            committed = False
            try:
                # 🔒 ล็อกห้องก่อนวางแผน/เขียนใด ๆ (protocol เดียวกันทั้งระบบ)
                #    ต้องอยู่ใน try เพราะ tx.start() ไปแล้ว — raise ที่นี่ต้องถูก rollback
                await _lock_room_money(conn, resolved_room_id)

                candidates = await cls._fetch_backfill_candidates(conn, resolved_room_id)
                plans, skipped = await cls._plan_backfill_journals(conn, resolved_room_id, candidates)

                created_ids: List[str] = []
                if apply and plans:
                    created_ids = await cls._write_backfill_journals(conn, resolved_room_id, plans)

                by_kind: Dict[str, int] = {}
                for p in plans:
                    by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1

                # ⚠️ รายงาน (ไม่บล็อก) ถ้าห้องนี้เคยถูกรัน reconcile มาก่อน — ดู docstring ของ
                # `_count_prior_adjustments` ว่าทำไมถึงต้องให้ผู้ใช้รัน reconcile ซ้ำหลัง backfill
                prior_adjustments = await cls._count_prior_adjustments(conn, resolved_room_id)

                report = {
                    "room_id": resolved_room_id,
                    "room_name": room_name,
                    "apply": apply,
                    "cutoff_date": CUTOFF_DATE.isoformat(),
                    "candidates": len(candidates),
                    "journals_planned": len(plans),
                    "journals_created": len(created_ids),
                    "created_journal_ids": created_ids,
                    "total_amount": round(sum(float(p["amount"]) for p in plans), 4),
                    "by_kind": by_kind,
                    "prior_adjustments": prior_adjustments,
                    "plans": plans,
                    "skipped": skipped,
                }

                if apply and created_ids:
                    await service_logger.log(
                        conn=conn, action="BACKFILL", actor_identifier="SYSTEM", client_source="script",
                        room_id=resolved_room_id, entity_type="FINANCE_BACKFILL",
                        entity_id=str(resolved_room_id), status="success",
                        new_values={
                            "candidates": len(candidates),
                            "journals_created": len(created_ids),
                            "total_amount": report["total_amount"],
                            "by_kind": by_kind,
                            "skipped": len(skipped),
                            "prior_adjustments": prior_adjustments,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                        },
                        endpoint_or_command="FinanceService.backfill_missing_journals",
                    )

                # 🛡️ แยกสองทางให้ชัด — ห้ามยุบเป็น `tx.commit()` ลอย ๆ
                #    `_plan_backfill_journals` **เขียนได้** (auto-provision ledger ผ่าน
                #    `_resolve_*_ledger` เมื่อห้องนั้นยังไม่มี ledger ของบัญชี/หมวดนั้น)
                #    ⇒ ถ้า commit ในโหมด dry-run ledger จะค้างใน DB จริง ทั้งที่สคริปต์
                #    รายงานผู้ใช้ว่า "ตรวจแล้วไม่มีการเขียนลงฐานข้อมูล" — ผู้ใช้ที่เชื่อ
                #    คำรายงานจะเข้าใจผิดว่าการซ้อมรบไม่แตะ DB แล้วรันบน production ได้
                if apply:
                    await tx.commit()
                else:
                    await tx.rollback()
                committed = True
                return report
            finally:
                # error ระหว่างทางตกลงมาที่นี่ ⇒ ไม่มีอะไรถูกเขียนค้าง
                if not committed:
                    try:
                        await tx.rollback()
                    except Exception:  # noqa: BLE001 — transaction อาจถูกปิดไปแล้ว
                        pass
