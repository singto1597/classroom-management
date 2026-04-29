<?php
require 'db.php';
$output_message = "";

if (isset($_POST['simulate'])) {
    $room_id = $_SESSION['room_id'];
    
    // ตั้งค่าเวลาไทย
    date_default_timezone_set('Asia/Bangkok');
    $tomorrow = new DateTime('tomorrow');
    $target_date = $tomorrow->format('Y-m-d');
    
    // หาวันภาษาไทย
    $thai_days = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
    $day_index = $tomorrow->format('w');
    $day_name = $thai_days[$day_index];

    // โครงสร้างข้อมูลเริ่มต้น
    $data = [
        "attire" => "-", "subjects" => "-", "bring" => "-", "note" => "-", "tasks" => []
    ];

    try {
        // 1. ดึงตารางเรียนยืนพื้น (default_schedules)
        $stmt = $pdo->prepare("SELECT attire, subjects FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
        $stmt->execute([$room_id, $day_name]);
        if ($row = $stmt->fetch()) {
            $data['attire'] = $row['attire'];
            $data['subjects'] = $row['subjects'];
        }

        // 2. ดึงข้อยกเว้นฉุกเฉิน (schedule_overrides)
        $stmt = $pdo->prepare("SELECT new_attire, note FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
        $stmt->execute([$room_id, $target_date]);
        $override = $stmt->fetch();
        if ($override) {
            $data['attire'] = "🚨 " . htmlspecialchars($override['new_attire']) . " (กรณีพิเศษ)";
            $data['note'] = htmlspecialchars($override['note']);
        }

        // 3. ดึงโน้ตรายวัน (daily_notes)
        $stmt = $pdo->prepare("SELECT bring_items, announcement FROM daily_notes WHERE room_id = ? AND target_date = ?");
        $stmt->execute([$room_id, $target_date]);
        if ($note_data = $stmt->fetch()) {
            $data['bring'] = htmlspecialchars($note_data['bring_items']);
            if (!$override && $note_data['announcement']) {
                $data['note'] = htmlspecialchars($note_data['announcement']); 
            }
        }

        // 4. ดึงงานค้างทั้งหมดที่สถานะยัง pending
        $stmt = $pdo->prepare("SELECT task_name, due_date FROM tasks WHERE room_id = ? AND status = 'pending' ORDER BY due_date ASC");
        $stmt->execute([$room_id]);
        $today = new DateTime('today');
        
        while ($t = $stmt->fetch()) {
            $due = new DateTime($t['due_date']);
            $diff = (int)$today->diff($due)->format('%R%a');
            
            if ($diff < 0) {
                $status = "🔴 <b>(เลยกำหนดมา ".abs($diff)." วัน!)</b>";
            } elseif ($diff == 0) {
                $status = "🔥 <b>(ส่งวันนี้!)</b>";
            } elseif ($diff == 1) {
                $status = "⚠️ <b>(ส่งพรุ่งนี้!)</b>";
            } else {
                $status = "🟢 (เหลืออีก $diff วัน)";
            }
            $data['tasks'][] = "• " . htmlspecialchars($t['task_name']) . " " . $status;
        }

        // ==========================================
        // สร้างข้อความแจ้งเตือน
        // ==========================================
        $output_message = "📢 <strong>@everyone สรุปตารางเรียนและงานของวันพรุ่งนี้</strong><br><br>";
        $output_message .= "📅 <strong>วัน{$day_name}ที่ {$target_date}</strong><br>";
        $output_message .= "👕 <strong>ชุดที่ต้องใส่:</strong> {$data['attire']}<br>";
        $output_message .= "📚 <strong>วิชาเรียน:</strong> {$data['subjects']}<br>";
        
        if ($data['bring'] !== "-") $output_message .= "🎒 <strong>สิ่งที่ต้องเตรียม:</strong> {$data['bring']}<br>";
        if ($data['note'] !== "-") $output_message .= "📢 <strong>ประกาศ/หมายเหตุ:</strong> {$data['note']}<br>";
        
        $output_message .= "<br>====================<br>";
        
        if (count($data['tasks']) > 0) {
            $output_message .= "⚠️ <strong>ลิสต์งานค้างทั้งหมด!</strong><br>";
            foreach ($data['tasks'] as $task_str) {
                $output_message .= $task_str . "<br>";
            }
        } else {
            $output_message .= "✅ <strong>ลิสต์งานค้างทั้งหมด!</strong><br>ไม่มีงานจ้า<br>";
        }

    } catch (PDOException $e) {
        $output_message = "<div class='text-danger'>❌ เกิดข้อผิดพลาดในฐานข้อมูล: " . $e->getMessage() . "</div>";
    }
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>Cron Simulator - Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-dark text-white">
    <div class="container mt-5 text-center">
        <h2>🛠️ Cron Job Simulator</h2>
        <p class="text-secondary">จำลองการทำงานของระบบที่จะเด้งแจ้งเตือนตอน 19:00 น.</p>
        
        <form method="POST" class="mb-4">
            <button type="submit" name="simulate" class="btn btn-lg btn-danger shadow">
                ⚡ กดเพื่อจำลองเวลา 19:00 น.
            </button>
        </form>

        <?php if($output_message): ?>
            <div class="card bg-secondary text-white text-start mx-auto shadow" style="max-width: 600px;">
                <div class="card-header bg-primary text-white font-weight-bold">
                    💬 ข้อความที่จะถูกส่งเข้ากลุ่มแชทของโรงเรียน (Mockup)
                </div>
                <div class="card-body" style="font-size: 1.1em; line-height: 1.6;">
                    <?= $output_message ?>
                </div>
            </div>
        <?php endif; ?>
        
        <div class="mt-5">
            <a href="index.php" class="btn btn-outline-light me-2">เพิ่มงานใหม่</a>
            <a href="view.php" class="btn btn-outline-light me-2">หน้ารายการงาน</a>
            <a href="note.php" class="btn btn-outline-light">จัดการโน้ตรายวัน</a>
        </div>
    </div>
</body>
</html>