# ใช้ Base Image ตามที่ระบุ
FROM python:3.12-slim

# ตั้งค่า Environment Variables เพื่อปรับแต่งการทำงานของ Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# กำหนด Working Directory ภายใน Container
WORKDIR /app

# ติดตั้ง System Dependencies ที่จำเป็น (เช่น สำหรับคอมไพล์แพ็กเกจบางตัว) 
# และลบ Cache ทิ้งทันทีเพื่อประหยัดพื้นที่
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# คัดลอกไฟล์ requirements.txt และติดตั้ง Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# สร้าง User แบบ Non-root เพื่อความปลอดภัยในระดับ Production
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser /app
USER appuser

# คัดลอก Source Code ทั้งหมดเข้าสู่ Container
COPY --chown=appuser:appuser . .

# กำหนด Port ที่ Container จะเปิดรับการเชื่อมต่อ
EXPOSE 8000

# คำสั่งรัน Uvicorn สำหรับ Production
# มีการใช้ --proxy-headers และ --forwarded-allow-ips เพื่อให้ระบบอ่านค่า IP และ HTTPS Schema ได้ถูกต้อง 
# ซึ่งจำเป็นมากสำหรับการทำ Discord OAuth2 Redirect
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]