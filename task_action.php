<?php
require 'db.php';

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $task_id = $_POST['task_id'];
    $action = $_POST['action'];
    $room_id = $_SESSION['room_id'];

    // ขอดึงชื่องานมาก่อน จะได้เอาไปบันทึกใน Log ได้ว่าลบงานอะไรไป (เหมือน _returning ใน Python)
    $stmt_get = $pdo->prepare("SELECT task_name FROM tasks WHERE id = ? AND room_id = ?");
    $stmt_get->execute([$task_id, $room_id]);
    $task = $stmt_get->fetch();
    
    if (!$task) {
        die("ไม่พบงานนี้ หรือคุณไม่มีสิทธิ์");
    }
    $task_name = $task['task_name'];

    if ($action == 'mark_done') {
        // อัปเดตสถานะเป็น done
        $stmt = $pdo->prepare("UPDATE tasks SET status = 'done' WHERE id = ? AND room_id = ?");
        $stmt->execute([$task_id, $room_id]);
        
        // บันทึก Log
        logAction($pdo, "Mark Done", "ส่งงาน: " . $task_name);

    } elseif ($action == 'delete') {
        // ลบงานทิ้ง
        $stmt = $pdo->prepare("DELETE FROM tasks WHERE id = ? AND room_id = ?");
        $stmt->execute([$task_id, $room_id]);
        
        // บันทึก Log[cite: 1]
        logAction($pdo, "Delete Task", "ลบงาน: " . $task_name);
    }
    
    header("Location: view.php");
    exit();
}
?>