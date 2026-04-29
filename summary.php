<?php
require 'db.php';

$room_id = $_SESSION['room_id'];
$room_name = $_SESSION['room_name'];

// ตรวจสอบว่าผู้ใช้กดดู 'today' หรือ 'tomorrow' (ค่าเริ่มต้นคือ today)
$view_mode = isset($_GET['day']) && $_GET['day'] == 'tomorrow' ? 'tomorrow' : 'today';

date_default_timezone_set('Asia/Bangkok');
$target_date_obj = new DateTime($view_mode);
$target_date = $target_date_obj->format('Y-m-d');

$thai_days = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
$day_name = $thai_days[$target_date_obj->format('w')];

// โครงสร้างข้อมูล (ลอจิกเดียวกับ fetch_daily_summary[cite: 1])
$data = ["attire" => "-", "subjects" => "-", "bring" => "-", "note" => "-", "tasks" => []];

// 1. ดึงตารางยืนพื้น
$stmt = $pdo->prepare("SELECT attire, subjects FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
$stmt->execute([$room_id, $day_name]);
if ($row = $stmt->fetch()) {
    $data['attire'] = $row['attire'];
    $data['subjects'] = $row['subjects'];
}

// 2. ดึงข้อยกเว้น
$stmt = $pdo->prepare("SELECT new_attire, note FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
$stmt->execute([$room_id, $target_date]);
if ($override = $stmt->fetch()) {
    $data['attire'] = "🚨 " . htmlspecialchars($override['new_attire']) . " (กรณีพิเศษ)";
    $data['note'] = htmlspecialchars($override['note']);
}

// 3. ดึงโน้ตรายวัน
$stmt = $pdo->prepare("SELECT bring_items, announcement FROM daily_notes WHERE room_id = ? AND target_date = ?");
$stmt->execute([$room_id, $target_date]);
if ($note_data = $stmt->fetch()) {
    $data['bring'] = htmlspecialchars($note_data['bring_items']);
    if (!$override && $note_data['announcement']) {
        $data['note'] = htmlspecialchars($note_data['announcement']); 
    }
}

// 4. ดึงงานค้าง (ลอจิกแจ้งเตือนสถานะ[cite: 1])
$stmt = $pdo->prepare("SELECT task_name, due_date FROM tasks WHERE room_id = ? AND status = 'pending' ORDER BY due_date ASC");
$stmt->execute([$room_id]);
$today = new DateTime('today');

while ($t = $stmt->fetch()) {
    $due = new DateTime($t['due_date']);
    $diff = (int)$today->diff($due)->format('%R%a');
    
    if ($diff < 0) {
        $status = "<span class='badge bg-danger'>เลยกำหนด $diff วัน!</span>";
    } elseif ($diff == 0) {
        $status = "<span class='badge bg-warning text-dark'>ส่งวันนี้!</span>";
    } elseif ($diff == 1) {
        $status = "<span class='badge bg-warning text-dark'>ส่งพรุ่งนี้!</span>";
    } else {
        $status = "<span class='badge bg-success'>เหลือ $diff วัน</span>";
    }
    $data['tasks'][] = "📌 " . htmlspecialchars($t['task_name']) . " " . $status;
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>สรุปตาราง - Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5" style="max-width: 700px;">
        
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h3 class="fw-bold">🏫 ห้องเรียน: <?= htmlspecialchars($room_name) ?></h3>
            <div class="btn-group">
                <a href="summary.php?day=today" class="btn <?= $view_mode == 'today' ? 'btn-primary' : 'btn-outline-primary' ?>">☀️ สรุปวันนี้</a>
                <a href="summary.php?day=tomorrow" class="btn <?= $view_mode == 'tomorrow' ? 'btn-dark' : 'btn-outline-dark' ?>">🌙 สรุปพรุ่งนี้</a>
            </div>
        </div>

        <div class="card shadow-sm border-0 mb-4">
            <div class="card-header <?= $view_mode == 'today' ? 'bg-primary' : 'bg-dark' ?> text-white">
                <h5 class="mb-0">📅 วัน<?= $day_name ?>ที่ <?= $target_date ?></h5>
            </div>
            <div class="card-body">
                <div class="row mb-3">
                    <div class="col-sm-4 text-muted fw-bold">👕 ชุดที่ต้องใส่</div>
                    <div class="col-sm-8"><?= $data['attire'] ?></div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-4 text-muted fw-bold">📚 วิชาเรียน</div>
                    <div class="col-sm-8"><?= $data['subjects'] ?></div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-4 text-muted fw-bold">🎒 สิ่งที่ต้องเตรียม</div>
                    <div class="col-sm-8"><?= $data['bring'] ?></div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-4 text-muted fw-bold">📢 ประกาศ</div>
                    <div class="col-sm-8"><?= $data['note'] ?></div>
                </div>
                <hr>
                <h6 class="fw-bold text-danger">⚠️ ลิสต์งานค้างทั้งหมด</h6>
                <?php if (count($data['tasks']) > 0): ?>
                    <ul class="list-unstyled">
                        <?php foreach ($data['tasks'] as $task_str): ?>
                            <li class="mb-2"><?= $task_str ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php else: ?>
                    <div class="alert alert-success">ไม่มีงานค้างเลยจ้า! พักผ่อนได้! 🎉</div>
                <?php endif; ?>
            </div>
        </div>

        <div class="text-center">
            <a href="index.php" class="btn btn-secondary">กลับหน้า Dashboard</a>
        </div>
    </div>
</body>
</html>