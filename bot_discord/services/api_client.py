import asyncio
import json
from typing import Any
from urllib.parse import unquote

import aiohttp
from core.config import API_BASE_URL, API_KEY


class APIException(Exception):
    """Custom Exception สำหรับดัก Error จาก Backend"""
    pass


# ⏱️ เพดานเวลารอ backend — **ต้องมี ไม่งั้นคำขอที่ค้างจะค้างตลอดไป**
#
# 🔴 เดิมไม่ตั้ง timeout เลย ⇒ aiohttp ใช้ค่า default ของตัวเอง (5 นาที) ⇒ ถ้า backend
#    ไม่ตอบ (container ตาย, Traefik ค้าง, DB lock) คำสั่ง Discord จะค้างเงียบ ๆ 5 นาที
#    โดยที่ interaction หมดอายุไปตั้งแต่ 3 วินาทีแล้ว ⇒ ผู้ใช้เห็น "The application
#    did not respond" **โดยไม่มีอะไรบอกว่าปัญหาคือ backend ไม่ตอบ**
#
# แยกสองค่าตามลักษณะงาน: คำขอทั่วไปควรเร็ว (ผิดปกติถ้าเกิน 15 วิ) แต่การรวม PDF
# ผ่าน Gotenberg เป็นงานหนักที่ *รู้ตัวว่าช้า* — ใช้เพดานเดียวกันจะทำให้ใบเสร็จ 40 ใบ
# ถูกตัดกลางทางทั้งที่ยังทำงานปกติอยู่
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)
PDF_TIMEOUT = aiohttp.ClientTimeout(total=180, connect=5)


def _describe_transport_error(exc: BaseException) -> str:
    """ข้อความไทยที่บอกผู้ใช้ว่า "ต่อ backend ไม่ได้" โดยไม่ต้อง Netflix log

    ⚠️ ต้องไม่พา `str(exc)` ดิบ ๆ ขึ้นจอ Discord — มันเป็นข้อความอังกฤษเชิงเทคนิค
    (เช่น `Cannot connect to host backend:8000 ssl:default`) ที่ผู้ใช้การ์ดอ่านไม่รู้เรื่อง
    แต่เก็บชนิดของ error ไว้ให้คนดูแลระบบไล่ต่อได้
    """
    if isinstance(exc, asyncio.TimeoutError):
        return "⏱️ Backend ใช้เวลานานเกินกำหนด — ระบบอาจกำลังทำงานหนัก ลองใหม่อีกครั้งนะ"
    return "🔌 เชื่อมต่อ Backend ไม่ได้ — ระบบหลังบ้านอาจกำลังรีสตาร์ท ลองใหม่อีกครั้งนะ"


def _parse_json(raw: bytes, status: int) -> Any:
    """แกะ JSON จาก body โดยแปลง "ไม่ใช่ JSON" ให้เป็น APIException

    🔴 เดิมเรียก `await response.json()` ตรง ๆ ⇒ ถ้า backend ไม่ได้ตอบ (เช่น Traefik
       ตอบหน้า HTML 502 มาแทน) จะได้ `aiohttp.ContentTypeError` หลุดออกไป **ไม่ใช่
       `APIException`** ⇒ ผู้เรียกที่ `except APIException` อยู่แล้วไม่ดัก ⇒ error ไปโผล่
       เป็น stack trace หรือบอทเงียบไปเฉย ๆ

    ⚠️ แกะจาก bytes ตรง ๆ ไม่ผ่าน `response.json()` — เพราะบังคับ content-type
       (proxy บางตัวตั้ง header ไม่ตรง ทั้งที่ body ถูก) และเพราะผู้เรียกอ่าน body
       ไปแล้วเพื่อดึง `detail` ของ error
    """
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        raise APIException(
            f"Backend ตอบกลับรูปแบบที่ไม่รู้จัก (HTTP {status}) — "
            "อาจเป็นหน้า error ของ reverse proxy ไม่ใช่ API"
        ) from e


def _clean_filename(value: str) -> str:
    """ทำชื่อไฟล์จาก header ให้ปลอดภัยพอจะเอาไปตั้งชื่อไฟล์แนบของ Discord

    ⚠️ ค่าที่มาจาก header คือ **ข้อมูลจากภายนอก** ⇒ ห้ามเอาไปใช้ดิบ ๆ:
       - ตัด CR/LF ทิ้ง (กัน header/ชื่อไฟล์ที่มีอักขระควบคุมหลุดเข้ามา)
       - ตัด path separator (ชื่อไฟล์ไม่ควรบอกโครงสร้างโฟลเดอร์ของอีกฝั่ง)
       - ตัดอักขระที่ Discord/OS ไม่ชอบ (`"` `\\` `:` `*` `?` `<` `>` `|`)
    คืน `""` เมื่อไม่เหลืออะไรให้ใช้ — ผู้เรียกต้อง fallback เอง
    """
    cleaned = str(value or "").replace("\r", "").replace("\n", "").strip().strip('"').strip()
    for bad in ('/', "\\", ":", "*", "?", "<", ">", "|"):
        cleaned = cleaned.replace(bad, "-")
    return cleaned.strip(" .")


def filename_from_content_disposition(value, fallback: str = "documents.pdf") -> str:
    """ดึงชื่อไฟล์จาก `Content-Disposition` — รองรับทั้ง `filename=` และ RFC 5987 `filename*=`

    🎯 ทำไมต้องรองรับสองแบบ: backend ส่งมาทั้งคู่
       `attachment; filename="receipts-....pdf"; filename*=UTF-8''receipts-....pdf`
       ⇒ `filename*` คือตัวที่ถูกต้องตามมาตรฐานเมื่อชื่อมีอักขระนอก ASCII และเป็นตัวที่
       **ควรชนะ** เสมอ · `filename=` เก็บไว้เป็น fallback เผื่ออนาคตมีคนถอดตัวหลังออก

    ⚠️ **ห้ามใช้ `email.message` / `cgi.parse_header`** เพื่อความสะดวก: ตัวหลังถูกถอดออก
       จาก stdlib แล้ว (PEP 594) และตัวแรกให้ object ที่ต้องอ่านซ้ำหลายรอบกว่าจะได้ค่า
       ⇒ parse เองแบบตรงไปตรงมาอ่านออกกว่า และเทสต์ได้โดยไม่ต้องมี aiohttp

    ⚠️ `filename*` รูปแบบคือ `charset'language'percent-encoded` — ภาษา (`''`) ว่างได้
       และต้อง `unquote` **ด้วย charset ที่ประกาศมา** ไม่ใช่ utf-8 ตายตัว
    """
    if not value:
        return fallback

    encoded_name = None
    plain_name = None
    for part in str(value).split(";"):
        part = part.strip()
        lowered = part.lower()
        if lowered.startswith("filename*="):
            encoded_name = part[len("filename*="):].strip()
        elif lowered.startswith("filename="):
            plain_name = part[len("filename="):].strip()

    if encoded_name:
        try:
            if "''" in encoded_name:
                charset, _, encoded = encoded_name.partition("''")
                decoded = unquote(encoded, encoding=(charset.strip() or "utf-8"), errors="strict")
            else:
                decoded = unquote(encoded_name, errors="strict")
        except (LookupError, UnicodeDecodeError, ValueError):
            # charset ที่ประกาศมาไม่รู้จัก หรือ percent-encoding พัง → ตกไปใช้ filename= ต่อ
            decoded = ""
        cleaned = _clean_filename(decoded)
        if cleaned:
            return cleaned

    if plain_name:
        cleaned = _clean_filename(plain_name)
        if cleaned:
            return cleaned

    return fallback


def _error_detail(raw: bytes) -> str:
    """แกะข้อความ error จาก body ของ response ที่ไม่ใช่ 2xx

    Backend ตอบ error เป็น JSON (`{"detail": "..."}`) เสมอ — รวมถึง route ที่สำเร็จเป็น
    binary ด้วย ⇒ แกะได้เหมือนกัน แต่ **ห้ามให้การแกะพังกลบ error ต้นทาง** (body ที่ไม่ใช่
    JSON ต้องได้ข้อความกลาง ๆ ไม่ใช่ exception ใหม่ที่อ่านไม่ออกว่าอะไรพัง)
    """
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return "เกิดข้อผิดพลาดจาก Backend"
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if detail is not None:
            return str(detail)
    return "เกิดข้อผิดพลาดจาก Backend"


class APIClient:
    def __init__(self):
        self.session = None

    async def init_session(self):
        """เปิด Session ค้างไว้เพื่อความเร็ว (ไม่ต้องเปิด-ปิดใหม่ทุก Request)"""
        headers = {"X-API-Key": API_KEY}
        self.session = aiohttp.ClientSession(headers=headers, timeout=DEFAULT_TIMEOUT)

    async def close(self):
        if self.session:
            await self.session.close()

    async def request(self, method: str, endpoint: str, **kwargs):
        """ฟังก์ชันครอบจักรวาลสำหรับยิง API

        คืนค่าที่แกะจาก JSON ของ response (ปกติเป็น `dict`) และ **โยน `APIException`
        เสมอเมื่อผิดพลาด** — ทั้งกรณี backend ตอบ error และกรณีต่อ backend ไม่ได้
        ⇒ ผู้เรียก `except APIException` ที่เดียวคุ้มทุกทาง (เดิม `ClientError`
        หลุดออกไปดื้อ ๆ แล้วไปพังที่อื่น)
        """
        url = f"{API_BASE_URL}{endpoint}"
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        try:
            async with self.session.request(method, url, **kwargs) as response:
                # อ่าน body ก่อนเช็ค status เพื่อให้ได้ `detail` ของ error มาด้วย
                # (เดิมเรียก `response.json()` แล้วค่อยเช็ค ⇒ body ที่ไม่ใช่ JSON
                #  ทำให้ error ต้นทางหายไป และได้ exception ที่อ่านไม่ออกแทน)
                raw = await response.read()

                # ถ้า Backend ตอบกลับมาเป็น Error (เช่น 404, 401)
                if response.status >= 400:
                    raise APIException(_error_detail(raw))

                return _parse_json(raw, response.status)
        except APIException:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise APIException(_describe_transport_error(e)) from e

    async def request_bytes(self, method: str, endpoint: str, fallback_filename: str = "documents.pdf", **kwargs):
        """เหมือน `request` แต่สำหรับ endpoint ที่ตอบ **ไบนารี** (PDF) → คืน `(bytes, filename)`

        🔴 **แยกเมธอดใหม่โดยเจตนา — ห้ามไปแก้ `request` ให้เดาชนิดของ body**:
           `request` เรียก `response.json()` ตรง ๆ และมีผู้เรียกอยู่ 4 ตัว
           (`finance_api` ทั้งไฟล์) ที่พึ่งสัญญานั้น ⇒ ถ้าเปลี่ยนเป็น "ถ้า content-type
           ไม่ใช่ json ก็อ่านเป็น bytes" ผู้เรียกเดิมจะได้ `dict` หรือ `bytes` สลับกัน
           ตามชนิด response โดยที่ type hint ไม่ช่วยอะไร (นี่คือเหตุผลที่ไฟล์
           `finance_api.py` เขียนไว้ว่า F3 ยังส่ง PDF เข้า Discord ไม่ได้)

        ⚠️ อ่านทั้ง body เข้า memory (`await response.read()`) — ใช้ได้เพราะผู้เรียก
           ตรวจเพดานขนาดอยู่แล้ว (`DISCORD_ATTACH_MAX_BYTES` ใน `pdf_attach.py`)
           ⚠️ **ไม่ใส่เพดานในนี้** เพราะชั้นนี้ไม่รู้ว่าปลายทางยอมรับได้เท่าไร และการตัด
              body เงียบ ๆ จะได้ไฟล์ที่เปิดไม่ได้โดยไม่มีใครรู้สาเหตุ
        """
        url = f"{API_BASE_URL}{endpoint}"
        # เพดานเวลายาวกว่า `request` เพราะผู้เรียกใช้เมธอดนี้กับงานรวม PDF (Gotenberg)
        # ที่ใช้เวลาหลายสิบวินาทีได้จริง — แต่ยัง *มี* เพดาน ไม่ค้างตลอดไป
        kwargs.setdefault("timeout", PDF_TIMEOUT)
        try:
            async with self.session.request(method, url, **kwargs) as response:
                raw = await response.read()

                if response.status >= 400:
                    # ⚠️ อ่าน body เป็น bytes มาก่อนแล้ว จึงต้องแกะ error เอง (เทียบเท่า
                    #    `data.get("detail", ...)` ของ `request`) — อย่าใช้ `response.json()`
                    #    ตรงนี้ เพราะ body ถูก consume ไปแล้ว
                    raise APIException(_error_detail(raw))

                return raw, filename_from_content_disposition(
                    response.headers.get("Content-Disposition"), fallback_filename
                )
        except APIException:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise APIException(_describe_transport_error(e)) from e

# สร้าง Instance แบบ Singleton ไว้ให้ไฟล์อื่นดึงไปใช้
api_client = APIClient()
