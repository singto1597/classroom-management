<?php
require 'db.php';

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $target_date = $_POST['target_date'];
    $bring_items = $_POST['bring_items'];
    $announcement = $_POST['announcement'];
    $room_id = 1;

    // เช็คว่ามีโน้ตของวันนี้อยู่แล้วไหม ถ้ามีให้ลบของเก่าออกก่อน (แบบเดียวกับลอจิก add_daily_note)
    $stmt = $pdo->prepare("DELETE FROM daily_notes WHERE room_id = ? AND target_date = ?");
    $stmt->execute([$room_id, $target_date]);

    // บันทึกโน้ตใหม่
    $stmt = $pdo->prepare("INSERT INTO daily_notes (room_id, target_date, bring_items, announcement) VALUES (?, ?, ?, ?)");
    $stmt->execute([$room_id, $target_date, $bring_items, $announcement]);
    
    $success_msg = "บันทึกโน้ตสำหรับวันที่ $target_date เรียบร้อย!";
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>จัดการโน้ตรายวัน</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5" style="max-width: 600px;">
        <div class="card shadow-sm">
            <div class="card-header bg-warning text-dark">
                <h5 class="mb-0">📌 เพิ่มโน้ตรายวัน / ประกาศพิเศษ</h5>
            </div>
            <div class="card-body">
                <?php if(isset($success_msg)): ?>
                    <div class="alert alert-success"><?= $success_msg ?></div>
                <?php endif; ?>
                <form method="POST">
                    <div class="mb-3">
                        <label>วันที่เป้าหมาย</label>
                        <input type="date" name="target_date" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>🎒 สิ่งที่ต้องเตรียม (เช่น สีไม้, เงินค่าเสื้อ)</label>
                        <input type="text" name="bring_items" class="form-control" placeholder="ถ้าไม่มีใส่ -">
                    </div>
                    <div class="mb-3">
                        <label>📢 ประกาศ (เช่น พรุ่งนี้งดเข้าแถว)</label>
                        <textarea name="announcement" class="form-control" rows="2" placeholder="ถ้าไม่มีใส่ -"></textarea>
                    </div>
                    <button type="submit" class="btn btn-warning w-100">บันทึกโน้ต</button>
                </form>
            </div>
        </div>
        <div class="mt-3 text-center">
            <a href="index.php" class="btn btn-outline-secondary">กลับหน้าหลัก</a>
        </div>
    </div>
</body>
</html>