import logging

import discord
from discord.ext import commands
from core.config import DISCORD_TOKEN
from services.api_client import api_client
from services.guild_setup import ensure_room_channels, save_channels_to_backend, send_join_notice

logger = logging.getLogger("DISCORD_BOT")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        print("Initializing API Client Session...")
        await api_client.init_session() # เปิดท่อเชื่อมไปหา FastAPI
        
        print("Loading Cogs...")
        # 🚨 โหลด Cog (Routers) เข้ามา โดยไม่ต้องส่ง DB แล้ว
        await self.load_extension('cogs.classroom_cmd')
        await self.load_extension('cogs.student_cmd')
        await self.load_extension('cogs.activity_cmd')
        await self.load_extension('cogs.finance_cmd')
        await self.load_extension("cogs.redis_listener")
        
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} command(s)")

    async def close(self):
        # ปิดท่อ API ก่อนบอทดับ
        await api_client.close()
        await super().close()

bot = MyBot()

@bot.event
async def on_ready():
    print(f'✅ บอท {bot.user} (API-Driven) พร้อมทำงานแล้ว!')

@bot.event
async def on_guild_join(guild: discord.Guild):
    """🏗️ บอทเข้าเซิร์ฟเวอร์ใหม่ → สร้างช่องที่ต้องใช้ทันที (announcement/birthday/info)

    ⚠️ ห้ามให้ error ที่นี่ทำให้บอทล้มทั้งตัว — ฟังก์ชันนี้ทำงานตอนไม่มีใครสั่ง
       และเจ้าของเซิร์ฟเวอร์อาจให้สิทธิ์ไม่ครบ ⇒ เก็บทุกอย่างไว้ใน try/except
       แล้วแจ้งใน log (ผู้ดูแลจะได้ตามไปแก้ ไม่ใช่บอทตายเงียบ)
    """
    logger.info("🤝 เข้าร่วมเซิร์ฟเวอร์ %s (id=%s)", guild.name, guild.id)
    try:
        channels = await ensure_room_channels(guild)
        saved = await save_channels_to_backend(guild.id, channels)
        await send_join_notice(guild, channels, saved)
    except Exception:
        logger.exception("ตั้งค่าช่องอัตโนมัติไม่สำเร็จ (guild_id=%s)", guild.id)

if __name__ == '__main__':
    bot.run(DISCORD_TOKEN)