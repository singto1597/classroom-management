<?php
require 'db.php';

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $task_name = $_POST['task_name'];
    $task_detail = $_POST['task_detail'];
    $due_date = $_POST['due_date'];
    $room_id = $_SESSION['room_id'];

    $stmt = $pdo->prepare("INSERT INTO tasks (room_id, task_name, task_detail, due_date) VALUES (?, ?, ?, ?)");
    $stmt->execute([$room_id, $task_name, $task_detail, $due_date]);
    
    $success_msg = "เพิ่มงานเรียบร้อยแล้ว!";
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>เพิ่มงานใหม่ - Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5">
        <div class="card shadow-sm max-w-md mx-auto" style="max-width: 500px;">
            <div class="card-header bg-primary text-white">
                <h4 class="mb-0">เพิ่มงาน/การบ้านใหม่</h4>
            </div>
            <div class="card-body">
                <?php if(isset($success_msg)): ?>
                    <div class="alert alert-success"><?= $success_msg ?></div>
                <?php endif; ?>
                
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">ชื่องาน</label>
                        <input type="text" name="task_name" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">รายละเอียดเพิ่มเติม</label>
                        <textarea name="task_detail" class="form-control" rows="3"></textarea>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">กำหนดส่ง</label>
                        <input type="date" name="due_date" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">บันทึกงาน</button>
                </form>
            </div>
        </div>
        <div class="text-center mt-3">
            <a href="view.php" class="btn btn-outline-secondary">ดูรายการงานทั้งหมด</a>
        </div>
    </div>
</body>
</html>