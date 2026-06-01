#!/bin/bash

# รับข้อความ Commit จากตอนพิมพ์คำสั่ง (ถ้าไม่พิมพ์จะใช้คำว่า "auto update" แทน)
MESSAGE=${1:-"chore: auto update"}

echo "🚀 กำลัง Push โค้ดทุก Repo สู่ GitHub..."

# 1. จัดการ Submodule ทุกตัว
git submodule foreach "git add . && git commit -m '$MESSAGE' && git push || true"

# 2. จัดการ Repo แม่
git add .
git commit -m "$MESSAGE"
git push origin main

echo "✅ เรียบร้อย! อัปเดตทุกอย่างจบในปุ่มเดียว"