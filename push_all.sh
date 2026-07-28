#!/bin/bash

# รับข้อความ Commit จากตอนพิมพ์คำสั่ง (ถ้าไม่พิมพ์จะใช้ค่า default)
MESSAGE=${1:-"chore: auto update"}

echo "🚀 กำลัง Push โค้ด Monorepo สู่ GitHub..."

git add .
git commit -m "$MESSAGE"
git push origin HEAD

echo "✅ เรียบร้อย! อัปเดตทุกอย่างขึ้น GitHub จบในปุ่มเดียว"