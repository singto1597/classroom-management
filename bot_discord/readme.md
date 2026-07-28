# Classroom-Sync (Classroom Management Bot)

Classroom-Sync คือ Discord Bot ที่ถูกออกแบบมาเพื่อช่วยจัดการระบบภายในห้องเรียนโดยเฉพาะ  ทำหน้าที่เสมือนเลขาประจำห้องที่คอยรวบรวมตารางเรียน งานที่ได้รับมอบหมาย ประกาศสำคัญ และมีระบบแจ้งเตือนอัตโนมัติรายวัน เพื่อป้องกันการตกหล่นของข้อมูลในหมู่นักเรียน

## Features 

- **Automated Daily Notifications:** ระบบตั้งเวลาแจ้งเตือนตารางเรียนและการบ้านของวันพรุ่งนี้อัตโนมัติ (รองรับการตั้งเวลาแยกแต่ละห้อง)
- **Task Management:** ระบบจดการบ้านและติดตามงานค้าง พร้อมตัวนับถอยหลังวันกำหนดส่ง
- **Interactive UI (Modals & Autocomplete):** รองรับการกรอกข้อมูลผ่านหน้าต่าง Pop-up (Modal) และมีระบบ Dropdown ค้นหางานอัตโนมัติ 
- **Schedule & Overrides:** ระบบบันทึกตารางเรียนยืนพื้น และรองรับการตั้งค่าข้อยกเว้นฉุกเฉิน (เช่น เปลี่ยนชุดกะทันหัน หรืองดคลาส)
- **Audit Logs:** บันทึกประวัติการแก้ไขข้อมูลทั้งหมด ป้องกันการลบข้อมูลโดยไม่ตั้งใจ

---

## การเชิญบอทเข้าเซิร์ฟเวอร์ (Invite Bot)

หากต้องการนำ Classroom-Sync ไปใช้งานในเซิร์ฟเวอร์ Discord ของคุณ สามารถกดที่ลิงก์ด้านล่างเพื่อเชิญบอท:
👉 **[คลิกที่นี่เพื่อเชิญ Classroom-Sync เข้าเซิร์ฟเวอร์](https://discord.com/oauth2/authorize?client_id=1484156048494559272)**

*(หมายเหตุ: ผู้เชิญจำเป็นต้องมีสิทธิ์ Manage Server ในเซิร์ฟเวอร์เป้าหมาย)*

---

## ข้อกำหนดเบื้องต้น (Prerequisites)

หากต้องการนำ Source Code ไปรันบนเซิร์ฟเวอร์ของตัวเอง จำเป็นต้องมี:
- Python 3.10 หรือใหม่กว่า
- API Key และ Base URL จาก `classroom-backend`

## การติดตั้งและการตั้งค่า (Installation & Setup)

**1. Clone Repository**
```bash
git clone https://github.com/singto1597/discord-classroom-announcement
cd discord-classroom-announcement
```

**2. สร้าง Virtual Environment และติดตั้งไลบรารี**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. การตั้งค่า Environment Variables (.env)**
สร้างไฟล์ `.env` ไว้ในโฟลเดอร์หลักของโปรเจกต์ และกำหนดค่าดังนี้:
```env
# ใส่ Token ของ Discord Bot
DISCORD_TOKEN=your_bot_token_here

# URL ของ Classroom API (FastAPI)
API_BASE_URL=http://your-api-server:8000/api/classroom

# X-API-Key สำหรับคุยกับ Backend
API_KEY=your_central_api_key_here
```

**4. รันบอท**
```bash
python main.py
```

---

## รายการคำสั่งทั้งหมด

บอทตัวนี้ทำงานด้วยระบบ Slash Commands (`/`) 

### 📊 หมวดเรียกดูข้อมูล
- `/today` - สรุปตารางเรียน ชุดที่ต้องใส่ และงานที่ต้องส่ง "วันนี้"
- `/tomorrow` - สรุปตารางเรียน ชุดที่ต้องใส่ และงานที่ต้องส่ง "วันพรุ่งนี้"

### 📝 หมวดจัดการงาน
- `/list_tasks` - ดูรายการการบ้านและงานค้างทั้งหมดของห้อง
- `/add_task` - เพิ่มงาน/การบ้านใหม่ (กรอกข้อมูลผ่านหน้าต่าง Modal)
- `/edit_task` - แก้ไขรายละเอียดงาน หรือเลื่อนวันส่ง
- `/mark_done` - ติ๊กเครื่องหมายว่างานนี้ทำเสร็จแล้ว
- `/delete_task` - ลบงานออกจากระบบ

### 📌 หมวดประกาศและข้อยกเว้น
- `/add_note` - เพิ่มประกาศสำคัญ หรือของที่ต้องเตรียมมาในวันนั้นๆ
- `/delete_note` - ลบประกาศที่เคยแจ้งไว้
- `/set_override` - ตั้งค่าข้อยกเว้นฉุกเฉิน (เช่น เปลี่ยนชุดกะทันหัน)

### ⚙️ หมวดตั้งค่าระบบ
- `/setup_room` - ลงทะเบียนเซิร์ฟเวอร์และตั้งชื่อห้อง (ต้องทำเป็นอันดับแรก)
- `/set_channel` - เลือก Text Channel สำหรับให้บอทส่งการแจ้งเตือนอัตโนมัติ
- `/set_schedule` - บันทึกตารางเรียนและชุดยืนพื้นประจำวัน (จันทร์-ศุกร์)
- `/set_time` - ตั้งเวลาสำหรับการแจ้งเตือนอัตโนมัติรายวัน (ค่าเริ่มต้นคือ 19:00 น.)

---
*Developed for Classroom Management.*
