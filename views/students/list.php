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
                    $percent = $s['data_completion']['percentage'] ?? 0;
                    $prog_color = ($percent == 100) ? 'bg-success' : (($percent > 50) ? 'bg-info' : 'bg-warning');
                ?>
                <tr class="student-row" data-name="<?= h($s['first_name'].' '.$s['last_name']) ?>" data-no="<?= $s['student_no'] ?>">
                    <td class="ps-4 fw-bold">#<?= $s['student_no'] ?></td>
                    <td>
                        <div class="fw-bold"><?= h($s['prefix'].$s['first_name'].' '.$s['last_name']) ?></div>
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
                        <a href="index.php?page=students_profile&no=<?= $s['student_no'] ?>" class="btn btn-sm btn-outline-info shadow-sm">👁️ ดูข้อมูล</a>
                        
                        <?php if ($_SESSION['role'] !== 'student'): ?>
                            <a href="index.php?page=students_edit&no=<?= $s['student_no'] ?>" class="btn btn-sm btn-outline-primary shadow-sm">✏️</a>
                            <form method="POST" action="index.php?page=students_action" class="d-inline">
                                <input type="hidden" name="student_no" value="<?= $s['student_no'] ?>">
                                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                                <input type="hidden" name="status" value="inactive">
                                <button type="submit" class="btn btn-sm btn-outline-danger shadow-sm" onclick="return confirm('จำหน่ายนักเรียนคนนี้ออก?')">🗑️</button>
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