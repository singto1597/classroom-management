"""💬 ตัวสร้าง embed สำหรับ "ข้อความตอบกลับ" ของบอท (ผลตรวจระบบ 2026-09-23 → M10)

## ทำไมต้องมีไฟล์นี้

บอทตอบกลับผู้ใช้ด้วยข้อความดิบ (`content=`) อยู่ **44 จุดใน 8 ไฟล์** ซึ่งขัดกับกติกา
ของโปรเจกต์เอง (`docs/rules/discord-bot.md`: "always render results as `discord.Embed`")
แต่ที่ร้ายกว่าเรื่องหน้าตาคือ **21 จุดในนั้นเป็น `f"❌ {e}"`** โดย `e` คือข้อความ
ที่มาจากชั้น API — **ข้อความที่เราไม่ได้เป็นคนเขียน และไม่รู้ความยาว**

🔴 **ทำไมความยาวที่ควบคุมไม่ได้จึงกลายเป็น "บอทไม่ตอบ"**
   `content=` ของ Discord มีเพดาน **2,000 ตัวอักษร** และเมื่อเกิน **API ปฏิเสธทั้งข้อความ**
   ด้วย HTTP 400 `Invalid Form Body` (code 50035) → discord.py โยน `HTTPException`

   ⇒ ผู้ใช้กดคำสั่ง แล้ว **เงียบสนิท** ทั้งที่งานข้างหลังอาจสำเร็จไปแล้ว
     และเพราะคำสั่งเหล่านี้ดักแค่ `APIException` ⇒ `HTTPException` **หลุดพ้นไปไม่ถูกจับ**
     (รูปแบบเดียวกับ H8 — error ที่อยู่นอกชนิดที่ดักไว้ จะไม่มีใครจับ)

   🧨 ข้อความ error จากปลายทางยาวเกิน 2,000 ได้จริงโดยไม่ต้องมีใครทำอะไรผิด:
      proxy/Cloudflare ตอบหน้า HTML, traceback หลุดออกมา, backend ตอบ JSON ก้อนใหญ่
      ⇒ นี่ไม่ใช่ความผิดของข้อมูล แต่เป็นเพราะ **เราไม่เคยจำกัดความยาวก่อนส่ง**

## กับดักเดียวกับ M11 — discord.py ไม่ตรวจให้

   discord.py **ไม่ตรวจเพดาน embed ฝั่ง client** · สร้าง `Embed(description=...)` ที่ยาว
   4,097 ตัวอักษรได้เงียบ ๆ ⇒ ไม่มี exception ตอนสร้าง ไม่มีอะไรให้ดักในโค้ดเรา
   ความผิดพลาดไปโผล่เป็น HTTP 400 ตอน `send` เท่านั้น

   ⇒ **เพดานถูกบังคับที่นี่ที่เดียว** (`clip`) และถูกล็อกด้วยเทสต์ เพราะถ้าไม่มีเทสต์
     "โค้ดที่ดูเหมือนป้องกัน" กับ "โค้ดที่ป้องกันจริง" แยกออกจากกันไม่ได้เลย

## เพดานที่ใช้

- `EMBED_DESC_LIMIT` = 4,096 — เพดาน description ของ embed (สูงกว่า `content` 2,000)
  ⇒ **ย้ายเข้า embed คือการยกเพดานขึ้นเท่าตัว** ไม่ใช่ย้ายภาชนะเฉย ๆ
  ⇒ และเป็นเหตุผลว่าทำไม `content=` จึงไม่ควรถูกใช้กับข้อความที่ความยาวไม่รู้ล่วงหน้า
- `ERROR_TEXT_BUDGET` = 1,000 — งบที่เราตั้งเองสำหรับข้อความ error **ต่ำกว่าเพดานมาก**
  📌 ไม่ได้กันแค่ HTTP 400: ข้อความ error 4,000 ตัวอักษรในมือครู **อ่านไม่รู้เรื่อง**
     ส่วนที่เกิน 1,000 แทบไม่เคยมีข้อมูลที่ต้องใช้ตัดสินใจ — มีแต่ stack trace
"""
from __future__ import annotations

import discord

# เพดานแข็งของ Discord — ตัวเลขของบุคคลที่สาม เขียนตรง ๆ ไม่ดึงจากที่อื่น
EMBED_DESC_LIMIT = 4096
EMBED_TITLE_LIMIT = 256

# งบที่เราตั้งเองสำหรับข้อความ error (ดูเหตุผลท้าย docstring)
ERROR_TEXT_BUDGET = 1000

# ข้อความที่ยาวเกินกว่าจะตัดทิ้งแล้วยังอ่านออก ⇒ คั่นด้วย `…` ให้รู้ว่ายังมีต่อ
_ELLIPSIS = "…"

# ⚠️ Discord ปฏิเสธ embed ที่ **ว่างเปล่า** ("Cannot send an empty message")
#    ⇒ ถ้าข้อความว่าง (หรือมีแต่ช่องว่าง) ต้องมีอะไรสักอย่างแทน ไม่งั้นเจอ 400 อีกทาง
_EMPTY_FALLBACK = "ไม่ระบุรายละเอียด"


def clip(text: str, limit: int) -> str:
    """ตัดสตริงให้ยาว **ไม่เกิน** `limit` ตัวอักษร โดยคงความยาวไว้ที่ `limit` พอดี

    🔑 ใช้ `…` แทนการตัดกลางคำเงียบ ๆ เพื่อให้ผู้อ่านรู้ว่า "ข้อความยังมีต่อ"
       (การตัดแล้วไม่มีร่องรอย ทำให้ข้อความที่ถูกตัดดูเหมือนข้อความเต็มที่จบแปลก ๆ)

    ⚠️ ผลลัพธ์ต้องยาว **ไม่เกิน** limit เสมอ — และต้องมีเทสต์คุม เพราะ **ไม่มีใครตรวจให้**
       (ดู "กับดัก" ใน docstring หลัก) ⇒ พลาดไป 1 ตัวอักษร = ข้อความทั้งใบหาย
    """
    if len(text) <= limit:
        return text
    return text[: limit - len(_ELLIPSIS)] + _ELLIPSIS


def _build(
    message: str, color: discord.Color, title: str | None, limit: int
) -> discord.Embed:
    """ประกอบ embed จากข้อความดิบ — จุดเดียวที่เพดานถูกบังคับ

    🔑 ทุกทางที่ข้อความของผู้ใช้/ปลายทางไหลเข้า embed ต้องผ่านฟังก์ชันนี้
      ⇒ มีที่เดียวให้ตรวจ และที่เดียวให้เทสต์ (ไม่ใช่ 44 ที่ที่ต้องเชื่อว่าทำถูก)
    """

    # ⚠️ `title` ถูกตัดที่ `EMBED_TITLE_LIMIT` ด้วยเหตุผลเดียวกับ description
    #    (เพดานนี้ไม่ค่อยได้ใช้ เพราะชื่อส่วนใหญ่เป็นคีย์คงที่ในโค้ด — ใส่ไว้กันพลาด)
    if title is not None:
        title = clip(title, EMBED_TITLE_LIMIT)

    text = message if message and message.strip() else _EMPTY_FALLBACK
    return discord.Embed(title=title, description=clip(text, limit), color=color)


def error_embed(message: str, *, title: str | None = None) -> discord.Embed:
    """ข้อความ error (แดง) — ใช้แทน `f"❌ {e}"` ทุกจุด

    📌 `message` มักเป็นข้อความที่ต่อจาก exception ⇒ **ความยาวไม่รู้ล่วงหน้า**
       ซึ่งคือเหตุผลทั้งหมดที่ฟังก์ชันนี้ต้องมี ไม่ใช่แค่เรื่องสี
    📌 งบของ error แน่นกว่า embed ปกติ (`ERROR_TEXT_BUDGET`) ⇒ ตัดตั้งแต่ 1,000
       ไม่รอถึง 4,096 — ข้อความ error ที่ยาวกว่านั้นอ่านไม่ได้อยู่ดี
    """
    return _build(message, discord.Color.red(), title, ERROR_TEXT_BUDGET)


def success_embed(message: str, *, title: str | None = None) -> discord.Embed:
    """ข้อความสำเร็จ (เขียว) — ใช้แทนข้อความ `"✅ ..."` เดิม"""
    return _build(message, discord.Color.green(), title, EMBED_DESC_LIMIT)


def warning_embed(message: str, *, title: str | None = None) -> discord.Embed:
    """ข้อความเตือน (ส้ม) — ข้อมูลไม่ครบ / ต้องให้ผู้ใช้ยืนยัน"""
    return _build(message, discord.Color.orange(), title, EMBED_DESC_LIMIT)


def info_embed(message: str, *, title: str | None = None) -> discord.Embed:
    """ข้อความทั่วไป (น้ำเงิน) — แจ้งผลที่ไม่ใช่ทั้งสำเร็จและผิดพลาด"""
    return _build(message, discord.Color.blue(), title, EMBED_DESC_LIMIT)
