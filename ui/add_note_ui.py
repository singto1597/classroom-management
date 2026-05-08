import discord
import datetime
from datetime import timezone, timedelta
from services.api_client import api_client, APIException # 🚨 นำเข้าตัวยิง API

THAI_TZ = timezone(timedelta(hours=7))

class AddNoteModal(discord.ui.Modal, title='📝 เพิ่มโน้ตใหม่'):
    # 🚨 ไม่ต้องรับ db แล้ว (รับแค่ server_id เผื่อไว้ หรือจะใช้ interaction.guild_id ตอน submit ก็ได้)
    def __init__(self, server_id: int = None):
        super().__init__()
        self.server_id = server_id

        tomorrow_str = (datetime.datetime.now(THAI_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

        self.target_date = discord.ui.TextInput(
            label='วันที่ต้องการเพิ่ม (YYYY-MM-DD)',
            default=tomorrow_str,
            required=True
        )
        self.bring_items = discord.ui.TextInput(
            label='ของที่ต้องนำมา',
            style=discord.TextStyle.paragraph, 
            default="-",
            required=False
        )
        self.announcement = discord.ui.TextInput(
            label='โน้ตที่อยากแจ้งให้ทราบ',
            style=discord.TextStyle.paragraph, 
            default="-",
            required=False
        )

        self.add_item(self.target_date)
        self.add_item(self.bring_items)
        self.add_item(self.announcement)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # เช็ค Format วันที่คร่าวๆ ฝั่ง Client
            datetime.datetime.strptime(self.target_date.value, "%Y-%m-%d").date()
        except ValueError:
            return await interaction.response.send_message("❌ วันที่ผิด YYYY-MM-DD นะ", ephemeral=True)

        bring_items = self.bring_items.value if self.bring_items.value.strip() else "-"
        announcement = self.announcement.value if self.announcement.value.strip() else "-"
        guild_id = self.server_id or interaction.guild_id

        # 🚨 เตรียม JSON Payload ตาม Schema ของ Backend
        payload = {
            "target_date": self.target_date.value,
            "bring_items": bring_items,
            "announcement": announcement,
            "user_name": interaction.user.name
        }

        try:
            # 🚨 ยิง API ไปให้ FastAPI จัดการ
            await api_client.request("POST", f"/{guild_id}/notes", json=payload)
            await interaction.response.send_message(
                f"📌 **บันทึกโน้ตวันที่ {self.target_date.value}**\n🎒 ให้เตรียม: {bring_items}\n📢 โน้ต: {announcement}"
            )
        except APIException as e:
            # ดัก Error จาก Backend มาโชว์
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)