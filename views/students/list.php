<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="mb-0">👥 รายชื่อนักเรียนในห้อง</h3>
    <div class="d-flex gap-2">
        <input type="text" id="studentSearch" class="form-control form-control-sm" placeholder="ค้นหาชื่อ/เลขที่...">
        <?php if ($_SESSION['role'] !== 'student'): ?>
            <a href="index.php?page=students_add" class="btn btn-sm btn-primary">➕ เพิ่มนักเรียน</a>
        <?php endif; ?>
    </div>
</div>

<div class="card shadow-sm border-0 rounded-4 overflow-hidden">
    <div class="table-responsive">
        <table class="table table-hover align-middle mb-0" id="studentTable">
            <thead class="bg-light">
                <tr>
                    <th class="ps-4">เลขที่</th>
                    <th>ชื่อ-นามสกุล</th>
                    <th>ตำแหน่ง</th>
                    <th style="width: 200px;">ความสมบูรณ์ข้อมูล</th>
                    <th class="text-end pe-4">จัดการ</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($students as $s): 
                    // 1. เช็คสถานะความสมบูรณ์ของข้อมูลสำหรับ Progress Bar
                    $percent = $s['data_completion']['percentage'] ?? 0;
                    $prog_color = ($percent == 100) ? 'bg-success' : (($percent > 50) ? 'bg-info' : 'bg-warning');
                    
                    // 2. 🚨 เช็คสถานะ Active/Inactive (ถ้าไม่มี status ให้ถือว่าเป็น active ไว้ก่อน)
                    $is_active = (!isset($s['status']) || $s['status'] !== 'inactive');
                    
                    // 3. ปรับสไตล์แถว: ถ้าโดนลบ (inactive) ให้แถวจางลงและมีพื้นหลังเทาอ่อน
                    $row_class = $is_active ? '' : 'opacity-50 bg-light';
                ?>
                <tr class="student-row <?= $row_class ?>" data-name="<?= h($s['first_name'].' '.$s['last_name']) ?>" data-no="<?= $s['student_no'] ?>">
                    <td class="ps-4 fw-bold">#<?= $s['student_no'] ?></td>
                    <td>
                        <div class="fw-bold <?= !$is_active ? 'text-decoration-line-through text-muted' : '' ?>">
                            <?= h($s['prefix'].$s['first_name'].' '.$s['last_name']) ?>
                            <?php if (!$is_active): ?>
                                <span class="badge bg-secondary ms-1" style="font-size: 0.65rem;">จำหน่ายแล้ว</span>
                            <?php endif; ?>
                        </div>
                        <small class="text-muted"><?= h($s['nickname'] ?: '-') ?></small>
                    </td>
                    <td><span class="badge bg-light text-dark border"><?= h($s['class_role']) ?></span></td>
                    <td>
                        <div class="d-flex align-items-center gap-2">
                            <div class="progress flex-grow-1" style="height: 8px;">
                                <div class="progress-bar <?= $prog_color ?>" style="width: <?= $percent ?>%"></div>
                            </div>
                            <small class="fw-bold"><?= $percent ?>%</small>
                        </div>
                    </td>
                    <td class="text-end pe-4">
                        <a href="index.php?page=students_profile&no=<?= $s['student_no'] ?>" class="btn btn-sm btn-outline-info shadow-sm" title="ดูโปรไฟล์">👁️</a>
                        
                        <?php if ($_SESSION['role'] !== 'student'): ?>
                            <a href="index.php?page=students_edit&no=<?= $s['student_no'] ?>" class="btn btn-sm btn-outline-primary shadow-sm" title="แก้ไข">✏️</a>
                            
                            <form method="POST" action="index.php?page=students_action" class="d-inline">
                                <input type="hidden" name="student_no" value="<?= $s['student_no'] ?>">
                                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                                
                                <?php if ($is_active): ?>
                                    <input type="hidden" name="status" value="inactive">
                                    <button type="submit" class="btn btn-sm btn-outline-danger shadow-sm" onclick="return confirm('ยืนยันการจำหน่ายนักเรียนเลขที่ <?= $s['student_no'] ?> ออกจากห้อง?')">🗑️</button>
                                <?php else: ?>
                                    <input type="hidden" name="status" value="active">
                                    <button type="submit" class="btn btn-sm btn-outline-success shadow-sm" onclick="return confirm('ต้องการดึงนักเรียนเลขที่ <?= $s['student_no'] ?> กลับเข้าระบบใช่หรือไม่?')">♻️</button>
                                <?php endif; ?>
                            </form>
                        <?php endif; ?>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>

<script>
document.getElementById('studentSearch').addEventListener('input', function(e) {
    const term = e.target.value.toLowerCase();
    document.querySelectorAll('.student-row').forEach(row => {
        const text = (row.dataset.name + row.dataset.no).toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
    });
});
</script>