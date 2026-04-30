<div class="card shadow-sm mx-auto" style="max-width: 500px;">
    <div class="card-header bg-primary text-white">
        <h4 class="mb-0">✏️ แก้ไขงาน</h4>
    </div>
    <div class="card-body">
        <!-- Controller: tasks_edit -->
        <form method="POST" action="index.php?page=tasks_edit&id=<?= $task['id'] ?>">
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
            <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
            <button type="submit" class="btn btn-primary w-100">บันทึกการแก้ไข</button>
            <a href="index.php?page=tasks" class="btn btn-secondary w-100 mt-2">ยกเลิก</a>
        </form>
    </div>
</div>