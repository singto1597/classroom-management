"""🧩 ตัวสร้าง embed ของงาน — แยกออกจาก cog เพื่อให้เทสต์ได้โดยไม่ต้องมี Discord (M11)

## ทำไมต้องมีไฟล์นี้

`/list_tasks` เดิมสร้าง embed ในลูปตรง ๆ แล้ว `add_field` ต่อ task หนึ่งตัว **โดยไม่จำกัดจำนวน**
⇒ ห้องที่มีงานค้าง 30 ชิ้น (ปกติมากช่วงสอบ) จะได้ฟิลด์ที่ 26 ซึ่ง **Discord API ปฏิเสธทั้งข้อความ**
ด้วย HTTP 400 `Invalid Form Body` (error code 50035) ⇒ discord.py โยน `HTTPException`

🔴 **กับดักที่ทำให้เรื่องนี้อันตรายกว่าที่คิด — และเป็นเหตุผลที่ต้องมีเทสต์ในไฟล์นี้:**
   discord.py **ไม่ตรวจเพดานเหล่านี้ฝั่ง client เลย** · `Embed.add_field` รับ 26 ฟิลด์,
   1,025 ตัวอักษร, ชื่อ 257 ตัวอักษร ไปเงียบ ๆ หมด (ยืนยันด้วยเทสต์ `PremiseTest` ด้านล่าง)
   ⇒ **ไม่มี exception ตอนสร้าง embed และไม่มีอะไรในโค้ดเราจับได้** ความผิดพลาดไปโผล่
      เป็น HTTP 400 ตอน `send` เท่านั้น ⇒ เทสต์ที่รอ `ValueError` จะ **ผ่านแบบหลอก ๆ**
      เพราะไม่มีอะไรโยนให้ดัก

🔴 อาการที่ผู้ใช้เห็นคือ **"ไม่ตอบสนอง"** ทั้งที่โหลดข้อมูลสำเร็จแล้ว — และเพราะ `except`
ในคำสั่งนั้นดักแค่ `APIException` ⇒ `HTTPException` หลุดออกไปไม่ถูกจับเลย
(เป็นรูปแบบเดียวกับ H8 ที่ error ชนิดอื่นหลุดพ้น `except APIException`)

⚠️ ยังมีเพดานที่สองที่มองไม่เห็น: embed ทั้งก้อนต้องไม่เกิน **6,000 ตัวอักษร**
   ⇒ 25 ฟิลด์ที่ `task_detail` ยาว ๆ ก็ยังทำให้ข้อความถูกปฏิเสธได้อีกทาง
   ของเดิมจึงพังได้สองทางจากข้อมูลชุดเดียวกัน

## กติกาที่ใช้จัดสรรที่ว่าง

- ฟิลด์ไม่เกิน `MAX_FIELDS` (25 — เพดานแข็งของ Discord)
- ชื่อ/ค่าฟิลด์ถูกตัดให้อยู่ในเพดานของตัวเอง **เพราะไม่มีใครตัดให้** (ดูกับดักด้านบน)
- งบตัวอักษรรวมหยุดก่อน 6,000 โดยกันที่ไว้ให้ footer
  ⇒ ของที่แสดงไม่ครบต้อง **บอกผู้ใช้ว่าซ่อนไปกี่ชิ้น** ไม่ใช่หายเงียบ ๆ
"""
from typing import Any

import discord

# เพดานแข็งของ Discord — ค่าเหล่านี้ไม่ใช่ตัวเลขที่เลือกเองได้
MAX_FIELDS = 25
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_EMBED_CHARS = 6000

# เผื่อที่ให้ footer + title ใต้เพดานจริง ⇒ ข้อความไม่มีทางชนเพดาน 6,000
EMBED_CHAR_BUDGET = 5500
_FOOTER_RESERVE = 150

_TITLE = "📋 รายการงานที่ยังไม่เสร็จ"

# ตัวคั่นที่ใช้แทนเมื่อข้อมูลหาย — ต้องมีค่าเป็นสตริงเสมอ
# เพราะ `f"{None}"` จะได้คำว่า "None" โผล่ให้ผู้ใช้เห็น
_UNKNOWN = "ไม่ระบุ"


def _clip(text: str, limit: int) -> str:
    """ตัดสตริงให้ไม่เกิน `limit` ตัวอักษร โดยคงความยาวไว้ที่ `limit` พอดี

    🔑 ใช้ `…` แทนการเฉย ๆ ตัดกลางคำ เพื่อให้ผู้ใช้อ่านออกว่า "ข้อความยังมีต่อ"
    ⚠️ ต้องได้ผลลัพธ์ยาว **ไม่เกิน** limit — ตรวจในเทสต์ เพราะ **ไม่มีใครตรวจให้**:
       discord.py รับค่าที่เกินเพดานไปเงียบ ๆ แล้วปล่อยให้ HTTP 400 ไปโผล่ตอนส่ง
       ⇒ พลาดไป 1 ตัวอักษร = ข้อความทั้งใบหาย โดยไม่มีอะไรเตือนระหว่างทาง
    """
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _task_to_field(task: dict[str, Any]) -> tuple[str, str]:
    """แปลง task หนึ่งตัวเป็น `(name, value)` ที่ผ่านเพดานของ Discord แล้ว

    ⚠️ ใช้ `.get()` ทุกช่อง — ข้อมูลจาก API อาจขาดคีย์ (งานที่ยังไม่กรอกรายละเอียด)
       ของเดิมใช้ `task['task_detail']` ตรง ๆ ⇒ `KeyError` หลุดพ้น `except APIException`
       เหมือนกัน เป็นบั๊กคนละทางที่ซ่อนอยู่ในบรรทัดเดียวกัน
    """
    name = task.get("task_name") or "ไม่ระบุชื่องาน"
    due_date = task.get("due_date") or _UNKNOWN
    detail = task.get("task_detail") or "-"

    raw_created = task.get("created_at") or ""
    # `created_at` มาเป็น ISO string ⇒ เอาแค่วันที่ (รูปแบบเดิมของคำสั่งนี้)
    created = raw_created.split("T")[0] if raw_created else _UNKNOWN

    value = f"📅 กำหนดส่ง: {due_date}\nรายละเอียด: {detail}\n(บันทึกเมื่อ: {created})"
    return _clip(f"📌 {name}", MAX_FIELD_NAME), _clip(value, MAX_FIELD_VALUE)


def build_no_pending_tasks_embed() -> discord.Embed:
    """ตอบเมื่อไม่มีงานค้างเลย — เป็น Embed เพื่อให้ทุกคำตอบของคำสั่งนี้หน้าตาเหมือนกัน

    📌 ข้อความคงคำเดิมไว้ทุกตัวอักษร ("ไม่มีงานเลยจ้าา") — เปลี่ยนแค่ภาชนะที่ใส่
       ไม่ใช่โอกาสที่จะแก้สำนวนของผลิตภัณฑ์
    """
    return discord.Embed(title="🎉 ไม่มีงานเลยจ้าา", color=discord.Color.green())


def build_pending_tasks_embed(tasks: list[dict[str, Any]]) -> discord.Embed:
    """สร้าง embed ของงานค้าง โดยรับประกันว่า Discord จะไม่ปฏิเสธ

    📌 ที่ว่างถูกใช้ตามลำดับที่ API ส่งมา (งานที่ถึงกำหนดก่อนอยู่บน) ⇒ งานที่ถูกซ่อน
       คือ "ท้ายรายการ" เสมอ ซึ่งเป็นครึ่งที่ผู้ใช้อ่านถึงน้อยที่สุด
    """
    embed = discord.Embed(title=_TITLE, color=discord.Color.blue())

    used = len(_TITLE)
    shown = 0
    total = len(tasks)

    for task in tasks:
        if shown >= MAX_FIELDS:
            break

        name, value = _task_to_field(task)
        field_cost = len(name) + len(value)
        if used + field_cost > EMBED_CHAR_BUDGET - _FOOTER_RESERVE:
            break

        embed.add_field(name=name, value=value, inline=False)
        used += field_cost
        shown += 1

    if shown < total:
        # 🔑 ต้องบอกเสมอว่าแสดงไม่ครบ — ไม่งั้นครูเห็น 25 งานแล้วนึกว่าห้องมีงานแค่นั้น
        embed.set_footer(text=f"แสดง {shown} จาก {total} งานค้าง — ที่เหลือดูได้จากหน้าเว็บ")

    return embed
