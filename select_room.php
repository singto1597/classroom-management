<?php
require_once 'config/database.php';

// ถ้าไม่มี temp_rooms แปลว่าแอบเข้าหน้านี้ตรงๆ ให้เตะกลับ
if (!isset($_SESSION['temp_rooms'])) {
    header("Location: login.php");
    exit();
}

$rooms = $_SESSION['temp_rooms'];

// ถ้ากดเลือกห้องมาแล้ว (Submit Form)
if ($_SERVER['REQUEST_METHOD'] == 'POST' && isset($_POST['selected_room_id'])) {
    $selected_id = $_POST['selected_room_id'];
    
    // ค้นหาห้องที่ตรงกับที่กดเลือก
    foreach ($rooms as $room) {
        if ($room['server_id'] == $selected_id) {
            $_SESSION['room_id'] = $room['server_id'];
            $_SESSION['room_name'] = $room['room_name'];
            $_SESSION['role'] = $room['role'];
            $_SESSION['user_name'] = $_SESSION['temp_user_name'];
            $_SESSION['discord_id'] = $_SESSION['temp_discord_id'];
            
            // ล้างข้อมูลชั่วคราวทิ้งให้สะอาด
            unset($_SESSION['temp_rooms'], $_SESSION['temp_user_name'], $_SESSION['temp_discord_id']);
            
            header("Location: index.php");
            exit();
        }
    }
}
?>
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>เลือกห้องเรียน | Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
    <div class="card shadow border-0 rounded-4 p-4" style="max-width: 500px; width: 100%;">
        <h3 class="fw-bold text-center mb-1">🏫 เลือกห้องเรียน</h3>
        <p class="text-center text-muted mb-4">สวัสดีคุณ <?= h($_SESSION['temp_user_name']) ?>,<br>คุณสังกัดอยู่หลายห้อง กรุณาเลือกห้องที่ต้องการจัดการ</p>
        
        <form method="POST">
            <div class="d-grid gap-3">
                <?php foreach($rooms as $room): ?>
                    <button type="submit" name="selected_room_id" value="<?= $room['server_id'] ?>" 
                            class="btn btn-outline-primary text-start p-3 rounded-3 shadow-sm position-relative">
                        <span class="fs-5 fw-bold d-block mb-1"><?= h($room['room_name']) ?></span>
                        <span class="badge bg-secondary">บทบาท: <?= h($room['role']) ?></span>
                    </button>
                <?php endforeach; ?>
            </div>
        </form>
        
        <div class="text-center mt-4">
            <a href="logout.php" class="text-danger text-decoration-none">ยกเลิก / ออกจากระบบ</a>
        </div>
    </div>
</body>
</html> 