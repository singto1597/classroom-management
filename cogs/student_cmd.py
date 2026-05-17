import discord
from discord import app_commands
from discord.ext import commands
from services.api_client import api_client, APIException
from ui.student_ui import QuickAddModal, BulkAddModal, ProfileView
import re

@app_commands.guild_only()
class StudentCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ระบบดักจับข้อความประกาศ (อ่านทุกคน)
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # บอทจะไม่คุยกับตัวเอง
        if message.author == self.bot.user:
            return

        text = message.content
        
        # เช็คแค่ว่ามีคีย์เวิร์ดพวกนี้อยู่ในข้อความมั้ย (ไม่ต้องสนว่าเป็นบอทหรือคนพิมพ์)
        if "ประกาศใหม่" in text and "หัวข้อ:" in text and "กำหนดส่ง" in text:
            try:
                # 🧹 ทริคเด็ด: ล้างพวกสัญลักษณ์ตัวหนา (**) ออกให้หมด จะได้จับ Regex ง่ายๆ
                clean_text = text.replace('*', '')

                # ใช้ Regex จับข้อมูล โดยไม่ต้องสนอิโมจิด้านหน้า
                topic_match = re.search(r"หัวข้อ:\s*(.+)", clean_text)
                type_match = re.search(r"ประเภท:\s*(.+)", clean_text)
                
                # รายละเอียดอาจมีหลายบรรทัด ให้กวาดจนกว่าจะเจอคำว่า กำหนดส่ง
                detail_match = re.search(r"รายละเอียด:\s*(.*?)(?=\n.*?กำหนดส่ง/วันที่:|$)", clean_text, re.DOTALL)
                date_match = re.search(r"กำหนดส่ง/วันที่:\s*(\d{2}/\d{2}/\d{4})", clean_text)

                # ถ้าจับข้อมูลที่จำเป็นได้ไม่ครบ ให้ปล่อยผ่านไป
                if not (topic_match and type_match and detail_match and date_match):
                    return

                topic = topic_match.group(1).strip()
                msg_type = type_match.group(1).strip()
                detail = detail_match.group(1).strip()
                date_str = date_match.group(1).strip()
                
                d, m, y = date_str.split('/')
                db_date = f"{y}-{m}-{d}"

                server_id = message.guild.id
                
                # บันทึกชื่อคนที่พิมพ์ประกาศจริงๆ (ถ้าบอทพิมพ์ ก็จะเป็นชื่อบอท)
                payload = {"user_name": str(message.author.name)}

                try:
                    room_data = await api_client.request("GET", f"/{server_id}")
                    main_channel_id = room_data.get('announcement_channel_id')
                    main_channel = self.bot.get_channel(main_channel_id) if main_channel_id else None
                except:
                    main_channel = None

                # 📝 ลอจิกแยกประเภท: งาน vs ประกาศทั่วไป
                if "งาน" in msg_type or "การบ้าน" in msg_type:
                    payload.update({
                        "task_name": topic,
                        "task_detail": detail,
                        "due_date": db_date
                    })
                    await api_client.request("POST", f"/{server_id}/tasks", json=payload)
                    await message.add_reaction("✅") 

                    # ถ้ามีช่องประกาศหลัก และไม่ได้สั่งจากช่องนั้น ให้ไปตะโกนบอก
                    if main_channel and message.channel.id != main_channel_id:
                        embed = discord.Embed(title="🚨 มีงานใหม่เข้าตาราง!", description=f"ดึงงานเข้าตารางให้เรียบร้อยแล้ว ไม่ต้องเหนื่อยพิมพ์!", color=discord.Color.green())
                        embed.add_field(name="📌 ชื่องาน", value=topic, inline=False)
                        embed.add_field(name="📅 กำหนดส่ง", value=f"{d}/{m}/{y}", inline=True)
                        await main_channel.send(content="<@&ROLE_ID_EVERYONE> เห้ยพวกมึง!", embed=embed)

                else: # ถ้าเป็นประกาศทั่วไป (แจ้งเตือนพิเศษ)
                    payload.update({
                        "target_date": db_date,
                        "bring_items": "-", 
                        "announcement": f"[{topic}] {detail}"
                    })
                    await api_client.request("POST", f"/{server_id}/notes", json=payload)
                    await message.add_reaction("📌") 

                    if main_channel and message.channel.id != main_channel_id:
                        embed = discord.Embed(title="📌 มีประกาศใหม่เข้าตาราง!", description=f"อัปเดตโน้ตรายวันให้แล้ว เข้าไปดูตารางพรุ่งนี้ได้เลย!", color=discord.Color.gold())
                        embed.add_field(name="หัวข้อ", value=topic, inline=False)
                        await main_channel.send(embed=embed)

            except Exception as e:
                print(f"⚠️ กวาดข้อมูลจากข้อความไม่สำเร็จ: {e}")

    @app_commands.command(name="sync_me", description="ผูก Discord ของคุณเข้ากับเลขที่นักเรียน (ทำครั้งแรกครั้งเดียว)")
    async def sync_me(self, interaction: discord.Interaction, student_no: int):
        try:
            payload = {
                "student_no": student_no,
                "discord_id": interaction.user.id, # ส่ง ID ของ Discord ยูสเซอร์ไป
                "user_name": interaction.user.name
            }
            await api_client.request("POST", f"/{interaction.guild_id}/students/sync", json=payload)
            await interaction.response.send_message(f"🎉 ผูกบัญชีกับเลขที่ {student_no} สำเร็จ! ลองพิมพ์ `/my_profile` ดูสิ!", ephemeral=True)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="my_profile", description="ดูบัตรประจำตัวและอัปเดตข้อมูลของคุณ")
    async def my_profile(self, interaction: discord.Interaction):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            data = await api_client.request("GET", f"/{interaction.guild_id}/students/me", headers=headers)
            
            completion = data.get('data_completion', {})
            percent = completion.get('percentage', 0)
            missing = completion.get('missing_fields', [])

            # จัดการสีขอบบัตรตามความสมบูรณ์
            embed = discord.Embed(
                title=f"💳 บัตรนักเรียน: {data.get('prefix') or ''}{data['first_name']} {data['last_name']} ({data.get('nickname') or '-'})",
                color=discord.Color.gold() if percent == 100 else discord.Color.red()
            )
            
            # บรรทัดบนสุด: ข้อมูลหลัก
            embed.add_field(name="เลขที่", value=data['student_no'], inline=True)
            embed.add_field(name="รหัสนักเรียน", value=data.get('student_id') or "-", inline=True)
            embed.add_field(name="วันเกิด", value=data.get('birthday') or "-", inline=True)

            # หมวด: หน้าที่และผลงาน
            academic_text = (
                f"**บทบาท:** {data.get('class_role')}\n"
                f"**คณะที่ใฝ่ฝัน:** {data.get('target_faculty') or '-'}\n"
                f"**เวรทำความสะอาด:** {data.get('cleaning_duty') or '-'}\n"
                f"**สอวน./ค่าย:** {data.get('olympic_camp') or '-'}\n"
                f"**ผลงาน:** {data.get('portfolio') or '-'}"
            )
            embed.add_field(name="📚 วิชาการและผลงาน", value=academic_text, inline=False)

            # หมวด: สุขภาพ
            health_text = (
                f"**กรุ๊ปเลือด:** {data.get('blood_group') or '-'} | "
                f"**ไซส์เสื้อ:** {data.get('shirt_size') or '-'} | "
                f"**แพ้อาหาร:** {data.get('food_allergy') or '-'} | "
                f"**โรคประจำตัว:** {data.get('congenital_disease') or '-'}"
            )
            embed.add_field(name="🏥 สุขภาพและกายภาพ", value=health_text, inline=False)

            # หมวด: ช่องทางติดต่อ
            parent_rel = data.get('phone_number_parent_relation') or 'ผู้ปกครอง'
            contact_text = (
                f"**เบอร์โทร:** {data.get('phone_number') or '-'}\n"
                f"**เบอร์{parent_rel}:** {data.get('phone_number_parent') or '-'}\n"
                f"**Line ID:** {data.get('line_id') or '-'}\n"
                f"**IG:** {data.get('ig_username') or '-'}\n"
                f"**Email:** {data.get('email') or '-'}"
            )
            embed.add_field(name="📱 การติดต่อ", value=contact_text, inline=True)

            # หมวด: ที่อยู่
            address_text = (
                f"{data.get('address_house_no') or '-'} ถ.{data.get('address_road') or '-'}\n"
                f"ต.{data.get('address_sub_district') or '-'} อ.{data.get('address_district') or '-'}\n"
                f"จ.{data.get('address_province') or '-'} {data.get('address_post_code') or '-'}"
            )
            embed.add_field(name="🏠 ที่อยู่", value=address_text, inline=True)

            # โชว์ความคืบหน้าด้านล่างสุด
            if percent == 100:
                embed.add_field(name="📊 สถานะข้อมูล", value="✅ ครบ 100% ขอบคุณครับ", inline=False)
            else:
                missing_str = ", ".join(missing)
                embed.add_field(name=f"📊 สถานะข้อมูล ({percent}%)", value=f"⚠️ ยังขาดข้อมูล: `{missing_str}`", inline=False)

            # แนบ Dropdown
            from ui.student_ui import ProfileView
            view = ProfileView(interaction.guild_id, data['student_no'], data)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except APIException as e:
            await interaction.response.send_message(f"❌ {e} (ลองพิมพ์ `/sync_me` ก่อนนะ)", ephemeral=True)
        
    @app_commands.command(name="add_student", description="(แอดมิน) เพิ่มนักเรียนใหม่แบบด่วน")
    async def add_student(self, interaction: discord.Interaction):
        await interaction.response.send_modal(QuickAddModal(interaction.guild_id))

    @app_commands.command(name="bulk_add", description="(แอดมิน) เพิ่มนักเรียนรวดเดียวจาก Excel")
    async def bulk_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BulkAddModal(interaction.guild_id))

    @app_commands.command(name="class_list", description="(หัวหน้า) เช็คสถานะการกรอกข้อมูลของเพื่อนทั้งห้อง")
    async def class_list(self, interaction: discord.Interaction):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            students = await api_client.request("GET", f"/{interaction.guild_id}/students", headers=headers)
            
            embed = discord.Embed(title="📋 รายงานสถานะการกรอกข้อมูลทั้งห้อง", color=discord.Color.blue())
            
            text = ""
            for s in students:
                percent = s.get('data_completion', {}).get('percentage', 0)
                icon = "✅" if percent == 100 else "⚠️"
                text += f"`เลขที่ {s['student_no']:02d}` | {icon} {percent}% | {s['first_name']}\n"
                
                if len(text) > 900:
                    embed.add_field(name="รายชื่อ", value=text, inline=False)
                    text = ""
            
            if text:
                embed.add_field(name="รายชื่อ (ต่อ)", value=text, inline=False)
                
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    
    async def student_search_autocomplete(self, interaction: discord.Interaction, current: str):
        if len(current) < 1: return []
        try:
            results = await api_client.request("GET", f"/{interaction.guild_id}/search", params={"q": current})
            choices = []
            for r in results:
                name = f"เลขที่ {r['student_no']} | {r['first_name']} {r['last_name']} ({r.get('nickname') or '-'})"
                choices.append(app_commands.Choice(name=name, value=r['student_no']))
            return choices[:25] 
        except:
            return []
    
    @app_commands.command(name="search", description="ค้นหาและดูโปรไฟล์เพื่อนในห้อง")
    @app_commands.autocomplete(student_no=student_search_autocomplete)
    async def search_student(self, interaction: discord.Interaction, student_no: int):
        try:
            results = await api_client.request("GET", f"/{interaction.guild_id}/search", params={"q": str(student_no)})
            if not results:
                return await interaction.response.send_message("❌ ไม่พบข้อมูลนักเรียนคนนี้ หรืออาจจะย้ายออกไปแล้ว", ephemeral=True)
            
            data = results[0] 
            
            embed = discord.Embed(
                title=f"🔎 ข้อมูลของ: {data.get('prefix') or ''}{data['first_name']} {data['last_name']}",
                color=discord.Color.blue()
            )
            embed.add_field(name="เลขที่", value=data['student_no'], inline=True)
            embed.add_field(name="ชื่อเล่น", value=data.get('nickname') or "-", inline=True)
            embed.add_field(name="เบอร์โทร", value=data.get('phone_number') or "-", inline=True)
            embed.add_field(name="LINE ID", value=data.get('line_id') or "-", inline=True)
            embed.add_field(name="IG", value=data.get('ig_username') or "-", inline=True)
            embed.add_field(name="คณะที่ใฝ่ฝัน", value=data.get('target_faculty') or "-", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="deactivate", description="(หัวหน้า) จำหน่ายเพื่อนออกจากห้อง (ย้าย/ลาออก)")
    @app_commands.autocomplete(student_no=student_search_autocomplete)
    async def deactivate_student(self, interaction: discord.Interaction, student_no: int):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            payload = {"status": "inactive", "user_name": interaction.user.name}
            
            await api_client.request("PATCH", f"/{interaction.guild_id}/students/{student_no}/status", headers=headers, json=payload)
            await interaction.response.send_message(f"✅ นำเลขที่ **{student_no}** ออกจากรายชื่อปัจจุบันเรียบร้อยแล้ว (ข้อมูลถูกซ่อนไว้ ไม่ถูกลบ)", ephemeral=True)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e} (คุณไม่มีสิทธิ์ที่จะนำเพื่อนออก)", ephemeral=True)

    @app_commands.command(name="activate", description="(หัวหน้า) จำหน่ายเพื่อนกลับเข้าห้อง (เช่น กดผิด)")
    async def activate_student(self, interaction: discord.Interaction, student_no: int):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            payload = {"status": "active", "user_name": interaction.user.name}
            
            await api_client.request("PATCH", f"/{interaction.guild_id}/students/{student_no}/status", headers=headers, json=payload)
            await interaction.response.send_message(f"✅ นำเลขที่ **{student_no}** เข้ารายชื่อปัจจุบันเรียบร้อยแล้ว", ephemeral=True)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e} (คุณไม่มีสิทธิ์ที่จะนำเพื่อนเข้า)", ephemeral=True)

    @app_commands.command(name="export_students", description="(หัวหน้า) ดาวน์โหลดข้อมูลเพื่อนเป็นไฟล์ Excel")
    async def export_students(self, interaction: discord.Interaction):
        from ui.student_ui import ExportSelectView
        await interaction.response.send_message("📊 **เลือกหมวดหมู่ข้อมูลที่ต้องการ Export ลง Excel:**\n*(สามารถติ๊กได้หลายอัน หากติ๊กเสร็จ ให้กดที่ว่างเปล่าข้างแชท)*", view=ExportSelectView(interaction.guild_id), ephemeral=True)

    @app_commands.command(name="check_incomplete", description="(หัวหน้า) ดูรายชื่อคนที่ยังกรอกข้อมูลโปรไฟล์ไม่ครบ")
    async def check_incomplete(self, interaction: discord.Interaction):
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            students = await api_client.request("GET", f"/{interaction.guild_id}/students", headers=headers)
            
            incomplete = [s for s in students if s.get('data_completion', {}).get('percentage', 0) < 100]
            
            if not incomplete:
                return await interaction.response.send_message("🎉 ทุกคนในห้องกรอกข้อมูลครบ 100% หมดแล้ว!", ephemeral=True)

            embed = discord.Embed(title="⚠️ รายชื่อคนดองประวัติ (กรอกไม่ครบ 100%)", color=discord.Color.orange())
            text = ""
            for s in incomplete:
                percent = s.get('data_completion', {}).get('percentage', 0)
                text += f"`เลขที่ {s['student_no']:02d}` | ความคืบหน้า: **{percent}%** | {s['first_name']}\n"
            
            embed.description = text
            embed.set_footer(text="ไปตามได้เลยครับ!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(StudentCommands(bot))