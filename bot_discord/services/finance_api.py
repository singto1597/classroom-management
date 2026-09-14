"""💰 ชั้นเรียก endpoint การเงินของ backend + ประกอบ embed — บอทไม่มี test harness จึงต้องซ่อน logic ไว้ที่นี่

## ทำไมต้องมีไฟล์นี้ (และทำไม cog ต้องโง่)

repo นี้ **ไม่มี test harness ของบอทเลย** — cog ทุกตัวไม่ถูก CI ตรวจ ดังนั้นโค้ดใน cog
คือโค้ดที่ไม่มีใครพิสูจน์ว่าถูก นอกจากรันมือ ⇒ ย้ายทุกอย่างที่ "คิด" ได้ออกมาไว้ที่นี่:

- **cog** = `defer()` → เรียกฟังก์ชันในไฟล์นี้ → `followup.send(embed=...)` เท่านั้น
- **ไฟล์นี้** = สร้าง params, validate, แปลงตัวเลข/วันที่, ประกอบ `discord.Embed`

ผลพลอยได้: ถ้าอนาคตมี harness ของบอท ไฟล์นี้คือส่วนที่เทสต์ได้ทันทีโดยไม่ต้องมี Discord

## ⚠️ กับดักที่ต้องระวังทุกฟังก์ชัน

1. **`target_type=server` ต้องส่งให้ชัด** — `get_target` ฝั่ง backend มี default เป็น `"room"`
   (สำหรับเว็บ) ถ้าไม่ส่ง `target_type` บอทจะส่ง `guild_id` ไปถูกตีความเป็น `room_id`
   แล้วได้ 404 "ไม่พบห้อง" ทั้งที่ห้องมีอยู่จริง
2. **`api_client.request` เรียก `response.json()` เสมอ** — endpoint ที่คืน binary/204 ใช้ไม่ได้
   (เหตุผลที่ F3 ไม่ส่ง PDF เข้า Discord จนกว่าจะแก้ client กลาง)
3. **เดือน+ปีของ `/finance summary` ต้องส่งคู่กันหรือไม่ส่งเลย** — `get_summary` ฝั่ง backend
   รับ `month`/`year` เป็น optional แยกกัน แต่จะได้ช่วงเวลาที่ไม่ตั้งใจถ้าส่งมาแค่ตัวเดียว
   ⇒ validate ที่นี่ที่เดียว (cog แค่ส่งค่าที่ผู้ใช้เลือกมา)
4. **`paid_at` เป็น naive UTC** ตามมาตรฐานของโปรเจกต์ (ดู `docs/skills.md`) → ห้ามเรียก
   `.astimezone()` ตรง ๆ ต้อง `.replace(tzinfo=utc)` ก่อน ไม่งั้นเวลาจะเพี้ยนตาม TZ ของเครื่องที่รันบอท
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import discord

from services.api_client import api_client

THAI_TZ = timezone(timedelta(hours=7))

THAI_MONTHS = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)

# 🔒 ขีดจำกัดของ Discord: embed field รับได้ 1024 ตัวอักษร · 1 ข้อความส่งได้รวม 10 embed
MAX_FIELD_CHARS = 1024
MAX_LIST_ROWS = 15

SUMMARY_ENDPOINT = "/{guild_id}/finance/summary"
DEBTORS_ENDPOINT = "/{guild_id}/finance/debtors"
COLLECTION_ENDPOINT = "/{guild_id}/finance/collections/{collection_id}"
MY_DEBTS_ENDPOINT = "/{guild_id}/finance/me/debts"


# --------------------------------------------------------------------------- จัดรูป
def format_baht(amount) -> str:
    """`1234.5` → `'1,234.50'` (ไม่มีคำว่า 'บาท' — ให้ผู้เรียกเติมเอง)"""
    return f"{float(amount or 0):,.2f}"


def format_thai_datetime(raw: Optional[str]) -> str:
    """ISO string จาก backend → `'31/08/2569 23:00'` เวลาไทย · คืน `'—'` เมื่อว่าง.

    ⚠️ ค่า naive ถือเป็น **UTC** ตามมาตรฐานของโปรเจกต์ — `datetime.fromisoformat` จะคืน
    ค่า naive มาถ้า string ไม่มี offset แล้ว `.astimezone()` บน naive จะตีความด้วย TZ
    ของเครื่องที่รันบอท (container = UTC ก็ถูก แต่ dev machine = เพี้ยน 7 ชม.)
    """
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return str(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    thai = dt.astimezone(THAI_TZ)
    return f"{thai.strftime('%d/%m/')}{thai.year + 543} {thai.strftime('%H:%M')}"


def format_thai_date(raw: Optional[str]) -> str:
    """`'2026-09-30'` → `'30/09/2569'` · คืน `'—'` เมื่อว่าง.

    `due_date` เป็น DATE ล้วน (ไม่มีเวลา) ⇒ **ห้าม**เอาไปเข้า timezone conversion
    แค่จัดรูปแบบและบวก พ.ศ. เอง
    """
    if not raw:
        return "—"
    text = str(raw)[:10]
    try:
        d = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return text
    return f"{d.strftime('%d/%m/')}{d.year + 543}"


def month_label(month: int) -> str:
    """1 → `'มกราคม'` (ค่าที่หลุดช่วงคืน `'เดือน 13'` ไม่โยน exception)"""
    if 1 <= int(month) <= 12:
        return THAI_MONTHS[int(month) - 1]
    return f"เดือน {month}"


def _clip(lines: List[str], limit: int = MAX_LIST_ROWS) -> str:
    """ต่อบรรทัดให้เป็น field value — ตัดเมื่อเกินทั้งจำนวนบรรทัดและ 1024 ตัวอักษร.

    ⚠️ Discord **ปฏิเสธทั้งข้อความ** (ไม่ใช่แค่ตัด) ถ้า field เกิน 1024 ตัวอักษร
    ⇒ ต้องกันทั้งสองด้าน: จำนวนบรรทัด *และ* ความยาวจริง (ชื่อไทยยาวได้)
    """
    if not lines:
        return "—"
    shown = lines[:limit]
    hidden = len(lines) - len(shown)
    text = "\n".join(shown)
    if hidden > 0:
        text += f"\n… และอีก {hidden} รายการ"
    if len(text) > MAX_FIELD_CHARS:
        text = text[: MAX_FIELD_CHARS - 20] + "\n… (ตัดการแสดงผล)"
    return text


# --------------------------------------------------------------------------- เรียก API
def _headers(discord_id) -> Dict[str, str]:
    return {"X-Discord-Id": str(discord_id)}


def _server_params(**extra) -> Dict[str, object]:
    """params ที่ทุกคำสั่งต้องมี — `target_type=server` คือหัวใจ (ดู docstring บนสุด)."""
    params: Dict[str, object] = {"target_type": "server"}
    # ตัด key ที่เป็น None ออก — aiohttp จะ serialize None เป็นสตริงว่างซึ่ง backend ตีเป็นค่าขยะ
    params.update({k: v for k, v in extra.items() if v is not None})
    return params


def validate_period(month: Optional[int], year: Optional[int]) -> None:
    """เดือน+ปีต้องมาคู่กัน หรือไม่มากันเลย (สัญญาของ `get_summary`).

    ⚠️ **มีเทสต์ของ backend ผูกกับสัญญานี้** — ส่ง `month` เดี่ยวจะได้ 422 จาก Pydantic
    ไม่ใช่ยอดของเดือนนั้น ⇒ ต้องดักที่ฝั่งบอทเพื่อให้ข้อความ error อ่านรู้เรื่อง
    """
    if (month is None) != (year is None):
        raise ValueError("ต้องระบุเดือนและปีพร้อมกัน หรือไม่ระบุเลยเพื่อดูภาพรวมทั้งหมดครับ")


async def get_summary(guild_id: int, discord_id, month: Optional[int] = None, year: Optional[int] = None) -> dict:
    """ภาพรวมการเงินของห้อง — ไม่ส่ง month/year = ภาพรวมทั้งหมด."""
    validate_period(month, year)
    return await api_client.request(
        "GET",
        SUMMARY_ENDPOINT.format(guild_id=guild_id),
        params=_server_params(month=month, year=year),
        headers=_headers(discord_id),
    )


async def get_debtors(guild_id: int, discord_id) -> list:
    """รายชื่อลูกหนี้ทั้งห้อง (เรียงตามยอดค้างจาก backend)."""
    return await api_client.request(
        "GET",
        DEBTORS_ENDPOINT.format(guild_id=guild_id),
        params=_server_params(),
        headers=_headers(discord_id),
    )


async def get_collection(guild_id: int, discord_id, collection_id: int) -> dict:
    """สถานะแคมเปญเก็บเงินรายตัว (สรุป + รายชื่อผู้จ่าย/ค้าง)."""
    return await api_client.request(
        "GET",
        COLLECTION_ENDPOINT.format(guild_id=guild_id, collection_id=collection_id),
        params=_server_params(),
        headers=_headers(discord_id),
    )


async def get_my_debts(guild_id: int, discord_id) -> dict:
    """หนี้ค้างของ "ตัวเอง" — backend resolve `students.id` จาก `X-Discord-Id` ให้เอง."""
    return await api_client.request(
        "GET",
        MY_DEBTS_ENDPOINT.format(guild_id=guild_id),
        params=_server_params(),
        headers=_headers(discord_id),
    )


# --------------------------------------------------------------------------- ประกอบ embed
def build_summary_embed(data: dict, month: Optional[int], year: Optional[int]) -> discord.Embed:
    """การ์ดภาพรวมการเงิน — ปีที่แสดงเป็น พ.ศ. (`year + 543`) ส่วนตัวเลขเป็นบาทล้วน."""
    if month and year:
        title = f"💰 ภาพรวมการเงิน — {month_label(month)} {year + 543}"
    else:
        title = "💰 ภาพรวมการเงินทั้งหมด"

    net_worth = float(data.get("net_worth", 0))
    embed = discord.Embed(
        title=title,
        description=f"**ยอดคงเหลือสุทธิ {format_baht(net_worth)} บาท**",
        color=discord.Color.green() if net_worth >= 0 else discord.Color.red(),
    )
    embed.add_field(name="📥 รายรับ", value=f"{format_baht(data.get('total_income'))} บาท", inline=True)
    embed.add_field(name="📤 รายจ่าย", value=f"{format_baht(data.get('total_expense'))} บาท", inline=True)
    embed.add_field(
        name="⏳ รอเก็บ",
        value=f"{format_baht(data.get('pending_collection_amount'))} บาท",
        inline=True,
    )

    breakdown = data.get("expense_breakdown") or []
    if breakdown:
        lines = [
            f"• **{b.get('category_name', 'ไม่ระบุ')}** — {format_baht(b.get('amount'))} บาท"
            for b in breakdown
        ]
        embed.add_field(name="🧾 รายจ่ายแยกตามหมวด", value=_clip(lines), inline=False)

    period = data.get("period")
    embed.set_footer(text=f"ช่วงเวลา: {period}" if period else "ภาพรวมทั้งห้อง")
    return embed


def build_debtors_embed(rows: list) -> discord.Embed:
    """ตารางลูกหนี้ — ยอดรวมคิดจากทุกแถวเสมอ แม้แสดงไม่ครบ (ห้ามให้ยอดรวมถูกตัดตามการแสดงผล)."""
    rows = rows or []
    total = sum(float(r.get("total_pending_amount", 0)) for r in rows)

    embed = discord.Embed(
        title="🧾 รายชื่อลูกหนี้",
        description=(
            f"มีลูกหนี้ **{len(rows)}** คน รวมค้างชำระ **{format_baht(total)} บาท**"
            if rows else "🎉 ไม่มีลูกหนี้ค้างชำระเลย"
        ),
        color=discord.Color.orange() if rows else discord.Color.green(),
    )
    if rows:
        lines = [
            f"• เลขที่ {r.get('student_no', '-')} **{r.get('student_name', 'ไม่ระบุ')}** — "
            f"{format_baht(r.get('total_pending_amount'))} บาท"
            + (f" ({r.get('overdue_count')} บิลเลยกำหนด)" if r.get("overdue_count") else "")
            for r in rows
        ]
        embed.add_field(name="📋 รายละเอียด", value=_clip(lines), inline=False)
    return embed


def build_collection_embed(data: dict) -> discord.Embed:
    """สถานะแคมเปญเก็บเงิน — `summary` เป็นตัวเลขก้อน ส่วน `students` ใช้แยกจ่าย/ค้าง."""
    summary = data.get("summary") or {}
    students = data.get("students") or []
    total = int(summary.get("total", 0) or 0)
    paid = int(summary.get("paid", 0) or 0)
    pending = int(summary.get("pending", 0) or 0)

    embed = discord.Embed(
        title=f"💳 แคมเปญเก็บเงิน #{data.get('collection_id', '-')}",
        description=f"จ่ายแล้ว **{paid}/{total}** คน · ค้าง **{pending}** คน",
        color=discord.Color.green() if pending == 0 else discord.Color.orange(),
    )

    paid_rows, pending_rows = [], []
    for s in students:
        name = s.get("nickname") or s.get("first_name") or "ไม่ระบุ"
        line = (
            f"• เลขที่ {s.get('student_no', '-')} **{name}** — "
            f"{format_baht(s.get('paid_amount'))}/{format_baht(s.get('total_amount'))} บาท"
        )
        if s.get("status") == "paid":
            paid_rows.append(line)
        else:
            pending_rows.append(line)

    if pending_rows:
        embed.add_field(name="⏳ ยังไม่จ่าย", value=_clip(pending_rows), inline=False)
    if paid_rows:
        embed.add_field(name="✅ จ่ายแล้ว", value=_clip(paid_rows), inline=False)
    return embed


def build_my_debts_embed(data: dict) -> discord.Embed:
    """หนี้ของตัวเอง — ต้องถูกส่งแบบ ephemeral เท่านั้น (ข้อมูลส่วนบุคคล)."""
    debts = data.get("debts") or []
    total = float(data.get("total_pending_amount", 0))

    embed = discord.Embed(
        title=f"💳 หนี้ค้างของ {data.get('student_name', 'คุณ')}",
        description=(
            f"ค้างชำระรวม **{format_baht(total)} บาท** จาก {len(debts)} รายการ"
            if debts else "🎉 คุณไม่มียอดค้างชำระเลย ขอบคุณครับ"
        ),
        color=discord.Color.red() if debts else discord.Color.green(),
    )
    for d in debts[:MAX_LIST_ROWS]:
        embed.add_field(
            name=f"📌 {d.get('title', 'ไม่ระบุ')}",
            value=(
                f"ยอดค้าง **{format_baht(d.get('amount'))} บาท**\n"
                f"กำหนดชำระ: {format_thai_date(d.get('due_date'))}"
            ),
            inline=True,
        )
    if len(debts) > MAX_LIST_ROWS:
        embed.set_footer(text=f"แสดง {MAX_LIST_ROWS} จาก {len(debts)} รายการ")
    return embed
