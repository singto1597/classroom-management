"""📜 [FIN-V2 / P3.4] ประวัติการรับเงิน — payment event + การส่งมอบเงินสด

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมเป็น module-level function ไม่ใช่ mixin
═══════════════════════════════════════════════════════════════════════════════
P3.4 อ่านล้วน ๆ (ไม่มี transaction/ล็อก/audit) และ brief ห้ามแตะ `service.py`
⇒ ไม่ต้องพึ่ง MRO ของ `FinanceService` เลย — ใช้ SQL + `require_member` ตรง ๆ
จะได้ไม่มีทางเผลอไปเพิ่ม `_MONEY_PATHS` หรือล็อกห้องโดยไม่จำเป็น

═══════════════════════════════════════════════════════════════════════════════
🔑 กติกาที่ห้ามพลาด
═══════════════════════════════════════════════════════════════════════════════
1. **cursor 3 คีย์ `(occurred_at, kind, id)`** — เวลาอาจซ้ำ (event หลายรายการใน
   transaction เดียวกัน) ⇒ ใช้ `LIMIT/OFFSET` ไม่ได้ และ `occurred_at` เดี่ยวก็ไม่พอ
2. **`COALESCE(event_at, created_at)`** ใช้ทั้ง select/filter/cursor — `event_at`
   เป็น NULL ได้ในอดีต ถ้าลืมที่ใดที่หนึ่ง event เก่าจะหายจากทุกหน้า
3. **วันไทย**: เทียบ `date` กับ `timestamptz` ตรง ๆ จะกลายเป็นเที่ยงคืน UTC
   ⇒ ต้องแปลง `($n::date::timestamp AT TIME ZONE 'Asia/Bangkok')`
4. **ห้าม JOIN บรรทัด/เอกสารใน query หลัก** — จะแถวทวีคูณและ pagination เพี้ยน
   ⇒ โหลดเป็น batch หลังได้หน้าแล้ว (ไม่ N+1)
5. รายการที่ถูกยกเลิก (event/handover `status='voided'`) **ต้องแสดง** พร้อมสถานะ —
   ประวัติการเงินที่ซ่อนรายการยกเลิกจะอธิบายยอดที่หายไปไม่ได้
"""
import base64
from datetime import date, datetime
from typing import Dict, List, Optional

import asyncpg

from core.rbac import require_member

_VALID_KINDS = ("all", "event", "handover")
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 30


def _money(value) -> float:
    """Decimal/None → float ทศนิยม 2 ตำแหน่ง (Pydantic `float` ใน response)"""
    return round(float(value or 0), 2)


def _encode_cursor(occurred_at: datetime, kind: str, row_id: int) -> str:
    raw = f"{occurred_at.isoformat()}|{kind}|{int(row_id)}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str, int]:
    """decode `base64url(f"{iso}|{kind}|{id}")` — ผิดรูปแบบ ⇒ ValueError (router → 400)"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        iso, kind, row_id = raw.split("|")
        if kind not in ("event", "handover"):
            raise ValueError
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, kind, int(row_id)
    except Exception:
        raise ValueError("cursor ไม่ถูกต้อง")


class PaymentHistoryService:
    """อ่านประวัติการเงินแบบ event-centric (ไม่เขียนอะไรเลย)"""

    @staticmethod
    async def list_payment_history(
        pool: asyncpg.Pool, *,
        room_id: int, user_id: int,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        kind: str = "all",
        student_id: Optional[int] = None,
        person_id: Optional[int] = None,
        receiver_id: Optional[int] = None,
        q: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> dict:
        if kind not in _VALID_KINDS:
            raise ValueError("ชนิดรายการไม่ถูกต้อง (all | event | handover)")
        if not (1 <= int(limit) <= _MAX_LIMIT):
            raise ValueError(f"จำนวนต่อหน้าไม่ถูกต้อง (1–{_MAX_LIMIT})")

        cursor_ts: Optional[datetime] = None
        cursor_kind: Optional[str] = None
        cursor_id: Optional[int] = None
        if cursor:
            cursor_ts, cursor_kind, cursor_id = _decode_cursor(cursor)

        term = (q or "").strip() or None
        fetch_limit = int(limit) + 1

        async with pool.acquire() as conn:
            # 🔒 ก่อน query ใด ๆ — กันอ่านข้ามห้องด้วยการเดา id
            await require_member(conn, room_id, user_id)

            event_sql = """
                SELECT 'event'::text AS kind, e.id,
                       COALESCE(e.event_at, e.created_at) AS occurred_at,
                       e.student_id, e.payer_name, e.receiver_name,
                       e.amount_received, e.credit_used, e.credit_added,
                       e.total_applied, e.status, e.reference_no,
                       NULL::numeric AS handover_amount,
                       NULL::int AS from_account_id,
                       NULL::int AS to_account_id,
                       NULL::bigint AS handed_over_by_person_id,
                       NULL::bigint AS received_by_person_id,
                       NULL::text AS note, NULL::text AS void_reason
                FROM finance_payment_events e
                WHERE e.room_id = $1
                  AND $11::text <> 'handover'
                  AND ($2::date IS NULL OR COALESCE(e.event_at, e.created_at) >=
                       ($2::date::timestamp AT TIME ZONE 'Asia/Bangkok'))
                  AND ($3::date IS NULL OR COALESCE(e.event_at, e.created_at) <
                       (($3::date + 1)::timestamp AT TIME ZONE 'Asia/Bangkok'))
                  AND ($4::int IS NULL OR e.student_id = $4)
                  AND ($5::bigint IS NULL OR e.receiver_person_id = $5)
                  AND ($6::text IS NULL OR e.payer_name ILIKE '%' || $6 || '%'
                        OR e.receiver_name ILIKE '%' || $6 || '%')
            """
            handover_sql = """
                SELECT 'handover'::text AS kind, h.id,
                       h.created_at AS occurred_at,
                       NULL::int AS student_id, NULL::text AS payer_name,
                       NULL::text AS receiver_name,
                       NULL::numeric AS amount_received,
                       NULL::numeric AS credit_used,
                       NULL::numeric AS credit_added,
                       NULL::numeric AS total_applied,
                       h.status, NULL::text AS reference_no,
                       h.amount AS handover_amount,
                       h.from_account_id, h.to_account_id,
                       h.handed_over_by_person_id, h.received_by_person_id,
                       h.note, h.void_reason
                FROM finance_custody_handovers h
                WHERE h.room_id = $1
                  AND $11::text <> 'event'
                  AND ($2::date IS NULL OR h.created_at >=
                       ($2::date::timestamp AT TIME ZONE 'Asia/Bangkok'))
                  AND ($3::date IS NULL OR h.created_at <
                       (($3::date + 1)::timestamp AT TIME ZONE 'Asia/Bangkok'))
                  AND $4::int IS NULL
                  AND ($7::bigint IS NULL OR EXISTS (
                        SELECT 1 FROM finance_accounts acc
                        WHERE acc.id IN (h.from_account_id, h.to_account_id)
                          AND acc.owner_person_id = $7))
            """

            # ⚠️ ต้องมี **ทั้งสองกิ่งเสมอ** เพื่อให้ทุก parameter ($5/$6/$7) ถูกอ้างอิง
            #    อย่างน้อยหนึ่งที่ — ถ้าตัดกิ่งทิ้ง asyncpg จะตอบ
            #    `IndeterminateDatatypeError` เพราะเดาชนิดของ param ที่ไม่ได้ใช้ไม่ได้
            #    ⇒ กรองชนิดด้วย `$11::text` ภายใน SQL แทนการประกอบ SQL ตาม kind
            sql = (
                "WITH items AS (" + event_sql + " UNION ALL " + handover_sql + ")\n"
                "SELECT * FROM items\n"
                "WHERE ($8::timestamptz IS NULL\n"
                "       OR (occurred_at, kind, id) < ($8::timestamptz, $9::text, $10::bigint))\n"
                "ORDER BY occurred_at DESC, kind DESC, id DESC\n"
                "LIMIT $12"
            )

            rows = await conn.fetch(
                sql,
                room_id, date_from, date_to, student_id, receiver_id, term,
                person_id, cursor_ts, cursor_kind, cursor_id, kind, fetch_limit,
            )

        has_more = len(rows) > int(limit)
        page = rows[: int(limit)]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = _encode_cursor(last["occurred_at"], last["kind"], last["id"])

        items = await _build_items(pool, page, room_id)
        return {"items": items, "next_cursor": next_cursor}


async def _build_items(
    pool: asyncpg.Pool, rows: List[asyncpg.Record], room_id: int
) -> List[dict]:
    """ประกอบรายละเอียดแบบ batch — query คงที่สูงสุด 5 ครั้งต่อหน้า (ไม่ขึ้นกับ N)"""
    if not rows:
        return []

    event_rows = [r for r in rows if r["kind"] == "event"]
    handover_rows = [r for r in rows if r["kind"] == "handover"]
    event_ids = [int(r["id"]) for r in event_rows]
    handover_ids = [int(r["id"]) for r in handover_rows]
    student_ids = sorted({int(r["student_id"]) for r in event_rows})

    lines_by_event: Dict[int, List[dict]] = {}
    docs_by_event: Dict[int, List[dict]] = {}
    student_names: Dict[int, Optional[str]] = {}
    account_names: Dict[int, str] = {}
    person_names: Dict[int, str] = {}

    async with pool.acquire() as conn:
        if event_ids:
            line_rows = await conn.fetch(
                """SELECT L.event_id, L.line_kind, L.amount,
                          L.bill_amount_before, L.bill_amount_after,
                          FC.title AS collection_title
                   FROM finance_payment_event_lines L
                   LEFT JOIN student_payments SP ON SP.id = L.student_payment_id
                   LEFT JOIN fee_collections FC ON FC.id = SP.collection_id
                   WHERE L.event_id = ANY($1::bigint[])
                   ORDER BY L.event_id,
                            CASE L.line_kind
                                WHEN 'bill' THEN 0
                                WHEN 'credit_apply' THEN 1
                                ELSE 2
                            END,
                            L.id""",
                event_ids,
            )
            for row in line_rows:
                lines_by_event.setdefault(int(row["event_id"]), []).append({
                    "line_kind": row["line_kind"],
                    "amount": _money(row["amount"]),
                    "bill_before": (
                        _money(row["bill_amount_before"])
                        if row["bill_amount_before"] is not None else None
                    ),
                    "bill_after": (
                        _money(row["bill_amount_after"])
                        if row["bill_amount_after"] is not None else None
                    ),
                    "collection_title": row["collection_title"],
                })

            doc_rows = await conn.fetch(
                """SELECT payment_event_id, doc_type, receipt_no, status
                   FROM finance_receipts
                   WHERE payment_event_id = ANY($1::bigint[])
                     AND doc_type IN ('receipt', 'deposit')
                     AND deleted_at IS NULL
                   ORDER BY payment_event_id, doc_type""",
                event_ids,
            )
            for row in doc_rows:
                docs_by_event.setdefault(int(row["payment_event_id"]), []).append({
                    "doc_type": row["doc_type"],
                    "receipt_no": row["receipt_no"],
                    "status": row["status"],
                })

            name_rows = await conn.fetch(
                """SELECT S.id, P.first_name, P.first_name_en, P.nickname
                   FROM students S
                   LEFT JOIN v_student_profiles P ON P.student_id = S.id
                   WHERE S.id = ANY($1::int[]) AND S.room_id = $2""",
                student_ids, room_id,
            )
            for row in name_rows:
                name = row["first_name"] or row["first_name_en"] or "Unknown"
                if row["nickname"]:
                    name += f" ({row['nickname']})"
                student_names[int(row["id"])] = name

        if handover_rows:
            account_rows = await conn.fetch(
                """SELECT id, account_name FROM finance_accounts
                   WHERE room_id = $1 AND id = ANY($2::int[])""",
                room_id,
                sorted({
                    int(r[col])
                    for r in handover_rows
                    for col in ("from_account_id", "to_account_id")
                    if r[col] is not None
                }),
            )
            for row in account_rows:
                account_names[int(row["id"])] = row["account_name"]

            people_ids = sorted({
                int(r[col])
                for r in handover_rows
                for col in ("handed_over_by_person_id", "received_by_person_id")
                if r[col] is not None
            })
            if people_ids:
                people_rows = await conn.fetch(
                    """SELECT id, display_name FROM finance_people
                       WHERE room_id = $1 AND id = ANY($2::bigint[])""",
                    room_id, people_ids,
                )
                for row in people_rows:
                    person_names[int(row["id"])] = row["display_name"]

    items: List[dict] = []
    for row in rows:
        occurred = row["occurred_at"]
        if row["kind"] == "event":
            sid = int(row["student_id"])
            items.append({
                "kind": "event",
                "id": int(row["id"]),
                "occurred_at": occurred,
                "status": row["status"],
                "event": {
                    "student_id": sid,
                    "student_name": student_names.get(sid),
                    "payer_name": row["payer_name"],
                    "receiver_name": row["receiver_name"],
                    "amount_received": _money(row["amount_received"]),
                    "credit_used": _money(row["credit_used"]),
                    "credit_added": _money(row["credit_added"]),
                    "total_applied": _money(row["total_applied"]),
                    "reference_no": row["reference_no"],
                    "lines": lines_by_event.get(int(row["id"]), []),
                    "documents": docs_by_event.get(int(row["id"]), []),
                },
                "handover": None,
            })
        else:
            items.append({
                "kind": "handover",
                "id": int(row["id"]),
                "occurred_at": occurred,
                "status": row["status"],
                "event": None,
                "handover": {
                    "from_account_name": account_names.get(int(row["from_account_id"])),
                    "to_account_name": account_names.get(int(row["to_account_id"])),
                    "amount": _money(row["handover_amount"]),
                    "handed_over_by_name": (
                        person_names.get(int(row["handed_over_by_person_id"]))
                        if row["handed_over_by_person_id"] is not None else None
                    ),
                    "received_by_name": (
                        person_names.get(int(row["received_by_person_id"]))
                        if row["received_by_person_id"] is not None else None
                    ),
                    "note": row["note"],
                    "void_reason": row["void_reason"],
                },
            })
    return items
