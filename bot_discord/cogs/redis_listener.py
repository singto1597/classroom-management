import discord
from discord.ext import commands
import redis.asyncio as aioredis
import json
import os
import asyncio
import logging

from services.action_service import BotActionService
from services.pdf_attach import MAX_CONCURRENT_PDF_FETCHES

from core.config import REDIS_URL

logger = logging.getLogger("DISCORD_BOT")


class RedisListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 🚨 สร้าง Instance ของ ActionService ขึ้นมาผูกกับบอท
        self.action_service = BotActionService(bot)

        # ================================================================
        # 🔀 งานที่รอเครือข่ายนาน (แนบ PDF) แยกออกจากลูปฟัง Redis — F5/PR-3
        # ================================================================
        # ⚠️ **นี่คือการเปลี่ยน concurrency model ของ listener ทั้งตัว**
        #    ลูปข้างล่างเป็น sequential โดยเจตนา (ทีละ event, มี sleep(0.1) คั่น) ⇒ ก่อนหน้านี้
        #    ทุก event รับประกันว่าจบก่อนตัวถัดไปเริ่ม หลังการเปลี่ยนนี้ **เฉพาะ**
        #    `FINANCE_PAYMENT` ที่มี `receipt_nos` เท่านั้นที่ไปวิ่งเบื้องหลัง
        #
        #    🔴 เหตุผลที่เลี่ยงไม่ได้: การแนบไฟล์ต้องเรียก Gotenberg ซึ่งฝั่ง backend ตั้ง
        #       `--api-timeout` ไว้ 120 วินาที · เพดานของบอทคือ 60 (`PDF_FETCH_TIMEOUT_S`)
        #       ⇒ ถ้า `await` ตรง ๆ แล้ว Gotenberg ค้าง **การแจ้งเตือนอื่นทั้งระบบจะหยุดรอ**
        #         60-120 วินาที (งานใหม่ ประกาศ กิจกรรม วันเกิด — ทุกอย่าง)
        #
        #    📌 ผลที่ยอมรับ: (ก) ลำดับข้อความของ FINANCE_PAYMENT สองอันที่มาพร้อมกัน
        #       ไม่รับประกันอีกต่อไป (ข) exception ในงานเบื้องหลัง **ไม่ถูกจับ** โดย
        #       try/except ของลูป ⇒ ต้องมี try/except ในตัว task เอง (ด้านล่าง)
        self._pdf_tasks: set = set()
        self._pdf_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PDF_FETCHES)

        self.bot.loop.create_task(self.listen_to_redis())

    def _spawn_pdf_task(self, server_id: int, data: dict) -> None:
        """รันการส่งข้อความ+แนบไฟล์เบื้องหลัง แล้ว **ไม่** บล็อกลูปฟัง Redis

        🛡️ ต้องเก็บ task ไว้ใน set: ถ้าไม่มี reference ค้างไว้ garbage collector
           อาจเก็บ task ทิ้งกลางทาง (asyncio เตือนเรื่องนี้ตรง ๆ) ⇒ ข้อความหายเงียบ ๆ
        🛡️ ต้องมี try/except ในตัว: task ที่ raise โดยไม่มีใคร await จะกลายเป็น
           "Task exception was never retrieved" ซึ่งไม่มีผลกับผู้ใช้และไม่มีใครเห็น
        🚦 semaphore จำกัดงานพร้อมกัน — Gotenberg เรนเดอร์ PDF ด้วย Chromium ซึ่งกิน CPU
           หนัก การยิงพร้อมกัน 500 ไฟล์ (import ห้องทั้งห้อง) จะทำให้ทุกรายการช้าลงหมด
        """
        async def runner():
            try:
                async with self._pdf_semaphore:
                    await self.action_service.notify_finance_payment(server_id, data)
            except Exception as e:
                logger.error(
                    f"⚠️ ส่งข้อความ FINANCE_PAYMENT แบบเบื้องหลังล้มเหลว "
                    f"({type(e).__name__}: {e}) server={server_id} — ข้ามไป ไม่ตัด subscription"
                )

        task = asyncio.create_task(runner())
        self._pdf_tasks.add(task)
        task.add_done_callback(self._pdf_tasks.discard)

    async def listen_to_redis(self):
        # หน่วงเวลาตอนเริ่มบอทนิดนึง เผื่อตู้ Redis ใน Docker ยังบูตตัวเองไม่เสร็จ
        await asyncio.sleep(3) 

        while True:
            try:
                # 1. เชื่อมต่อแบบคลีนๆ พร้อมตั้งให้แปลงข้อมูลเป็น String ทันที (decode_responses=True)
                redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
                
                # 2. ลองเต๊าะ (Ping) ดู 1 ทีเพื่อความชัวร์ ว่าเซิร์ฟเวอร์ Redis มีชีวิตอยู่จริงมั้ย
                await redis_client.ping()
                logger.info("✅ เทสต์ปิง Redis สำเร็จ! กำลังเตรียมหูฟัง...")

                pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe("classroom_events")
                
                logger.info("🎧 บอทเริ่มดักฟังช่อง 'classroom_events' แบบเสถียรแล้ว!")

                # 3. ท่าไม้ตาย! ใช้ get_message แบบมี Timeout ป้องกันการค้าง
                while True:
                    # เช็คข้อความ (ถ้าใน 1 วินาทีไม่มีใครส่งมา ให้ปล่อยผ่าน ไม่บล็อกการทำงาน)
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    
                    if message and message["type"] == "message":
                        try:
                            # ถอดรหัส JSON แล้วโยนไปทำงานต่อ
                            data = json.loads(message["data"])
                            await self.process_event(data)
                        except Exception as e:
                            # 🛡️ เหตุการณ์เดี่ยวพัง ไม่ควรทำให้ subscription ทั้งหมดหลุด
                            # (เดิม event ตัวเดียว error → หลุดออกจาก loop → ฟังข้ามช่วงไป)
                            logger.error(f"⚠️ Event ล้มเหลว (ข้ามไป ไม่ตัด subscription): {type(e).__name__}: {e}")

                    # หายใจเว้นจังหวะนิดนึง ปล่อยให้บอทไปประมวลผลคำสั่ง Discord อื่นๆ
                    await asyncio.sleep(0.1)

            except Exception as e:
                # พิมพ์ชื่อ Error ออกมาด้วย จะได้รู้ชัดๆ ว่าหลุดเพราะอะไร
                logger.error(f"❌ Redis หลุด! ({type(e).__name__}): {e} -> ขอเริ่มใหม่ใน 5 วินาที...")
                await asyncio.sleep(5)

    async def process_event(self, data):
        """ฟังก์ชันคัดแยกพัสดุ (Router)"""
        event_type = data.get("event")
        server_id = data.get("server_id")

        if not event_type or not server_id:
            return

        # 🚨 โยนข้อมูลไปให้ ActionService ปั้นหน้าตาและส่งข้อความ
        if event_type == "NEW_TASK":
            await self.action_service.notify_new_task(server_id, data)
        
        elif event_type == "TASK_DONE":
            await self.action_service.notify_task_done(server_id, data)
        
        elif event_type == "NEW_NOTE":
            await self.action_service.notify_new_note(server_id, data)
        
        elif event_type == "CUSTOM_MESSAGE":
            await self.action_service.notify_custom_message(server_id, data)

        elif event_type == "FINANCE_TRANSACTION":
            await self.action_service.notify_finance_transaction(server_id, data)

        elif event_type == "FINANCE_PAYMENT":
            # 🧾 ข้อความนี้ **อาจต้องโหลด PDF จาก Gotenberg** (เมื่อ payload มี `receipt_nos`)
            #    ⇒ ต้องไม่ await ในลูป (ดูเหตุผลเต็มใน `__init__`)
            #    🔑 แยกสองทางด้วยการ **มี/ไม่มี `receipt_nos`** ไม่ใช่แยกที่ชนิด event:
            #       เส้นทางเดิม (บิลเดียว, ติ๊กออกใบเสร็จออก) ยังเดินแบบ sequential เหมือนก่อน
            #       ทุกไบต์ — พฤติกรรมที่ไม่มีไฟล์แนบไม่ต้องแลกอะไรเลย
            if data.get("receipt_nos"):
                self._spawn_pdf_task(server_id, data)
            else:
                await self.action_service.notify_finance_payment(server_id, data)

        elif event_type == "FINANCE_COLLECTION":
            await self.action_service.notify_finance_collection(server_id, data)

        elif event_type == "NEW_STUDENT":
            await self.action_service.notify_new_student(server_id, data)

        elif event_type == "STUDENT_INVITE":
            await self.action_service.notify_student_invite(server_id, data)

        elif event_type == "INVITE_ACCEPTED":
            await self.action_service.notify_invite_accepted(server_id, data)

        elif event_type == "NEW_ACTIVITY":
            await self.action_service.notify_new_activity(server_id, data)

async def setup(bot):
    await bot.add_cog(RedisListener(bot))