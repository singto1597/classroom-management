<div class="card shadow-sm max-w-md mx-auto" style="max-width: 500px;">
    <div class="card-header bg-primary text-white">
        <h4 class="mb-0">เพิ่มงาน/การบ้านใหม่</h4>
    </div>
    <div class="card-body">
        <?php if(isset($success_msg)): ?>
            <div class="alert alert-success"><?= $success_msg ?></div>
        <?php endif; ?>
        
        <!-- อยู่หน้าเดิม -->
        <form method="POST" action="index.php?page=tasks_add">
            <div class="mb-3">
                <label class="form-label">ชื่องาน</label>
                <input type="text" name="task_name" class="form-control" required>
            </div>
            <div class="mb-3">
                <label class="form-label">รายละเอียด</label>
                <textarea name="task_detail" class="form-control" rows="3"></textarea>
            </div>
            <div class="mb-3">
                <label class="form-label">กำหนดส่ง</label>
                <input type="date" name="due_date" class="form-control" required>
            </div>
            <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
            <button type="submit" class="btn btn-primary w-100">บันทึกงาน</button>
        </form>
    </div>
</div>
<div class="text-center mt-3">
    <a href="index.php?page=tasks" class="btn btn-outline-secondary">กลับหน้ารายการงาน</a>
</div>