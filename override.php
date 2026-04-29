<?php
require 'db.php';

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $target_date = $_POST['target_date'];
    $new_attire = $_POST['new_attire'];
    $note = $_POST['note'];
    $room_id = $_SESSION['room_id'];

    // ลอจิกเดิม: ลบของเก่าออกก่อน แล้วค่อยเพิ่มใหม่[cite: 2]
    $stmt_delete = $pdo->prepare("DELETE FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
    $stmt_delete->execute([$room_id, $target_date]);

    $stmt_insert = $pdo->prepare("INSERT INTO schedule_overrides (room_id, target_date, new_attire, note) VALUES (?, ?, ?, ?)");
    $stmt_insert->execute([$room_id, $target_date, $new_attire, $note]);
    
    $success_msg = "🚨 ตั้งข้อยกเว้นสำหรับวันที่ $target_date เรียบร้อยแล้ว!";
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>ตั้งข้อยกเว้นฉุกเฉิน</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5" style="max-width: 600px;">
        <div class="card shadow-sm border-danger">
            <div class="card-header bg-danger text-white">
                <h5 class="mb-0">🚨 ตั้งข้อยกเว้นฉุกเฉิน (เปลี่ยนชุด/กิจกรรมพิเศษ)</h5>
            </div>
            <div class="card-body">
                <?php if(isset($success_msg)): ?>
                    <div class="alert alert-success"><?= $success_msg ?></div>
                <?php endif; ?>
                <form method="POST">
                    <div class="mb-3">
                        <label>วันที่เกิดการยกเว้น</label>
                        <input type="date" name="target_date" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>👕 ชุดใหม่ที่ต้องใส่</label>
                        <input type="text" name="new_attire" class="form-control" placeholder="เช่น ชุดกีฬา, ชุดผ้าไทย" required>
                    </div>
                    <div class="mb-3">
                        <label>📢 หมายเหตุ / สาเหตุที่เปลี่ยน</label>
                        <textarea name="note" class="form-control" rows="2" placeholder="เช่น มีกิจกรรมกีฬาสีงดเรียน" required></textarea>
                    </div>
                    <button type="submit" class="btn btn-danger w-100">บันทึกข้อยกเว้น</button>
                </form>
            </div>
        </div>
        <div class="mt-3 text-center">
            <a href="index.php" class="btn btn-outline-secondary">กลับหน้าหลัก</a>
        </div>
    </div>
</body>
</html>