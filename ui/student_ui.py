import io
import discord
from services.api_client import api_client, APIException
from core.config import API_BASE_URL

class QuickAddModal(discord.ui.Modal, title='👤 เพิ่มนักเรียนใหม่ (ด่วน)'):
    def __init__(self, server_id: int):
        super().__init__()
        self.server_id = server_id
        
        self.student_no = discord.ui.TextInput(label='เลขที่', required=True)
        self.first_name = discord.ui.TextInput(label='ชื่อจริง (ไม่ต้องใส่ ด.ช./นาย)', required=True)
        self.last_name = discord.ui.TextInput(label='นามสกุล', required=True)
        
        self.add_item(self.student_no)
        self.add_item(self.first_name)
        self.add_item(self.last_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            payload = {
                "student_no": int(self.student_no.value),
                "first_name": self.first_name.value.strip(),
                "last_name": self.last_name.value.strip(),
                "user_name": interaction.user.name
            }
            await api_client.request("POST", f"/{self.server_id}/students", json=payload)
            await interaction.response.send_message(f"✅ เพิ่มเลขที่ {self.student_no.value} สำเร็จ!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ เลขที่ต้องเป็นตัวเลขเท่านั้น!", ephemeral=True)
        except APIException as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

class BulkAddModal(discord.ui.Modal, title='🚀 เพิ่มนักเรียน (ก๊อปวางจาก Excel)'):
    def __init__(self, server_id: int):
        super().__init__()
        self.server_id = server_id
        
        self.bulk_data = discord.ui.TextInput(
            label='รูปแบบ: เลขที่,ชื่อ,นามสกุล (บรรทัดละคน)',
            style=discord.TextStyle.paragraph,
            placeholder="1,สมชาย,ใจดี\n2,สมหญิง,รักเรียน",
            required=True
        )
        self.add_item(self.bulk_data)

    async def on_submit(self, interaction: discord.Interaction):
        lines = self.bulk_data.value.strip().split('\n')
        students = []
        try:
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 3:
                    students.append({
                        "student_no": int(parts[0].strip()),
                        "first_name": parts[1].strip(),
                        "last_name": parts[2].strip()
                    })
            
            payload = {"students": students, "user_name": interaction.user.name}
            await api_client.request("POST", f"/{self.server_id}/students/bulk", json=payload)
            await interaction.response.send_message(f"✅ เพิ่มข้อมูลรวดเดียว {len(students)} คน สำเร็จ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ รูปแบบข้อมูลผิดพลาด เช็คลูกน้ำ (,) ให้ดีนะ", ephemeral=True)


class EditBaseModal(discord.ui.Modal):
    """คลาสแม่ เอาไว้เก็บลอจิกยิง API ตอนกด Save"""
    def __init__(self, title, server_id, student_no):
        super().__init__(title=title)
        self.server_id = server_id
        self.student_no = student_no

    async def save_data(self, interaction: discord.Interaction, payload: dict):
        await interaction.response.defer(ephemeral=True)
        
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            await api_client.request("PATCH", f"/{self.server_id}/students/{self.student_no}", headers=headers, json=payload)
            
            await interaction.followup.send("✅ อัปเดตข้อมูลสำเร็จ! พิมพ์ `/my_profile` เพื่อดูข้อมูลล่าสุด", ephemeral=True)
        except APIException as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

class EditCoreModal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🔵 ข้อมูลส่วนตัว', server_id, student_no)
        self.student_id = discord.ui.TextInput(label='รหัสนักเรียน', default=data.get('student_id', ''), required=False)
        self.prefix = discord.ui.TextInput(label='คำนำหน้า (นาย/นางสาว)', default=data.get('prefix', ''), required=False)
        self.nickname = discord.ui.TextInput(label='ชื่อเล่น', default=data.get('nickname', ''), required=False)
        self.birthday = discord.ui.TextInput(label='วันเกิด (YYYY-MM-DD)', default=data.get('birthday', ''), required=False)
        self.email = discord.ui.TextInput(label='อีเมล', default=data.get('email', ''), required=False)
        
        for item in [self.student_id, self.prefix, self.nickname, self.birthday, self.email]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "student_id": self.student_id.value or None,
            "prefix": self.prefix.value or None,
            "nickname": self.nickname.value or None,
            "birthday": self.birthday.value or None,
            "email": self.email.value or None
        }
        await self.save_data(interaction, payload)

class EditAcademicModal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🟡 ข้อมูลวิชาการและผลงาน', server_id, student_no)
        
        self.duty = discord.ui.TextInput(label='หน้าที่เวรทำความสะอาด', default=data.get('cleaning_duty', ''), required=False)
        self.faculty = discord.ui.TextInput(label='คณะที่ใฝ่ฝัน', default=data.get('target_faculty', ''), required=False)
        
        self.camp = discord.ui.TextInput(label='ค่าย สอวน. / ค่ายวิชาการ', style=discord.TextStyle.paragraph, default=data.get('olympic_camp', ''), required=False)
        self.portfolio = discord.ui.TextInput(label='ผลงาน / รางวัลที่เคยได้รับ', style=discord.TextStyle.paragraph, default=data.get('portfolio', ''), required=False)
        
        for item in [self.duty, self.faculty, self.camp, self.portfolio]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "cleaning_duty": self.duty.value or None,
            "target_faculty": self.faculty.value or None,
            "olympic_camp": self.camp.value or None,
            "portfolio": self.portfolio.value or None
        }
        await self.save_data(interaction, payload)

class EditHealthModal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🔴 สุขภาพและกายภาพ', server_id, student_no)
        self.blood = discord.ui.TextInput(label='กรุ๊ปเลือด (A, B, AB, O)', default=data.get('blood_group', ''), required=False)
        self.shirt = discord.ui.TextInput(label='ไซส์เสื้อ', default=data.get('shirt_size', ''), required=False)
        self.allergy = discord.ui.TextInput(label='แพ้อาหาร (ไม่มีให้ขีด -)', default=data.get('food_allergy', ''), required=False)
        self.disease = discord.ui.TextInput(label='โรคประจำตัว (ไม่มีให้ขีด -)', default=data.get('congenital_disease', ''), required=False)
        
        for item in [self.blood, self.shirt, self.allergy, self.disease]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "blood_group": self.blood.value or None,
            "shirt_size": self.shirt.value or None,
            "food_allergy": self.allergy.value or None,
            "congenital_disease": self.disease.value or None
        }
        await self.save_data(interaction, payload)

class EditContactModal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🟣 ข้อมูลการติดต่อ', server_id, student_no)
        self.phone = discord.ui.TextInput(label='เบอร์โทรศัพท์มือถือ', default=data.get('phone_number', ''), required=False)
        self.p_phone = discord.ui.TextInput(label='เบอร์โทรผู้ปกครอง', default=data.get('phone_number_parent', ''), required=False)
        self.p_rel = discord.ui.TextInput(label='เกี่ยวข้องเป็น (พ่อ/แม่/ญาติ)', default=data.get('phone_number_parent_relation', ''), required=False)
        self.line = discord.ui.TextInput(label='Line ID', default=data.get('line_id', ''), required=False)
        self.ig = discord.ui.TextInput(label='IG Username', default=data.get('ig_username', ''), required=False)
        
        for item in [self.phone, self.p_phone, self.p_rel, self.line, self.ig]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "phone_number": self.phone.value or None,
            "phone_number_parent": self.p_phone.value or None,
            "phone_number_parent_relation": self.p_rel.value or None,
            "line_id": self.line.value or None,
            "ig_username": self.ig.value or None
        }
        await self.save_data(interaction, payload)

class EditAddress1Modal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🟤 ข้อมูลที่อยู่ (ส่วนที่ 1)', server_id, student_no)
        self.house_no = discord.ui.TextInput(label='บ้านเลขที่/หมู่/ซอย', default=data.get('address_house_no', ''), required=False)
        self.road = discord.ui.TextInput(label='ถนน', default=data.get('address_road', ''), required=False)
        
        for item in [self.house_no, self.road]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "address_house_no": self.house_no.value or None,
            "address_road": self.road.value or None
        }
        await self.save_data(interaction, payload)

class EditAddress2Modal(EditBaseModal):
    def __init__(self, server_id, student_no, data):
        super().__init__('🟤 ข้อมูลที่อยู่ (ส่วนที่ 2)', server_id, student_no)
        self.sub_dist = discord.ui.TextInput(label='ตำบล/แขวง', default=data.get('address_sub_district', ''), required=False)
        self.dist = discord.ui.TextInput(label='อำเภอ/เขต', default=data.get('address_district', ''), required=False)
        self.province = discord.ui.TextInput(label='จังหวัด', default=data.get('address_province', ''), required=False)
        self.post_code = discord.ui.TextInput(label='รหัสไปรษณีย์', default=data.get('address_post_code', ''), required=False)
        
        for item in [self.sub_dist, self.dist, self.province, self.post_code]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        payload = {
            "address_sub_district": self.sub_dist.value or None,
            "address_district": self.dist.value or None,
            "address_province": self.province.value or None,
            "address_post_code": self.post_code.value or None
        }
        await self.save_data(interaction, payload)

class RoleSelectMenu(discord.ui.Select):
    def __init__(self, server_id, student_no):
        self.server_id = server_id
        self.student_no = student_no

        options = [
            discord.SelectOption(label='นักเรียนทั่วไป (Student)', value='student', emoji='🧑‍🎓'),

            discord.SelectOption(label='หัวหน้าห้อง (Class President)', value='president', emoji='👑'),

            discord.SelectOption(label='รองฯ ฝ่ายวิชาการ (Vice Academic)', value='vice_academic', emoji='📖'),
            discord.SelectOption(label='รองฯ ฝ่ายกิจกรรม (Vice Activity)', value='vice_activity', emoji='🎭'),
            discord.SelectOption(label='รองฯ ฝ่ายระเบียบวินัย (Vice Discipline)', value='vice_discipline', emoji='⚖️'),
            discord.SelectOption(label='รองฯ ฝ่ายปฏิคม (Vice Receptionist)', value='vice_reception', emoji='🤝'),

            discord.SelectOption(label='กรรมการฝ่ายวิชาการ (Academic Staff)', value='staff_academic', emoji='📝'),
            discord.SelectOption(label='กรรมการฝ่ายกิจกรรม (Activity Staff)', value='staff_activity', emoji='🎪'),
            discord.SelectOption(label='กรรมการฝ่ายระเบียบวินัย (Discipline Staff)', value='staff_discipline', emoji='🛡️'),
            discord.SelectOption(label='กรรมการฝ่ายปฏิคม (Reception Staff)', value='staff_reception', emoji='🎀'),
            
            discord.SelectOption(label='เหรัญญิก (Treasurer)', value='treasurer', emoji='💰'),
        ]
        
        super().__init__(
            placeholder='เลือกตำแหน่ง/บทบาทของคุณ...', 
            min_values=1, 
            max_values=1, 
            options=options
        )
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        payload = {"class_role": self.values[0]}
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            await api_client.request("PATCH", f"/{self.server_id}/students/{self.student_no}", headers=headers, json=payload)
            selected_label = next(opt.label for opt in self.options if opt.value == self.values[0])
            await interaction.followup.send(f"✅ อัปเดตบทบาทเป็น **{selected_label}** สำเร็จ!", ephemeral=True)
        except APIException as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, server_id, student_no):
        super().__init__(timeout=None)
        self.add_item(RoleSelectMenu(server_id, student_no))


class ProfileEditDropdown(discord.ui.Select):
    def __init__(self, server_id: int, student_no: int, current_data: dict):
        self.server_id = server_id
        self.student_no = student_no
        self.current_data = current_data
        
        options = [
            discord.SelectOption(label='🔵 แก้ไขข้อมูลส่วนตัว', description='รหัสนักเรียน, ชื่อเล่น, วันเกิด, อีเมล', value='core', emoji='🆔'),
            discord.SelectOption(label='🟡 แก้ไขหน้าที่และผลงาน', description='เวร, คณะ, สอวน., ผลงานต่างๆ', value='academic', emoji='📚'),
            discord.SelectOption(label='🔴 แก้ไขข้อมูลสุขภาพ', description='กรุ๊ปเลือด, ไซส์เสื้อ, โรคประจำตัว', value='health', emoji='🏥'),
            discord.SelectOption(label='🟣 แก้ไขช่องทางติดต่อ', description='เบอร์โทร, LINE, IG, ผู้ปกครอง', value='contact', emoji='📱'),
            discord.SelectOption(label='🟤 แก้ไขที่อยู่ (ส่วนที่ 1)', description='บ้านเลขที่, ถนน', value='address1', emoji='🏠'),
            discord.SelectOption(label='🟤 แก้ไขที่อยู่ (ส่วนที่ 2)', description='ตำบล, อำเภอ, จังหวัด, รหัสไปรษณีย์', value='address2', emoji='📮'),
            
            discord.SelectOption(label='👑 เปลี่ยนบทบาทในห้อง', description='หัวหน้า, รองหัวหน้า, ฝ่ายต่างๆ', value='role', emoji='⚙️'),
        ]
        super().__init__(placeholder='คลิกเพื่อเลือกหมวดหมู่ที่ต้องการแก้ไข...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == 'core':
            await interaction.response.send_modal(EditCoreModal(self.server_id, self.student_no, self.current_data))
        elif selected == 'academic':
            await interaction.response.send_modal(EditAcademicModal(self.server_id, self.student_no, self.current_data))
        elif selected == 'health':
            await interaction.response.send_modal(EditHealthModal(self.server_id, self.student_no, self.current_data))
        elif selected == 'contact':
            await interaction.response.send_modal(EditContactModal(self.server_id, self.student_no, self.current_data))
        elif selected == 'address1':
            await interaction.response.send_modal(EditAddress1Modal(self.server_id, self.student_no, self.current_data))
        elif selected == 'address2':
            await interaction.response.send_modal(EditAddress2Modal(self.server_id, self.student_no, self.current_data))
        elif selected == 'role':
            from ui.student_ui import RoleSelectView 
            await interaction.response.send_message("👑 กรุณาเลือกบทบาทของคุณจากเมนูด้านล่าง:", view=RoleSelectView(self.server_id, self.student_no), ephemeral=True)

class ProfileView(discord.ui.View):
    def __init__(self, server_id: int, student_no: int, current_data: dict):
        super().__init__(timeout=None)
        self.add_item(ProfileEditDropdown(server_id, student_no, current_data))

class ExportSelectMenu(discord.ui.Select):
    def __init__(self, server_id):
        self.server_id = server_id
        options = [
            discord.SelectOption(label='🔵 ข้อมูลส่วนตัว (Core)', description='เลขที่, รหัส, ชื่อ, วันเกิด', value='core', emoji='🆔'),
            discord.SelectOption(label='🟡 วิชาการ (Academic)', description='บทบาท, เวร, คณะ, สอวน.', value='academic', emoji='📚'),
            discord.SelectOption(label='🔴 สุขภาพ (Health)', description='กรุ๊ปเลือด, โรคประจำตัว', value='health', emoji='🏥'),
            discord.SelectOption(label='🟣 ติดต่อ (Contact)', description='เบอร์โทร, เบอร์ผู้ปกครอง, LINE', value='contact', emoji='📱'),
            discord.SelectOption(label='🟤 ที่อยู่ (Address)', description='ที่อยู่ทั้งหมด, รหัสไปรษณีย์', value='address', emoji='🏠'),
        ]
        super().__init__(placeholder='ติ๊กเลือกข้อมูลที่ต้องการ (เลือกได้หลายอัน)...', min_values=1, max_values=5, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        field_map = {
            'core': ['student_no', 'student_id', 'prefix', 'first_name', 'last_name', 'nickname', 'birthday'],
            'academic': ['class_role', 'cleaning_duty', 'olympic_camp', 'target_faculty', 'portfolio'],
            'health': ['blood_group', 'shirt_size', 'food_allergy', 'congenital_disease'],
            'contact': ['phone_number', 'phone_number_parent', 'phone_number_parent_relation', 'line_id', 'ig_username', 'email'],
            'address': ['address_house_no', 'address_road', 'address_sub_district', 'address_district', 'address_province', 'address_post_code']
        }
        
        selected_fields = []
        for val in self.values:
            selected_fields.extend(field_map[val])
            
        payload = {
            "fields": selected_fields,
            "user_name": interaction.user.name
        }
        
        try:
            url = f"{API_BASE_URL}/{self.server_id}/export"
            headers = {
                "X-API-Key": api_client.session._default_headers.get("X-API-Key"),
                "X-Discord-Id": str(interaction.user.id)
            }
            
            async with api_client.session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    file_data = await resp.read()
                    discord_file = discord.File(io.BytesIO(file_data), filename=f"students_{self.server_id}.xlsx")
                    await interaction.followup.send("✅ สร้างไฟล์ Excel สำเร็จ! โหลดไปใช้งานได้เลยครับ", file=discord_file, ephemeral=True)
                elif resp.status == 403:
                    error_data = await resp.json()
                    await interaction.followup.send(error_data.get('detail', "❌ สิทธิ์ไม่เพียงพอ"), ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Backend Error: ไม่สามารถสร้างไฟล์ได้ ({resp.status})", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ ระบบขัดข้อง: {e}", ephemeral=True)

class ExportSelectView(discord.ui.View):
    def __init__(self, server_id):
        super().__init__(timeout=None)
        self.add_item(ExportSelectMenu(server_id))