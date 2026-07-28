# ==========================================
# Stage 1: Build Stage (ใช้ Node.js สำหรับคอมไพล์โค้ด)
# ==========================================
FROM node:22-alpine AS build-stage

# กำหนด Working Directory ภายใน Container
WORKDIR /app

# คัดลอก package.json และ package-lock.json (ถ้ามี) เข้ามาก่อน
# เพื่อใช้ประโยชน์จาก Docker Cache หากไม่ได้มีการเปลี่ยนแปลง Dependencies
COPY package*.json ./

# ติดตั้ง Dependencies ทั้งหมด
RUN npm install

# คัดลอก Source Code ทั้งหมดเข้าสู่ Container
COPY . .

# รันคำสั่งคอมไพล์ TypeScript และ Build โปรเจกต์ด้วย Vite
# ผลลัพธ์ที่ได้จะไปอยู่ในโฟลเดอร์ /app/dist
RUN npm run build


# ==========================================
# Stage 2: Production Stage (ใช้ Nginx สำหรับเสิร์ฟไฟล์ Static)
# ==========================================
FROM nginx:alpine AS production-stage

# ลบไฟล์ default ของ Nginx ออก (เพื่อเตรียมพื้นที่ให้ไฟล์ของเรา)
RUN rm -rf /usr/share/nginx/html/*

# คัดลอกเฉพาะโฟลเดอร์ dist จาก build-stage มาวางที่ root ของ Nginx
COPY --from=build-stage /app/dist /usr/share/nginx/html

# (สำคัญสำหรับ Vue Router) เพื่อให้การกด Refresh หน้าเว็บ (ที่ไม่ได้อยู่ที่ Root path) ไม่ติด 404
# เราจะสร้างไฟล์คอนฟิกพื้นฐานของ Nginx ให้ชี้ทุก Request กลับไปที่ index.html เสมอ
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

# เปิดรับการเชื่อมต่อที่ Port 80
EXPOSE 80

# คำสั่งรัน Nginx ให้อยู่เบื้องหน้า (Foreground) เพื่อไม่ให้ Container ดับ
CMD ["nginx", "-g", "daemon off;"]