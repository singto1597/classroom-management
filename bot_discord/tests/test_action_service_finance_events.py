"""🧪 เทสต์เหตุการณ์ค่าปรับ/เตือนผู้ค้างชำระบน Discord (Phase 6)

ล็อกสิ่งที่ผู้ใช้เห็น:
1. เลือกช่องถูก — ค่าปรับ 3 ตัวไปช่อง `minor` · เตือนรายวันไปช่อง `announcement`
2. **ไม่ @everyone** ทุกกรณี (ค่าปรับเป็นเรื่องบางคน ไม่ใช่ประกาศทั้งห้อง)
3. ยอดเงินฟอร์แมตเป็น `1,234.56` และค่าดิบจาก backend (`discount`/`uncollectible`)
   ถูกแปลงเป็นป้ายไทย
4. เตือนรายวัน: `part`/`total_parts` ขึ้นในหัวเรื่อง · รายชื่ออยู่ใน **description**
   (เพดาน 4,096) ไม่ใช่ field (เพดาน 1,024) ⇒ 20 คน + ชื่อยาวยังส่งได้
5. payload ขาดฟิลด์ = ไม่ crash (ข้อมูลจาก backend เวอร์ชันเก่า/ฟิลด์ใหม่)

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
from services.api_client import api_client

MINOR = 333
ANNOUNCEMENT = 111


class _FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


def _service():
    channel = _FakeChannel()
    bot = SimpleNamespace(
        user=SimpleNamespace(id=1),
        get_channel=lambda cid: channel,
    )
    return BotActionService(bot), channel


def _patch_room(**overrides):
    room = {
        "announcement_channel_id": ANNOUNCEMENT,
        "minor_notify_channel_id": MINOR,
        "muted_channel_ids": [],
    }
    room.update(overrides)
    return mock.patch.object(
        api_client, "request", new=mock.AsyncMock(return_value=room)
    )


class FineEventsTest(unittest.IsolatedAsyncioTestCase):
    async def test_ออกค่าปรับ_ไปช่องงานเล็กและไม่mention(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_fines_issued(123, {
                "fine_type_name": "มาสาย",
                "student_count": 3,
                "total_amount": 60.0,
                "due_date": "2026-12-01",
                "user_name": "ครูสมชาย",
                "category": "⚖️ ออกค่าปรับ",
            })

        self.assertEqual(len(channel.sent), 1)
        sent = channel.sent[0]
        self.assertNotIn("@everyone", sent["content"])
        embed = sent["embed"]
        self.assertIn("มาสาย", embed.description)
        self.assertIn("3 คน", embed.description)
        self.assertIn("60.00", embed.description)
        self.assertIn("2026-12-01", str(embed.fields))
        self.assertNotIn("ครูสมชาย", str(embed.description))  # ผู้ทำอยู่ใน footer

    async def test_ยกเว้นค่าปรับ_แปลงหมวดเป็นไทย(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_fine_waived(123, {
                "student_name": "สมชาย ใจดี",
                "fine_type_name": "มาสาย",
                "amount": 20.0,
                "remaining_amount": 10.0,
                "reason_category": "discount",
                "user_name": "ครูสมหญิง",
            })

        embed = channel.sent[0]["embed"]
        self.assertIn("สมชาย ใจดี", embed.description)
        self.assertIn("20.00", embed.description)
        self.assertIn("10.00", embed.description)
        fields = {f.name: f.value for f in embed.fields}
        self.assertEqual(fields.get("📄 เหตุผล"), "ยกเว้น/ลด")

    async def test_คืนเงินค่าปรับ_แสดงเลขใบสำคัญจ่าย(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_fine_refunded(123, {
                "student_name": "สมชาย ใจดี",
                "fine_type_name": "มาสาย",
                "amount": 20.0,
                "receipt_no": "PV-2569-0007",
                "user_name": "ครูสมหญิง",
            })

        embed = channel.sent[0]["embed"]
        fields = {f.name: f.value for f in embed.fields}
        self.assertEqual(fields.get("🧾 ใบสำคัญจ่าย"), "PV-2569-0007")

    async def test_คืนเงินไม่มีเลขเอกสาร_ไม่แสดงfield(self):
        """`receipt_no` เป็น Optional — ต้องไม่สร้าง field ที่มีค่า None"""
        service, channel = _service()
        with _patch_room():
            await service.notify_fine_refunded(123, {
                "student_name": "ก",
                "fine_type_name": "ข",
                "amount": 5.0,
                "receipt_no": None,
                "user_name": "ค",
            })

        embed = channel.sent[0]["embed"]
        self.assertNotIn("ใบสำคัญจ่าย", str(embed.fields))


class DebtReminderTest(unittest.IsolatedAsyncioTestCase):
    def _payload(self, **overrides):
        data = {
            "as_of": "2026-11-24",
            "total_students": 2,
            "total_amount": 130.0,
            "students": [
                {"student_no": 3, "name": "สมชาย ใจดี", "total": 100.0,
                 "overdue_count": 2, "due_soon_count": 0},
                {"student_no": 5, "name": "สมหญิง (หญิง)", "total": 30.0,
                 "overdue_count": 0, "due_soon_count": 1},
            ],
            "part": 1,
            "total_parts": 1,
            "category": "📣 แจ้งเตือนผู้ค้างชำระ",
        }
        data.update(overrides)
        return data

    async def test_เตือนรายวัน_ไปช่องประกาศและไม่mention(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_debt_reminder(123, self._payload())

        sent = channel.sent[0]
        self.assertNotIn("@everyone", sent["content"])
        self.assertEqual(sent["content"], "📣 แจ้งเตือนผู้ค้างชำระ")
        embed = sent["embed"]
        self.assertIn("2026-11-24", embed.description)
        self.assertIn("2 คน", embed.description)
        self.assertIn("130.00", embed.description)
        self.assertIn("3. **สมชาย ใจดี** — 100.00 บาท (เลยกำหนด 2 รายการ)", embed.description)
        self.assertIn("5. **สมหญิง (หญิง)** — 30.00 บาท", embed.description)
        # รายชื่อต้องอยู่ใน description (เพดาน 4,096) ไม่ใช่ field (เพดาน 1,024)
        self.assertNotIn("สมชาย ใจดี", str(embed.fields))

    async def test_หลายส่วน_หัวเรื่องบอกส่วนที่(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_debt_reminder(123, self._payload(part=2, total_parts=3))

        self.assertIn("ส่วนที่ 2/3", channel.sent[0]["embed"].title)

    async def test_ส่วนเดียว_ไม่แสดงส่วนที่(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_debt_reminder(123, self._payload())

        self.assertNotIn("ส่วนที่", channel.sent[0]["embed"].title)

    async def test_รายชื่อ20คนยาว_ไม่เกินเพดานdescription(self):
        """ชื่อไทย+ชื่อเล่น+ยอดยาว ๆ 20 คน ยังต้องอยู่ใต้ 4,096 และไม่ถูกตัดชื่อแรกทิ้ง"""
        service, channel = _service()
        students = [
            {"student_no": i, "name": "ก" * 100, "total": 123456.78,
             "overdue_count": 5, "due_soon_count": 0}
            for i in range(1, 21)
        ]
        with _patch_room():
            await service.notify_debt_reminder(123, self._payload(
                total_students=20, total_amount=2469135.6, students=students,
            ))

        description = channel.sent[0]["embed"].description
        self.assertLessEqual(len(description), 4096)
        self.assertIn("1. **ก", description)

    async def test_payloadขาดฟิลด์_ไม่crash(self):
        service, channel = _service()
        with _patch_room():
            await service.notify_debt_reminder(123, {})

        self.assertEqual(len(channel.sent), 1)


class ChannelRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_ช่องminorถูกmute_ค่าปรับไม่ถูกย้ายไปช่องประกาศ(self):
        service, channel = _service()
        with _patch_room(muted_channel_ids=[MINOR]):
            await service.notify_fines_issued(123, {"fine_type_name": "x"})

        self.assertEqual(channel.sent, [])

    async def test_ช่องประกาศถูกmute_เตือนรายวันเงียบ(self):
        service, channel = _service()
        with _patch_room(muted_channel_ids=[ANNOUNCEMENT], minor_notify_channel_id=None):
            await service.notify_debt_reminder(123, {})

        self.assertEqual(channel.sent, [])


if __name__ == "__main__":
    unittest.main()
