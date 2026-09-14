"""[F3] เรนเดอร์ใบเสร็จ/ใบแจ้งหนี้เป็น PDF ผ่าน Gotenberg (headless Chromium)

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้อง Gotenberg (headless Chrome) ไม่ใช้ reportlab
═══════════════════════════════════════════════════════════════════════════════
ภาษาไทยซ้อนสระ/วรรณยุกต์ (เช่น ญ ฎ ฐ ที่มีตัวหาง + ไม้โท/ไม้เอก ซ้อนกัน) ต้องอาศัย
**OpenType shaping engine** (harfbuzz) ในการจัดตำแหน่ง glyph ให้ถูก
reportlab ไม่มี harfbuzz → วรรณยุกต์จะไปลอยผิดตำแหน่งบนเอกสารที่ครูพิมพ์แจกจริง
ส่วน Chromium มี harfbuzz ในตัวและจัดวางฟอนต์ไทยได้ถูกต้องอยู่แล้ว ⇒ เลือกใช้ของที่ถูก

═══════════════════════════════════════════════════════════════════════════════
ทำไมฝังฟอนต์เป็น base64 data URI (ไม่ส่ง multipart / ไม่อ้าง file://)
═══════════════════════════════════════════════════════════════════════════════
Gotenberg เรนเดอร์ HTML **ใน container ของตัวเอง** ⇒ URL แบบ `file:///app/assets/fonts/...`
จะไป resolve ที่ filesystem ของ Gotenberg ไม่ใช่ของ backend → 404 เงียบ ๆ แล้ว Chromium
fallback ไปฟอนต์อื่นที่ไม่มี glyph ไทย = เอกสารออกมาเป็นกล่องสี่เหลี่ยม

ทางเลือกคือส่งไฟล์ฟอนต์ไปกับ multipart แล้วอ้าง `url('NotoSansThai.ttf')` ซึ่งได้ผลเช่นกัน
แต่ผูกกับพฤติกรรมการวางไฟล์ใน working directory ของ Gotenberg (ต่างกันตามเวอร์ชัน/รูปแบบ request)
⇒ **ฝังเป็น data URI ไปใน CSS เลย** ตัดตัวแปรทั้งหมดทิ้ง: HTML ไฟล์เดียวจบ
ไม่ต้องพึ่งไฟล์ในเครื่อง Gotenberg เลย และได้ผลเหมือนกันทุก environment
"""
import base64
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from core.config import settings
from .constants import (
    PDF_ASSET_MISSING_MSG, PDF_RENDER_FAILED_MSG, PDF_RENDER_UNAVAILABLE_MSG,
    RECEIPT_FONT_DIR, RECEIPT_FONT_FAMILY, RECEIPT_FONT_FILES,
    RECEIPT_TEMPLATE_DIR, RECEIPT_TEMPLATE_NAME,
)

logger = logging.getLogger("API_FINANCE_PDF")

# 🎯 ยึดจากตำแหน่งไฟล์ ไม่ใช่ cwd — backend รันที่ WORKDIR /app แต่ test_runner
#    mount ./backend → /app คนละบริบท ถ้าอิง cwd จะพังเงียบ ๆ ในเทสต์
#    services/finance/pdf.py → parents[2] = โฟลเดอร์ backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = BACKEND_ROOT / RECEIPT_TEMPLATE_DIR / RECEIPT_TEMPLATE_NAME
FONT_DIR = BACKEND_ROOT / RECEIPT_FONT_DIR

# Gotenberg 8: endpoint เดียวที่ใช้ (multipart: ฟิลด์ชื่อ `files` และต้องชื่อ index.html)
GOTENBERG_CONVERT_PATH = "/forms/chromium/convert/html"
# A4 (นิ้ว) — เอกสารการเงินควรเป็น A4 มาตรฐาน ไม่ใช่ Letter (8.27×11.69 in = 210×297 mm)
_PAPER = {"paperWidth": "8.27", "paperHeight": "11.69"}
# 🎯 ขอบกระดาษ = 0 **โดยเจตนา** — ให้ CSS ในเทมเพลต (`.doc { padding: 14mm ... }`) เป็น
#    แหล่งเดียวที่กำหนดระยะขอบ ถ้าตั้งที่นี่ด้วยจะกลายเป็นระยะขอบสองชั้นซ้อนกัน (26 มม.)
#    แล้วแก้ที่เทมเพลตไม่เห็นผล ทำให้จูนเลย์เอาต์ไม่ได้
#    ⚠️ padding ต้องอยู่ที่ **`.doc` (บล็อกต่อใบ) ไม่ใช่ `body`** — padding ของ `body`
#       มีผลเฉพาะหน้าแรกกับหน้าสุดท้ายของ flow ที่แบ่งหน้า ⇒ ในไฟล์รวม หน้า 2..N
#       จะไม่มีขอบเลย (ทดสอบด้วยตากับ Gotenberg จริงแล้ว)
_MARGINS = {"marginTop": "0", "marginBottom": "0", "marginLeft": "0", "marginRight": "0"}
# เรนเดอร์ฟอนต์/สีพื้นหลังให้ครบ (default ของ Chromium ตัด background ทิ้ง)
_OPTS = {"printBackground": "true", "preferCssPageSize": "false"}


class PdfRenderError(Exception):
    """เรียก Gotenberg ไม่สำเร็จ หรือเรนเดอร์ไม่ผ่าน"""


@lru_cache(maxsize=len(RECEIPT_FONT_FILES))
def _font_data_uri(font_key: str) -> str:
    """อ่านไฟล์ฟอนต์ → base64 data URI (cache เพราะไฟล์ละ ~45KB และอ่านซ้ำทุกใบเสร็จ)"""
    filename = RECEIPT_FONT_FILES[font_key][0]
    path = FONT_DIR / filename
    if not path.is_file():
        # 🔒 ข้อความถึงผู้ใช้ห้ามมี path — ดูเหตุผลที่ PDF_ASSET_MISSING_MSG ใน constants.py
        logger.error("ไม่พบไฟล์ฟอนต์สำหรับ PDF: %s", path)
        raise PdfRenderError(PDF_ASSET_MISSING_MSG)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


@lru_cache(maxsize=1)
def _get_template():
    """โหลด Jinja2 template ครั้งเดียว (autoescape เปิด — กันชื่อนักเรียนที่มี < > ทำ HTML พัง)"""
    try:
        import jinja2
    except ImportError as e:  # pragma: no cover - กัน dependency หายตอน deploy
        logger.error("ยังไม่ได้ติดตั้ง jinja2 — เพิ่ม jinja2 ลง backend/requirements.txt")
        raise PdfRenderError(PDF_ASSET_MISSING_MSG) from e

    if not TEMPLATE_PATH.is_file():
        logger.error("ไม่พบเทมเพลตใบเสร็จ: %s", TEMPLATE_PATH)
        raise PdfRenderError(PDF_ASSET_MISSING_MSG)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_PATH.parent)),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env.get_template(TEMPLATE_PATH.name)


def render_receipts_html(contexts: list) -> str:
    """เรนเดอร์เอกสาร **N ใบ** เป็น HTML ไฟล์เดียว (PDF รวม = หน้าละใบ)

    `contexts` = ลิสต์ของ context ต่อใบ (โครงเดียวกับที่ `render_receipt_html` รับ)
    เทมเพลตวนสร้าง `<div class="doc">` ต่อหนึ่งใบ — **`<style>` อยู่นอกลูป**
    ⇒ `@font-face` ยังมี 2 อันเท่าเดิมไม่ว่าจะกี่ใบ (ฟอนต์ฝังครั้งเดียว ไม่บวมตาม N)

    ⚠️ ฟอนต์เป็น data URI ~61,000 ตัวอักษรต่อไฟล์ ⇒ ถ้าเผลอย้าย `<style>` เข้าไปในลูป
       ไฟล์ HTML จะโตเป็น N เท่าโดยไม่จำเป็นและเทสต์นับ `data:font/ttf;base64,` จะพัง
    """
    if not contexts:
        raise ValueError("ต้องมีอย่างน้อย 1 เอกสารในการเรนเดอร์")

    ctx = {
        "documents": contexts,
        # 🏷️ `<title>` ของไฟล์รวม — เอกสารหลายใบไม่มี "เลขที่" เดียวให้ใช้
        #    (ต้องส่งค่านี้เสมอ ไม่งั้น `<title>` ว่าง)
        "page_title": (
            f"{contexts[0].get('doc_title') or ''} {contexts[0].get('receipt_no') or ''}".strip()
            if len(contexts) == 1
            else f"เอกสารการเงิน {len(contexts)} ฉบับ"
        ),
        "font_family": RECEIPT_FONT_FAMILY,
        "font_faces": _font_faces(),
    }
    return _get_template().render(**ctx)


def render_receipt_html(context: dict) -> str:
    """เรนเดอร์เอกสาร **1 ใบ** — shim บาง ๆ เหนือ `render_receipts_html`

    `context` ถูกส่งเข้าเทมเพลตทั้งก้อน — เทมเพลตเป็นคนเลือกใช้ (ไม่ทำ whitelist
    เพราะ context ประกอบจาก service ที่อ่าน DB เอง ไม่ได้มาจาก client)

    🖋️ ส่ง `font_faces` เป็น **ลิสต์** (ไฟล์ + น้ำหนัก) ให้เทมเพลตวนสร้าง @font-face
       ⇒ จับคู่ "ไฟล์ ↔ น้ำหนัก" ไว้ที่ `constants.RECEIPT_FONT_FILES` ที่เดียว
       เทมเพลตไม่ต้องรู้จักชื่อไฟล์ และเพิ่มน้ำหนักใหม่ไม่ต้องแก้ HTML
       ⚠️ ห้ามเปลี่ยนไปใช้ `font-weight: 100 900` กับฟอนต์ตัวแปร — ดูเหตุผลใน constants.py

    ⚠️ **คงชื่อนี้ไว้ public** แม้จะเป็น shim: เทสต์เรียกตรงโดยไม่ต้องมี DB
       (`test_receipt_template_declares_one_font_face_per_weight`) ⇒ เปลี่ยนชื่อ = เทสต์พัง
    """
    return render_receipts_html([context])


def _font_faces() -> list:
    """[{uri, weight}] สำหรับเทมเพลต — มาจาก `RECEIPT_FONT_FILES` ที่เดียว"""
    return [
        {"uri": _font_data_uri(key), "weight": weight}
        for key, (_, weight) in RECEIPT_FONT_FILES.items()
    ]


async def html_to_pdf(html: str, *, timeout: float = 30.0) -> bytes:
    """POST HTML เข้า Gotenberg → คืน bytes ของ PDF

    ⚠️ ต้องเป็นการเรียก **ข้าม service** เสมอ (container `*_pdf_gotenberg:3000`)
       ค่า default ของ GOTENBERG_URL เป็น localhost เพื่อให้เทสต์ import ได้โดยไม่ต้องมี service
       แต่ตอน deploy ต้องตั้ง env ตาม docker-compose.app.yml
    """
    url = f"{settings.GOTENBERG_URL.rstrip('/')}{GOTENBERG_CONVERT_PATH}"
    files = {"files": ("index.html", html.encode("utf-8"), "text/html")}
    data = {**_PAPER, **_MARGINS, **_OPTS}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, files=files, data=data)
    except httpx.HTTPError as e:
        # ครอบ network error ให้เป็น domain error — router แปลงเป็น 502 ได้ที่เดียว
        #
        # 🔒 ข้อความที่ผู้ใช้เห็นต้อง **ไม่มี URL/hostname ภายใน** และไม่มีความดิบจาก upstream
        #    เพราะเส้นทาง PDF เปิดแค่ `require_member` ⇒ สมาชิกทุกคนของห้องอ่านได้
        #    รายละเอียดจริงที่ต้องมีไว้สอบสวนไปที่ log ฝั่ง server แทน (ไม่หายไปไหน)
        logger.error("สร้าง PDF ไม่สำเร็จ: ต่อ Gotenberg ไม่ได้ (url=%s): %s", url, e)
        raise PdfRenderError(PDF_RENDER_UNAVAILABLE_MSG) from e

    if resp.status_code != 200:
        # Gotenberg คืนข้อความ error ที่มีประโยชน์ (เช่น Chromium crash) — ตัดมาแค่ 500 ตัวแรก
        # ⚠️ เก็บไว้ที่ log เท่านั้น ห้ามใส่ใน exception ที่ส่งถึงผู้ใช้
        detail = resp.text[:500] if resp.text else "(ไม่มีรายละเอียด)"
        logger.error("สร้าง PDF ไม่สำเร็จ: Gotenberg ตอบ %s — %s", resp.status_code, detail)
        raise PdfRenderError(PDF_RENDER_FAILED_MSG)

    if not resp.content:
        # ⚠️ เดิมข้อความนี้เอ่ยชื่อ "Gotenberg" ตรง ๆ — ชื่อ service ภายในต้องไม่ถึงมือสมาชิก
        #    และมันขัดกับเทสต์ที่ห้ามคำนี้ในอีกสองสาขาข้างบน ⇒ ใช้ข้อความกลางตัวเดียวกัน
        logger.error("สร้าง PDF ไม่สำเร็จ: Gotenberg ตอบ 200 แต่เนื้อหาว่าง (url=%s)", url)
        raise PdfRenderError(PDF_RENDER_FAILED_MSG)
    return resp.content


def pdf_filename(receipt_no: str, doc_type: str) -> str:
    """ชื่อไฟล์ดาวน์โหลด — ใช้ receipt_no ตรง ๆ เพื่อให้ตรงกับเลขบนเอกสาร

    ⚠️ ต้องเป็น dict ที่มี default **ไม่ใช่ if/else สองทาง**: เดิมเขียน
    `"receipt" if doc_type == "receipt" else "invoice"` ⇒ ชนิดเอกสารที่สาม
    (deposit) จะถูกตั้งชื่อว่า `invoice-DEP-2569-0001.pdf` = **ชื่อไฟล์โกหก**
    โดยไม่มีอะไรฟ้อง (ต่างจาก `DOC_TYPE_PREFIXES[doc_type]` ที่ `KeyError` ให้เห็น)
    """
    prefix = {
        "receipt": "receipt",
        "invoice": "invoice",
        "deposit": "deposit",
    }.get(doc_type, "document")
    safe = receipt_no.replace("/", "-")
    return f"{prefix}-{safe}.pdf"


def pdf_filename_batch(receipt_nos: list, doc_type: str = "receipt") -> str:
    """ชื่อไฟล์ของ **PDF รวมหลายใบ** — บอกช่วงเลขที่ไว้ในชื่อเพื่อให้แยกออกจากไฟล์ใบเดียว

    ⚠️ ตั้งชื่อตาม "ช่วง" ไม่ใช่ "วันที่ที่กดโหลด": ไฟล์ที่ชื่อเป็นวันที่จะแยกไม่ออกว่า
       เป็นชุดไหนเมื่อมีหลายชุดในวันเดียวกัน และไม่ตรงกับเลขบนเอกสารข้างใน
    """
    prefix = {"receipt": "receipts", "invoice": "invoices"}.get(doc_type, "documents")
    first = str(receipt_nos[0]).replace("/", "-")
    last = str(receipt_nos[-1]).replace("/", "-")
    if first == last:
        return f"{prefix}-{first}.pdf"
    return f"{prefix}-{first}-to-{last}.pdf"


def gotenberg_configured() -> Optional[str]:
    """คืน URL ถ้าตั้งค่าชี้ปลายทางที่ไม่ใช่ค่า default (ใช้ตัดสิน skip ในเทสต์จริง)"""
    url = (settings.GOTENBERG_URL or "").strip()
    if not url or "localhost" in url or "127.0.0.1" in url:
        return None
    return url
