import discord
from discord.ext import commands
import redis.asyncio as aioredis
import json
import os
import asyncio
import logging

from services.action_service import BotActionService

from core.config import REDIS_URL

logger = logging.getLogger("DISCORD_BOT")


class RedisListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 🚨 สร้าง Instance ของ ActionService ขึ้นมาผูกกับบอท
        self.action_service = BotActionService(bot)
        
        self.bot.loop.create_task(self.listen_to_redis())

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
            await self.action_service.notify_finance_payment(server_id, data)

        elif event_type == "FINANCE_COLLECTION":
            await self.action_service.notify_finance_collection(server_id, data)

        elif event_type == "NEW_STUDENT":
            await self.action_service.notify_new_student(server_id, data)

        elif event_type == "NEW_ACTIVITY":
            await self.action_service.notify_new_activity(server_id, data)

async def setup(bot):
    await bot.add_cog(RedisListener(bot))