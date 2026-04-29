<div class="card shadow-sm border-danger mx-auto" style="max-width: 600px;">
    <div class="card-header bg-danger text-white">
        <h5 class="mb-0">🚨 ตั้งข้อยกเว้นฉุกเฉิน (เปลี่ยนชุด/กิจกรรมพิเศษ)</h5>
    </div>
    <div class="card-body">
        <?php if(isset($success_msg)): ?>
            <div class="alert alert-success"><?= $success_msg ?></div>
        <?php endif; ?>
        
        <!-- Router: schedules_override -->
        <form method="POST" action="index.php?page=schedules_override">
            <div class="mb-3">
                <label>วันที่เกิดการยกเว้น</label>
                <input type="date" name="target_date" class="form-control" required>
            </div>
            <div class="mb-3">
                <label>👕 ชุดใหม่ที่ต้องใส่</label>
                <input type="text" name="new_attire" class="form-control" placeholder="เช่น ชุดนักเรียน, ชุดพละ" required>
            </div>
            <div class="mb-3">
                <label>📢 หมายเหตุ / สาเหตุที่เปลี่ยน</label>
                <textarea name="note" class="form-control" rows="2" placeholder="เช่น มีกิจกรรม...จึงต้องใส่ชุดนักเรียน" required></textarea>
            </div>
            <button type="submit" class="btn btn-danger w-100">บันทึกข้อยกเว้น</button>
        </form>
    </div>
</div>
<div class="mt-3 text-center">
    <a href="index.php" class="btn btn-outline-secondary">🏠 กลับหน้าหลัก</a>
</div>