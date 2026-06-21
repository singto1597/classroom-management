import discord
import datetime
from datetime import timezone, timedelta
from services.api_client import api_client, APIException

THAI_TZ = timezone(timedelta(hours=7))

class AddTaskModal(discord.ui.Modal, title='📝 เพิ่มงาน/การบ้านใหม่'):
    def __init__(self, server_id: int):
        super().__init__()
        self.server_id = server_id

        tomorrow_str = (datetime.datetime.now(THAI_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

        self.task_name = discord.ui.TextInput(
            label='ชื่องาน',
            required=True
        )
        self.task_detail = discord.ui.TextInput(
            label='รายละเอียดเพิ่มเติม',
            style=discord.TextStyle.paragraph, 
            default="-",
            required=False
        )
        self.due_date = discord.ui.TextInput(
            label='กำหนดส่ง (YYYY-MM-DD)',
            default=tomorrow_str,
            required=True
        )

        self.add_item(self.task_name)
        self.add_item(self.task_detail)
        self.add_item(self.due_date)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.datetime.strptime(self.due_date.value, "%Y-%m-%d").date()
        except ValueError:
            return await interaction.response.send_message("❌ วันที่ผิด YYYY-MM-DD นะ", ephemeral=True)

        detail_val = self.task_detail.value if self.task_detail.value.strip() else "-"

        payload = {
            "task_name": self.task_name.value,
            "task_detail": detail_val,
            "due_date": self.due_date.value,
            "user_name": interaction.user.name
        }

        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            # 🚨 แทรก target_type="server"
            await api_client.request("POST", f"/{self.server_id}/tasks", params={"target_type": "server"}, json=payload, headers=headers)
            await interaction.response.send_message(
                f"📝 **เพิ่มงานใหม่:** {self.task_name.value}\n"
                f"ℹ️ **รายละเอียด:** {detail_val}\n"
                f"⏳ **กำหนดส่ง:** {self.due_date.value}"
            )
        except APIException as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)