# Classroom-Sync PHP (Web Interface)
### ⚠️ DEPRECATED: โปรเจกต์นี้ไม่ได้ใช้งานแล้ว ถูกย้ายไปเขียนใหม่ด้วย TypeScript ที่ Repository: [https://github.com/singto1597/classroom-management_web-announcement_ts]
ระบบจัดการห้องเรียนผ่านเว็บไซต์ ทำหน้าที่เป็น Client เชื่อมต่อกับ Central API

### การตั้งค่า Environment (.env)
ให้สร้างไฟล์ `.env` ไว้ที่ root directory ของโปรเจกต์ฝั่ง Web:
```env
# URL ของ Central API (FastAPI)
API_BASE_URL=http://your-api-server:8000/api/classroom/

# X-API-Key สำหรับคุยกับ Backend
API_KEY=your_central_api_key_here

# Discord OAuth2 Config
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=https://your-domain.com/callback.php

# Environment (local/production)
APP_ENV=local
```

### การติดตั้ง (Installation)
1.  ติดตั้ง Dependencies ผ่าน Composer:
    ```bash
    composer install
    ```
2.  รันด้วย Web Server (Nginx + PHP-FPM)

---
*หมายเหตุ: เว็บไซต์นี้ไม่มีการต่อฐานข้อมูลเองโดยตรง (No Database Policy) ข้อมูลทั้งหมดจะถูกจัดการผ่าน Central API*
