import discord
from discord.ext import commands
from core.config import DISCORD_TOKEN
from services.api_client import api_client

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

if __name__ == '__main__':
    bot.run(DISCORD_TOKEN)