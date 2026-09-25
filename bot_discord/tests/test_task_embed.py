"""🧪 เทสต์ของ `services/task_embed` — embed ของ `/list_tasks` ต้องไม่ถูก Discord ปฏิเสธ (M11)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```

## บั๊กที่เทสต์ชุดนี้ล็อกไว้ (พบจากการตรวจระบบ 2026-09-23)

เดิม `/list_tasks` ต่อ `add_field` หนึ่งฟิลด์ต่อหนึ่งงาน **โดยไม่จำกัด** ⇒ ห้องที่มีงานค้าง
30 ชิ้นจะได้ฟิลด์ที่ 26 ซึ่ง **Discord API ปฏิเสธทั้งข้อความ** (HTTP 400, error code 50035)
และเพราะคำสั่งนั้น `except APIException` เท่านั้น ⇒ `HTTPException` หลุด ⇒ ครูเห็น
"ไม่ตอบสนอง" ทั้งที่โหลดข้อมูลสำเร็จแล้ว

## ⚠️ กับดักของเทสต์ชุดนี้ — อ่านก่อนแก้

**discord.py ไม่ตรวจเพดานพวกนี้ฝั่ง client** · `Embed.add_field` รับ 26 ฟิลด์ / 1,025 ตัวอักษร
ไปเงียบ ๆ (ดู `PremiseTest`) ⇒

🔴 **ห้ามเขียนเทสต์ที่คาดหวัง `ValueError` จาก `add_field`** — มันจะ **ผ่านแบบหลอก ๆ**
   ในทางกลับกันก็ไม่มีประโยชน์ เพราะไม่มีอะไรโยนให้ดัก
   เทสต์ที่ถูกต้องคือ **วัดค่าจริงใน embed ที่สร้างเสร็จ** แล้วเทียบกับเพดานของ Discord
"""
import unittest

import discord

from services.task_embed import (
    MAX_EMBED_CHARS,
    MAX_FIELDS,
    MAX_FIELD_NAME,
    MAX_FIELD_VALUE,
    build_no_pending_tasks_embed,
    build_pending_tasks_embed,
)


def _task(**overrides) -> dict:
    """task หนึ่งตัวตามรูปร่างที่ API ส่งมา (คีย์ครบ) — override เฉพาะที่เทสต์สนใจ"""
    task = {
        "id": 1,
        "task_name": "การบ้านคณิตศาสตร์",
        "task_detail": "หน้า 45 ข้อ 1-10",
        "due_date": "2026-09-30",
        "created_at": "2026-09-24T10:30:00",
    }
    task.update(overrides)
    return task


def _assert_within_discord_limits(case: unittest.TestCase, embed: discord.Embed) -> None:
    """เพดานจริงของ Discord — ตรวจจาก embed ที่สร้างเสร็จ ไม่ใช่จาก exception"""
    case.assertLessEqual(len(embed.fields), MAX_FIELDS, "ฟิลด์เกิน 25 ⇒ Discord ปฏิเสธทั้งข้อความ")
    case.assertLessEqual(len(embed), MAX_EMBED_CHARS, "embed เกิน 6,000 ตัวอักษร ⇒ Discord ปฏิเสธ")
    for field in embed.fields:
        case.assertLessEqual(len(field.name), MAX_FIELD_NAME, f"ชื่อฟิลด์ยาวเกิน: {field.name[:40]}")
        case.assertLessEqual(len(field.value), MAX_FIELD_VALUE, "ค่าฟิลด์ยาวเกิน 1,024")


class PremiseTest(unittest.TestCase):
    """🔑 เทสต์ที่พิสูจน์ "สมมติฐาน" ของเทสต์ชุดอื่น

    ⚠️ ตัวเลขในคลาสนี้เป็น **ความจริงของ Discord** (25 / 256 / 1,024 / 6,000)
       จึงเขียนเป็นเลขตรง ๆ **ไม่ใช่**ดึงจากค่าคงที่ของเรา — ถ้าดึงมา มันจะกลายเป็น
       เทสต์ที่ตรวจตัวเอง (แก้เพดานเป็นเท่าไรก็ผ่าน) ซึ่งไม่กันอะไรเลย
    """

    def test_our_caps_match_discords_documented_limits(self):
        """ถ้ามีใครแก้ค่าคงที่ของเราให้เพี้ยนไปจากความจริงของ Discord ⇒ ต้องรู้ตัวที่นี่"""
        self.assertEqual(MAX_FIELDS, 25)
        self.assertEqual(MAX_FIELD_NAME, 256)
        self.assertEqual(MAX_FIELD_VALUE, 1024)
        self.assertEqual(MAX_EMBED_CHARS, 6000)

    def test_discord_py_does_not_enforce_the_field_limit_client_side(self):
        """ฟิลด์ที่ 26 → discord.py **ไม่** โยนอะไร ⇒ ไม่มี ValueError ให้ดัก (ยืนยันแล้ว 2.7.1)"""
        embed = discord.Embed(title="x")
        for i in range(26):  # 26 = หนึ่งฟิลด์เกินเพดานจริงของ Discord
            embed.add_field(name=f"f{i}", value="v")
        self.assertEqual(len(embed.fields), 26)

    def test_discord_py_does_not_enforce_the_value_limit_client_side(self):
        embed = discord.Embed(title="x")
        embed.add_field(name="n", value="a" * 1025)  # 1,025 = หนึ่งตัวอักษรเกินเพดานจริง
        self.assertEqual(len(embed.fields[0].value), 1025)

    def test_len_of_an_embed_counts_its_characters(self):
        """`len(embed)` คือจำนวนตัวอักษรที่ Discord นับ — ใช้เป็นเครื่องมือวัดในเทสต์อื่น

        🔑 เทสต์นี้มีไว้ **สอบเทียบเครื่องมือวัด** ก่อนเทสต์อื่นจะเชื่อมัน
           (นับเอง: title 3 + description 2 + ชื่อฟิลด์ 1 + ค่าฟิลด์ 2 = 8)
        """
        embed = discord.Embed(title="abc", description="de")
        embed.add_field(name="f", value="gh")
        self.assertEqual(len(embed), 8)


class PendingTasksEmbedTest(unittest.TestCase):
    def test_a_class_sized_list_fits_without_hiding_anything(self):
        """25 งาน = พอดีเพดาน ⇒ ต้องแสดงครบและ **ไม่ต้องมี footer** (พฤติกรรมเดิมไม่เปลี่ยน)"""
        embed = build_pending_tasks_embed([_task(task_name=f"งาน {i}") for i in range(MAX_FIELDS)])

        _assert_within_discord_limits(self, embed)
        self.assertEqual(len(embed.fields), MAX_FIELDS)
        self.assertIsNone(embed.footer.text, "แสดงครบแล้วไม่ควรมี footer")

    def test_more_tasks_than_the_limit_are_capped_and_the_footer_declares_the_rest(self):
        """🔴 หัวใจของ M11 — 30 งานเคยทำให้ทั้งข้อความหาย ตอนนี้ต้องเหลือ 25 + บอกว่าซ่อน 5"""
        embed = build_pending_tasks_embed([_task(task_name=f"งาน {i}") for i in range(30)])

        _assert_within_discord_limits(self, embed)
        self.assertEqual(len(embed.fields), MAX_FIELDS)
        self.assertIsNotNone(embed.footer.text, "แสดงไม่ครบต้องบอกผู้ใช้ ไม่ใช่หายเงียบ ๆ")
        self.assertIn("25", embed.footer.text)
        self.assertIn("30", embed.footer.text)

    def test_the_earliest_tasks_are_the_ones_kept(self):
        """งานที่ API ส่งมาก่อน (ถึงกำหนดก่อน) ต้องรอด ส่วนท้ายถูกลด — ไม่ใช่สุ่ม"""
        tasks = [_task(task_name=f"งาน {i}") for i in range(30)]
        embed = build_pending_tasks_embed(tasks)

        self.assertIn("งาน 0", embed.fields[0].name)
        self.assertIn("งาน 24", embed.fields[-1].name)
        self.assertNotIn("งาน 25", "".join(f.name for f in embed.fields))

    def test_a_very_long_detail_is_clipped_to_the_value_limit(self):
        """รายละเอียด 4,000 ตัวอักษรต้องถูกตัด ไม่ใช่ทำให้ Discord ปฏิเสธทั้งข้อความ"""
        embed = build_pending_tasks_embed([_task(task_detail="ก" * 4000)])

        _assert_within_discord_limits(self, embed)
        self.assertEqual(len(embed.fields), 1)
        self.assertLessEqual(len(embed.fields[0].value), MAX_FIELD_VALUE)
        self.assertTrue(embed.fields[0].value.endswith("…"), "ต้องบอกว่าข้อความยังมีต่อ")

    def test_a_very_long_task_name_is_clipped_to_the_name_limit(self):
        embed = build_pending_tasks_embed([_task(task_name="งาน" * 200)])

        _assert_within_discord_limits(self, embed)
        self.assertLessEqual(len(embed.fields[0].name), MAX_FIELD_NAME)

    def test_the_whole_embed_stays_under_the_char_limit_with_many_long_tasks(self):
        """🔴 เพดานที่สองที่มองไม่เห็น — 25 ฟิลด์ที่รายละเอียดยาว ๆ ก็ยังเกิน 6,000 ได้"""
        embed = build_pending_tasks_embed([_task(task_detail="ก" * 4000) for _ in range(30)])

        _assert_within_discord_limits(self, embed)
        self.assertLess(len(embed), MAX_EMBED_CHARS)
        self.assertIsNotNone(embed.footer.text, "ตัดเพราะงบตัวอักษรก็ต้องบอกผู้ใช้ด้วย")

    def test_missing_optional_fields_render_placeholders_not_the_word_none(self):
        """งานที่ยังไม่กรอกรายละเอียด — เดิมใช้ `task['task_detail']` ตรง ๆ ⇒ `KeyError`"""
        embed = build_pending_tasks_embed([{"task_name": None}])

        _assert_within_discord_limits(self, embed)
        self.assertEqual(len(embed.fields), 1)
        self.assertNotIn("None", embed.fields[0].name)
        self.assertNotIn("None", embed.fields[0].value)

    def test_an_empty_list_produces_an_embed_with_no_fields(self):
        """ผู้เรียกเป็นคนตัดสินใจเรื่อง "ไม่มีงาน" — ตัวสร้างต้องไม่พังกับลิสต์ว่าง"""
        embed = build_pending_tasks_embed([])

        self.assertEqual(embed.fields, [])
        self.assertIsNone(embed.footer.text)


class NoPendingTasksEmbedTest(unittest.TestCase):
    def test_the_empty_reply_is_an_embed_and_the_wording_is_unchanged(self):
        """คำตอบ "ไม่มีงาน" ต้องเป็น Embed (กฎ Embeds First) แต่ **คำต้องไม่ถูกแก้**

        🔑 เทสต์นี้กันการ "ปรับปรุงสำนวน" โดยไม่ตั้งใจตอนแปลงเป็น Embed —
           สิ่งที่ผู้ใช้เห็นควรเปลี่ยนแค่ภาชนะ ไม่ใช่ข้อความ
        """
        embed = build_no_pending_tasks_embed()

        self.assertEqual(embed.title, "🎉 ไม่มีงานเลยจ้าา")
        self.assertEqual(embed.fields, [])


if __name__ == "__main__":
    unittest.main()
