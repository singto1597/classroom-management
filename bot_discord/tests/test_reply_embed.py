"""🧪 เทสต์ของ `services/reply_embed` — ข้อความตอบกลับต้องไม่ถูก Discord ปฏิเสธ (M10)

รัน:
```
docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
    classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
```

## บั๊กที่เทสต์ชุดนี้ล็อกไว้ (พบจากการตรวจระบบ 2026-09-23)

บอทตอบกลับด้วยข้อความดิบ 44 จุด ซึ่งในนั้น **21 จุดเป็น `f"❌ {e}"`** โดย `e` มาจากชั้น API
= ข้อความที่เราไม่ได้เขียนและไม่รู้ความยาว · `content=` ของ Discord จำกัด **2,000 ตัวอักษร**
และเมื่อเกิน **API ปฏิเสธทั้งข้อความ** (HTTP 400 / code 50035) ⇒ ครูเห็น "บอทไม่ตอบ"
ทั้งที่งานข้างหลังอาจสำเร็จแล้ว

## ⚠️ กับดักของเทสต์ชุดนี้ — อ่านก่อนแก้

**discord.py ไม่ตรวจเพดาน embed ฝั่ง client** (ดู `PremiseTest`) ⇒

🔴 **ห้ามเขียนเทสต์ที่คาดหวัง exception ตอนสร้าง embed** — มันจะ **ผ่านแบบหลอก ๆ**
   เพราะไม่มีอะไรโยนให้ดัก · เทสต์ที่ถูกต้องคือ **วัดความยาวจริงของ embed ที่สร้างเสร็จ**
   แล้วเทียบกับเพดาน ⇒ เทสต์ในไฟล์นี้จึงเป็นการ "วัด" ไม่ใช่ "ดัก exception"
"""
import unittest

import discord

from services.reply_embed import (
    EMBED_DESC_LIMIT,
    EMBED_TITLE_LIMIT,
    ERROR_TEXT_BUDGET,
    clip,
    error_embed,
    info_embed,
    success_embed,
    warning_embed,
)


class PremiseTest(unittest.TestCase):
    """🔎 พิสูจน์ "กับดัก" — ว่าเพดานไม่ได้ถูกบังคับโดยใครนอกจากเราเอง

    ถ้าเทสต์ในคลาสนี้ล้ม (คือ discord.py เริ่มโยน exception เอง) แปลว่าพฤติกรรมของ
    ไลบรารีเปลี่ยน ⇒ กลับมาทบทวนได้ว่าเทสต์ที่เหลือยังมีเหตุผลอยู่ไหม
    """

    def test_discord_py_ไม่ตรวจเพดาน_description_ให้(self):
        # 4,097 ตัวอักษร = เกินเพดานจริง 1 ตัว — discord.py ยอมรับเงียบ ๆ
        over = "ก" * (EMBED_DESC_LIMIT + 1)

        embed = discord.Embed(description=over)  # ⬅️ ไม่โยนอะไรเลย

        self.assertEqual(len(embed.description), EMBED_DESC_LIMIT + 1)
        # ⇒ ถ้าเราไม่ตัดเอง ไม่มีชั้นไหนตัดให้ · ความผิดพลาดไปโผล่เป็น HTTP 400 ตอน send

    def test_ของเดิม_content_จะถูกปฏิเสธ_แต่งานเราไม่ถูก(self):
        """เทียบ "ของเดิม" กับ "ของใหม่" บนข้อมูลชุดเดียวกัน

        🔑 ไม่ได้พิสูจน์ว่า Discord รับ 2,000 (อันนั้นเป็น spec ที่เชื่อถือได้)
           แต่พิสูจน์ว่า **บั๊กเข้าถึงได้จริงด้วยข้อมูลที่เกิดขึ้นได้จริง** และ
           ของใหม่กันได้ — ถ้าไม่มีเทสต์นี้ คำถามว่า "2,000 มันเกินจริงหรือเปล่า"
           จะไม่มีคำตอบในโค้ดเลย
        """
        # หน้า HTML ที่ proxy ตอบกลับมาแทน JSON — เกิดได้ตอน backend ล่ม/Traefik 503
        realistic_error = f"❌ {('<html>' + 'x' * 4000 + '</html>')}"

        # ของเดิม: `content=realistic_error` ⇒ เกิน 2,000 ⇒ Discord ปฏิเสธ **ทั้งข้อความ**
        #          และเพราะคำสั่งดักแค่ APIException ⇒ HTTPException หลุด ⇒ ผู้ใช้เห็นความเงียบ
        self.assertGreater(len(realistic_error), 2000)

        # ของใหม่: เข้า embed + ถูกตัด ⇒ อยู่ในเพดานที่ Discord รับแน่นอน
        embed = error_embed(realistic_error)
        self.assertLessEqual(len(embed.description), ERROR_TEXT_BUDGET)
        self.assertLessEqual(len(embed.description), EMBED_DESC_LIMIT)


class ClipTest(unittest.TestCase):
    """เทสต์ของ `clip` โดยตรง — ฟังก์ชันเดียวที่บังคับเพดาน"""

    def test_สั้นกว่าเพดาน_ไม่ถูกแตะ(self):
        self.assertEqual(clip("สั้น ๆ", 100), "สั้น ๆ")

    def test_เท่าเพดานพอดี_ไม่ถูกแตะ(self):
        # ขอบเขตที่พลาดง่ายที่สุด: `len == limit` ต้อง **ไม่** ตัด
        text = "ก" * 50
        self.assertEqual(clip(text, 50), text)

    def test_เกินเพดาน_หนึ่งตัว_ผลลัพธ์ยาวไม่เกินเพดาน(self):
        result = clip("ก" * 51, 50)
        self.assertLessEqual(len(result), 50)
        # ยาวเท่าเพดานพอดี — ไม่ใช่ 50+1 เพราะเราใช้ `…` แทนตัวสุดท้าย ไม่ใช่ต่อท้าย
        self.assertEqual(len(result), 50)

    def test_ร่องรอยการตัด_ยังอ่านออก(self):
        result = clip("ก" * 100, 10)
        self.assertTrue(result.endswith("…"))

    def test_ทุกความยาว_รอบจุดตัด_ไม่ทะลุเพดาน(self):
        # 🔑 เทสต์ที่สำคัญที่สุด: ไล่ทีละความยาวรอบ ๆ จุดตัด
        #    การตัดที่ผิดไป 1 ตัวจะโผล่ที่นี่ที่เดียว (ที่อื่นผ่านหมด)
        for limit in (1, 2, 5, ERROR_TEXT_BUDGET):
            for length in range(limit - 2, limit + 3):
                if length < 0:
                    continue
                with self.subTest(limit=limit, length=length):
                    self.assertLessEqual(len(clip("ก" * length, limit)), limit)


class ErrorEmbedTest(unittest.TestCase):
    """หัวใจของ M10 — ข้อความจาก exception ต้องถูกจำกัดความยาว"""

    def test_ข้อความ_error_ยาวมาก_ถูกตัดที่งบของ_error(self):
        # จำลองสิ่งที่เกิดขึ้นจริง: proxy ตอบหน้า HTML กลับมา 20,000 ตัวอักษร
        err = "❌ " + ("<html><body>" + "x" * 20000)

        embed = error_embed(err)

        self.assertLessEqual(len(embed.description), ERROR_TEXT_BUDGET)
        self.assertTrue(embed.description.endswith("…"))

    def test_งบของ_error_แน่นกว่าเพดาน_embed(self):
        # ถ้ามีคนเผลอตั้ง ERROR_TEXT_BUDGET = EMBED_DESC_LIMIT เทสต์นี้เตือน
        self.assertLess(ERROR_TEXT_BUDGET, EMBED_DESC_LIMIT)

    def test_ข้อความ_error_สั้น_คงเดิมทุกตัวอักษร(self):
        # 📌 ต้องไม่แก้สำนวนของผลิตภัณฑ์ — เปลี่ยนแค่ภาชนะ
        msg = "❌ ไม่พบห้องเรียนที่ระบุ"

        self.assertEqual(error_embed(msg).description, msg)

    def test_สีแดง(self):
        self.assertEqual(error_embed("พัง").color, discord.Color.red())

    def test_ไม่ใส่_title_โดยปริยาย(self):
        # ⚠️ ข้อความเดิมมี emoji นำอยู่แล้ว ("❌ …") ⇒ ใส่ title ทับจะได้ emoji ซ้ำสองที่
        self.assertIsNone(error_embed("❌ พัง").title)


class OtherEmbedsTest(unittest.TestCase):
    def test_สีของแต่ละชนิด(self):
        self.assertEqual(success_embed("ok").color, discord.Color.green())
        self.assertEqual(warning_embed("ระวัง").color, discord.Color.orange())
        self.assertEqual(info_embed("ทราบ").color, discord.Color.blue())

    def test_success_ยาวเกิน_ถูกตัดที่เพดาน_embed(self):
        embed = success_embed("✅ " + "ก" * (EMBED_DESC_LIMIT + 500))
        self.assertLessEqual(len(embed.description), EMBED_DESC_LIMIT)

    def test_title_ที่ยาวเกิน_ถูกตัด(self):
        embed = info_embed("เนื้อหา", title="ก" * (EMBED_TITLE_LIMIT + 50))
        self.assertLessEqual(len(embed.title), EMBED_TITLE_LIMIT)

    def test_title_ที่ส่งมา_ถูกใช้ตามที่ให้(self):
        self.assertEqual(info_embed("เนื้อหา", title="หัวข้อ").title, "หัวข้อ")


class EmptyMessageTest(unittest.TestCase):
    """⚠️ เพดานอีกทางที่มองไม่เห็น — Discord ปฏิเสธ embed ที่ว่างเปล่า

    `f"❌ {e}"` ที่ `e` เป็นสตริงว่าง จะได้ข้อความ `"❌ "` ซึ่งมีแต่ emoji+ช่องว่าง
    ⇒ ถ้าปล่อยผ่านเป็น description ว่าง จะเจอ HTTP 400 อีกทางหนึ่ง ("empty message")
    """

    def test_ข้อความว่าง_ได้ข้อความแทนที่ไม่ใช่สตริงว่าง(self):
        embed = error_embed("")
        self.assertTrue(embed.description.strip())

    def test_ข้อความที่มีแต่ช่องว่าง_ได้ข้อความแทน(self):
        embed = error_embed("   \n\t ")
        self.assertTrue(embed.description.strip())

    def test_ข้อความว่าง_ความยาวยังอยู่ในเพดาน(self):
        self.assertLessEqual(len(error_embed("").description), ERROR_TEXT_BUDGET)


if __name__ == "__main__":
    unittest.main()
