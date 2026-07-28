# ใช้ Base Image ตามที่ระบุ
FROM python:3.12-slim

# ตั้งค่า Environment Variables
# ป้องกัน Python เขียนไฟล์ .pyc และบังคับให้แสดงผล Log (print) ออกมาที่ Console ทันที
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# กำหนด Working Directory ภายใน Container
WORKDIR /app

# ติดตั้ง System Dependencies ที่จำเป็น (เผื่อสำหรับบางแพ็กเกจที่ต้องใช้ C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# คัดลอกเฉพาะ requirements.txt มาก่อน เพื่อใช้ประโยชน์จาก Docker Cache
COPY requirements.txt .

# ติดตั้ง Dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# สร้าง User แบบ Non-root เพื่อความปลอดภัย
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser /app
USER appuser

# คัดลอก Source Code ทั้งหมดเข้าสู่ Container
COPY --chown=appuser:appuser . .

# คำสั่งสำหรับรัน Discord Bot
CMD ["python", "main.py"]