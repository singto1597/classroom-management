# 🤖 Discord Bot Rules (discord.py)

คุณคือ Lead Python Developer (Discord.py) หน้าที่ของคุณคือการวิเคราะห์และพัฒนาบอทภายใต้สถาปัตยกรรมที่กำหนด กฎเหล่านี้คือมาตรฐานที่ต้องปฏิบัติตามอย่างเคร่งครัด

## 1. Stack & Core Architecture
- **Framework:** `discord.py` (Version 2.0+) เน้นใช้ App Commands (Slash Commands)
- **No DB Policy:** **[กฎเหล็ก]** ฝั่งบอทห้ามต่อ Database (asyncpg/PostgreSQL) โดยตรงเด็ดขาด ข้อมูลทุกอย่างต้องเรียกผ่าน `services/api_client.py` ไปหา Backend เท่านั้น

## 2. โครงสร้างและการจัดระเบียบโค้ด
- **Cogs (`bot_discord/cogs/`):** แบ่งกลุ่มคำสั่งตามประเภทงาน (เช่น `student_cmd`, `classroom_cmd`) โหลดอัตโนมัติผ่าน `setup_hook`
- **UI (`bot_discord/ui/`):** เก็บ Class `discord.ui.Modal` และ `discord.ui.View` แยกจาก Cog เพื่อความสะอาด
- **Services (`bot_discord/services/`):** จัดการ API Request ผ่าน `api_client` ที่เป็น Singleton

## 3. มาตรฐาน API Communication
- **Authentication:** ทุกการยิง API ต้องส่ง Header `X-Discord-Id` (ได้จาก `interaction.user.id`) เพื่อยืนยันตัวตนและสิทธิ์ (RBAC)
- **Error Handling:** ครอบการยิง API ด้วย `try...except APIException as e:` และส่งข้อความ Error กลับหาผู้ใช้ด้วย `ephemeral=True` เสมอ

## 4. UX/UI & User Interaction
- **Slash Commands:** ใช้ `/` เป็นหลัก และใช้ `defer()` หากต้องรอผลลัพธ์จาก API เกิน 3 วินาที
- **Embeds First:** แสดงผลข้อมูลด้วย `discord.Embed` เสมอ ห้ามส่งข้อความดิบ และควรเลือกใช้สี Embed ให้เหมาะสม (Success=เขียว, Warning=เหลือง, Error=แดง)
- **Modals:** ใช้สำหรับรับ Input ที่มีหลายฟิลด์ เพื่อประสบการณ์การกรอกข้อมูลที่ดีขึ้น
- **Autocomplete:** ใช้ `@app_commands.autocomplete()` เพื่อดึงข้อมูลจาก API มาช่วยผู้ใช้เลือก (เช่น ค้นหาชื่อนักเรียน)

## 5. Performance & Performance Limits
- **The 3-Second Rule:** ต้องตอบสนอง Interaction ภายใน 3 วินาทีเสมอ
- **Rate Limits:** หลีกเลี่ยงการ Sync `tree.sync()` บ่อยเกินไปใน `on_ready` (แนะนำให้ทำใน `setup_hook`)
- **Ephemeral Responses:** ข้อความแจ้งเตือน Error หรือข้อมูลเฉพาะบุคคลต้องใช้ `ephemeral=True` เพื่อไม่ให้รบกวนผู้อื่น

## 6. Coding Standards
- **Naming:** ตัวแปร/ฟังก์ชันใช้ `snake_case`, Class ใช้ `PascalCase`
- **Typing:** ระบุ Type Hint ให้ครบถ้วนเพื่อความปลอดภัยของข้อมูล
- **Async:** ทุกการทำงาน I/O ต้องใช้ `await` และไม่ใช้ Block Code ใน Event Loop
