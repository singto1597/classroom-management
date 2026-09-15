"""🧪 เทสต์ของการแนบ PDF ใบเสร็จเข้า Discord (F5/PR-3) — stdlib `unittest`

รัน (ไม่ต้องติดตั้งอะไรเพิ่ม — ใช้ image ของบอทที่มี discord.py อยู่แล้ว):

```
docker run --rm -v "$PWD/bot_discord:/app:z" -w /app classroom-classroom-bot:latest \
    python -m unittest discover -s tests -t . -v
```

## ขอบเขตที่เทสต์ชุดนี้พิสูจน์

| กลุ่ม | พิสูจน์ว่า |
|---|---|
| `FilenameHeaderTest` | parse `Content-Disposition` ได้ทั้ง `filename=` และ RFC 5987 `filename*` และ **ไม่รับชื่อไฟล์ที่เป็นอันตราย** |
| `BuildReceiptFilesTest` | ทั้ง 6 สาขาของการตัดสินใจแนบ/ไม่แนบ — รวม timeout, error, ไฟล์ใหญ่เกิน |
| `NotifyFinancePaymentTest` | **ไฟล์แนบพังแล้วข้อความต้องออก** (ชั้นที่ 3) และเส้นทางเดิม (บิลเดียว) ไม่เปลี่ยน |
| `ProcessEventConcurrencyTest` | `FINANCE_PAYMENT` ที่มีใบเสร็จ **ไม่บล็อกลูปฟัง Redis** ส่วนที่ไม่มีใบเสร็จยัง await เหมือนเดิม |

⚠️ กลุ่ม `ProcessEventConcurrencyTest` สร้าง Cog ด้วย `__new__` เพื่อข้าม `__init__`
   ที่ไปสร้าง task ผูกกับ event loop ของบอทจริง — เป็นเทคนิคที่ตั้งใจ ไม่ใช่การหลบเลี่ยง
   (ไม่งั้นเทสต์จะต้องมีบอท Discord และ Redis จริง ซึ่งไม่มีใน CI ของ repo นี้)
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs.redis_listener import RedisListener
from services.action_service import BotActionService
from services.api_client import _error_detail, filename_from_content_disposition
from services.pdf_attach import (
    ATTACH_FAILED_NOTE,
    DISCORD_ATTACH_MAX_BYTES,
    build_receipt_files,
)
from services.finance_api import PDF_CHUNK_SIZE


class _FakeHTTPException(discord.HTTPException):
    """`discord.HTTPException` ที่สร้างได้โดยไม่ต้องมี aiohttp response จริง

    ⚠️ ข้าม `__init__` ของแม่โดยเจตนา — constructor ของ discord.py อ่าน `response.status`
       และ `response.reason` ⇒ ถ้าอนาคตตัวไลบรารีเปลี่ยนรูป signature เทสต์จะพังทั้งที่
       พฤติกรรมที่เราสนใจ (`except discord.HTTPException`) ไม่ได้เปลี่ยน
    """

    def __init__(self, message: str = "payload too large"):
        Exception.__init__(self, message)
        self.status = 413
        self.code = 40005
        self.text = message


class _FakeChannel:
    """ช่อง Discord ปลอม — เก็บ kwarg ของทุกครั้งที่ `send` ถูกเรียก

    `fail_when_files=True` ⇒ เรียกครั้งแรกที่มี `files` จะ raise (จำลอง Discord ปฏิเสธไฟล์)
    """

    def __init__(self, fail_when_files: bool = False):
        self.calls = []
        self._fail_when_files = fail_when_files
        self._failed_once = False

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("files") and self._fail_when_files and not self._failed_once:
            self._failed_once = True
            raise _FakeHTTPException()


class FilenameHeaderTest(unittest.TestCase):
    def test_prefers_rfc5987_filename_star(self):
        header = (
            'attachment; filename="receipts-REC-2569-0042.pdf"; '
            "filename*=UTF-8''receipts-REC-2569-0043.pdf"
        )
        self.assertEqual(
            filename_from_content_disposition(header), "receipts-REC-2569-0043.pdf"
        )

    def test_decodes_percent_encoded_thai_name(self):
        # ใบเสร็จ = %E0%B9%83%E0%B8%9A%E0%B9%80%E0%B8%AA%E0%B8%A3%E0%B9%87%E0%B8%88
        header = "attachment; filename*=UTF-8''%E0%B9%83%E0%B8%9A%E0%B9%80%E0%B8%AA%E0%B8%A3%E0%B9%87%E0%B8%88.pdf"
        self.assertEqual(filename_from_content_disposition(header), "ใบเสร็จ.pdf")

    def test_falls_back_to_plain_filename(self):
        header = 'attachment; filename="receipts-1-to-2.pdf"'
        self.assertEqual(
            filename_from_content_disposition(header), "receipts-1-to-2.pdf"
        )

    def test_falls_back_when_header_missing_or_broken(self):
        self.assertEqual(
            filename_from_content_disposition(None), "documents.pdf"
        )
        self.assertEqual(
            filename_from_content_disposition("attachment"), "documents.pdf"
        )

    def test_falls_back_when_percent_encoding_is_not_valid_utf8(self):
        """`%FF%FE` ถอดรหัสเป็น UTF-8 ไม่ได้ ⇒ ต้องไม่คืนชื่อขยะ ต้องตกไปใช้ fallback"""
        self.assertEqual(
            filename_from_content_disposition(
                "attachment; filename*=UTF-8''%FF%FE", "fallback.pdf"
            ),
            "fallback.pdf",
        )

    def test_falls_back_when_charset_is_unknown_with_escapes(self):
        """charset ที่ไม่รู้จัก **และมี** percent-escape ⇒ `unquote` raise `LookupError` ⇒ fallback"""
        self.assertEqual(
            filename_from_content_disposition(
                "attachment; filename*=X-NOT-A-CHARSET''%E0%B9%83.pdf", "fallback.pdf"
            ),
            "fallback.pdf",
        )

    def test_unknown_charset_without_escapes_is_passed_through(self):
        """⚠️ เคสที่ **ไม่** error: ไม่มี `%` เลย ⇒ `unquote` ไม่ต้องแตะ codec

        🔑 บทเรียน: `unquote` เรียก `codecs.lookup` **ขี้เกียจ** (เฉพาะเมื่อเจอ `%`)
           ⇒ "charset ผิด" ไม่ได้แปลว่าจะ raise เสมอ · สตริง ASCII ล้วนผ่านได้ทั้งที่
           ประกาศ charset มั่ว ⇒ เทสต์ที่คาดหวัง fallback ต้อง**ใส่ `%` เสมอ**
        """
        self.assertEqual(
            filename_from_content_disposition(
                "attachment; filename*=X-NOT-A-CHARSET''abc.pdf", "fallback.pdf"
            ),
            "abc.pdf",
        )

    def test_partial_thai_name_is_returned_as_is(self):
        """⚠️ เคสที่ **ไม่** error: `%E0%B9%83` เป็น UTF-8 ที่ถูกต้อง (='ใ') เป๊ะ

        🔑 บทเรียน: `unquote(errors="strict")` **ไม่ช่วย** กับ percent-encoding ที่ถูกตัด
           กลางทาง ถ้าไบต์ที่เหลือบังเอิญประกอบเป็นอักขระที่ถูกต้อง ⇒ ตัวแยกแยะ
           "ชื่อไฟล์ที่ถูกตัด" กับ "ชื่อไฟล์สั้นจริง" **ไม่มีอยู่ในชั้นนี้** และไม่ควรมี:
           ทางออกเดียวที่ตรงคือยอมรับตาม header (ซึ่งเป็นข้อมูลที่ backend ของเราเซ็นเอง)
        """
        self.assertEqual(
            filename_from_content_disposition(
                "attachment; filename*=UTF-8''%E0%B9%83"
            ),
            "ใ",
        )

    def test_rejects_header_smuggling(self):
        """ชื่อไฟล์คือข้อมูลจากภายนอก — ต้องไม่มี CR/LF/ตัวคั่น path หลุดไปถึง Discord"""
        header = 'attachment; filename="../../etc/passwd\r\nX-Evil: 1"'
        cleaned = filename_from_content_disposition(header)
        self.assertNotIn("\n", cleaned)
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("/", cleaned)


class ErrorDetailTest(unittest.TestCase):
    def test_extracts_thai_detail(self):
        raw = '{"detail": "ต้องเลือกเอกสารอย่างน้อย 1 ฉบับ"}'.encode()
        self.assertEqual(_error_detail(raw), "ต้องเลือกเอกสารอย่างน้อย 1 ฉบับ")

    def test_non_json_body_does_not_explode(self):
        self.assertEqual(_error_detail(b"<html>502</html>"), "เกิดข้อผิดพลาดจาก Backend")


class BuildReceiptFilesTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_receipt_nos_never_touches_network(self):
        fetch = AsyncMock()
        files, note = await build_receipt_files(1, 2, None, fetch=fetch)
        self.assertEqual(files, [])
        self.assertIsNone(note)
        fetch.assert_not_called()

    async def test_empty_list_never_touches_network(self):
        fetch = AsyncMock()
        files, note = await build_receipt_files(1, 2, [], fetch=fetch)
        self.assertEqual((files, note), ([], None))
        fetch.assert_not_called()

    async def test_over_chunk_limit_refuses_without_fetching(self):
        fetch = AsyncMock()
        nos = [f"REC-2569-{i:04d}" for i in range(PDF_CHUNK_SIZE + 1)]
        files, note = await build_receipt_files(1, 2, nos, fetch=fetch)
        self.assertEqual(files, [])
        self.assertIn(str(PDF_CHUNK_SIZE + 1), note)
        fetch.assert_not_called()

    async def test_exactly_chunk_limit_is_allowed(self):
        fetch = AsyncMock(return_value=(b"x" * 10, "a.pdf"))
        nos = [f"REC-2569-{i:04d}" for i in range(PDF_CHUNK_SIZE)]
        files, note = await build_receipt_files(1, 2, nos, fetch=fetch)
        self.assertIsNone(note)
        self.assertEqual(len(files), 1)
        fetch.assert_awaited_once()

    async def test_fetch_error_returns_note_not_exception(self):
        fetch = AsyncMock(side_effect=RuntimeError("boom"))
        files, note = await build_receipt_files(1, 2, ["REC-1"], fetch=fetch)
        self.assertEqual(files, [])
        self.assertEqual(note, ATTACH_FAILED_NOTE)

    async def test_fetch_timeout_returns_note_not_exception(self):
        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(5)

        files, note = await build_receipt_files(
            1, 2, ["REC-1"], fetch=never_returns, timeout=0.05
        )
        self.assertEqual(files, [])
        self.assertEqual(note, ATTACH_FAILED_NOTE)

    async def test_empty_body_is_treated_as_failure(self):
        fetch = AsyncMock(return_value=(b"", "a.pdf"))
        files, note = await build_receipt_files(1, 2, ["REC-1"], fetch=fetch)
        self.assertEqual(files, [])
        self.assertEqual(note, ATTACH_FAILED_NOTE)

    async def test_oversized_pdf_is_refused_with_real_size(self):
        size = DISCORD_ATTACH_MAX_BYTES + 1
        fetch = AsyncMock(return_value=(b"x" * size, "a.pdf"))
        files, note = await build_receipt_files(1, 2, ["REC-1"], fetch=fetch)
        self.assertEqual(files, [])
        self.assertIn("MB", note)

    async def test_success_returns_file_with_filename_from_header(self):
        fetch = AsyncMock(return_value=(b"%PDF-1.4 fake", "receipts-REC-1.pdf"))
        files, note = await build_receipt_files(1, 2, ["REC-1", "REC-2"], fetch=fetch)
        self.assertIsNone(note)
        self.assertEqual([f.filename for f in files], ["receipts-REC-1.pdf"])
        # positional args ที่ส่งต่อให้ fetch ต้องเป็น (server_id, discord_id, nos)
        self.assertEqual(fetch.await_args.args, (1, 2, ["REC-1", "REC-2"]))


class _StubActionService(BotActionService):
    """ActionService ที่ไม่แตะ network — คืนช่องปลอมทันที"""

    def __init__(self, channel):
        self.bot = SimpleNamespace(user=SimpleNamespace(id=999))
        self.channel = channel

    async def _get_announcement_channel(self, server_id, channel="announcement"):
        return self.channel


class NotifyFinancePaymentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.batch_payload = {
            "event": "FINANCE_PAYMENT",
            "server_id": 1,
            "category": "✅ จ่ายเงินแล้ว",
            "payer_name": "เด็กชายทดสอบ",
            "items": [{"title": "ค่าเทอม", "amount": 100.0}],
            "count": 1,
            "total_amount": 100.0,
            "user_name": "ครูสมชาย",
            "receipt_nos": ["REC-2569-0001"],
        }

    def _embed_titles(self, call):
        # ⚠️ discord.py คืน `EmbedProxy` (ไม่ใช่ dict) ⇒ ต้องเข้าถึงด้วย attribute
        return [f.name for f in call["embed"].fields]

    async def test_attaches_file_and_adds_no_note(self):
        channel = _FakeChannel()
        service = _StubActionService(channel)
        fake_file = object()
        with patch(
            "services.action_service.build_receipt_files",
            new=AsyncMock(return_value=([fake_file], None)),
        ):
            await service.notify_finance_payment(1, self.batch_payload)

        self.assertEqual(len(channel.calls), 1)
        self.assertEqual(channel.calls[0]["files"], [fake_file])
        self.assertNotIn("🧾 ใบเสร็จ", self._embed_titles(channel.calls[0]))

    async def test_note_is_added_when_attachment_fails(self):
        channel = _FakeChannel()
        service = _StubActionService(channel)
        with patch(
            "services.action_service.build_receipt_files",
            new=AsyncMock(return_value=([], "🧾 แนบไม่ได้เพราะเหตุผลบางอย่าง")),
        ):
            await service.notify_finance_payment(1, self.batch_payload)

        self.assertEqual(len(channel.calls), 1)
        self.assertNotIn("files", channel.calls[0])
        self.assertIn("🧾 ใบเสร็จ", self._embed_titles(channel.calls[0]))

    async def test_message_survives_discord_rejecting_the_file(self):
        """🔑 ชั้นที่ 3 ของ 4 — ไฟล์แนบพังแล้วข้อความ 'รับเงินแล้ว' ต้องยังออก"""
        channel = _FakeChannel(fail_when_files=True)
        service = _StubActionService(channel)
        with patch(
            "services.action_service.build_receipt_files",
            new=AsyncMock(return_value=([object()], None)),
        ):
            await service.notify_finance_payment(1, self.batch_payload)

        self.assertEqual(len(channel.calls), 2)
        self.assertIn("files", channel.calls[0])
        self.assertNotIn("files", channel.calls[1])
        # ข้อความที่สองต้องบอกความจริงว่าทำไมไม่มีไฟล์ (ไม่เงียบ)
        self.assertIn("🧾 ใบเสร็จ", self._embed_titles(channel.calls[1]))

    async def test_legacy_single_bill_path_is_untouched(self):
        """🛡️ บิลเดียว (`confirm_payment`) ไม่มี `items`/`receipt_nos` ⇒ ห้ามแตะเส้นทางเดิม"""
        channel = _FakeChannel()
        service = _StubActionService(channel)
        builder = AsyncMock()
        with patch("services.action_service.build_receipt_files", new=builder):
            await service.notify_finance_payment(
                1, {"payer_name": "ก", "title": "ค่าอาหาร", "amount": 50.0, "user_name": "ข"}
            )
        builder.assert_not_called()
        self.assertEqual(len(channel.calls), 1)
        self.assertNotIn("files", channel.calls[0])
        self.assertEqual(channel.calls[0]["embed"].title, "✅ มีการชำระเงิน")


class _Recorder:
    """ActionService ปลอมสำหรับทดสอบ routing ของ listener"""

    def __init__(self):
        self.calls = []

    async def notify_finance_payment(self, server_id, data):
        self.calls.append((server_id, data))


class ProcessEventConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    def _cog(self):
        # ⚠️ ข้าม __init__ (ตัวนั้นจะไปสร้าง task ผูกกับ loop ของบอทจริง) — ดู docstring บนสุด
        cog = RedisListener.__new__(RedisListener)
        cog.action_service = _Recorder()
        cog._pdf_tasks = set()
        cog._pdf_semaphore = asyncio.Semaphore(2)
        return cog

    async def test_payment_with_receipts_is_not_awaited_inline(self):
        """🔑 ลูปฟัง Redis ต้องไม่ถูกบล็อกรอ Gotenberg (ได้ถึง 60s)"""
        cog = self._cog()
        await cog.process_event(
            {"event": "FINANCE_PAYMENT", "server_id": 7, "receipt_nos": ["REC-1"]}
        )
        self.assertEqual(cog.action_service.calls, [])  # ยังไม่ถูกเรียก ⇒ ไม่บล็อก

        await asyncio.sleep(0.05)  # ให้ task เบื้องหลังได้รัน
        self.assertEqual(len(cog.action_service.calls), 1)
        self.assertEqual(cog.action_service.calls[0][0], 7)

    async def test_payment_without_receipts_stays_sequential(self):
        """เส้นทางเดิม (บิลเดียว / ติ๊กออกใบเสร็จออก) ต้องถูก await ทันทีเหมือนก่อนหน้านี้"""
        cog = self._cog()
        await cog.process_event(
            {"event": "FINANCE_PAYMENT", "server_id": 8, "amount": 10.0}
        )
        self.assertEqual(len(cog.action_service.calls), 1)
        self.assertEqual(cog._pdf_tasks, set())

    async def test_background_failure_does_not_escape(self):
        """task เบื้องหลังที่ raise ต้องถูกกลืนและ log — ห้ามทำให้ลูปพัง"""
        cog = self._cog()

        class _Boom(_Recorder):
            async def notify_finance_payment(self, server_id, data):
                raise RuntimeError("boom")

        cog.action_service = _Boom()
        with self.assertLogs("DISCORD_BOT", level="ERROR"):
            await cog.process_event(
                {"event": "FINANCE_PAYMENT", "server_id": 9, "receipt_nos": ["REC-1"]}
            )
            await asyncio.sleep(0.05)
        # งานถูกเก็บกวาดออกจาก set หลังจบ (ไม่รั่ว reference)
        self.assertEqual(cog._pdf_tasks, set())


if __name__ == "__main__":
    unittest.main()
