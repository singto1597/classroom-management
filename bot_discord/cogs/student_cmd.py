import discord
from discord import app_commands
from discord.ext import commands
from services.api_client import api_client, APIException

class StudentCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync_room", description="ผูก Discord ของคุณเข้ากับรหัสห้องและเลขที่นักเรียน (ทำครั้งแรกครั้งเดียว)")
    async def sync_room(self, interaction: discord.Interaction, room_code: str, student_no: int):
        """Sync Discord account with a classroom using room_code and student_no"""
        await interaction.response.defer(ephemeral=True)
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            payload = {
                "room_code": room_code,
                "student_no": student_no
            }
            # New endpoint POST /discord/sync
            await api_client.request("POST", "/discord/sync", headers=headers, json=payload)
            await interaction.followup.send(
                f"🎉 ผูกบัญชีกับห้อง {room_code} เลขที่ {student_no} สำเร็จ! ลองพิมพ์ `/my_profile` ดูสิ!",
                ephemeral=True
            )
        except APIException as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="my_profile", description="ดูโปรไฟล์ส่วนตัวของคุณ")
    async def my_profile(self, interaction: discord.Interaction):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            # 🚨 แทรก target_id=guild + target_type="server" — backend route คือ /{target_id}/students/me
            data = await api_client.request("GET", f"/{interaction.guild_id}/students/me", params={"target_type": "server"}, headers=headers)

            completion = data.get('data_completion', {})
            percent = completion.get('percentage', 0)
            missing = completion.get('missing_fields', [])

            embed = discord.Embed(
                title=f"💳 บัตรนักเรียน: {data.get('prefix') or ''}{data['first_name']} {data['last_name']} ({data.get('nickname') or '-'})",
                color=discord.Color.gold() if percent == 100 else discord.Color.red()
            )

            embed.add_field(name="เลขที่", value=data['student_no'], inline=True)
            embed.add_field(name="รหัสนักเรียน", value=data.get('student_id') or "-", inline=True)
            embed.add_field(name="วันเกิด", value=data.get('birthday') or "-", inline=True)

            academic_text = (
                f"**บทบาท:** {data.get('class_role')}\n"
                f"**คณะที่ใฝ่ฝัน:** {data.get('target_faculty') or '-'}\n"
                f"**เวรทำความสะอาด:** {data.get('cleaning_duty') or '-'}\n"
                f"**สอวน./ค่าย:** {data.get('olympic_camp') or '-'}\n"
                f"**ผลงาน:** {data.get('portfolio') or '-'}"
            )
            embed.add_field(name="📚 วิชาการและผลงาน", value=academic_text, inline=False)

            health_text = (
                f"**กรุ๊ปเลือด:** {data.get('blood_group') or '-'} | "
                f"**ไซส์เสื้อ:** {data.get('shirt_size') or '-'} | "
                f"**แพ้อาหาร:** {data.get('food_allergy') or '-'} | "
                f"**โรคประจำตัว:** {data.get('congenital_disease') or '-'}"
            )
            embed.add_field(name="🏥 สุขภาพและกายภาพ", value=health_text, inline=False)

            parent_rel = data.get('phone_number_parent_relation') or 'ผู้ปกครอง'
            contact_text = (
                f"**เบอร์โทร:** {data.get('phone_number') or '-'}\n"
                f"**เบอร์{parent_rel}:** {data.get('phone_number_parent') or '-'}\n"
                f"**Line ID:** {data.get('line_id') or '-'}\n"
                f"**IG:** {data.get('ig_username') or '-'}\n"
                f"**Email:** {data.get('email') or '-'}"
            )
            embed.add_field(name="📱 การติดต่อ", value=contact_text, inline=True)

            address_text = (
                f"{data.get('address_house_no') or '-'} ถ.{data.get('address_road') or '-'}\n"
                f"ต.{data.get('address_sub_district') or '-'} อ.{data.get('address_district') or '-'}\n"
                f"จ.{data.get('address_province') or '-'} {data.get('address_post_code') or '-'}"
            )
            embed.add_field(name="🏠 ที่อยู่", value=address_text, inline=True)

            if percent == 100:
                embed.add_field(name="📊 สถานะข้อมูล", value="✅ ครบ 100% ขอบคุณครับ", inline=False)
            else:
                missing_str = ", ".join(missing)
                embed.add_field(name=f"📊 สถานะข้อมูล ({percent}%)", value=f"⚠️ ยังขาดข้อมูล: `{missing_str}`", inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except APIException as e:
            await interaction.response.send_message(f"❌ {e} (ลองพิมพ์ `/sync_room` ก่อนนะ)", ephemeral=True)


async def setup(bot):
    await bot.add_cog(StudentCommands(bot))
