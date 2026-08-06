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

    @staticmethod
    def _build_content(data: dict, fallback: str = "📢 แจ้งเตือน") -> str:
        """สร้างข้อความก่อน embed: 'หมวดหมู่ @everyone' (ถ้า mention) หรือ 'หมวดหมู่' (แค่แจ้งเฉยๆ)"""
        category = data.get("category") or fallback
        if data.get("mention"):
            return f"{category} @everyone"
        return category

    async def notify_new_task(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="📝 มีการบ้าน/ภาระงานใหม่",
            description="มีการเพิ่มภาระงานใหม่ลงในระบบ กรุณาตรวจสอบรายละเอียดครับ",
            color=discord.Color.green()
        )
        embed.add_field(name="📌 ชื่องาน", value=data.get("task_name"), inline=False)

        task_detail = data.get("task_detail")
        if task_detail and str(task_detail).strip() not in ["", "-"]:
            embed.add_field(name="📄 รายละเอียด", value=task_detail, inline=False)

        embed.add_field(name="📅 กำหนดส่ง", value=data.get("due_date"), inline=True)
        embed.set_footer(text=f"อัปเดตข้อมูลโดย: {data.get('user_name')}")

        await channel.send(content=self._build_content(data, "📝 มีงานใหม่นะ"), embed=embed)

    async def notify_task_done(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="✅ อัปเดตสถานะงาน",
            description=f"**{data.get('user_name')}** ได้ทำเครื่องหมายว่างาน **{data.get('task_name')}** เสร็จสิ้นแล้ว",
            color=discord.Color.blue()
        )
        await channel.send(content=self._build_content(data, "✅ ส่งงานแล้ว"), embed=embed)

    async def notify_new_note(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="📌 ประกาศรายวันใหม่",
            description=f"ข้อมูลอัปเดตสำหรับวันที่ {data.get('target_date')}",
            color=discord.Color.gold()
        )
        embed.add_field(name="หัวข้อ", value=data.get("topic"), inline=False)
        embed.set_footer(text=f"ประกาศโดย: {data.get('user_name')}")

        await channel.send(content=self._build_content(data, "📌 ประกาศรายวันนะ"), embed=embed)

    async def notify_custom_message(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title=f"📢 {data.get('title')}",
            description=data.get("message"),
            color=discord.Color.red()
        )
        embed.set_footer(text=f"ประกาศโดย: {data.get('user_name')} (ระบบประกาศแจ้งเตือน)")

        await channel.send(content=self._build_content(data, "📢 ประกาศนะทุกคน"), embed=embed)

    async def notify_finance_transaction(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        txn_type = data.get("txn_type")
        if txn_type == "income":
            emoji, color = "💰", discord.Color.green()
            desc = f"มีรายรับเข้ามา **{float(data.get('amount', 0)):,.2f} บาท**"
        else:
            emoji, color = "💸", discord.Color.red()
            desc = f"มีรายจ่าย **{float(data.get('amount', 0)):,.2f} บาท**"

        embed = discord.Embed(
            title=f"{emoji} รายการเงินใหม่",
            description=desc,
            color=color
        )
        if data.get("description"):
            embed.add_field(name="📄 รายละเอียด", value=data.get("description"), inline=False)
        embed.set_footer(text=f"บันทึกโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "💰 มีรายการเงินใหม่"), embed=embed)

    async def notify_finance_payment(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="✅ มีการชำระเงิน",
            description=f"**{data.get('payer_name')}** จ่ายค่า **{data.get('title')}** จำนวน **{float(data.get('amount', 0)):,.2f} บาท** แล้ว",
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"รับเงินโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "✅ จ่ายเงินแล้ว"), embed=embed)

    async def notify_finance_collection(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="💳 แจ้งเก็บเงิน",
            description=f"**{data.get('title')}** จำนวน **{float(data.get('amount', 0)):,.2f} บาท** ครบกำหนดวันที่ **{data.get('due_date')}**",
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"สร้างโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "💳 แจ้งเก็บเงินนะทุกคน"), embed=embed)

    async def notify_new_student(self, server_id: int, data: dict):
        channel = await self._get_announcement_channel(server_id)
        if not channel: return

        embed = discord.Embed(
            title="👤 มีสมาชิกใหม่",
            description=f"**{data.get('first_name')} {data.get('last_name')}** (เลขที่ {data.get('student_no')}) เข้าสู่ระบบแล้ว",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"เพิ่มโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "👤 มีสมาชิกใหม่"), embed=embed)