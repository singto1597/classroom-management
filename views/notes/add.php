<div class="card shadow-sm mx-auto" style="max-width: 600px;">
    <div class="card-header bg-warning text-dark">
        <h5 class="mb-0">📌 เพิ่มโน้ตรายวัน / ประกาศพิเศษ</h5>
    </div>
    <div class="card-body">
        <?php if(isset($success_msg)): ?>
            <div class="alert alert-success"><?= $success_msg ?></div>
        <?php endif; ?>
        <form method="POST" action="index.php?page=notes">
            <div class="mb-3">
                <label>วันที่เป้าหมาย</label>
                <input type="date" name="target_date" class="form-control" required>
            </div>
            <div class="mb-3">
                <label>🎒 สิ่งที่ต้องเตรียม</label>
                <input type="text" name="bring_items" class="form-control" placeholder="ถ้าไม่มีใส่ -">
            </div>
            <div class="mb-3">
                <label>📢 ประกาศ</label>
                <textarea name="announcement" class="form-control" rows="2" placeholder="ถ้าไม่มีใส่ -"></textarea>
            </div>
            <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
            <button type="submit" class="btn btn-warning w-100">บันทึกโน้ต</button>
        </form>
    </div>
</div>
<div class="mt-3 text-center">
    <a href="index.php" class="btn btn-outline-secondary">กลับหน้าหลัก</a>
</div>