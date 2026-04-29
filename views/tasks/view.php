<h3 class="mb-4">📋 รายการงานที่ยังไม่เสร็จ</h3>

<div class="row">
    <?php 
    $today = new DateTime();
    foreach($tasks as $task): 
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
                
                <!-- ส่วนปุ่มจัดการงาน -->
                <div class="card-footer bg-transparent border-top-0 d-flex justify-content-between">
                    <!-- Router: task_action -->
                    <form method="POST" action="index.php?page=task_action" class="d-inline">
                        <input type="hidden" name="task_id" value="<?= $task['id'] ?>">
                        <input type="hidden" name="action" value="mark_done">
                        <button type="submit" class="btn btn-sm btn-outline-success">✅ เสร็จแล้ว</button>
                    </form>

                    <!-- Router: tasks_edit พร้อม id -->
                    <a href="index.php?page=tasks_edit&id=<?= $task['id'] ?>" class="btn btn-sm btn-outline-primary">✏️ แก้ไข</a>

                    <!-- Router: task_action -->
                    <form method="POST" action="index.php?page=task_action" class="d-inline" onsubmit="return confirm('ลบงานนี้ทิ้งเลยไหม?');">
                        <input type="hidden" name="task_id" value="<?= $task['id'] ?>">
                        <input type="hidden" name="action" value="delete">
                        <button type="submit" class="btn btn-sm btn-outline-danger">🗑️ ลบ</button>
                    </form>
                </div>
            </div>
        </div>
    <?php endforeach; ?>
    
    <?php if(empty($tasks)): ?>
        <div class="alert alert-success">🎉 ไม่มีงานค้างเลย</div>
    <?php endif; ?>
</div>

<div class="mt-4 text-center">
    <a href="index.php?page=tasks_add" class="btn btn-primary me-2">➕ เพิ่มงานใหม่</a>
    <a href="index.php" class="btn btn-secondary">🏠 กลับหน้าหลัก</a>
</div>