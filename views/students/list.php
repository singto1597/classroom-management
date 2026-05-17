<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="mb-0">👥 รายชื่อนักเรียนในห้อง</h3>
    <div class="d-flex gap-3 align-items-center">
        <div class="form-check form-switch mb-0">
            <input class="form-check-input" type="checkbox" id="showInactiveToggle">
            <label class="form-check-label small text-muted fw-bold" for="showInactiveToggle">แสดงคนที่ถูกจำหน่าย</label>
        </div>
        
        <input type="text" id="studentSearch" class="form-control form-control-sm" placeholder="ค้นหาชื่อ/เลขที่..." style="max-width: 200px;">
        
        <?php if ($_SESSION['role'] !== 'student'): ?>
            <a href="index.php?page=students_add" class="btn btn-sm btn-primary shadow-sm">➕ เพิ่มนักเรียน</a>
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
                    
                    $is_active = (!isset($s['status']) || $s['status'] !== 'inactive');
                    $row_class = $is_active ? '' : 'opacity-50 bg-light';
                ?>
                <tr class="student-row <?= $row_class ?>" 
                    data-name="<?= h($s['first_name'].' '.$s['last_name']) ?>" 
                    data-no="<?= $s['student_no'] ?>"
                    data-status="<?= $is_active ? 'active' : 'inactive' ?>">
                    
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
                            <?php if ($is_active): ?>
                                <a href="index.php?page=students_edit&no=<?= $s['student_no'] ?>" class="btn btn-sm btn-outline-primary shadow-sm" title="แก้ไข">✏️</a>
                            <?php endif; ?>
                            
                            <form method="POST" action="index.php?page=students_action" class="d-inline">
                                <input type="hidden" name="student_no" value="<?= $s['student_no'] ?>">
                                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                                
                                <?php if ($is_active): ?>
                                    <input type="hidden" name="action_type" value="soft_delete">
                                    <button type="submit" class="btn btn-sm btn-outline-warning shadow-sm" onclick="return confirm('จำหน่ายนักเรียนเลขที่ <?= $s['student_no'] ?> ชั่วคราว?')">🗑️ ซ่อน</button>
                                <?php else: ?>
                                    <input type="hidden" name="action_type" value="restore">
                                    <button type="submit" class="btn btn-sm btn-outline-success shadow-sm" onclick="return confirm('ดึงนักเรียนเลขที่ <?= $s['student_no'] ?> กลับมา?')">♻️ กู้คืน</button>
                                    
                                    <button type="submit" name="action_type" value="hard_delete" class="btn btn-sm btn-danger shadow-sm ms-1" onclick="return confirm('⚠️ คำเตือน: ลบข้อมูลนักเรียนเลขที่ <?= $s['student_no'] ?> ออกจากฐานข้อมูลถาวร กู้คืนไม่ได้แล้วนะ แน่ใจหรือไม่?')">💀 ลบถาวร</button>
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
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('studentSearch');
    const toggleInactive = document.getElementById('showInactiveToggle');
    const rows = document.querySelectorAll('.student-row');

    // 🧠 ฟังก์ชันกรองตาราง (ประมวลผลทั้ง Search และ Toggle พร้อมกัน)
    function filterTable() {
        const term = searchInput.value.toLowerCase();
        const showInactive = toggleInactive.checked;

        rows.forEach(row => {
            const text = (row.dataset.name + row.dataset.no).toLowerCase();
            const status = row.dataset.status; // 'active' หรือ 'inactive'

            // เช็คว่าผ่านเงื่อนไขการค้นหามั้ย?
            const matchSearch = text.includes(term);
            // เช็คว่าผ่านเงื่อนไขสถานะมั้ย? (ถ้าเปิดสวิตช์ = ดูได้หมด, ถ้าปิดสวิตช์ = ดูได้แค่ active)
            const matchStatus = showInactive ? true : (status === 'active');

            if (matchSearch && matchStatus) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    searchInput.addEventListener('input', filterTable);
    toggleInactive.addEventListener('change', filterTable);
    
    // รันฟังก์ชันนี้ 1 รอบตอนเปิดหน้าเว็บ เพื่อซ่อนคนที่ Inactive ตั้งแต่แรก
    filterTable();
});
</script>