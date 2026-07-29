#!/bin/bash
echo "🚨 เริ่มกระบวนการกู้ภัยฉุกเฉิน (Rollback)!"

# 1. โหลดตัวแปรจาก .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ ไม่พบไฟล์ .env"
    exit 1
fi

# 2. ถอยหลัง Git กลับไป 1 Commit ก่อนหน้า
echo "⏪ กำลังถอยหลังโค้ดบนเซิร์ฟเวอร์กลับไป 1 Commit..."
git reset --hard HEAD~1

# 3. สกัดเลข Commit Hash (ของเก่าที่ทำงานได้) มาใช้
export IMAGE_TAG=$(git rev-parse --short HEAD)
echo "🏷️ ถอยกลับมาที่เวอร์ชัน: ${IMAGE_TAG}"

# 4. สั่ง Deploy ใหม่ด้วย Image เดิมที่เคยรันผ่านแล้ว
echo "🚀 กำลังสลับระบบกลับไปเวอร์ชัน ${IMAGE_TAG} แบบ Zero Downtime..."
docker stack deploy -c docker-compose.app.yml ${ENV_NAME}_app

echo "✅ กู้ภัยสำเร็จ! เซิร์ฟเวอร์กลับไปใช้โค้ดและ Image เวอร์ชันที่ปลอดภัยแล้ว!"