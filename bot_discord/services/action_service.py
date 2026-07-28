import discord
import logging
from services.api_client import api_client, APIException

logger = logging.getLogger("DISCORD_BOT")

class BotActionService:
    def __init__(self, bot):
        self.bot = bot

    async def _get_announcement_channel(self, server_id: int):
        try:
            headers = {"X-Discord-Id": str(self.bot.user.id)}
            # 🚨 แจ้ง Backend ว่าไอดีที่ส่งไปคือ server
            room_data = await api_client.request("GET", f"/{server_id}", params={"target_type": "server"}, headers=headers)
            channel_id = room_data.get("announcement_channel_id")
            if channel_id: return self.bot.get_channel(int(channel_id))
        except Exception as e:
            logger.error(f"Failed fetching channel: {e}")
        return None

    async def notify_new_task(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="📝 แจ้งเตือน: มีการบ้าน/ภาระงานใหม่", 
            description="มีการเพิ่มภาระงานใหม่ลงในระบบ กรุณาตรวจสอบรายละเอียดครับ",
            color=discord.Color.green()
        )
        embed.add_field(name="📌 ชื่องาน", value=data.get("task_name"), inline=False)
        
        task_detail = data.get("task_detail")
        if task_detail and str(task_detail).strip() not in ["", "-"]:
            embed.add_field(name="📄 รายละเอียด", value=task_detail, inline=False)

        embed.add_field(name="📅 กำหนดส่ง", value=data.get("due_date"), inline=True)
        embed.set_footer(text=f"อัปเดตข้อมูลโดย: {data.get('user_name')}")
        
        await channel.send(content="@everyone", embed=embed) 

    async def notify_task_done(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="✅ อัปเดตสถานะงาน",
            description=f"**{data.get('user_name')}** ได้ทำเครื่องหมายว่างาน **{data.get('task_name')}** เสร็จสิ้นแล้ว",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed)

    async def notify_new_note(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="📌 ประกาศใหม่จากระบบ", 
            description=f"ข้อมูลอัปเดตสำหรับวันที่ {data.get('target_date')}",
            color=discord.Color.gold()
        )
        embed.add_field(name="หัวข้อ", value=data.get("topic"), inline=False)
        embed.set_footer(text=f"ประกาศโดย: {data.get('user_name')}")
        
        await channel.send(embed=embed)

    async def notify_custom_message(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title=f"📢 {data.get('title')}", 
            description=data.get("message"),
            color=discord.Color.red()
        )
        embed.set_footer(text=f"ประกาศโดย: {data.get('user_name')} (ระบบประกาศแจ้งเตือน)")
        
        await channel.send(content="@everyone", embed=embed)