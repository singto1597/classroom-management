"""🧮 [FIN-V2 / P1.5] เครื่องจัดสรรเงินรับ — pure engine + preview (อ่านอย่างเดียว)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องแยก engine
═══════════════════════════════════════════════════════════════════════════════
หน้าจอรับเงิน (P2.3) ต้องโชว์ "เงินก้อนนี้จะไปลงบิลไหนเท่าไร" ก่อนครูกดยืนยัน และ
P2.1 ต้องเขียนผลลัพธ์ชุดเดียวกันลง DB ⇒ ถ้าสองที่คำนวณคนละโค้ด วันหนึ่งจะมีคนแก้
ข้างเดียวแล้ว "จอโชว์หัก 500 แต่ระบบหัก 700" โดยไม่มีอะไรฟ้อง

⇒ ไฟล์นี้ถือ **สูตรเดียว**: `build_allocation_plan()` เป็น pure function
   (`assert_plan_equation()` ตรวจสมการปิดท้ายทุกครั้ง) และ `AllocationMixin`
   แค่โหลดข้อมูลจาก DB มาเรียกมัน — **ห้ามมี SQL/logic จัดสรรใน mixin**

═══════════════════════════════════════════════════════════════════════════════
📐 กติกาตัวเลข — สตางค์จำนวนเต็ม (`int`) ตลอดทาง
═══════════════════════════════════════════════════════════════════════════════
`0.1 + 0.2 != 0.3` ในทศนิยมฐานสอง ⇒ เงินทุกบาทถูกแปลงเป็นสตางค์ก่อนเข้า engine
(`to_satang`) และแปลงกลับเฉพาะตอนคืน (`from_satang`) ⇒ ไม่มีเศษหายระหว่างบิล
และบิล 333.33 × 3 กับเงิน 1000.00 ต้องได้ผลรวม 1000.00 เป๊ะ (มีเทสต์ปิดไว้)

═══════════════════════════════════════════════════════════════════════════════
🪙 นโยบาย "เงินสดก่อนเครดิต" (จงใจ)
═══════════════════════════════════════════════════════════════════════════════
ในบิลเดียวกันจ่ายด้วยเงินสดก่อน แล้วค่อยใช้เครดิตปิดส่วนที่เหลือ ⇒ เครดิตของผู้ใช้
ไม่ถูกกินเมื่อเงินสดพออยู่แล้ว — แต่ต้องมี warning บอก (`CREDIT_UNUSED_BECAUSE_CASH_COVERED`)
ไม่ใช่เงียบ ๆ ให้ผู้ใช้เดาเอง

⚠️ **preview ไม่ใช่สัญญา**: ระหว่างผู้ใช้เปิด modal มีคนอื่นรับเงินบิลเดียวกันได้
   ⇒ P2.1 ต้องโหลดซ้ำใต้ `_lock_room_money` แล้วเรียก engine อีกครั้ง
   (ห้ามนำค่าจาก preview ไปเขียนตรง ๆ)

⚠️ ห้ามแตะ `credits.py::_build_plan` — หน้าเงินรับล่วงหน้าเดิมมีเทสต์ปิดพฤติกรรมไว้
   การรวมเป็น engine เดียวกันเป็นงานแยก (P6.5)
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Literal, Optional

import asyncpg

from core.exceptions import RoomNotFoundError, StudentNotFoundError
from core.rbac import require_permission

from .base import service_logger

# 🪙 1 สตางค์ — จำนวนเงินที่เล็กที่สุดที่ระบบถือว่ามีความหมาย
MIN_AMOUNT_SATANG = 1

_CENT = Decimal("0.01")
_SATANG_PER_BAHT = Decimal("100")

ExcessAction = Literal["credit", "none"]
BillSelection = Literal["auto", "manual"]
LineSource = Literal["cash", "credit"]

VALID_EXCESS_ACTIONS = ("credit", "none")
VALID_BILL_SELECTIONS = ("auto", "manual")


class AllocationError(ValueError):
    """ข้อผิดพลาดเชิงธุรกิจของ engine — router แปล `code` เป็น HTTP status

    ⚠️ `code` ต้องคงที่ (สตริงอังกฤษ) เพราะ router ใช้ตัดสิน status:
       `EXCESS_NOT_ALLOWED`/`INVALID_AMOUNT` → 400 · `BILL_NOT_OPEN` → 409
       ข้อความ (`str(e)`) เป็นภาษาไทยไว้ให้ผู้ใช้เห็นตรง ๆ
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ChannelNotFoundError(Exception):
    """ไม่พบช่องทางชำระเงินที่ระบุ (หรือปิดใช้งานแล้ว) — router แปลเป็น 404

    ประกาศที่นี่แทน `core/exceptions.py` เพราะเป็นของเส้น preview เท่านั้น
    และไฟล์นี้ไม่ถูกผู้อื่น import
    """


# ═══════════════════════════════════════════════════════════════════════════
# ตัวแปลงเงิน — จุดเดียวที่ทศนิยมกลายเป็นสตางค์
# ═══════════════════════════════════════════════════════════════════════════
def to_satang(value: object) -> int:
    """บาท (Decimal/str/float/int) → สตางค์จำนวนเต็ม — ปัดครึ่งขึ้นที่ 2 ตำแหน่ง

    ⚠️ `Decimal` จาก asyncpg ต้องผ่านฟังก์ชันนี้ก่อนเข้า engine เสมอ
       (`int(Decimal("0.29") * 100)` ก็ตรง แต่อย่าพึ่งการเดา — ใช้ quantize)
    """
    if value is None or value == "":
        return 0
    if isinstance(value, Decimal):
        dec = value
    else:
        # 🔴 ห้าม `Decimal(float)` ตรง ๆ (จะได้เศษ binary) — ผ่าน `str` ก่อน
        dec = Decimal(str(value))
    return int(dec.quantize(_CENT, rounding=ROUND_HALF_UP) * _SATANG_PER_BAHT)


def from_satang(value: int) -> float:
    """สตางค์จำนวนเต็ม → บาท (float 2 ตำแหน่ง) — ใช้เฉพาะตอนคืนผล

    คืน `float` ตามสัญญา service เดิม; response ที่ผู้ใช้เห็นเป็น string 2 ตำแหน่ง
    (สร้างจาก `Decimal(value) / 100` ใน `_money_str` ของ mixin)
    """
    return float(Decimal(int(value)) / _SATANG_PER_BAHT)


def sort_open_bills(bills: List[dict]) -> List[dict]:
    """เรียงบิลเปิดแบบ **เดียวกับ SQL ของทั้งระบบ**: `due_date ASC NULLS LAST, FC.id ASC`

    🔑 ใช้ `collection_id` (แทน `FC.id`) เป็นตัวตัดสินเมื่อครบกำหนดวันเดียวกัน —
       และ `payment_id` เป็นตัวสำรองสุดท้ายเพื่อให้ deterministic แม้ข้อมูลผิดปกติ
       (ถ้า engine กับ SQL เรียงไม่เหมือนกัน ครูจะเห็นยอดคนละแบบกับหน้าเครดิต)
    """
    return sorted(
        bills,
        key=lambda b: (
            b.get("due_date") is None,
            b.get("due_date") or date.min,
            int(b.get("collection_id") or 0),
            int(b.get("payment_id") or 0),
        ),
    )


def _line(
    bill: dict, source: LineSource, amount_stang: int, before_stang: int
) -> dict:
    """บรรทัดจัดสรร 1 บรรทัด — **1 แหล่งเงินต่อบรรทัด** (ห้ามรวม cash+credit)"""
    return {
        "payment_id": int(bill["payment_id"]),
        "collection_id": bill.get("collection_id"),
        "title": bill.get("title") or "",
        "collection_kind": bill.get("collection_kind"),
        "fund_type": bill.get("fund_type"),
        "due_date": bill.get("due_date"),
        "source": source,
        "amount_stang": int(amount_stang),
        # ยอดคงเหลือของบิล "ก่อน/หลัง" บรรทัดนี้ — P2.1 ใช้เขียน snapshot
        "bill_before_stang": int(before_stang),
        "bill_after_stang": int(before_stang) - int(amount_stang),
    }


def assert_plan_equation(plan: dict) -> None:
    """ตรวจสมการเงินของแผน — `amount_received + credit_used == total_applied + credit_added`

    ตรงกับ CHECK ของ `finance_payment_events` ใน P1.1 ⇒ ถ้าสมการไม่ผ่าน ข้อมูลชุดนี้
    จะถูก DB ปฏิเสธตอน P2.1 เขียนอยู่ดี — ให้พังที่นี่พร้อมบริบทของแผนจะ debug ง่ายกว่า
    """
    received = int(plan["amount_received_stang"])
    credit_used = int(plan["credit_used_stang"])
    applied = int(plan["total_applied_stang"])
    added = int(plan["credit_added_stang"])
    if received + credit_used != applied + added:
        raise AssertionError(
            "สมการจัดสรรไม่สมดุล: "
            f"{received} + {credit_used} != {applied} + {added}"
        )
    line_sum = sum(int(a["amount_stang"]) for a in plan["allocations"])
    if line_sum != applied:
        raise AssertionError(
            f"ผลรวมบรรทัด ({line_sum}) ไม่เท่ากับ total_applied ({applied})"
        )


def build_allocation_plan(
    *,
    bills: List[dict],
    amount_received_stang: int,
    credit_available_stang: int,
    use_credit: bool,
    excess_action: ExcessAction,
    bill_selection: BillSelection,
    bill_ids: Optional[List[int]],
) -> dict:
    """จัดสรรเงินสด + เครดิตลงบิลเปิด — **pure function, deterministic, ไม่แตะ DB**

    ``bills`` ต้องมีคีย์ (สตางค์ทุกยอด): ``payment_id``, ``collection_id``, ``title``,
    ``collection_kind``, ``fund_type``, ``due_date``, ``outstanding_stang``
    (outstanding = ยอดบิล − จ่ายแล้ว − ตัดจำหน่าย; service เป็นผู้คำนวณให้)

    คืน plan ที่มี ``_stang`` ทุกยอด — mixin แปลงเป็น string ก่อนตอบ HTTP
    """
    # ── 0) ตรวจค่าขาเข้า ───────────────────────────────────────────────
    amount_received_stang = int(amount_received_stang)
    credit_available_stang = max(0, int(credit_available_stang))
    if amount_received_stang < 0:
        raise AllocationError("INVALID_AMOUNT", "ยอดรับเงินต้องไม่ติดลบ")
    if excess_action not in VALID_EXCESS_ACTIONS:
        raise AllocationError(
            "INVALID_AMOUNT", "ค่า excess_action ต้องเป็น credit หรือ none"
        )
    if bill_selection not in VALID_BILL_SELECTIONS:
        raise AllocationError(
            "INVALID_AMOUNT", "ค่า bill_selection ต้องเป็น auto หรือ manual"
        )
    if amount_received_stang == 0 and (
        not use_credit or credit_available_stang == 0
    ):
        raise AllocationError(
            "INVALID_AMOUNT",
            "ต้องมีเงินรับหรือเครดิตที่ใช้ได้อย่างน้อยหนึ่งอย่าง",
        )

    # ── 1) บิลเปิด (ตัดบิลที่จ่าย/ตัดจำหน่ายครบแล้วออก) ────────────────
    open_bills = [
        b for b in sort_open_bills(bills) if int(b.get("outstanding_stang") or 0) > 0
    ]

    # ── 2) เลือกบิล ────────────────────────────────────────────────────
    unselected: List[dict] = []
    if bill_selection == "manual":
        ids = [int(i) for i in (bill_ids or [])]
        # 🧾 [FIN-V2 / P3.3] `manual` + `[]` = **เลือกไม่ปิดบิลสักใบ** (ถูกต้อง)
        #    ใช้ตอนเติมเครดิตล้วนผ่าน payment event: เงินทั้งก้อนต้องกลายเป็น
        #    `credit_added` ไม่ใช่ถูกจัดเข้าบิลที่ครูไม่ได้ติ๊ก
        #    ⚠️ ถ้า `excess_action='none'` จะถูกปฏิเสธที่ข้อ 4 (`EXCESS_NOT_ALLOWED`)
        #       ⇒ ไม่มีทางเงียบ ๆ กลืนเงินเป็นเครดิตโดยผู้ใช้ไม่ได้เลือกไว้
        if len(set(ids)) != len(ids):
            raise AllocationError("INVALID_AMOUNT", "มีบิลซ้ำในรายการที่เลือก")
        open_ids = {int(b["payment_id"]) for b in open_bills}
        if any(i not in open_ids for i in ids):
            raise AllocationError(
                "BILL_NOT_OPEN",
                "มีบิลที่ไม่ได้เปิดอยู่ในรายการที่เลือก — โหลดข้อมูลใหม่แล้วลองอีกครั้ง",
            )
        wanted = set(ids)
        # ⚠️ คงลำดับจาก engine ไม่ใช่ลำดับที่ client ส่ง — เงินสดต้องลงบิล
        #    ครบกำหนดก่อนเสมอ ไม่ว่า client จะเรียงมาแบบไหน
        selected = [b for b in open_bills if int(b["payment_id"]) in wanted]
        unselected = [b for b in open_bills if int(b["payment_id"]) not in wanted]
    else:
        selected = open_bills

    # ── 3) วนบิล: เงินสดก่อน แล้วค่อยเครดิตในบิลเดียวกัน ────────────────
    cash_left = amount_received_stang
    credit_left = credit_available_stang if use_credit else 0
    allocations: List[dict] = []
    total_applied_stang = 0
    credit_used_stang = 0

    for bill in selected:
        outstanding = int(bill["outstanding_stang"])
        cash_pay = min(cash_left, outstanding)
        credit_pay = 0
        if credit_left > 0:
            credit_pay = min(credit_left, outstanding - cash_pay)

        before = outstanding
        if cash_pay >= MIN_AMOUNT_SATANG:
            allocations.append(_line(bill, "cash", cash_pay, before))
            before -= cash_pay
            cash_left -= cash_pay
            total_applied_stang += cash_pay
        if credit_pay >= MIN_AMOUNT_SATANG:
            allocations.append(_line(bill, "credit", credit_pay, before))
            credit_left -= credit_pay
            credit_used_stang += credit_pay
            total_applied_stang += credit_pay

    # ── 4) เงินเหลือ: เก็บเป็นเครดิต หรือปฏิเสธตั้งแต่ preview ───────────
    credit_added_stang = 0
    if cash_left > 0:
        if excess_action == "credit":
            credit_added_stang = cash_left
        else:
            raise AllocationError(
                "EXCESS_NOT_ALLOWED",
                f"ยอดรับเงินเกินยอดที่ต้องใช้ {from_satang(cash_left):,.2f} บาท — "
                "เลือกเก็บส่วนเกินเป็นเครดิตหรือแก้ยอดให้ตรง",
            )

    # ── 5) warning — ทุกอย่างที่ "ผู้ใช้ควรรู้" แต่ไม่ใช่ error ───────────
    selected_outstanding = sum(int(b["outstanding_stang"]) for b in selected)
    warnings: List[str] = []
    if unselected:
        warnings.append("UNSELECTED_OPEN_BILLS")
    if use_credit and credit_used_stang < credit_available_stang:
        warnings.append("CREDIT_REMAINS")
    if total_applied_stang < selected_outstanding:
        warnings.append("PARTIAL_PAYMENT")
    if credit_added_stang > 0:
        warnings.append("EXCESS_TO_CREDIT")
    if use_credit and credit_used_stang == 0 and excess_action == "credit":
        warnings.append("CREDIT_UNUSED_BECAUSE_CASH_COVERED")

    plan = {
        "amount_received_stang": amount_received_stang,
        "credit_available_stang": credit_available_stang,
        "total_applied_stang": total_applied_stang,
        "credit_used_stang": credit_used_stang,
        "credit_added_stang": credit_added_stang,
        "remaining_unapplied_stang": 0,
        "allocations": allocations,
        "warnings": warnings,
    }
    assert_plan_equation(plan)
    return plan


# ═══════════════════════════════════════════════════════════════════════════
# mixin — อ่าน DB แล้วเรียก engine (ห้ามมี logic จัดสรรที่นี่)
# ═══════════════════════════════════════════════════════════════════════════
class AllocationMixin:
    """`preview_allocation` — snapshot ของแผนจัดสรรสำหรับหน้าจอรับเงิน (P2.3)"""

    @staticmethod
    def _money_str(stang: int) -> str:
        return f"{Decimal(int(stang)) / _SATANG_PER_BAHT:.2f}"

    @staticmethod
    async def _assert_preview_student(
        conn: asyncpg.Connection, room_id: int, student_id: int
    ) -> None:
        """นักเรียนต้องอยู่ในห้องนี้ — 404 ไม่ใช่ 403 (ให้ตรงกับบัญชีรายบุคคล P1.3)"""
        found = await conn.fetchval(
            "SELECT 1 FROM students WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
            student_id, room_id,
        )
        if not found:
            raise StudentNotFoundError("ไม่พบนักเรียนคนนี้ในห้องเรียน")

    @classmethod
    async def _load_preview_bills(
        cls, conn: asyncpg.Connection, room_id: int, student_id: int
    ) -> List[dict]:
        """บิลเปิดของนักเรียน + ยอดคงเหลือเป็นสตางค์

        🔴 ใช้ `_open_bill_predicate()` ตัวกลาง (เดียวกับผู้ค้างชำระ/AR/ใบแจ้งหนี้)
           และหัก `written_off_amount` (P1.1) ⇒ preview ตรงกับยอดที่หน้าอื่นโชว์
        """
        rows = await conn.fetch(
            f"""SELECT SP.id AS payment_id, FC.id AS collection_id, FC.title,
                       FC.amount AS total_amount, SP.paid_amount,
                       COALESCE(SP.written_off_amount, 0) AS written_off_amount,
                       FC.due_date, FC.collection_kind, FC.fund_type
                FROM student_payments SP
                JOIN fee_collections FC ON SP.collection_id = FC.id
                JOIN students S ON S.id = SP.student_id
                WHERE S.room_id = $1 AND SP.student_id = $2
                  AND {cls._open_bill_predicate()}
                ORDER BY FC.due_date ASC NULLS LAST, FC.id ASC""",
            room_id, student_id,
        )
        bills: List[dict] = []
        for r in rows:
            outstanding = (
                to_satang(r["total_amount"])
                - to_satang(r["paid_amount"])
                - to_satang(r["written_off_amount"])
            )
            bills.append({
                "payment_id": r["payment_id"],
                "collection_id": r["collection_id"],
                "title": r["title"],
                "collection_kind": r["collection_kind"],
                "fund_type": r["fund_type"],
                "due_date": r["due_date"],
                "bill_total_stang": to_satang(r["total_amount"]),
                "bill_paid_stang": to_satang(r["paid_amount"]),
                "written_off_stang": to_satang(r["written_off_amount"]),
                "outstanding_stang": outstanding,
            })
        return bills

    @classmethod
    def _shape_preview(cls, plan: dict) -> dict:
        """plan (สตางค์) → response dict (string 2 ตำแหน่ง) ตาม `AllocationPreviewResponse`"""
        return {
            "allocations": [
                {
                    "student_payment_id": a["payment_id"],
                    "collection_id": a["collection_id"],
                    "title": a["title"],
                    "collection_kind": a["collection_kind"],
                    "fund_type": a["fund_type"],
                    "due_date": a["due_date"],
                    "source": a["source"],
                    "amount": cls._money_str(a["amount_stang"]),
                    "bill_before": cls._money_str(a["bill_before_stang"]),
                    "bill_after": cls._money_str(a["bill_after_stang"]),
                }
                for a in plan["allocations"]
            ],
            "total_applied": cls._money_str(plan["total_applied_stang"]),
            "credit_used": cls._money_str(plan["credit_used_stang"]),
            "credit_added": cls._money_str(plan["credit_added_stang"]),
            "remaining_unapplied": cls._money_str(plan["remaining_unapplied_stang"]),
            "warnings": list(plan["warnings"]),
        }

    @classmethod
    async def preview_allocation(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        *,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: int,
        req,
    ) -> dict:
        """พรีวิวการจัดสรรเงิน/เครดิต — อ่านอย่างเดียว ไม่ล็อกห้อง ไม่เขียนอะไรเลย

        ⚠️ ต้อง `MANAGE_FINANCE`: เป็นขั้นของ flow รับเงินและเผยรายละเอียดบิล/เครดิต
           ของนักเรียน — การเปิดให้สมาชิกเห็นกว้างกว่าหน้าผู้ค้างชำระเดิมโดยไม่จำเป็น

        🔒 ไม่ `_lock_room_money` โดยเจตนา: preview เป็น snapshot, การล็อกจะทำให้ modal
           ค้างรอเมื่อมีคนรับเงินพร้อมกันโดยไม่ได้ป้องกันอะไร (ไม่ได้เขียน)
        """
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(
                    conn, target_room_id, user_id, "MANAGE_FINANCE"
                )
                await cls._assert_preview_student(
                    conn, target_room_id, req.student_id
                )

                if req.channel_id is not None:
                    channel_ok = await conn.fetchval(
                        """SELECT 1 FROM finance_payment_channels
                           WHERE id = $1 AND room_id = $2
                             AND is_active AND deleted_at IS NULL""",
                        req.channel_id, target_room_id,
                    )
                    if not channel_ok:
                        raise ChannelNotFoundError(
                            "ไม่พบช่องทางชำระเงินนี้ในห้อง (หรือถูกปิดใช้งานแล้ว)"
                        )

                bills = await cls._load_preview_bills(
                    conn, target_room_id, req.student_id
                )
                balance = await cls._load_credit_balance(
                    conn, room_id=target_room_id, student_id=req.student_id
                )

                plan = build_allocation_plan(
                    bills=bills,
                    amount_received_stang=to_satang(req.amount_received),
                    credit_available_stang=to_satang(balance),
                    use_credit=bool(req.use_credit),
                    excess_action=req.excess_action,
                    bill_selection=req.bill_selection,
                    bill_ids=req.bill_ids,
                )
                # 📝 preview เป็น "การอ่าน" — บันทึกแบบ VIEW เหมือนบัญชีรายบุคคล
                #    (มีประโยชน์ตอนสืบว่าใครเปิดดูบิล/เครดิตของใครเมื่อไร)
                await service_logger.log(
                    conn=conn, action="VIEW",
                    actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None,
                    entity_type="PAYMENT_EVENT_PREVIEW",
                    entity_id=str(req.student_id), status="success",
                    endpoint_or_command="FinanceService.preview_allocation",
                )
                return cls._shape_preview(plan)
        except AllocationError:
            # 🚫 ไม่ log error ลง audit_logs: เป็น input ผู้ใช้ที่แก้ได้ ไม่ใช่ระบบล้ม
            #    (router แปลเป็น 400/409 พร้อมข้อความไทยให้แล้ว)
            raise
