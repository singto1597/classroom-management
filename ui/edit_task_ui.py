import discord
import datetime
from services.api_client import api_client, APIException

class EditTaskModal(discord.ui.Modal, title='✏️ แก้ไขรายละเอียดงาน'):
    # 🚨 ไม่ต้องรับ db แล้ว รับแค่ข้อมูลเก่ามาโชว์ในช่อง
    def __init__(self, task_id: int, old_name: str, old_detail: str, old_date: str):
        super().__init__()
        self.task_id = task_id

        self.task_name = discord.ui.TextInput(
            label='ชื่องาน',
            default=old_name,
            required=True
        )
        self.task_detail = discord.ui.TextInput(
            label='รายละเอียดเพิ่มเติม',
            style=discord.TextStyle.paragraph, 
            default=old_detail if old_detail != "-" else "",
            required=False
        )
        self.due_date = discord.ui.TextInput(
            label='กำหนดส่ง (YYYY-MM-DD)',
            default=str(old_date),
            required=True
        )

        self.add_item(self.task_name)
        self.add_item(self.task_detail)
        self.add_item(self.due_date)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.datetime.strptime(self.due_date.value, "%Y-%m-%d").date()
        except ValueError:
            return await interaction.response.send_message("❌ วันที่ผิด YYYY-MM-DD นะเว้ย", ephemeral=True)

        detail_val = self.task_detail.value if self.task_detail.value.strip() else "-"

        payload = {
            "task_name": self.task_name.value,
            "task_detail": detail_val,
            "due_date": self.due_date.value,
            "user_name": interaction.user.name
        }

        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            await api_client.request("PUT", f"/{interaction.guild_id}/tasks/{self.task_id}", json=payload, headers=headers)
            await interaction.response.send_message(
                f"✅ **อัปเดตงานสำเร็จ!**\n📌 ชื่องาน: {self.task_name.value}\nℹ️ รายละเอียด: {detail_val}\n⏳ ส่งวันที่: {self.due_date.value}"
            )
        except APIException as e:
            await interaction.response.send_message(f"❌ แก้ไขไม่สำเร็จ: {e}", ephemeral=True)