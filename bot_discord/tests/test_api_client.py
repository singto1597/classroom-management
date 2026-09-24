"""
🧪 เทสต์ของ `api_client` — **ทุกทางที่ผิดพลาดต้องออกเป็น `APIException`** (H8)

รัน (ไม่ต้องติดตั้งอะไรเพิ่ม):
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```

## บั๊กที่เทสต์ชุดนี้ล็อกไว้ (พบจากการตรวจระบบ 2026-09-23)

`api_client.request()` เดิมเรียก `await response.json()` ตรง ๆ และไม่ตั้ง timeout:

1. **`aiohttp.ContentTypeError` หลุดออกไปแทน `APIException`** — ถ้า backend ไม่ได้ตอบ
   (Traefik ตอบหน้า HTML 502 มาแทน) `response.json()` จะ raise `ContentTypeError`
   ซึ่ง **ไม่ใช่** `APIException` ⇒ ทุก `except APIException` ในโค้ดบอทไม่ดัก
   ⇒ error ไปโผล่เป็น stack trace หรือบอทเงียบไปเฉย ๆ
2. **ไม่มี timeout** ⇒ aiohttp ใช้ default 5 นาที ⇒ คำสั่ง Discord ค้างเงียบ ๆ
   ทั้งที่ interaction หมดอายุตั้งแต่ 3 วินาที ⇒ ผู้ใช้เห็น "The application did not
   respond" โดยไม่มีอะไรบอกว่าต้นเหตุคือ backend ไม่ตอบ

## ขอบเขต — สิ่งที่ **ไม่** เทสต์ซ้ำที่นี่

`test_pdf_attach.py` มี `ErrorDetailTest` และ `FilenameHeaderTest` ครอบ `_error_detail`
และ `filename_from_content_disposition` ไว้แล้ว ⇒ ที่นี่เก็บเฉพาะสัญญาของ `request`/
`request_bytes` (การแปลง error + timeout) และการบังคับ `API_KEY` ของ config

⚠️ ใช้ stdlib `unittest` ตามธรรมเนียมของโฟลเดอร์นี้ (ไม่ใช่ pytest) — image ของบอท
   ไม่มี pytest และไม่ควรต้อง `pip install` ทุกครั้งที่รัน
"""
import asyncio
import ast
import importlib
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import aiohttp

from services.api_client import (
    DEFAULT_TIMEOUT,
    PDF_TIMEOUT,
    APIClient,
    APIException,
    _error_detail,
)


# === stub ของ aiohttp — ไม่ต่อเครือข่ายจริง ===


class _StubResponse:
    """เลียนแบบ `aiohttp.ClientResponse` เท่าที่ `APIClient` ใช้จริง

    ⚠️ **ต้องมี `json()` ที่เลียนแบบของจริง** (raise `ContentTypeError` เมื่อ content-type
       ไม่ใช่ JSON) ไม่ใช่แค่ `read()`
       ถ้าไม่มี เมธอดนี้ โค้ดเวอร์ชันเก่าจะพังด้วย `AttributeError` ซึ่งเป็นเหตุผลผิด
       ⇒ เทสต์จะ "จับบั๊กได้" ก็จริง แต่จับด้วยเหตุผลที่ไม่มีในโลกจริง
       ⇒ พิสูจน์ไม่ได้ว่าเทสต์แยกแยะบั๊กจริง (ContentTypeError หลุด) ได้หรือไม่
    """

    def __init__(
        self,
        status: int,
        body: bytes,
        headers: dict | None = None,
        content_type: str = "application/json",
    ):
        self.status = status
        self._body = body
        self.headers = headers or {}
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._body

    async def json(self, *args, **kwargs):
        if self.content_type != "application/json":
            raise aiohttp.ContentTypeError(
                request_info=mock.Mock(),
                history=(),
                message=(
                    "Attempt to decode JSON with unexpected mimetype: "
                    f"{self.content_type}"
                ),
            )
        return json.loads(self._body.decode("utf-8", "replace"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _StubSession:
    """คืน response ที่กำหนด หรือ **โยน exception** เพื่อจำลองพังระดับ transport"""

    def __init__(self, response=None, raises: BaseException | None = None):
        self._response = response
        self._raises = raises
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if self._raises is not None:
            raise self._raises
        return self._response


def _client_with(session) -> APIClient:
    client = APIClient()
    client.session = session
    return client


# === 1. backend ตอบ error ===


class BackendErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_parsed_json_on_success(self):
        session = _StubSession(_StubResponse(200, '{"task_name": "การบ้าน"}'.encode()))
        self.assertEqual(
            await _client_with(session).request("GET", "/tasks/1"),
            {"task_name": "การบ้าน"},
        )

    async def test_hits_the_expected_url(self):
        session = _StubSession(_StubResponse(200, b"{}"))
        await _client_with(session).request("POST", "/rooms/1/tasks")
        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertTrue(session.calls[0]["url"].endswith("/rooms/1/tasks"))

    async def test_error_status_carries_the_backend_detail(self):
        session = _StubSession(_StubResponse(404, '{"detail": "ไม่พบงานนี้"}'.encode()))
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/999")
        self.assertEqual(str(ctx.exception), "ไม่พบงานนี้")

    async def test_non_json_error_body_does_not_leak_content_type_error(self):
        """🔴 หัวใจของ H8 — proxy ตอบ HTML มาแทน JSON

        ก่อนแก้: ได้ `aiohttp.ContentTypeError` ซึ่ง **ไม่ใช่** `APIException`
        ⇒ `except APIException` ทุกจุดในโค้ดบอทไม่ดัก
        """
        session = _StubSession(
            _StubResponse(
                502, b"<html><body>502 Bad Gateway</body></html>", content_type="text/html"
            )
        )
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")

        self.assertNotIsInstance(ctx.exception, aiohttp.ContentTypeError)
        self.assertIn("เกิดข้อผิดพลาดจาก Backend", str(ctx.exception))

    async def test_non_json_body_on_success_status_also_translates(self):
        """200 แต่ body เป็น HTML (proxy แทรก / captive portal) ก็ต้องไม่หลุด"""
        session = _StubSession(
            _StubResponse(200, b"<html>hello</html>", content_type="text/html")
        )
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")
        self.assertIn("รูปแบบที่ไม่รู้จัก", str(ctx.exception))


# === 2. transport พัง (ต่อ backend ไม่ได้ / หมดเวลา) ===


class TransportErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_error_becomes_api_exception(self):
        session = _StubSession(raises=aiohttp.ClientConnectionError("refused"))
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")
        self.assertIn("เชื่อมต่อ Backend ไม่ได้", str(ctx.exception))

    async def test_server_timeout_becomes_api_exception(self):
        session = _StubSession(raises=aiohttp.ServerTimeoutError())
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")
        self.assertIn("ใช้เวลานานเกินกำหนด", str(ctx.exception))

    async def test_asyncio_timeout_becomes_api_exception(self):
        session = _StubSession(raises=asyncio.TimeoutError())
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")
        self.assertIn("ใช้เวลานานเกินกำหนด", str(ctx.exception))

    async def test_message_has_no_raw_english_jargon(self):
        """ผู้ใช้อ่านข้อความนี้บน Discord — ห้าม `str(exc)` ดิบ ๆ หลุดขึ้นจอ"""
        session = _StubSession(
            raises=aiohttp.ClientConnectionError("Cannot connect to host backend:8000")
        )
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/tasks/1")
        self.assertNotIn("Cannot connect to host", str(ctx.exception))

    async def test_api_exception_is_not_double_wrapped(self):
        """`raise APIException(...)` ข้างในต้องไม่ถูกแปลงเป็นข้อความ transport"""
        session = _StubSession(_StubResponse(400, '{"detail": "ข้อมูลไม่ถูกต้อง"}'.encode()))
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request("GET", "/x")
        self.assertEqual(str(ctx.exception), "ข้อมูลไม่ถูกต้อง")
        self.assertIsNone(ctx.exception.__cause__)


# === 3. timeout ถูกตั้งจริง ===


class RequestTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_request_sets_a_default_timeout(self):
        """ก่อนแก้ ไม่มี timeout ใน kwargs เลย ⇒ aiohttp ใช้ 5 นาทีของตัวเอง"""
        session = _StubSession(_StubResponse(200, b"{}"))
        await _client_with(session).request("GET", "/tasks/1")
        self.assertIs(session.calls[0]["kwargs"]["timeout"], DEFAULT_TIMEOUT)

    async def test_caller_can_override_the_timeout(self):
        session = _StubSession(_StubResponse(200, b"{}"))
        custom = aiohttp.ClientTimeout(total=99)
        await _client_with(session).request("GET", "/tasks/1", timeout=custom)
        self.assertIs(session.calls[0]["kwargs"]["timeout"], custom)

    async def test_pdf_download_gets_the_longer_timeout(self):
        """รวม PDF ผ่าน Gotenberg ใช้เวลาหลายสิบวินาที — 15 วิ จะตัดกลางทาง"""
        session = _StubSession(
            _StubResponse(
                200,
                b"%PDF-1.4 fake",
                {"Content-Disposition": 'attachment; filename="a.pdf"'},
            )
        )
        raw, name = await _client_with(session).request_bytes("POST", "/pdf")
        self.assertIs(session.calls[0]["kwargs"]["timeout"], PDF_TIMEOUT)
        self.assertEqual(raw, b"%PDF-1.4 fake")
        self.assertEqual(name, "a.pdf")

    async def test_pdf_transport_errors_are_translated_too(self):
        session = _StubSession(raises=aiohttp.ClientConnectionError("boom"))
        with self.assertRaises(APIException):
            await _client_with(session).request_bytes("POST", "/pdf")

    async def test_pdf_error_status_uses_backend_detail(self):
        session = _StubSession(
            _StubResponse(502, '{"detail": "สร้างไฟล์ PDF ไม่สำเร็จ"}'.encode())
        )
        with self.assertRaises(APIException) as ctx:
            await _client_with(session).request_bytes("POST", "/pdf")
        self.assertEqual(str(ctx.exception), "สร้างไฟล์ PDF ไม่สำเร็จ")


class TimeoutValuesTest(unittest.TestCase):
    def test_timeouts_are_sane(self):
        self.assertGreater(PDF_TIMEOUT.total, DEFAULT_TIMEOUT.total)
        # interaction ของ Discord หมดอายุที่ 3 วิ — คำขอทั่วไปไม่ควรค้างเกิน 30 วิ
        self.assertLessEqual(DEFAULT_TIMEOUT.total, 30)
        self.assertIsNotNone(DEFAULT_TIMEOUT.connect, "ต้องมีเพดานตอนเชื่อมต่อด้วย")


# === 4. error body ที่พัง — ต้องไม่กลบ error ต้นทาง ===


class ErrorDetailRobustnessTest(unittest.TestCase):
    def test_invalid_utf8_bytes_do_not_raise(self):
        """ไบต์ที่ถอดเป็น UTF-8 ไม่ได้ต้องถูกแทนด้วย U+FFFD ไม่ใช่ raise"""
        detail = _error_detail(b'{"detail": "ok \xff\xfe"}')
        self.assertIn("ok", detail)

    def test_non_string_detail_is_stringified(self):
        self.assertEqual(_error_detail(b'{"detail": 42}'), "42")

    def test_empty_body_falls_back(self):
        self.assertEqual(_error_detail(b""), "เกิดข้อผิดพลาดจาก Backend")


# === 5. config ต้องไม่ให้ค่า default ที่เดาได้ (M8) ===


class APIKeyConfigTest(unittest.TestCase):
    def test_config_refuses_to_start_without_api_key(self):
        """เดิม fallback เป็นคีย์ที่เขียนไว้ในซอร์สสาธารณะ ⇒ บอทสตาร์ทได้แล้วได้ 401 ทุกคำสั่ง"""
        from core import config

        original = os.environ.pop("API_KEY", None)
        try:
            # กันไม่ให้ load_dotenv() ไปเติม API_KEY จาก .env ของเครื่อง
            with mock.patch.object(config, "load_dotenv", lambda *a, **k: None):
                with self.assertRaises(ValueError) as ctx:
                    importlib.reload(config)
            self.assertIn("ไม่พบ API_KEY", str(ctx.exception))
        finally:
            if original is not None:
                os.environ["API_KEY"] = original
            importlib.reload(config)  # คืนโมดูลให้ใช้งานได้ตามปกติ

    def test_config_gives_api_key_no_default(self):
        """กันคนเผลอใส่ `os.getenv("API_KEY", "<ค่าเดาได้>")` กลับเข้าไป

        ⚠️ ตรวจด้วย AST ไม่ใช่ค้นสตริง — เพราะชื่อคีย์ปลอมยังปรากฏอยู่ใน **คอมเมนต์**
           ที่อธิบายว่าทำไมถึงลบมันออก (ค้นสตริงจะ fail ทั้งที่โค้ดถูก)
        """
        from core import config

        tree = ast.parse(Path(config.__file__).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "API_KEY"
        ]

        self.assertTrue(calls, "ต้องมีการอ่าน API_KEY จาก environment")
        for call in calls:
            self.assertEqual(
                len(call.args), 1, "os.getenv('API_KEY', <default>) — ห้ามมี default"
            )
            self.assertEqual(call.keywords, [], "ห้ามส่ง default ด้วย keyword")


if __name__ == "__main__":
    unittest.main()
