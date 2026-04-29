<div class="card shadow-sm mx-auto" style="max-width: 600px;">
    <div class="card-header bg-success text-white">
        <h5 class="mb-0">📅 ตั้งตารางเรียนยืนพื้น (จันทร์ - ศุกร์)</h5>
    </div>
    <div class="card-body">
        <?php if(isset($success_msg)): ?>
            <div class="alert alert-success"><?= $success_msg ?></div>
        <?php endif; ?>
        
        <!-- Router: schedules_set -->
        <form method="POST" action="index.php?page=schedules_set">
            <div class="mb-3">
                <label>วันในสัปดาห์</label>
                <select name="day_of_week" class="form-select" required>
                    <option value="จันทร์">จันทร์</option>
                    <option value="อังคาร">อังคาร</option>
                    <option value="พุธ">พุธ</option>
                    <option value="พฤหัสบดี">พฤหัสบดี</option>
                    <option value="ศุกร์">ศุกร์</option>
                </select>
            </div>
            <div class="mb-3">
                <label>👕 ชุดที่ต้องใส่ (เช่น ชุดนักเรียน, ชุดพละ)</label>
                <input type="text" name="attire" class="form-control" required>
            </div>
            <div class="mb-3">
                <label>📚 วิชาเรียน (เรียงตามคาบ)</label>
                <textarea name="subjects" class="form-control" rows="2" placeholder="คณิต, ไทย, อังกฤษ, พักกลางวัน, ฟิสิกส์..." required></textarea>
            </div>
            <button type="submit" class="btn btn-success w-100">บันทึกตารางเรียน</button>
        </form>
    </div>
</div>
<div class="mt-3 text-center">
    <a href="index.php" class="btn btn-outline-secondary">🏠 กลับหน้าหลัก</a>
</div>