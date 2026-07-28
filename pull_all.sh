#!/bin/bash

# 1. โหลดตัวแปรจากไฟล์ .env นอกสุด
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "⚙️ โหลด Environment: $ENV_NAME"
else
    echo "❌ ไม่พบไฟล์ .env"
    exit 1
fi

CURRENT_BRANCH=$(git branch --show-current)
if [ -z "$CURRENT_BRANCH" ]; then
    echo "❌ ไม่สามารถหาชื่อ Branch ได้"
    exit 1
fi

# 2. ดึงโค้ดล่าสุด (ลบโค้ด Submodule ทิ้งไปให้หมด!)
echo "⬇️ กำลังดึงโค้ดล่าสุดจาก Monorepo..."
git fetch origin
git reset --hard origin/$CURRENT_BRANCH

# 3. เตรียมไฟล์ .env ให้ Frontend (Vite) ก่อน Build
echo "📝 คัดลอก .env โยนให้ Frontend..."
cp .env frontend/.env

# 4. Build Image (แก้พาธเป็น ./frontend)
echo "🔨 กำลังสร้าง Docker Image สำหรับ $ENV_NAME..."
docker build -t classroom-${ENV_NAME}-backend:latest ./backend
docker build -t classroom-${ENV_NAME}-frontend:latest ./frontend
docker build -t classroom-${ENV_NAME}-bot:latest ./bot_discord

# 5. Deploy อัปเดตระบบแบบ Zero Downtime
echo "🚀 กำลังสลับสวิตช์ระบบ $ENV_NAME แบบ Zero Downtime..."
docker stack deploy -c docker-compose.app.yml ${ENV_NAME}_app

echo "✅ อัปเดตเสร็จสมบูรณ์ ระบบทำงานต่อเนื่องไม่มีสะดุด!"