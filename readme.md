# 🏫 Classroom Management System (Deployment & Infrastructure)

Repository นี้เป็นศูนย์กลาง (Monorepo) สำหรับจัดการ Infrastructure และ Deployment ของระบบบริหารจัดการห้องเรียน (Classroom Management) โดยเชื่อมโยงบริการต่างๆ เข้าด้วยกันผ่าน Git Submodules และรันระบบทั้งหมดด้วย Docker Compose

## 📂 โครงสร้างโปรเจกต์ (Architecture)

โปรเจกต์นี้แบ่งออกเป็นส่วนต่างๆ ดังนี้:

- `backend/` : FastAPI Backend สำหรับจัดการฐานข้อมูลและ API กลาง
- `bot_discord/` : Discord Bot สำหรับแจ้งเตือนและรับคำสั่งจากนักเรียน
- `frontend_ts/` : หน้าเว็บ Frontend หลัก (Vue/Vite + TypeScript)
- `frontend_php/` : *(Deprecated)* หน้าเว็บเวอร์ชันเก่า (PHP) เก็บไว้เป็น Reference
- `docker-compose.yml` : ไฟล์ตั้งค่าสำหรับรันระบบทั้งหมด (รวม PostgreSQL และ Redis)

## 🚀 วิธีติดตั้งและใช้งาน (Getting Started)

### 1. โคลนโปรเจกต์ (สำคัญมาก)
เนื่องจากโปรเจกต์นี้ใช้ Git Submodules **ต้อง** โคลนด้วย flag `--recurse-submodules` เพื่อดึงโค้ดของทุกส่วนมาพร้อมกัน:

```bash
git clone --recurse-submodules [https://github.com/singto1597/classroom-deployment.git](https://github.com/singto1597/classroom-deployment.git)
cd classroom-deployment

```

*(หากโคลนมาแบบธรรมดาแล้วโฟลเดอร์ลูกว่างเปล่า ให้รัน `git submodule update --init --recursive`)*

### 2. ตั้งค่า Environment Variables

สำหรับ Repo หลักนี้ จะมี .env ที่เก็บการตั้งค่าของระบบหลักเอาไว้ ให้สร้างไฟล์ `.env` เอาไว้หน้าสุดด้วย 

```env
COMPOSE_PROJECT_NAME=classroom_staging
ENV_NAME=staging
WEB_PORT=8200
API_PORT=8000
```

สำหรับ Services ย่อย ให้เข้าไปสร้างและแก้ไขไฟล์ `.env` ในแต่ละ Services ให้เรียบร้อย:

* `/backend/.env`
* `/bot_discord/.env`
* `/frontend_ts/.env`

*(ดูตัวอย่างตัวแปรที่ต้องใช้ได้ในไฟล์ `.env.example` ของแต่ละโฟลเดอร์)*

### 3. รันระบบด้วย Docker Compose

เมื่อตั้งค่าเสร็จแล้ว สามารถสั่งรันทุกระบบพร้อมกันได้เลย:

```bash
docker compose up -d --build

```

ระบบจะทำการ Build Images และผูก Network ให้โดยอัตโนมัติ

* 🌐 **Web Frontend:** เข้าถึงได้ที่ Port ตามที่ตั้งใน Docker Compose (เช่น `8080` หรือ `9090`)
* ⚙️ **API Backend:** วิ่งอยู่บน Port `8000` (สื่อสารภายในวง Docker)

## 🔄 วิธีดึงอัปเดตล่าสุด

หากมีการ Push โค้ดใหม่เข้าไปใน Submodule ย่อยๆ สามารถดึงโค้ดล่าสุดของทุกเซอร์วิสได้ด้วยคำสั่ง:

```bash
git submodule update --remote --merge
docker compose up -d --build

```
