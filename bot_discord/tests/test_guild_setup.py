"""🧪 เทสต์การสร้างช่องอัตโนมัติเมื่อบอทเข้าร่วมเซิร์ฟเวอร์ (P7)

สิ่งที่ล็อกไว้:
1. สร้างช่องที่ยังไม่มีครบ 3 ชนิด (announcement / birthday / info)
2. **idempotent** — ชื่อซ้ำที่มีอยู่แล้วต้องใช้ของเดิม ไม่สร้างเพิ่ม
3. ช่องเดียวล้ม (ไม่มีสิทธิ์/HTTP error) ต้องไม่ทำให้ช่องที่เหลือหาย
4. ไม่มีสิทธิ์ Manage Channels ⇒ ไม่พยายามสร้างเลย และคืน `{}`
5. `save_channels_to_backend` ยิง system RPC ถูก path/รูปแบบ และ "ยังไม่ผูกห้อง" = False
   (ไม่ใช่ exception ที่ทำให้ on_guild_join ล้ม)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```
"""
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from services.api_client import APIException, api_client
from services.guild_setup import (
    CHANNEL_SPECS,
    ensure_room_channels,
    save_channels_to_backend,
)


def _permissions(manage_channels: bool = True):
    return SimpleNamespace(manage_channels=manage_channels)


def _channel(channel_id: int, name: str):
    return SimpleNamespace(id=channel_id, name=name, mention=f"<#{channel_id}>")


def _guild(*, existing=(), manage_channels=True, create_side_effect=None):
    guild = SimpleNamespace(
        id=123456789,
        name="Test Guild",
        text_channels=list(existing),
        me=SimpleNamespace(guild_permissions=_permissions(manage_channels)),
    )

    async def _create(name, topic=None, reason=None):
        if create_side_effect is not None:
            raise create_side_effect
        return _channel(900_000 + len(name), name)

    guild.create_text_channel = mock.AsyncMock(side_effect=_create)
    return guild


def _forbidden():
    return discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "ไม่มีสิทธิ์")


class EnsureRoomChannelsTest(unittest.IsolatedAsyncioTestCase):
    async def test_สร้างช่องที่ขาดทั้งสาม(self):
        guild = _guild()
        result = await ensure_room_channels(guild)

        self.assertEqual(set(result), {name for name, _ in CHANNEL_SPECS})
        self.assertEqual(guild.create_text_channel.await_count, 3)

    async def test_ใช้ช่องเดิมเมื่อชื่อซ้ำ_ไม่สร้างซ้ำ(self):
        existing = _channel(111, "announcement")
        guild = _guild(existing=[existing])

        result = await ensure_room_channels(guild)

        self.assertEqual(result["announcement"], 111)
        # สร้างเพิ่มแค่ 2 ช่องที่ขาด
        self.assertEqual(guild.create_text_channel.await_count, 2)
        created_names = {call.kwargs["name"] for call in guild.create_text_channel.await_args_list}
        self.assertEqual(created_names, {"birthday", "info"})

    async def test_ช่องเดียวล้ม_ช่องที่เหลือยังถูกสร้าง(self):
        guild = _guild(create_side_effect=_forbidden())

        result = await ensure_room_channels(guild)

        # สร้างไม่สำเร็จทุกช่อง ⇒ ผลลัพธ์ว่าง แต่ **ต้องไม่โยน exception**
        self.assertEqual(result, {})
        self.assertEqual(guild.create_text_channel.await_count, 3)

    async def test_ไม่มีสิทธิ์manage_channels_ไม่พยายามสร้าง(self):
        guild = _guild(manage_channels=False)

        result = await ensure_room_channels(guild)

        self.assertEqual(result, {})
        guild.create_text_channel.assert_not_awaited()


class SaveChannelsTest(unittest.IsolatedAsyncioTestCase):
    async def test_ยิงไปที่_channels_auto_พร้อม_servertarget(self):
        with mock.patch.object(api_client, "request", new=mock.AsyncMock(return_value={})) as req:
            ok = await save_channels_to_backend(123456789, {"announcement": 111, "info": 333})

        self.assertTrue(ok)
        args, kwargs = req.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "/123456789/channels/auto")
        self.assertEqual(kwargs["params"], {"target_type": "server"})
        self.assertEqual(kwargs["json"], {"channels": {"announcement": 111, "info": 333}})

    async def test_ยังไม่ผูกห้องคือ_False_ไม่ใช่_exception(self):
        with mock.patch.object(
            api_client, "request", new=mock.AsyncMock(side_effect=APIException("ไม่พบห้องเรียน"))
        ):
            ok = await save_channels_to_backend(123456789, {"announcement": 111})

        self.assertFalse(ok)

    async def test_ไม่มีช่องให้บันทึก_ไม่ยิง_API(self):
        with mock.patch.object(api_client, "request", new=mock.AsyncMock()) as req:
            ok = await save_channels_to_backend(123456789, {})

        self.assertFalse(ok)
        req.assert_not_awaited()
