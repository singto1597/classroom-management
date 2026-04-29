<?php
require 'db.php';

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $day_of_week = $_POST['day_of_week'];
    $attire = $_POST['attire'];
    $subjects = $_POST['subjects'];
    $room_id = $_SESSION['room_id'];

    // ลอจิกเดิม: ลบของเก่าออกก่อน แล้วค่อยเพิ่มใหม่[cite: 2]
    $stmt_delete = $pdo->prepare("DELETE FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
    $stmt_delete->execute([$room_id, $day_of_week]);

    $stmt_insert = $pdo->prepare("INSERT INTO default_schedules (room_id, day_of_week, attire, subjects) VALUES (?, ?, ?, ?)");
    $stmt_insert->execute([$room_id, $day_of_week, $attire, $subjects]);
    
    $success_msg = "✅ บันทึกตารางวัน $day_of_week เรียบร้อยแล้ว!";
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>ตั้งตารางเรียน</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5" style="max-width: 600px;">
        <div class="card shadow-sm">
            <div class="card-header bg-success text-white">
                <h5 class="mb-0">📅 ตั้งตารางเรียนยืนพื้น (จันทร์ - ศุกร์)</h5>
            </div>
            <div class="card-body">
                <?php if(isset($success_msg)): ?>
                    <div class="alert alert-success"><?= $success_msg ?></div>
                <?php endif; ?>
                <form method="POST">
                    <div class="mb-3">
                        <label>วันในสัปดาห์</label>
                        <select name="day_of_week" class="form-select" required>
                            <option value="จันทร์">จันทร์</option>
                            <option value="อังคาร">อังคาร</option>
                            <option value="พุธ">พุธ</option>
                            <option value="พฤหัสบดี">พฤหัสบดี</option>
                            <option value="ศุกร์">ศุกร์</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label>👕 ชุดที่ต้องใส่ (เช่น ชุดนักเรียน, ชุดพละ)</label>
                        <input type="text" name="attire" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>📚 วิชาเรียน (เรียงตามคาบ)</label>
                        <textarea name="subjects" class="form-control" rows="2" placeholder="คณิต, ไทย, อังกฤษ, ว่าง, ฟิสิกส์..." required></textarea>
                    </div>
                    <button type="submit" class="btn btn-success w-100">บันทึกตารางเรียน</button>
                </form>
            </div>
        </div>
        <div class="mt-3 text-center">
            <a href="index.php" class="btn btn-outline-secondary">กลับหน้าหลัก</a>
        </div>
    </div>
</body>
</html>