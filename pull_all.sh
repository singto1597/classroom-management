#!/bin/bash

# ดึงชื่อ branch ปัจจุบันมาใช้เลย ชัวร์กว่า HEAD เพียวๆ
BRANCH=$(git branch --show-current)

echo "⬇️ กำลังดึงโค้ดล่าสุดของ Repo แม่ (Branch: $BRANCH)..."
git pull origin $BRANCH

echo "🔄 กำลังอัปเดต Submodule ทุกตัวให้ตรงกับ Repo แม่..."
# ใช้คำสั่งนี้แทน! มันจะบังคับให้ Submodule วิ่งไปหา commit ที่ตรงกับ Repo แม่เป๊ะๆ
# ไม่เกิดอาการ diverged (แตกแขนง) แน่นอน
git submodule update --init --recursive

echo "✅ ดึงโค้ดเสร็จสิ้น! ทุกโปรเจกต์อัปเดตแล้ว"