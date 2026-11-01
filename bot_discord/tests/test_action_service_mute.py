"""🧪 เทสต์ mute รายช่องใน `BotActionService._get_announcement_channel` (P7)

สิ่งที่ล็อกไว้:
1. ช่องที่ถูก mute → คืน `None` (บอทไม่ส่งอะไรในช่องนั้น)
2. **mute ไม่ fallback ไปช่องอื่น** — mute ช่องวันเกิด = งดคำอวยพรวันเกิด
   ไม่ใช่ย้ายไปโพสต์ในช่องประกาศ (fallback มีไว้เฉพาะ "ยังไม่ได้ตั้งช่อง")
3. ช่องที่ไม่ได้ mute ยังทำงานเหมือนเดิม (กัน over-block)
4. `muted_channel_ids` ว่าง/ไม่มีคีย์ = ไม่ mute อะไร (เข้ากันได้กับข้อมูลเก่า)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from services.action_service import BotActionService
from services.api_client import APIException, api_client


def _service():
    bot = SimpleNamespace(
        user=SimpleNamespace(id=1),
        get_channel=lambda cid: SimpleNamespace(id=cid, name=f"ch-{cid}"),
    )
    return BotActionService(bot)


def _room(**overrides):
    data = {
        "announcement_channel_id": 111,
        "birthday_channel_id": 222,
        "minor_notify_channel_id": 333,
        "muted_channel_ids": [],
    }
    data.update(overrides)
    return data


def _patch(room_data=None, side_effect=None):
    if side_effect is not None:
        return mock.patch.object(api_client, "request", new=mock.AsyncMock(side_effect=side_effect))
    return mock.patch.object(api_client, "request", new=mock.AsyncMock(return_value=room_data))


class ChannelMuteTest(unittest.IsolatedAsyncioTestCase):
    async def test_ช่องปกติยังใช้ได้(self):
        with _patch(_room()):
            channel = await _service()._get_announcement_channel(123, "announcement")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.id, 111)

    async def test_ช่องหลักถูกmute_คืนNone(self):
        with _patch(_room(muted_channel_ids=[111])):
            channel = await _service()._get_announcement_channel(123, "announcement")
        self.assertIsNone(channel)

    async def test_ช่องวันเกิดถูกmute_ไม่fallbackไปช่องประกาศ(self):
        """🔑 หัวใจของ mute — ต้องปิดจริง ไม่ใช่ย้ายที่โพสต์"""
        with _patch(_room(muted_channel_ids=[222])):
            channel = await _service()._get_announcement_channel(123, "birthday")
        self.assertIsNone(channel)

    async def test_ช่องวันเกิดไม่ถูกmute_ยังใช้ช่องวันเกิด(self):
        with _patch(_room(muted_channel_ids=[111])):
            channel = await _service()._get_announcement_channel(123, "birthday")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.id, 222)

    async def test_ยังไม่ได้ตั้งช่องวันเกิด_ตกไปช่องประกาศ(self):
        with _patch(_room(birthday_channel_id=None)):
            channel = await _service()._get_announcement_channel(123, "birthday")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.id, 111)

    async def test_ช่องวันเกิดว่างและช่องประกาศถูกmute_คืนNone(self):
        with _patch(_room(birthday_channel_id=None, muted_channel_ids=[111])):
            channel = await _service()._get_announcement_channel(123, "birthday")
        self.assertIsNone(channel)

    async def test_ไม่มีคีย์muted_channel_ids_ยังทำงานได้(self):
        """ข้อมูลจาก backend เวอร์ชันเก่า (ก่อน migration) ต้องไม่ทำให้ TypeError"""
        room = _room()
        del room["muted_channel_ids"]
        with _patch(room):
            channel = await _service()._get_announcement_channel(123, "announcement")
        self.assertIsNotNone(channel)

    async def test_APIล่ม_คืนNone_ตามพฤติกรรมเดิม(self):
        with _patch(side_effect=APIException("backend down")):
            channel = await _service()._get_announcement_channel(123, "announcement")
        self.assertIsNone(channel)
