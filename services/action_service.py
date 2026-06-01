import discord
import logging
from services.api_client import api_client, APIException

logger = logging.getLogger("DISCORD_BOT")

class BotActionService:
    def __init__(self, bot):
        self.bot = bot

    async def _get_announcement_channel(self, server_id: int):
        """ดึงช่องแจ้งเตือนหลักของห้องจาก API"""
        try:
            # ใช้ ID ของบอทเป็น X-Discord-Id สำหรับการยิง API ภายใน
            headers = {"X-Discord-Id": str(self.bot.user.id)}
            room_data = await api_client.request("GET", f"/{server_id}", headers=headers)
            
            channel_id = room_data.get("announcement_channel_id")
            if channel_id:
                return self.bot.get_channel(int(channel_id))
        except APIException as e:
            logger.error(f"Failed to fetch room data for {server_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching channel for {server_id}: {e}")
        
        return None

    # ==========================================
    # หมวดหมู่ Functions สำหรับจัดหน้าตาข้อความ
    # ==========================================

    async def notify_new_task(self, server_id: int, data: dict):
        """แจ้งเตือนเมื่อมีงานใหม่"""
        channel = await self._get_announcement_channel(server_id)
        if not channel:
            return

        embed = discord.Embed(
            title="📝 มีงานใหม่สั่งเข้ามา!", 
            description="หยิบสมุดจดขึ้นมาเลยพวกเรา!",
            color=discord.Color.green()
        )
        embed.add_field(name="📌 ชื่องาน", value=data.get("task_name"), inline=False)
        embed.add_field(name="📅 กำหนดส่ง", value=data.get("due_date"), inline=True)
        embed.set_footer(text=f"เพิ่มข้อมูลโดย: {data.get('user_name')}")
        
        await channel.send(content="<@&ROLE_ID_EVERYONE>", embed=embed)  # ปรับแก้ Tag @everyone ได้ตามต้องการ

    async def notify_task_done(self, server_id: int, data: dict):
        """แจ้งเตือนเมื่อมีคนส่งงาน (อาจจะส่งเข้าห้องเงียบๆ ไม่ต้อง tag)"""
        channel = await self._get_announcement_channel(server_id)
        if not channel:
            return

        embed = discord.Embed(
            title="✅ มีคนส่งงานแล้ว!",
            description=f"**{data.get('user_name')}** ได้ทำการติ๊กส่งงาน **{data.get('task_name')}** แล้ว",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed)

    async def notify_new_note(self, server_id: int, data: dict):
        """แจ้งเตือนประกาศรายวันใหม่"""
        channel = await self._get_announcement_channel(server_id)
        if not channel:
            return

        embed = discord.Embed(
            title="📌 มีประกาศใหม่เข้าตาราง!", 
            description=f"สำหรับวันที่ {data.get('target_date')}",
            color=discord.Color.gold()
        )
        embed.add_field(name="หัวข้อ", value=data.get("topic"), inline=False)
        embed.set_footer(text=f"ประกาศโดย: {data.get('user_name')}")
        
        await channel.send(embed=embed)