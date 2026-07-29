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

# 2. ดึงโค้ดล่าสุดจาก Monorepo
echo "⬇️ กำลังดึงโค้ดล่าสุดจาก Monorepo..."
git fetch origin
git reset --hard origin/$CURRENT_BRANCH

# --- 🚀 [NEW] ดึงเลข Commit 7 หลักล่าสุดมาใช้เป็นชื่อ Image ---
export IMAGE_TAG=$(git rev-parse --short HEAD)
echo "🏷️ ตรวจพบ Commit ล่าสุด: ${IMAGE_TAG}"

# 3. เตรียมไฟล์ .env ให้ Frontend (Vite) ก่อน Build
echo "📝 คัดลอก .env โยนให้ Frontend..."
cp .env frontend/.env

# 4. Build Image (ใช้เลข Commit เป็น Tag แทน latest)
echo "🔨 กำลังสร้าง Docker Image เวอร์ชัน: ${IMAGE_TAG}..."
docker build -t classroom-${ENV_NAME}-backend:${IMAGE_TAG} ./backend
docker build -t classroom-${ENV_NAME}-frontend:${IMAGE_TAG} ./frontend
docker build -t classroom-${ENV_NAME}-bot:${IMAGE_TAG} ./bot_discord

# 5. Deploy อัปเดตระบบแบบ Zero Downtime
echo "🚀 กำลังสลับสวิตช์ระบบ $ENV_NAME แบบ Zero Downtime (เวอร์ชัน ${IMAGE_TAG})..."
docker stack deploy -c docker-compose.app.yml ${ENV_NAME}_app

echo "✅ อัปเดตเสร็จสมบูรณ์ ระบบทำงานต่อเนื่องไม่มีสะดุด!"