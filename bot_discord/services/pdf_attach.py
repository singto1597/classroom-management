"""📎 แนบ PDF เอกสารการเงินไปกับข้อความแจ้งเตือน (F5/PR-3 · F6/PR-6)

ใช้สองเส้นทาง (ตัวช่วยเดียวกันทั้งคู่ — ตรรกะ "แนบไม่ได้ ≠ ส่งไม่ได้" เหมือนกันเป๊ะ):
- `FINANCE_PAYMENT` → ใบเสร็จ/ใบรับเงินล่วงหน้า (F5/PR-3)
- `FINANCE_TRANSACTION` → ใบสำคัญจ่าย/ใบรับเงิน (F6/PR-6)

⚠️ ชื่อ `build_receipt_files` ยังเป็นชื่อเดิมจาก PR-3 โดยเจตนา — มันคือ "ไฟล์ของ
   *เอกสาร* ที่ออกให้เหตุการณ์การเงินหนึ่งครั้ง" ไม่ได้ผูกกับ `doc_type` ใด ๆ
   (ฝั่ง backend เลือก template/ชื่อไฟล์จาก `doc_type` เองอยู่แล้ว)
   🔑 ข้อความที่ผู้ใช้อ่าน **ห้ามพูดว่า "ใบเสร็จ"** เมื่อเอกสารอาจเป็นใบสำคัญจ่าย
      ⇒ ใช้คำกลางว่า "เอกสาร" (ใบสำคัญจ่ายไม่ใช่ใบเสร็จ)

## กฎเหล็กของไฟล์นี้: **ไฟล์แนบพัง = ข้อความต้องไม่งั้นพัง**

การแจ้งเตือน "รับเงินแล้ว" คือหลักฐานความโปร่งใสที่ห้องต้องเห็น — การที่ Gotenberg ล่ม
หรือไฟล์ใหญ่เกิน **ห้าม** ทำให้ข้อความหายไป ⇒ ทุกเส้นทางในไฟล์นี้คืนค่าเป็น
`(files, note)` โดย `files` ว่างได้เสมอ และ `note` คือบรรทัดที่ต้องต่อท้าย embed เพื่อ
บอกความจริงว่าทำไมไม่มีไฟล์ (ดีกว่าเงียบแล้วคนเข้าใจว่าลืมแนบ)

## ทำไมต้องมี `asyncio.wait_for` (ชั้นที่ 1 ของ 4)

Gotenberg ตั้ง `--api-timeout` ไว้ 120 วินาที ฝั่ง backend จึงรอได้นานขนาดนั้น
⇒ ถ้าบอทรอตามโดยไม่มีเพดานของตัวเอง **ข้อความจะมาช้ากว่าสองนาที** ซึ่งแย่กว่าไม่มีไฟล์
⇒ เพดานของบอทต้องสั้นกว่าของ backend (`PDF_FETCH_TIMEOUT_S = 60`) เพื่อให้ "ยังไม่ทัน"
กลายเป็น "แนบไม่ได้ แต่ข้อความออกเลย"

⚠️ **`asyncio.wait_for` ยกเลิกงานจริง** (cancel coroutine ข้างใน) ไม่ใช่แค่เลิกรอ
   ⇒ คำขอที่ค้างจะไม่ไปกิน connection ของ aiohttp ต่อ
"""
import asyncio
import io
import logging
from typing import List, Optional, Sequence, Tuple

import discord

from services.finance_api import (
    PDF_CHUNK_SIZE,
    fetch_documents_pdf,
)

logger = logging.getLogger("DISCORD_BOT")

# 🔒 Discord จำกัดไฟล์แนบ 10 MB สำหรับ server ที่ไม่ boost — เผื่อไว้ 1 MB
#    (ค่า 10 MB คือขีดที่ Discord **ปฏิเสธทั้งข้อความ** ไม่ใช่แค่ตัดไฟล์ทิ้ง)
DISCORD_ATTACH_MAX_BYTES = 9 * 1024 * 1024

# ⏱️ ต้องสั้นกว่า Gotenberg `--api-timeout` (120s) — ดูเหตุผลใน docstring บนสุด
PDF_FETCH_TIMEOUT_S = 60

# 🚦 เพดานจำนวน PDF ที่โหลดพร้อมกัน — listener เปลี่ยนเป็น `create_task` แล้ว (ดู
#    `cogs/redis_listener.py`) ⇒ ถ้าไม่จำกัด งาน import 500 คนพร้อมกันจะยิง Gotenberg
#    ทั้งชุดและแย่ง CPU กันจนไม่มีใครเสร็จ · 2 พอสำหรับเหตุการณ์จริง (เงินก้อนหนึ่ง =
#    บิลของนักเรียน **คนเดียว** — `batch_confirm_payments` ปฏิเสธหลายคนตั้งแต่ต้นทาง)
MAX_CONCURRENT_PDF_FETCHES = 2

# 📌 ข้อความกลางที่ใช้เมื่อ "แนบไม่ได้" ด้วยเหตุที่ผู้ใช้อ่านไม่รู้เรื่อง (timeout/HTTP error)
ATTACH_FAILED_NOTE = "📎 แนบไฟล์ไม่ได้ในตอนนี้ (ดาวน์โหลดได้ที่หน้าทะเบียนเอกสาร)"


async def build_receipt_files(
    server_id: int,
    discord_id,
    receipt_nos: Optional[Sequence[str]],
    *,
    fetch=None,
    timeout: float = PDF_FETCH_TIMEOUT_S,
) -> Tuple[List[discord.File], Optional[str]]:
    """โหลด PDF ของ `receipt_nos` แล้วห่อเป็นไฟล์แนบ → คืน `(files, note)`

    | กรณี | `files` | `note` |
    |---|---|---|
    | ไม่มีเลขใบเสร็จใน payload (บิลเดียว / ติ๊กปิด) | `[]` | `None` (ไม่แนบ ไม่ต้องอธิบาย) |
    | เกิน `PDF_CHUNK_SIZE` | `[]` | บอกจำนวนจริง + ทางออก |
    | timeout / error / body ว่าง | `[]` | `ATTACH_FAILED_NOTE` |
    | ไฟล์ใหญ่เกิน `DISCORD_ATTACH_MAX_BYTES` | `[]` | บอกขนาดจริง + ทางออก |
    | สำเร็จ | `[discord.File]` | `None` |

    ⚠️ **งดแนบเมื่อเกิน `PDF_CHUNK_SIZE` แทนการแบ่งเป็นหลายไฟล์** — ฝั่ง backend รับ
       "หลายไฟล์ต่อหนึ่งคำขอ" ไม่ได้ และการยิงหลายคำขอจะได้ PDF หลายไฟล์ที่แยกกัน
       (คนละเลขหน้า) ⇒ ผู้ใช้ได้ไฟล์ที่ต้องรวมเองอยู่ดี แลกกับความซับซ้อนที่ไม่จำเป็น
       📌 ข้อความยังออกครบพร้อมทางออก ⇒ "เรียบง่าย ซื่อสัตย์ ตรงกับข้อมูลจริง"

    🔑 `fetch` ฉีดได้ (dependency injection) ⇒ เทสต์ครอบทุกสาขาข้างบนได้โดยไม่ต้องมี
       เซิร์ฟเวอร์หรือ mock aiohttp (ดู `tests/test_pdf_attach.py`)
    """
    nos = [str(n).strip() for n in (receipt_nos or []) if str(n).strip()]
    if not nos:
        # เส้นทางเดิม (บิลเดียว / ติ๊ก "ออกใบเสร็จ" ออก) ⇒ ต้องไม่แตะ network เลย
        return [], None

    if len(nos) > PDF_CHUNK_SIZE:
        return [], (
            f"🧾 ชุดนี้มี {len(nos)} ใบ เกินกว่าจะแนบใน Discord "
            f"(แนบได้ครั้งละไม่เกิน {PDF_CHUNK_SIZE} ใบ) — ดาวน์โหลดได้ที่หน้าทะเบียนเอกสาร"
        )

    fetch = fetch or fetch_documents_pdf
    try:
        pdf_bytes, filename = await asyncio.wait_for(
            fetch(server_id, discord_id, nos), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(
            f"⏱️ ขอ PDF ไม่ทันเวลา (>{timeout}s) server={server_id} · {len(nos)} ใบ "
            "— ส่งข้อความต่อโดยไม่มีไฟล์"
        )
        return [], ATTACH_FAILED_NOTE
    except Exception as e:
        # 🛡️ ชั้นที่ 2 ของ 4: กว้างโดยเจตนา — APIException / aiohttp error / bug ในโค้ด
        #    แปลงไฟล์ ล้วนต้องจบที่ "ไม่มีไฟล์" ไม่ใช่ "ไม่มีข้อความ"
        logger.error(
            f"❌ ขอ PDF ไม่สำเร็จ ({type(e).__name__}: {e}) server={server_id} · {len(nos)} ใบ "
            "— ส่งข้อความต่อโดยไม่มีไฟล์"
        )
        return [], ATTACH_FAILED_NOTE

    if not pdf_bytes:
        logger.error(f"❌ ได้ PDF ความยาว 0 ไบต์ server={server_id} · {len(nos)} ใบ")
        return [], ATTACH_FAILED_NOTE

    if len(pdf_bytes) > DISCORD_ATTACH_MAX_BYTES:
        logger.error(
            f"❌ ไฟล์ใหญ่เกินเพดาน Discord ({len(pdf_bytes)} > {DISCORD_ATTACH_MAX_BYTES} ไบต์) "
            f"server={server_id} · {len(nos)} ใบ"
        )
        return [], (
            f"🧾 ไฟล์เอกสารใหญ่เกินกว่าจะแนบใน Discord "
            f"({len(pdf_bytes) / 1024 / 1024:.1f} MB) — ดาวน์โหลดได้ที่หน้าทะเบียนเอกสาร"
        )

    return [discord.File(io.BytesIO(pdf_bytes), filename=filename)], None
