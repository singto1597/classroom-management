<?php
require 'db.php';

$room_id = $_SESSION['room_id'];
// คำสั่ง SQL ดึงเฉพาะงานที่ status = 'pending'[cite: 2]
$stmt = $pdo->prepare("SELECT * FROM tasks WHERE room_id = ? AND status = 'pending' ORDER BY due_date ASC");
$stmt->execute([$room_id]);
$tasks = $stmt->fetchAll();

$today = new DateTime();
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>รายการงานค้าง - Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5">
        <h3 class="mb-4">📋 รายการงานที่ยังไม่เสร็จ</h3>
        
        <div class="row">
            <?php foreach($tasks as $task): 
                $due_date = new DateTime($task['due_date']);
                $interval = $today->diff($due_date);
                $days_left = (int)$interval->format('%R%a');
                
                $badge_class = 'bg-success';
                $status_text = "เหลืออีก {$days_left} วัน";
                
                if ($days_left < 0) {
                    $badge_class = 'bg-danger';
                    $status_text = "เลยกำหนดมา " . abs($days_left) . " วัน!";
                } elseif ($days_left == 0) {
                    $badge_class = 'bg-warning text-dark';
                    $status_text = "ส่งวันนี้!";
                } elseif ($days_left == 1) {
                    $badge_class = 'bg-warning text-dark';
                    $status_text = "ส่งพรุ่งนี้!";
                }
                
            ?>
                <div class="col-md-4 mb-3">
                    <div class="card shadow-sm h-100">
                        <div class="card-body">
                            <h5 class="card-title">📌 <?= htmlspecialchars($task['task_name']) ?></h5>
                            <h6 class="card-subtitle mb-2 text-muted">กำหนดส่ง: <?= $task['due_date'] ?></h6>
                            <p class="card-text"><?= htmlspecialchars($task['task_detail']) ?></p>
                            <span class="badge <?= $badge_class ?>"><?= $status_text ?></span>
                        </div>
                    </div>
                </div>
                <div class="card-footer bg-transparent border-top-0 d-flex justify-content-between">
                    <!-- ฟอร์มสำหรับ Mark Done -->
                    <form method="POST" action="task_action.php" class="d-inline">
                        <input type="hidden" name="task_id" value="<?= $task['id'] ?>">
                        <input type="hidden" name="action" value="mark_done">
                        <button type="submit" class="btn btn-sm btn-outline-success">✅ เสร็จแล้ว</button>
                    </form>

                    <a href="edit_task.php?id=<?= $task['id'] ?>" class="btn btn-sm btn-outline-primary">✏️ แก้ไข</a>

                    <!-- ฟอร์มสำหรับ Delete -->
                    <form method="POST" action="task_action.php" class="d-inline" onsubmit="return confirm('ลบงานนี้ทิ้งเลยไหม?');">
                        <input type="hidden" name="task_id" value="<?= $task['id'] ?>">
                        <input type="hidden" name="action" value="delete">
                        <button type="submit" class="btn btn-sm btn-outline-danger">🗑️ ลบ</button>
                    </form>
                </div>
            <?php endforeach; ?>
            
            <?php if(empty($tasks)): ?>
                <div class="alert alert-info">ไม่มีงานค้างเลย</div>
            <?php endif; ?>
        </div>
        <div class="mt-3">
            <a href="index.php" class="btn btn-secondary">กลับไปหน้าเพิ่มงาน</a>
            <a href="cron_simulator.php" class="btn btn-warning">ดูหน้าจำลองแจ้งเตือน (Cron)</a>
        </div>
    </div>
</body>
</html>