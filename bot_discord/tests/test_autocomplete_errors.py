"""🧪 เทสต์ของ autocomplete — `except:` เปล่ากลืนการยกเลิกงาน (ผลตรวจระบบ 2026-09-23 → L4)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```

## บั๊กที่เทสต์ชุดนี้ล็อกไว้

`task_autocomplete` และ `deleted_task_autocomplete` ใน `cogs/classroom_cmd.py` จบด้วย

```python
except:            # ⬅️ ไม่ระบุชนิด
    return []
```

🔴 **`except:` เปล่าไม่ได้แปลว่า "ดัก error" — มันแปลว่า "ดักทุกอย่างที่โยนได้"**
   ซึ่งรวมถึง `asyncio.CancelledError` และ `KeyboardInterrupt` ที่สืบทอดจาก
   **`BaseException`** ไม่ใช่ `Exception` (ตั้งแต่ Python 3.8)

   ⇒ ตอน deploy (`pull_all.sh` ส่ง SIGTERM) หรือตอนปิดบอท with Ctrl-C งานที่กำลังรอ
     API อยู่จะ **ถูกสั่งยกเลิก แต่ถูกกลืน** ⇒ ลูปไม่ยอมจบ · บอทปิดไม่สนิท
   ⇒ และเพราะไม่มี log อะไรเลย อาการ "ปิดบอทแล้วค้าง" จะหาสาเหตุไม่ได้

## สิ่งที่เทสต์ชุดนี้ยืนยัน

1. `APIException` (ความล้มเหลวที่ **คาดไว้**) → เงียบ คืน `[]` ตามเดิม — พฤติกรรมผลิตภัณฑ์ไม่เปลี่ยน
2. `CancelledError` / `KeyboardInterrupt` (**BaseException**) → **ต้องหลุดออกไป**
3. error ที่ไม่คาดคิด (เช่น คีย์ใน response เปลี่ยน) → ยังคืน `[]` แต่ **ต้องมี log**
   ไม่งั้นอาการ "autocomplete ขึ้นแต่รายการว่าง" จะวินิจฉัยไม่ได้เลย

⚠️ ใช้ stdlib `unittest` ตามธรรมเนียมของโฟลเดอร์นี้
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.classroom_cmd import BotCommands
from services.api_client import api_client, APIException


def _cog() -> BotCommands:
    """สร้าง cog โดยข้าม `__init__`

    `__init__` เรียก `self.daily_notification.start()` ซึ่งต้องมี bot จริงและ event loop
    ของ discord.py — เทสต์ชุดนี้สนใจเฉพาะ autocomplete จึงข้ามไป
    """
    return BotCommands.__new__(BotCommands)


def _interaction() -> SimpleNamespace:
    """interaction ปลอมเท่าที่ autocomplete แตะ: `guild_id` และ `user.id`"""
    return SimpleNamespace(guild_id=123456789, user=SimpleNamespace(id=987654321))


def _patch_request(**kwargs):
    return mock.patch.object(api_client, "request", new=mock.AsyncMock(**kwargs))


class AutocompleteErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_api_error_เงียบและคืนรายการว่าง(self):
        """ความล้มเหลวที่คาดไว้ — พฤติกรรมเดิมต้องคงไว้ (ห้ามเปลี่ยนเป็นโยน error)"""
        cog = _cog()
        with _patch_request(side_effect=APIException("Backend ล่ม")):
            result = await cog.task_autocomplete(_interaction(), "")
        self.assertEqual(result, [])

    async def test_cancelled_error_ต้องหลุดออกไป(self):
        """🔴 หัวใจของ L4 — ถ้ากลับไปใช้ `except:` เทสต์นี้จะล้มทันที"""
        cog = _cog()
        with _patch_request(side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await cog.task_autocomplete(_interaction(), "")

    async def test_keyboard_interrupt_ต้องหลุดออกไป(self):
        """`KeyboardInterrupt` ก็เป็น BaseException — ต้องไม่ถูกกลืน"""
        cog = _cog()
        with _patch_request(side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                await cog.task_autocomplete(_interaction(), "")

    async def test_error_ที่ไม่คาดคิด_ต้องมี_log(self):
        """คืน `[]` เหมือนเดิม แต่ต้องทิ้งร่องรอย — ไม่งั้นอาการ "รายการว่าง" วินิจฉัยไม่ได้"""
        cog = _cog()
        with _patch_request(side_effect=KeyError("task_name")):
            with self.assertLogs("DISCORD_BOT", level="ERROR") as captured:
                result = await cog.task_autocomplete(_interaction(), "")

        self.assertEqual(result, [])
        self.assertTrue(
            any("autocomplete" in line for line in captured.output),
            f"ไม่พบ log ของ autocomplete ใน: {captured.output}",
        )

    async def test_deleted_autocomplete_ก็ต้องไม่กลืน_cancelled(self):
        """จุดที่สองในไฟล์เดียวกัน — แก้ไม่ครบคู่คือแก้ไม่จริง"""
        cog = _cog()
        with _patch_request(side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await cog.deleted_task_autocomplete(_interaction(), "")

    async def test_สำเร็จยังสร้างตัวเลือกได้ตามเดิม(self):
        """กัน regression: การแก้ except ต้องไม่กระทบเส้นทางปกติ"""
        cog = _cog()
        tasks = [{"id": 7, "task_name": "การบ้านคณิต", "due_date": "2026-09-30"}]
        with _patch_request(return_value=tasks):
            choices = await cog.task_autocomplete(_interaction(), "")

        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].value, 7)

    async def test_ชื่อตัวเลือกที่ยาวเกิน_ถูกตัดตามเดิม(self):
        """ตรรกะตัดชื่อ 100 ตัวอักษรเดิมต้องยังอยู่"""
        cog = _cog()
        tasks = [{"id": 1, "task_name": "ก" * 200, "due_date": "2026-09-30"}]
        with _patch_request(return_value=tasks):
            choices = await cog.task_autocomplete(_interaction(), "")

        self.assertLessEqual(len(choices[0].name), 100)

    async def test_กรองตามคำที่พิมพ์(self):
        cog = _cog()
        tasks = [
            {"id": 1, "task_name": "การบ้านคณิต", "due_date": "2026-09-30"},
            {"id": 2, "task_name": "รายงานวิทย์", "due_date": "2026-10-01"},
        ]
        with _patch_request(return_value=tasks):
            choices = await cog.task_autocomplete(_interaction(), "วิทย์")

        self.assertEqual([c.value for c in choices], [2])


if __name__ == "__main__":
    unittest.main()
