<?php
require 'db.php';

// ถ้าไม่ได้ส่ง id มา ให้เด้งกลับ
if (!isset($_GET['id'])) {
    header("Location: view.php");
    exit();
}

$task_id = $_GET['id'];

// บันทึกการแก้ไขเมื่อกด Submit
if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $task_name = $_POST['task_name'];
    $task_detail = $_POST['task_detail'];
    $due_date = $_POST['due_date'];

    $stmt = $pdo->prepare("UPDATE tasks SET task_name = ?, task_detail = ?, due_date = ? WHERE id = ?");
    $stmt->execute([$task_name, $task_detail, $due_date, $task_id]);
    
    header("Location: view.php");
    exit();
}

// ดึงข้อมูลเดิมมาแสดง
$stmt = $pdo->prepare("SELECT * FROM tasks WHERE id = ?");
$stmt->execute([$task_id]);
$task = $stmt->fetch();

if (!$task) {
    die("ไม่พบข้อมูลงานนี้!");
}
?>

<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>แก้ไขงาน</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5">
        <div class="card shadow-sm mx-auto" style="max-width: 500px;">
            <div class="card-header bg-primary text-white">
                <h4 class="mb-0">✏️ แก้ไขงาน</h4>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="mb-3">
                        <label>ชื่องาน</label>
                        <input type="text" name="task_name" class="form-control" value="<?= htmlspecialchars($task['task_name']) ?>" required>
                    </div>
                    <div class="mb-3">
                        <label>รายละเอียด</label>
                        <textarea name="task_detail" class="form-control" rows="3"><?= htmlspecialchars($task['task_detail']) ?></textarea>
                    </div>
                    <div class="mb-3">
                        <label>กำหนดส่ง</label>
                        <input type="date" name="due_date" class="form-control" value="<?= $task['due_date'] ?>" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">บันทึกการแก้ไข</button>
                    <a href="view.php" class="btn btn-secondary w-100 mt-2">ยกเลิก</a>
                </form>
            </div>
        </div>
    </div>
</body>
</html>