import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
from datetime import timezone, timedelta
import re

# นำเข้า UI Modals (เดี๋ยวเราค่อยไปแก้ไฟล์พวกนี้ให้ยิง API ทีหลัง)
from ui import edit_task_ui
from ui import add_task_ui
from ui import add_note_ui
from ui import set_override_ui

# 🚨 นำเข้าตัวยิง API จากโครงสร้างใหม่ที่เราจะสร้างกัน
from services.api_client import api_client, APIException

THAI_TZ = timezone(timedelta(hours=7))

@app_commands.guild_only()
class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 🚨 ลบ self.db ออกไปแล้ว เพราะเราใช้ api_client แบบ Global แทน
        self.daily_notification.start()
    
    def cog_unload(self):
        self.daily_notification.cancel()

    def parse_date(self, date_str: str):
        try:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def get_thai_day(self, date_obj):
        days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        return days[date_obj.weekday()]

    # ==========================================
    # ระบบ Autocomplete 
    # ==========================================
    async def task_autocomplete(self, interaction: discord.Interaction, current: str):
        server_id = interaction.guild_id
        try:
            # 🚨 ยิง API ขอข้อมูล Tasks
            tasks_data = await api_client.request("GET", f"/{server_id}/tasks", params={"status": "pending"})
            
            choices = []
            for t in tasks_data:
                if current.lower() in t['task_name'].lower():
                    display_name = f"{t['task_name']} (ส่ง {t['due_date']})"
                    if len(display_name) > 100:
                        display_name = display_name[:95] + "..."
                    
                    choices.append(app_commands.Choice(name=display_name, value=t['id']))
            return choices[:25]
        except:
            return []
    
    async def deleted_task_autocomplete(self, interaction: discord.Interaction, current: str):
        server_id = interaction.guild_id
        try:
            tasks_data = await api_client.request("GET", f"/{server_id}/tasks/deleted")
            choices = []
            for t in tasks_data:
                if current.lower() in t['task_name'].lower():
                    # เอาวันที่ลบมาโชว์ด้วย จะได้จำได้
                    deleted_date = t['deleted_at'].split("T")[0] if t.get('deleted_at') else "ไม่ระบุ"
                    display_name = f"🗑️ {t['task_name']} (ลบเมื่อ {deleted_date})"
                    if len(display_name) > 100: display_name = display_name[:95] + "..."
                    choices.append(app_commands.Choice(name=display_name, value=t['id']))
            return choices[:25]
        except:
            return []
    
    # ==========================================
    # ระบบ Loop แจ้งเตือนอัตโนมัติ
    # ==========================================
    @tasks.loop(minutes=1)
    async def daily_notification(self):
        """ฟังก์ชันนี้จะรันเช็คตัวเองทุกๆ 1 นาที"""
        now = datetime.datetime.now(THAI_TZ)
        current_time_str = now.strftime("%H:%M")

        try:
            # 🚨 ยิง API ขอรายชื่อห้องที่ต้องเตือน
            rooms_to_notify = await api_client.request("GET", "/notifications/targets", params={"current_time": current_time_str})
            if not rooms_to_notify: 
                return

            target_date = now.date() + timedelta(days=1)

            for room in rooms_to_notify:
                server_id = room['server_id']
                channel_id = room['announcement_channel_id']
                
                channel = self.bot.get_channel(channel_id)
                if channel:
                    # 🚨 ยิง API ดึงข้อมูล Summary ของพรุ่งนี้
                    data = await api_client.request("GET", f"/{server_id}/summary", params={"target_date": str(target_date)})
                    if data:
                        embed = self.build_summary_embed("🌙 แจ้งเตือนอัตโนมัติ: เตรียมตัวสำหรับวันพรุ่งนี้!", data)
                        await channel.send(content="📢 @everyone สรุปตารางเรียนและงานของวันพรุ่งนี้", embed=embed)
        except Exception as e:
            print(f"⚠️ [Loop Warning] API Error: {e}")
    
    @daily_notification.before_loop
    async def before_daily_notification(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="help", description="ดูคู่มือและคำสั่งทั้งหมดของบอท")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="คู่มือการใช้งาน Classroom-Sync",
            description="บอทผู้ช่วยประจำห้อง พิมพ์ `/` แล้วตามด้วยคำสั่งพวกนี้ได้เลย:",
            color=discord.Color.blue()
        )

        embed.add_field(name="📅 หมวดเช็คตาราง", value=
            "`/today` - ดูตารางเรียนและงานของวันนี้\n"
            "`/tomorrow` - ดูตารางเรียนและงานของวันพรุ่งนี้\n"
            "`/list_tasks` - เช็คงานค้างทั้งหมดของห้อง", inline=False)

        embed.add_field(name="📝 หมวดจัดการงาน", value=
            "`/add_task` - เพิ่มงาน/การบ้านใหม่\n"
            "`/edit_task` - แก้ไขชื่องานหรือวันส่ง\n"
            "`/mark_done` - ติ๊กส่งงาน (จะได้เลิกเตือน)\n"
            "`/delete_task` - ลบงานทิ้งไปเลย\n"
            "`/restore_task` - นำงานที่ลบกลับมา\n"
            
            , inline=False)

        embed.add_field(name="📌 หมวดโน้ตและข้อยกเว้น", value=
            "`/add_note` - โน้ตของที่ต้องเอามา/ประกาศพิเศษ\n"
            "`/delete_note` - ลบโน้ตรายวัน\n"
            "`/set_override` - ตั้งข้อยกเว้นชุดหรือกิจกรรมรายวัน", inline=False)

        embed.add_field(name="⚙️ หมวดตั้งค่าระบบ (แอดมิน)", value=
            "`/setup_room` - ลงทะเบียนห้อง (ทำครั้งแรก)\n"
            "`/set_channel` - เลือกห้องแชทให้บอทส่งแจ้งเตือน\n"
            "`/set_schedule` - ตั้งตารางเรียนยืนพื้นจันทร์-ศุกร์\n"
            "`/set_time` - ตั้งเวลาแจ้งเตือนรายวันอัตโนมัติ", inline=False)

        embed.add_field(name="👥 หมวดข้อมูลนักเรียน ", value=
            "`/sync_me` - ผูกดิสคอร์ดกับเลขที่ (ทำครั้งแรก)\n"
            "`/my_profile` - ดูบัตรนักเรียนและแก้ไขข้อมูลตัวเอง\n"
            "`/search` - ค้นหาดูข้อมูลเพื่อนในห้อง", inline=False)

        embed.add_field(name="👑 สำหรับผู้ดูแลห้อง", value=
            "`/export_students` - ดาวน์โหลดข้อมูลเพื่อนเป็น Excel\n"
            "`/check_incomplete` - เช็คว่าใครยังดองประวัติอยู่บ้าง\n"
            "`/class_list` - ดูรายชื่อเพื่อน\n"
            "`/deactivate` - นำเพื่อนที่ ย้ายห้อง/ลาออก ออก\n"
            "`/activate` - นำเพื่อนที่กดผิดกลับเข้ามา\n\n"
            
            "`/add_student` - เพิ่มเพื่อนเข้าห้อง\n"
            "`/bulk_add` - เพิ่มเพื่อนเข้าห้อง ทีละเยอะๆ\n"
            , inline=False)
        

        embed.set_footer(text="💡 ทริค: หลายคำสั่งมีเมนูให้กดเลือก ไม่ต้องพิมพ์เองทั้งหมดนะ")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==========================================
    # คำสั่งให้แอดมินเปลี่ยนเวลาได้
    # ==========================================
    @app_commands.command(name="set_time", description="ตั้งเวลาแจ้งเตือนรายวัน (ค่าเริ่มต้น 19:00)")
    @app_commands.describe(time_str="ระบุเวลาแบบ 24 ชั่วโมง เช่น 19:00, 20:30")
    async def set_time(self, interaction: discord.Interaction, time_str: str):
        if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", time_str):
            return await interaction.response.send_message("❌ รูปแบบเวลาผิด ต้องเป็น HH:MM เช่น 19:00, 20:30", ephemeral=True)
            
        try:
            payload = {"notify_time": time_str, "user_name": interaction.user.name}
            await api_client.request("PUT", f"/{interaction.guild_id}/time", json=payload)
            await interaction.response.send_message(f"⏰ เปลี่ยนเวลาแจ้งเตือนอัตโนมัติเป็น **{time_str} น.** เรียบร้อยแล้ว!")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    # ==========================================
    # หมวด 1: จัดการห้อง
    # ==========================================
    @app_commands.command(name="setup_room", description="ตั้งค่าบอทและกำหนดชื่อห้องเรียน")
    async def setup_room(self, interaction: discord.Interaction, room_name: str):
        try:
            payload = {"server_id": interaction.guild_id, "room_name": room_name, "user_name": interaction.user.name}
            await api_client.request("POST", "/setup", json=payload)
            await interaction.response.send_message(f"✅ ลงทะเบียนห้อง **{room_name}** สำเร็จ!\n👉 กด `/set_channel` ด้วยนะ")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="set_channel", description="กำหนดห้องแชทที่จะให้บอทแจ้งเตือน")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            payload = {"channel_id": channel.id, "user_name": interaction.user.name}
            await api_client.request("PUT", f"/{interaction.guild_id}/channel", json=payload)
            await interaction.response.send_message(f"📢 ตั้งค่าสำเร็จ! บอทจะแจ้งเตือนที่ห้อง {channel.mention}")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    # ==========================================
    # หมวด 2: ตารางเรียนและข้อยกเว้น
    # ==========================================
    @app_commands.command(name="set_schedule", description="ตั้งตารางเรียนยืนพื้น")
    @app_commands.choices(day=[app_commands.Choice(name=d, value=d) for d in ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์"]])
    async def set_schedule(self, interaction: discord.Interaction, day: app_commands.Choice[str], attire: str, subjects: str):
        try:
            payload = {
                "day_of_week": day.value, 
                "attire": attire, 
                "subjects": subjects, 
                "user_name": interaction.user.name
            }
            await api_client.request("POST", f"/{interaction.guild_id}/schedule/default", json=payload)
            await interaction.response.send_message(f"✅ บันทึกตารางวัน**{day.value}**\n👕 ชุด: {attire}\n📚 วิชา: {subjects}")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="set_override", description="ตั้งค่าข้อยกเว้นฉุกเฉิน")
    async def set_override(self, interaction: discord.Interaction):
        # 🚨 ตัด db ออก ส่งแค่ server_id
        modal = set_override_ui.SetOverrideModal(server_id=interaction.guild_id)
        await interaction.response.send_modal(modal)

    # ==========================================
    # หมวด 3: จัดการงาน 
    # ==========================================
    @app_commands.command(name="add_task", description="เพิ่มงานใหม่")
    async def add_task(self, interaction: discord.Interaction):
        # 🚨 ตัด db ออก ส่งแค่ server_id
        modal = add_task_ui.AddTaskModal(server_id=interaction.guild_id)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="mark_done", description="ติ๊กงานว่าเสร็จแล้ว (มีเมนูให้เลือก)")
    @app_commands.autocomplete(task_id=task_autocomplete)
    async def mark_done(self, interaction: discord.Interaction, task_id: int):
        try:
            payload = {"user_name": interaction.user.name}
            res = await api_client.request("PATCH", f"/{interaction.guild_id}/tasks/{task_id}/done", json=payload)
            await interaction.response.send_message(f"✅ ทำสัญลักษณ์ว่างาน **{res['task_name']}** เสร็จ เรียบร้อยแล้ว!")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="delete_task", description="ลบงานทิ้ง (มีเมนูให้เลือก)")
    @app_commands.autocomplete(task_id=task_autocomplete)
    async def delete_task(self, interaction: discord.Interaction, task_id: int):
        try:
            payload = {"user_name": interaction.user.name}
            res = await api_client.request("DELETE", f"/{interaction.guild_id}/tasks/{task_id}", json=payload)
            await interaction.response.send_message(f"🗑️ ลบงาน **{res['task_name']}** ทิ้งแล้ว")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="restore_task", description="กู้คืนงานที่เผลอลบทิ้งไปจากถังขยะ")
    @app_commands.autocomplete(task_id=deleted_task_autocomplete)
    async def restore_task(self, interaction: discord.Interaction, task_id: int):
        try:
            payload = {"user_name": interaction.user.name}
            res = await api_client.request("PATCH", f"/{interaction.guild_id}/tasks/{task_id}/restore", json=payload)
            await interaction.response.send_message(f"♻️ กู้คืนงาน **{res['task_name']}** กลับมาที่หน้าหลักเรียบร้อยแล้ว!", ephemeral=False)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="list_tasks", description="ดูลิสต์งานทั้งหมดที่ยังไม่เสร็จ")
    async def list_tasks(self, interaction: discord.Interaction):
        try:
            tasks_data = await api_client.request("GET", f"/{interaction.guild_id}/tasks", params={"status": "pending"})
            if not tasks_data: return await interaction.response.send_message("🎉 ไม่มีงานเลยจ้าา")

            embed = discord.Embed(title="📋 รายการงานที่ยังไม่เสร็จ", color=discord.Color.blue())
            for task in tasks_data:
                # API จะส่ง created_at มาเป็น ISO string (เช่น "2026-05-05T12:00:00")
                created_str = task['created_at'].split("T")[0] if task.get('created_at') else "ไม่ระบุ"
                embed.add_field(
                    name=f"📌 {task['task_name']}", 
                    value=f"📅 กำหนดส่ง: {task['due_date']} \nรายละเอียด: {task['task_detail']}\n(บันทึกเมื่อ: {created_str})", 
                    inline=False
                )
            await interaction.response.send_message(embed=embed)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    
    @app_commands.command(name="edit_task", description="แก้ไขชื่องาน หรือ วันกำหนดส่ง (มีป๊อปอัปให้แก้)")
    @app_commands.autocomplete(task_id=task_autocomplete)
    async def edit_task(self, interaction: discord.Interaction, task_id: int):
        try:
            task_data = await api_client.request("GET", f"/{interaction.guild_id}/tasks/{task_id}")
            # 🚨 ตัด db ออก
            modal = edit_task_ui.EditTaskModal(
                task_id=task_id, 
                old_name=task_data['task_name'], 
                old_detail=task_data['task_detail'], 
                old_date=task_data['due_date']
            )
            await interaction.response.send_modal(modal)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    
    # ==========================================
    # หมวด 4: โน้ตรายวัน
    # ==========================================
    @app_commands.command(name="add_note", description="เพิ่มโน้ตรายวัน")
    async def add_note(self, interaction: discord.Interaction):
        # 🚨 ตัด db ออก และแถมส่ง server_id เข้าไปให้ Modal ด้วย เพื่อให้มันยิง API ได้ถูกห้อง
        modal = add_note_ui.AddNoteModal(server_id=interaction.guild_id)
        await interaction.response.send_modal(modal)
        
    @app_commands.command(name="delete_note", description="ลบโน้ตรายวัน")
    async def delete_note(self, interaction: discord.Interaction, date_str: str):
        target_date = self.parse_date(date_str)
        if not target_date: return await interaction.response.send_message("❌ วันที่ผิด", ephemeral=True)

        try:
            payload = {"user_name": interaction.user.name}
            deleted_data = await api_client.request("DELETE", f"/{interaction.guild_id}/notes/{target_date}", json=payload)
            await interaction.response.send_message(f"🗑️ **ลบโน้ตวันที่ {target_date} แล้ว!**\nสิ่งที่ลบไป:\n🎒 {deleted_data['bring_items']}\n📢 {deleted_data['announcement']}")
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    # ==========================================
    # หมวด 5: เรียกดูข้อมูล
    # ==========================================


    def build_summary_embed(self, title, data):
        embed = discord.Embed(title=title, description=f"📅 **วัน{data['day']}ที่ {data['date']}**", color=discord.Color.green())
        embed.add_field(name="👕 ชุดที่ต้องใส่", value=data['attire'], inline=True)
        embed.add_field(name="📚 วิชาเรียน", value=data['subjects'], inline=True)
        
        if data['bring'] != "-": embed.add_field(name="🎒 สิ่งที่ต้องเตรียม", value=data['bring'], inline=False)
        if data['note'] != "-": embed.add_field(name="📢 ประกาศ/หมายเหตุ", value=data['note'], inline=False)
            
        if data['tasks_due']:
            # 🚨 ดึงข้อมูลจาก display_text ที่ Backend จัดเตรียม format สวยๆ มาให้แล้ว
            task_list = "\n".join([t['display_text'] for t in data['tasks_due']])
            if len(task_list) > 1024:
                task_list = task_list[:1000] + "...\n*(และงานอื่นๆ อีกเพียบ ไปเคลียร์ด้วย!)*"
            embed.add_field(name="⚠️ ลิสต์งานค้างทั้งหมด!", value=task_list, inline=False)
        else:
            embed.add_field(name="✅ ลิสต์งานค้างทั้งหมด!", value="ไม่มีงานจ้า", inline=False)
            
        return embed

    @app_commands.command(name="today", description="สรุปข้อมูลทั้งหมดของวันนี้")
    async def today(self, interaction: discord.Interaction):
        target = datetime.datetime.now(THAI_TZ).date()
        try:
            data = await api_client.request("GET", f"/{interaction.guild_id}/summary", params={"target_date": str(target)})
            await interaction.response.send_message(embed=self.build_summary_embed("☀️ สรุปตารางวันนี้", data))
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="tomorrow", description="สรุปข้อมูลทั้งหมดของวันพรุ่งนี้")
    async def tomorrow(self, interaction: discord.Interaction):
        target = datetime.datetime.now(THAI_TZ).date() + timedelta(days=1)
        try:
            data = await api_client.request("GET", f"/{interaction.guild_id}/summary", params={"target_date": str(target)})
            await interaction.response.send_message(embed=self.build_summary_embed("🌙 เตรียมตัวสำหรับวันพรุ่งนี้", data))
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    
    @app_commands.command(name="view_logs", description="(ผู้ดูแล) ดูประวัติการแก้ไขข้อมูลระบบย้อนหลัง 20 รายการ")
    async def view_logs(self, interaction: discord.Interaction):
        try:
            logs = await api_client.request("GET", f"/{interaction.guild_id}/logs")
            if not logs:
                return await interaction.response.send_message("📭 ยังไม่มีประวัติการทำรายการในระบบครับ", ephemeral=True)
            
            embed = discord.Embed(title="📜 ประวัติการทำรายการล่าสุด (Audit Logs)", color=discord.Color.dark_theme())
            text = ""
            for log in logs:
                # จัด Format วันเวลาให้ดูง่ายขึ้น 
                # (API มักจะส่งมาเป็น ISO Format เช่น 2026-05-08T14:30:00.123456)
                dt_parts = log['created_at'].split("T")
                if len(dt_parts) == 2:
                    date_str = dt_parts[0][5:] # เอาแค่เดือนกับวัน (MM-DD)
                    time_str = dt_parts[1][:5] # เอาแค่ชั่วโมงกับนาที (HH:MM)
                    display_time = f"{date_str} {time_str}"
                else:
                    display_time = "Unknown"

                text += f"`[{display_time}]` **{log['user_name']}** ➜ {log['action']}: *{log['detail']}*\n"
            
            embed.description = text
            embed.set_footer(text="ระบบบันทึกทุกความเคลื่อนไหว เพื่อป้องกันข้อมูลสูญหายครับ")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotCommands(bot))