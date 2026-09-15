import json
from urllib.parse import unquote

import aiohttp
from core.config import API_BASE_URL, API_KEY

class APIException(Exception):
    """Custom Exception สำหรับดัก Error จาก Backend"""
    pass


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
        self.session = aiohttp.ClientSession(headers=headers)

    async def close(self):
        if self.session:
            await self.session.close()

    async def request(self, method: str, endpoint: str, **kwargs):
        """ฟังก์ชันครอบจักรวาลสำหรับยิง API"""
        url = f"{API_BASE_URL}{endpoint}"
        async with self.session.request(method, url, **kwargs) as response:
            data = await response.json()
            
            # ถ้า Backend ตอบกลับมาเป็น Error (เช่น 404, 401)
            if response.status >= 400:
                error_detail = data.get("detail", "เกิดข้อผิดพลาดจาก Backend")
                raise APIException(error_detail)
                
            return data

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

# สร้าง Instance แบบ Singleton ไว้ให้ไฟล์อื่นดึงไปใช้
api_client = APIClient()
