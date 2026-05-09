<?php
require_once 'config/database.php';
require_once 'services/ApiClient.php';

// ถ้าไม่มี Discord ID หลุดมา แปลว่ายังไม่ได้ล็อกอิน ให้เตะออก
if (!isset($_SESSION['discord_id'])) {
    header("Location: logout.php");
    exit();
}

try {
    // 1. ยิง Guzzle ไปถาม FastAPI ดึงห้องล่าสุด (เผื่อครูเพิ่งดึงมึงเข้าห้องใหม่สดๆ ร้อนๆ)
    $api = new ApiClient();
    $rooms = $api->request('GET', "{$_SESSION['discord_id']}/rooms"); 
    
    // 2. เซ็ตตัวแปรชั่วคราวให้หน้า select_room.php รู้จัก
    $_SESSION['temp_rooms'] = $rooms;
    $_SESSION['temp_user_name'] = $_SESSION['user_name'];
    $_SESSION['temp_discord_id'] = $_SESSION['discord_id'];
    
    // 3. 🚨 ทำลาย Session ของห้องเดิมทิ้งซะ!
    unset($_SESSION['room_id']);
    unset($_SESSION['room_name']);
    unset($_SESSION['role']);
    
    // 4. เด้งกลับไปหน้าเลือกห้อง
    header("Location: select_room.php");
    exit();

} catch (Exception $e) {
    // ถ้ายิง API พัง ให้บังคับล็อกเอาท์ไปเลย ปลอดภัยสุด
    header("Location: logout.php");
    exit();
}
?>