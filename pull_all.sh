#!/bin/bash

echo "⬇️ กำลังดึงโค้ดล่าสุดของ Repo แม่..."
git pull origin HEAD

echo "🔄 กำลังอัปเดต Submodule ทุกตัวให้เป็นเวอร์ชันล่าสุด..."
# --remote คือให้วิ่งไปดูบน GitHub ว่ามีอัปเดตไหม
# --merge คือถ้ามีโค้ดใหม่ ให้เอามาผสม (merge) กับโค้ดในเครื่องอย่างปลอดภัย
git submodule update --remote --merge

echo "✅ ดึงโค้ดเสร็จสิ้น! ทุกโปรเจกต์อัปเดตแล้ว"