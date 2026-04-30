# Classroom-Sync

### User Session
ในระบบนี้จะใช้การยืนยันตัวตนด้วย Session หากเข้าไปที่ `config/database.php` จะเห็นบรรทัด
```php
if (!isset($_SESSION['room_id'])) {
    $_SESSION['room_id'] = 2; 
    $_SESSION['room_name'] = 'ม.4/2';
    $_SESSION['user_name'] = 'หัวหน้าห้อง_Demo';
    $_SESSION['role'] = 'student';
}
```
หมายความว่านี่เป็นข้อมูลจำลอง ถ้าหากว่าไม่เคยเข้าเลย จะเซ็ตค่าเริ่มต้นให้
การที่จะนำไปใช้ในระบบอื่น จะต้องสร้าง `session` เพิ่มเติมให้กับ user นั้นด้วย

### ข้อมูลส่วนตัวของผู้ดูแลระบบ
ให้สร้างไฟล์ `.env` ไว้ที่ root directory ของ project
```env
DB_HOST=localhost
DB_NAME=ess_classroom_announcement
DB_USER=classroom_user
DB_PASS=YOUR_PASSWORD
CRON_API_KEY=your-very-long-random-secret-key-here
```

สร้าง key ด้วย `php -r "echo bin2hex(random_bytes(32));"`

### โครงสร้าง Database (MySQL)
```SQL
-- สร้างฐานข้อมูล
CREATE DATABASE IF NOT EXISTS ess_classroom_announcement CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ess_classroom_announcement;

-- ==========================================
-- ตารางห้องเรียน (Rooms)
-- ==========================================
CREATE TABLE IF NOT EXISTS rooms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- ตารางงานและการบ้าน (Tasks)
-- ==========================================
CREATE TABLE IF NOT EXISTS tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    task_name VARCHAR(255) NOT NULL,
    task_detail TEXT,
    due_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
);

-- ==========================================
-- ตารางตารางเรียนยืนพื้น (Default Schedules)
-- ==========================================
CREATE TABLE IF NOT EXISTS default_schedules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    day_of_week VARCHAR(20) NOT NULL,
    attire TEXT,
    subjects TEXT,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
);

-- ==========================================
-- ตารางข้อยกเว้นฉุกเฉิน (Schedule Overrides)
-- ==========================================
CREATE TABLE IF NOT EXISTS schedule_overrides (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    target_date DATE NOT NULL,
    new_attire TEXT,
    note TEXT,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
);

-- ==========================================
-- ตารางโน้ตรายวัน (Daily Notes)
-- ==========================================
CREATE TABLE IF NOT EXISTS daily_notes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    target_date DATE NOT NULL,
    bring_items TEXT,
    announcement TEXT,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
);

-- ==========================================
-- ตารางเก็บประวัติการใช้งาน (Audit Logs)
-- ==========================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_id INT NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    detail TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
);

-- ==========================================
-- ใส่ข้อมูลจำลองสำหรับเริ่มต้นทดสอบระบบ
-- ==========================================
INSERT INTO rooms (id, room_name) VALUES 
(1, 'ม.4/1'),
(2, 'ม.4/2')
ON DUPLICATE KEY UPDATE room_name=VALUES(room_name);
```