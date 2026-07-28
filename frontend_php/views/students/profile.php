<?php 
// เช็คสิทธิ์: ถ้าเป็นนักเรียนธรรมดา ให้เซ็นเซอร์ข้อมูล
$is_admin = ($_SESSION['role'] !== 'student'); 
$mask = function($data) use ($is_admin) {
    if (empty($data)) return '-';
    // if ($is_admin) return htmlspecialchars($data);
    return htmlspecialchars($data);
    // return '<span class="text-muted">🔒 (ซ่อนข้อมูลส่วนตัว)</span>';
};
?>
<div class="max-w-4xl mx-auto" style="max-width: 800px;">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <a href="index.php?page=students" class="btn btn-outline-secondary btn-sm">⬅️ กลับไปหน้ารายชื่อ</a>
        <?php if ($is_admin): ?>
            <a href="index.php?page=students_edit&no=<?= $profile['student_no'] ?>" class="btn btn-primary btn-sm shadow-sm">✏️ แก้ไขข้อมูลคนนี้</a>
        <?php endif; ?>
    </div>

    <div class="card shadow border-0 rounded-4">
        <div class="card-header bg-dark text-white p-4 rounded-top-4 d-flex justify-content-between align-items-center">
            <div>
                <h2 class="mb-0 fw-bold">💳 บัตรนักเรียน: <?= h($profile['prefix'].$profile['first_name'].' '.$profile['last_name']) ?></h2>
                <p class="mb-0 text-light opacity-75">ชื่อเล่น: <?= h($profile['nickname'] ?: '-') ?></p>
            </div>
            <div class="bg-white text-dark p-2 rounded-3 text-center" style="min-width: 80px;">
                <small class="d-block fw-bold text-muted">เลขที่</small>
                <span class="h3 fw-bold mb-0"><?= $profile['student_no'] ?></span>
            </div>
        </div>
        <div class="card-body p-4">
            <div class="row g-4">
                <div class="col-md-6">
                    <h5 class="fw-bold text-primary mb-3">📚 วิชาการและตำแหน่ง</h5>
                    <ul class="list-group list-group-flush">
                        <li class="list-group-item px-0"><strong>ตำแหน่ง:</strong> <?= h($profile['class_role']) ?></li>
                        <li class="list-group-item px-0"><strong>คณะที่ใฝ่ฝัน:</strong> <?= h($profile['target_faculty'] ?: '-') ?></li>
                        <li class="list-group-item px-0"><strong>เวรทำความสะอาด:</strong> <?= h($profile['cleaning_duty'] ?: '-') ?></li>
                    </ul>
                </div>
                <div class="col-md-6">
                    <h5 class="fw-bold text-danger mb-3">🔒 ข้อมูลการติดต่อ</h5>
                    <ul class="list-group list-group-flush">
                        <li class="list-group-item px-0"><strong>เบอร์โทร:</strong> <?= $mask($profile['phone_number']) ?></li>
                        <li class="list-group-item px-0"><strong>Line ID:</strong> <?= $mask($profile['line_id']) ?></li>
                        <li class="list-group-item px-0"><strong>IG:</strong> <?= $mask($profile['ig_username']) ?></li>
                    </ul>
                </div>
                <div class="col-12">
                    <div class="p-3 bg-light rounded-3 border">
                        <h6 class="fw-bold text-primary mb-2">🏆 ผลงานและค่ายวิชาการ</h6>
                        <p class="mb-0 small"><?= nl2br(h($profile['portfolio'] ?: 'ยังไม่มีข้อมูลผลงาน')) ?></p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>