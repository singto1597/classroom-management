#!/bin/bash

# รับข้อความ Commit จากตอนพิมพ์คำสั่ง
MESSAGE=${1:-"chore: auto update"}

echo "🚀 กำลัง Push โค้ดทุก Repo สู่ GitHub..."

# ใช้ origin HEAD เพื่อสั่งให้ push branch ปัจจุบันที่กำลัง active อยู่ขึ้นไปเลย (ไม่ว่าจะ main หรือ staging)
git submodule foreach "git add . && git commit -m '$MESSAGE' && git push origin HEAD || true"

git add .
git commit -m "$MESSAGE"
git push origin HEAD

echo "✅ เรียบร้อย! อัปเดตทุกอย่างจบในปุ่มเดียว"