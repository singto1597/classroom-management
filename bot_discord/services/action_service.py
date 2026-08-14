import discord
import logging
from services.api_client import api_client, APIException

logger = logging.getLogger("DISCORD_BOT")

class BotActionService:
    def __init__(self, bot):
        self.bot = bot

    async def _get_announcement_channel(self, server_id: int, channel: str = "announcement"):
        """
        หาช่อง Discord ที่จะส่งข้อความ
        - channel="announcement" → ห้องแจ้งเตือนหลัก (announcement_channel_id)
        - channel="birthday" → ห้องแฮปปี้เบิร์ดเดย์ (birthday_channel_id) ถ้าไม่ตั้ง ตกไปใช้ announcement
        - channel="minor" → ห้องแจ้งเตือนงานเล็กๆน้อยๆ (minor_notify_channel_id) ถ้าไม่ตั้ง ตกไปใช้ announcement
        """
        try:
            headers = {"X-Discord-Id": str(self.bot.user.id)}
            # 🚨 แจ้ง Backend ว่าไอดีที่ส่งไปคือ server
            room_data = await api_client.request("GET", f"/{server_id}", params={"target_type": "server"}, headers=headers)

            # เลือกคอลัมน์ช่องตามประเภท ตามลำดับความสำคัญ: ช่องเฉพาะ → ตกไปช่องหลัก
            if channel == "birthday":
                channel_id = room_data.get("birthday_channel_id") or room_data.get("announcement_channel_id")
            elif channel == "minor":
                channel_id = room_data.get("minor_notify_channel_id") or room_data.get("announcement_channel_id")
            else:
                channel_id = room_data.get("announcement_channel_id")

            if channel_id:
                return self.bot.get_channel(int(channel_id))
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
        channel = await self._get_announcement_channel(server_id, channel="minor")
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
        channel = await self._get_announcement_channel(server_id, channel="minor")
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
        channel = await self._get_announcement_channel(server_id, channel="minor")
        if not channel: return

        # ✨ Batch (ปลดหนี้หลายรายการครั้งเดียว) → embed สรุปทีเดียว ไม่เด้งหลายรอบ
        items = data.get("items")
        if items:
            lines = "\n".join(
                f"• **{item.get('title')}** — {float(item.get('amount', 0)):,.2f} บาท"
                for item in items
            )
            count = data.get("count") or len(items)
            embed = discord.Embed(
                title="✅ รับเงินรวบยอด",
                description=f"**{data.get('payer_name')}** ชำระเงินแล้ว **{count}** รายการ รวม **{float(data.get('total_amount', 0)):,.2f} บาท**",
                color=discord.Color.teal()
            )
            embed.add_field(name="📄 รายการที่ชำระ", value=lines, inline=False)
            embed.set_footer(text=f"รับเงินโดย: {data.get('user_name')}")
            await channel.send(content=self._build_content(data, "✅ จ่ายเงินแล้ว"), embed=embed)
            return

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
        channel = await self._get_announcement_channel(server_id, channel="minor")
        if not channel: return

        embed = discord.Embed(
            title="👤 มีสมาชิกใหม่",
            description=f"**{data.get('first_name')} {data.get('last_name')}** (เลขที่ {data.get('student_no')}) เข้าสู่ระบบแล้ว",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"เพิ่มโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "👤 มีสมาชิกใหม่"), embed=embed)

    async def notify_new_activity(self, server_id: int, data: dict):
        """
        🎪 กิจกรรมใหม่ (NEW_ACTIVITY) — render embed จาก metadata ได้อย่างเต็มที่
        - location_url → ลิงก์ Google Maps
        - agenda (list/str) → กำหนดการคร่าว ๆ วนลูป
        - tags → badge หมวดหมู่
        """
        channel = await self._get_announcement_channel(server_id)
        if not channel:
            return

        meta = data.get("metadata") or {}
        title = data.get("title", "กิจกรรมใหม่")
        embed = discord.Embed(
            title=f"📢 กิจกรรมใหม่: {title}",
            description=f"วันที่ {data.get('activity_date')} · ⏱️ ชั่วโมงจิตอาสา: {data.get('base_hours', 0)} ชม.",
            color=discord.Color.purple(),
        )

        # 📍 สถานที่ (location_url / location_name จาก metadata)
        location_url = meta.get("location_url")
        location_name = meta.get("location_name")
        if location_url or location_name:
            location_text = ""
            if location_name:
                location_text += f"**{location_name}**"
            if location_url:
                maps_label = "คลิกเพื่อดู Google Maps"
                if isinstance(location_url, str) and not location_url.startswith("http"):
                    maps_label = f"ดู {location_url}"
                    location_url = f"https://www.google.com/maps/search/?api=1&query={location_url}"
                link_text = f"[{maps_label}]({location_url})"
                location_text = f"{location_text} {link_text}".strip()
            embed.add_field(name="📍 สถานที่", value=location_text, inline=False)

        # 📋 กำหนดการคร่าว ๆ (agenda จาก metadata — list หรือ string คั่น |)
        agenda = meta.get("agenda")
        if agenda:
            if isinstance(agenda, list):
                agenda_lines = "\n".join(f"• {str(item).strip()}" for item in agenda if str(item).strip())
            else:
                agenda_lines = "\n".join(f"• {item.strip()}" for item in str(agenda).split("|") if item.strip())
            if agenda_lines:
                embed.add_field(name="📋 กำหนดการคร่าว ๆ", value=agenda_lines[:1024], inline=False)

        # 🏷️ แท็กหมวดหมู่ (tags จาก metadata)
        tags = meta.get("tags")
        if tags:
            if isinstance(tags, list):
                tag_str = " · ".join(f"#{str(t)}" for t in tags if str(t).strip())
            else:
                tag_str = " · ".join(f"#{t.strip()}" for t in str(tags).split(",") if t.strip())
            if tag_str:
                embed.add_field(name="🏷️ หมวดหมู่", value=tag_str, inline=False)

        # 👥 ผู้เข้าร่วม
        participant_count = data.get("participant_count", 0)
        embed.add_field(
            name="👥 ผู้เข้าร่วม",
            value=f"**{participant_count} คน** — เช็คหน้าที่และเบอร์สแตนด์เชียร์ของตัวเองได้ที่หน้าเว็บ!",
            inline=False,
        )

        embed.set_footer(text=f"สร้างกิจกรรมโดย: {data.get('user_name')}")
        await channel.send(content=self._build_content(data, "🎪 มีกิจกรรมใหม่นะ"), embed=embed)

    async def notify_birthday(self, server_id: int, data: dict):
        """🎂 ส่งคำอวยพรวันเกิดไปที่ห้องแฮปปี้เบิร์ดเดย์ (ถ้าไม่ตั้ง → ห้องแจ้งเตือนหลัก)"""
        channel = await self._get_announcement_channel(server_id, channel="birthday")
        if not channel: return

        celebrants = data.get("celebrants") or []
        names = "\n".join(
            f"🎉 **{c.get('first_name')} {c.get('last_name')}** (เลขที่ {c.get('student_no')})"
            for c in celebrants
        )

        embed = discord.Embed(
            title="🎂 Happy Birthday! 🎉",
            description=f"สุขสันต์วันเกิดนะครับ/ค่ะ\n{names}\n\nขอให้มีความสุขมากๆ สมหวังในทุกสิ่งที่ปรารถนา 🥳🎈",
            color=discord.Color.pink()
        )
        await channel.send(content="🎂 🎉", embed=embed)