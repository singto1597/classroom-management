#!/bin/bash

# 1. ให้มันอ่านชื่อ Branch ปัจจุบันที่คุณกำลังยืนอยู่
CURRENT_BRANCH=$(git branch --show-current)

# ดักไว้เผื่อหัวหลุด (Detached HEAD)
if [ -z "$CURRENT_BRANCH" ]; then
  echo "❌ ไม่สามารถหาชื่อ Branch ได้ (คุณอาจจะหัวหลุดอยู่) กรุณา git checkout ชื่อbranch ก่อนรัน"
  exit 1
fi

echo "⬇️ กำลังดึงโค้ดล่าสุดของ Repo แม่ (Branch: $CURRENT_BRANCH)..."
git fetch origin
# ไม่ต้องใช้ git checkout ซ้ำ เพราะเรายืนอยู่บน branch นี้อยู่แล้ว
git reset --hard origin/$CURRENT_BRANCH

echo "🔄 กำลังเตรียมโครงสร้าง Submodule..."
git submodule update --init

echo "📥 กำลังบังคับจับลูกๆ ทุกตัวเข้ากิ่ง $CURRENT_BRANCH และซิงค์กับ GitHub..."

# 2. ต้อง export ตัวแปรนี้ เพื่อให้สคริปต์ใน foreach มองเห็น
export CURRENT_BRANCH

git submodule foreach '
  if [ "$name" = "frontend_php" ]; then
    echo "⏭️ ข้าม $name"
    exit 0
  fi
  
  # ดึงข้อมูลจากเซิร์ฟเวอร์
  git fetch origin
  
  # บังคับสลับไปกิ่งเดียวกับตัวแม่ (ถ้าไม่มีให้สร้างใหม่)
  git checkout $CURRENT_BRANCH || git checkout -b $CURRENT_BRANCH
  
  # บังคับทับโค้ดให้เหมือนบนเซิร์ฟเวอร์แบบ 100%
  git reset --hard origin/$CURRENT_BRANCH
'

echo "✅ ดึงโค้ดเสร็จสิ้น! ทุกโปรเจกต์อยู่บนกิ่ง $CURRENT_BRANCH อย่างปลอดภัย 🚀"