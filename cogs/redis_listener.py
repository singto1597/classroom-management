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
        while True:
            try:
                redis_client = aioredis.from_url(REDIS_URL)
                pubsub = redis_client.pubsub()
                await pubsub.subscribe("classroom_events")
                
                logger.info("🎧 บอทเริ่มดักฟัง Redis ช่อง 'classroom_events' แล้ว...")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        # โยนงานไปให้ process_event จัดการ
                        await self.process_event(data)
                        
            except Exception as e:
                logger.error(f"❌ Redis Connection Lost: {e}. Retrying in 5 seconds...")
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

async def setup(bot):
    await bot.add_cog(RedisListener(bot))