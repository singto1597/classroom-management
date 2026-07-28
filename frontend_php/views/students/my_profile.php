<div class="max-w-4xl mx-auto">
    <div class="card shadow border-0 rounded-4 mb-4">
        <div class="card-header bg-primary text-white p-4 rounded-top-4 d-flex justify-content-between align-items-center">
            <div>
                <h2 class="mb-0 fw-bold">💳 บัตรประจำตัวนักเรียน</h2>
                <p class="mb-0 opacity-75">ข้อมูลโปรไฟล์ในระบบ Classroom-Sync</p>
            </div>
            <a href="index.php?page=students_edit&no=<?= $profile['student_no'] ?>" class="btn btn-light fw-bold rounded-pill px-4">✏️ แก้ไขข้อมูล</a>
        </div>
        <div class="card-body p-4">
            <div class="row mb-4 align-items-center">
                <div class="col-md-8">
                    <h1 class="display-6 fw-bold"><?= h($profile['prefix'].$profile['first_name'].' '.$profile['last_name']) ?></h1>
                    <h4 class="text-primary"><?= h($profile['nickname'] ? "({$profile['nickname']})" : "") ?></h4>
                </div>
                <div class="col-md-4 text-md-end">
                    <div class="p-3 bg-light rounded-3 border d-inline-block text-center">
                        <small class="text-muted d-block">เลขที่</small>
                        <span class="display-5 fw-bold"><?= $profile['student_no'] ?></span>
                    </div>
                </div>
            </div>

            <hr class="opacity-10">

            <div class="row g-4">
                <div class="col-md-6">
                    <h5 class="fw-bold mb-3 text-primary">📚 วิชาการและหน้าที่</h5>
                    <ul class="list-group list-group-flush">
                        <li class="list-group-item d-flex justify-content-between px-0"><span>บทบาท:</span> <strong><?= h($profile['class_role']) ?></strong></li>
                        <li class="list-group-item d-flex justify-content-between px-0"><span>เวรทำความสะอาด:</span> <strong><?= h($profile['cleaning_duty'] ?: '-') ?></strong></li>
                        <li class="list-group-item d-flex justify-content-between px-0"><span>คณะที่ใฝ่ฝัน:</span> <strong><?= h($profile['target_faculty'] ?: '-') ?></strong></li>
                    </ul>
                </div>
                <div class="col-md-6">
                    <h5 class="fw-bold mb-3 text-danger">🏥 ข้อมูลสุขภาพ</h5>
                    <div class="row g-2">
                        <div class="col-6"><div class="p-2 bg-light rounded border text-center small">เลือด: <strong><?= h($profile['blood_group'] ?: '-') ?></strong></div></div>
                        <div class="col-6"><div class="p-2 bg-light rounded border text-center small">เสื้อ: <strong><?= h($profile['shirt_size'] ?: '-') ?></strong></div></div>
                        <div class="col-12"><div class="p-2 bg-light rounded border text-center small">โรค/แพ้อาหาร: <strong><?= h($profile['food_allergy'] ?: '-') ?></strong></div></div>
                    </div>
                </div>
            </div>

            <div class="mt-4 p-3 bg-primary bg-opacity-10 rounded-3 border-start border-primary border-4">
                <h6 class="fw-bold text-primary mb-2">🏆 ผลงานและค่ายวิชาการ</h6>
                <p class="mb-0 small"><?= nl2br(h($profile['portfolio'] ?: 'ยังไม่มีข้อมูลผลงาน')) ?></p>
            </div>
        </div>
    </div>
</div>