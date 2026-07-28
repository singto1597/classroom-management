#!/bin/bash

# 1. โหลดตัวแปรจากไฟล์ .env
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

# 2. ดึงโค้ดล่าสุด
echo "⬇️ กำลังดึงโค้ดล่าสุด..."
git fetch origin
git reset --hard origin/$CURRENT_BRANCH
git submodule update --init

export CURRENT_BRANCH
git submodule foreach '
  if [ "$name" = "frontend_php" ]; then exit 0; fi
  git fetch origin
  git checkout $CURRENT_BRANCH || git checkout -b $CURRENT_BRANCH
  git reset --hard origin/$CURRENT_BRANCH
'

# 3. Build Image
echo "🔨 กำลังสร้าง Docker Image สำหรับ $ENV_NAME..."
docker build -t classroom-${ENV_NAME}-backend:latest ./backend
docker build -t classroom-${ENV_NAME}-frontend:latest ./frontend_ts
docker build -t classroom-${ENV_NAME}-bot:latest ./bot_discord

# 4. Deploy อัปเดตระบบแบบ Zero Downtime
echo "🚀 กำลังสลับสวิตช์ระบบ $ENV_NAME แบบ Zero Downtime..."
docker stack deploy -c docker-compose.app.yml ${ENV_NAME}_app

echo "✅ อัปเดตเสร็จสมบูรณ์ ระบบทำงานต่อเนื่องไม่มีสะดุด!"