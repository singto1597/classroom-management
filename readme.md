# 🏫 Classroom Management System

ระบบบริหารจัดการห้องเรียนที่ออกแบบมาด้วยสถาปัตยกรรม **Microservices & Monorepo** รองรับการ Deploy ด้วย Docker Swarm และ Traefik 

## 📂 โครงสร้างโปรเจกต์ (Monorepo Architecture)

โปรเจกต์นี้ได้ยุบรวม Submodules ทั้งหมดเข้าด้วยกันเพื่อให้จัดการโค้ดและ CI/CD ได้ง่ายที่สุด:

- `backend/` : FastAPI (Python) - จัดการ Database, Business Logic และ API กลาง
- `frontend/` : Vue.js + Vite + TypeScript - หน้าเว็บสำหรับนักเรียนและครู
- `bot_discord/` : Discord.py - บอทสำหรับรับคำสั่ง แจ้งเตือน และเชื่อมต่อ API
- `docker-compose.infra.yml` : ไฟล์รันฐานข้อมูล (PostgreSQL & Redis)
- `docker-compose.app.yml` : ไฟล์รันตัวแอปพลิเคชัน (Backend, Frontend, Bot)

## 🏗️ สถาปัตยกรรมเซิร์ฟเวอร์ (Infrastructure)

ระบบนี้ใช้ **Docker Swarm** ในการทำ Cluster และใช้ **Traefik** เป็น Reverse Proxy / Load Balancer ทำให้เราสามารถ:
1. แยกระบบ `Staging` และ `Production` ออกจากกันอย่างเด็ดขาดบนเซิร์ฟเวอร์เดียว
2. อัปเดตโค้ดแบบ **Zero Downtime** (เว็บไม่ล่มระหว่างรอโหลดคอนเทนเนอร์ใหม่)
3. รัน API และ Web ซ้อนกันหลาย Replicas เพื่อรองรับโหลดที่มากขึ้น

---

## 🚀 วิธีติดตั้งและใช้งาน (Getting Started)

### 1. โคลนโปรเจกต์
```bash
git clone [https://github.com/singto1597/classroom-management.git](https://github.com/singto1597/classroom-management.git)
cd classroom-management

```

### 2. ตั้งค่า Environment Variables

คัดลอกไฟล์ `.env.example` มาสร้างเป็นไฟล์ `.env` ที่โฟลเดอร์นอกสุดของโปรเจกต์ (Root Directory) **เพียงไฟล์เดียวเท่านั้น**:

```bash
cp .env.example .env
nano .env

```

*(ระบบทั้งหมดจะดึงค่าคอนฟิกจากไฟล์ตัวแม่ไฟล์นี้โดยอัตโนมัติ)*

### 3. เปิดใช้งาน Docker Swarm & Traefik (สำหรับรันครั้งแรก)

หากเซิร์ฟเวอร์ยังไม่เคยเปิดโหมด Swarm ให้รันคำสั่งต่อไปนี้:

```bash
docker swarm init
docker network create --driver=overlay traefik-public

```

*(ต้องรัน Traefik Proxy ไว้ที่เซิร์ฟเวอร์เพื่อรอรับทราฟฟิกพอร์ต 80 เสมอ)*

สำหรับการรัน Traefik Proxy ให้สร้างไฟล์ `docker-compose.yml` เอาไว้ที่ไหนก็ได้ใน server ที่ไม่ได้อยู่ใน repo นี้

```bash
cd ..
mkdir traefik-proxy
nano docker-compose.yml

```

และนำ Setting นี้เข้าไปใส่:

```yaml
version: "3.8"
services:
  traefik:
    image: traefik:latest
    command:
      - "--api.insecure=false"
      - "--providers.swarm=true"
      - "--providers.swarm.exposedbydefault=false"
      - "--providers.swarm.network=traefik-public"
      - "--entrypoints.web.address=:80"
    ports:
      - "80:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - traefik-public
    deploy:
      placement:
        constraints: [node.role == manager]

networks:
  traefik-public:
    external: true

```

รันด้วยคำสั่งนี้:

```bash
docker stack deploy -c docker-compose.yml global_proxy

```

### 4. สตาร์ท Infrastructure (ฐานข้อมูล)

เราจะแยกฐานข้อมูลให้ทำงานเป็นอิสระ รันคำสั่งนี้ทิ้งไว้เลย:

```bash
# โหลดตัวแปรสภาพแวดล้อมชั่วคราว
export $(grep -v '^#' .env | xargs)
docker stack deploy -c docker-compose.infra.yml ${ENV_NAME}_infra

```

### 5. Deploy แอปพลิเคชัน (ครั้งแรก & อัปเดตโค้ด)

เมื่อต้องการปล่อยระบบขึ้นเซิร์ฟเวอร์ หรืออัปเดตโค้ดใหม่ ให้รันสคริปต์กู้ชีพปุ่มเดียวจบ:

```bash
chmod +x pull_all.sh
./pull_all.sh

```

สคริปต์นี้จะทำการดึงโค้ดล่าสุด -> Build Image ตามเลข Commit ล่าสุด -> สลับสวิตช์ตู้คอนเทนเนอร์แบบ Zero Downtime ทันที!

---

## 🚨 การกู้ภัยฉุกเฉิน (Rollback)

ด้วยความที่เราตั้งชื่อ Docker Image ตาม **Git Commit Hash** ทำให้ระบบเก็บ Image ของเวอร์ชันก่อนหน้าไว้เสมอ หากคุณ Deploy ระบบไปแล้วพบว่าเว็บพัง (Cowboy Coding) คุณสามารถกู้ภัยได้ 2 วิธี:

### วิธีที่ 1: สลับคอนเทนเนอร์ทันที (Hot Rollback - ไวที่สุด)

หากต้องการให้เว็บกลับมาใช้งานได้ทันทีโดยยังไม่ต้องแก้โค้ด ให้ใช้คำสั่งของ Docker Swarm เพื่อดึง Container ตัวก่อนหน้ากลับมา (ใช้เวลา ~2 วินาที):

```bash
docker service rollback staging_app_backend
# หรือ
docker service rollback staging_app_frontend

```

*(เปลี่ยน `staging` เป็น `production` หากเกิดเหตุบนระบบจริง)*

### วิธีที่ 2: ถอยหลังเต็มรูปแบบ (Full Rollback Script)

หากต้องการให้ **โค้ดบนเซิร์ฟเวอร์ถอยกลับไป 1 Commit** พร้อมกับสลับระบบกลับไปใช้ Image ตัวเก่าที่ทำงานได้ ให้รันสคริปต์:

```bash
chmod +x oh_shit.sh
./oh_shit.sh

```

สคริปต์นี้จะดึง Image ของ Commit ก่อนหน้าที่อยู่ในเครื่องขึ้นมารันทันที **โดยไม่ต้องเสียเวลา Build ใหม่** ระบบจะกลับสู่สภาวะปกติ 100%

```
