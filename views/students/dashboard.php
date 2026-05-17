<div class="row mb-4">
    <div class="col-md-12">
        <div class="card border-0 shadow-sm rounded-4 bg-primary text-white p-4">
            <h2 class="fw-bold mb-0">สวัสดี! คุณ<?= h($_SESSION['user_name']) ?></h2>
            <p class="mb-0">วันนี้มีงานค้างอยู่ <strong>3 งาน</strong> และมีคนกรอกข้อมูลโปรไฟล์ไม่ครบ <strong>12 คน</strong></p>
        </div>
    </div>
</div>

<div class="row g-4">
    <div class="col-md-6">
        <div class="card h-100 shadow-sm border-0 rounded-4">
            <div class="card-body">
                <h5 class="fw-bold mb-3">📅 ตารางเรียนและงาน</h5>
                <a href="index.php?page=tasks" class="btn btn-outline-primary w-100 rounded-pill">ดูรายการงานทั้งหมด</a>
            </div>
        </div>
    </div>

    <div class="col-md-6">
        <div class="card h-100 shadow-sm border-0 rounded-4">
            <div class="card-body">
                <h5 class="fw-bold mb-3">👥 ข้อมูลนักเรียนในห้อง</h5>
                <div class="d-flex align-items-center mb-3">
                    <div class="flex-grow-1">
                        <div class="small text-muted">ความสมบูรณ์ของข้อมูลห้อง</div>
                        <div class="fw-bold h4 mb-0">85%</div>
                    </div>
                    <div class="progress flex-grow-1 mx-3" style="height: 10px;">
                        <div class="progress-bar bg-success" style="width: 85%"></div>
                    </div>
                </div>
                <div class="row g-2">
                    <div class="col-6"><a href="index.php?page=students" class="btn btn-light w-100 border text-start">📑 รายชื่อนักเรียน</a></div>
                    <div class="col-6"><a href="index.php?page=students_me" class="btn btn-light w-100 border text-start">🪪 โปรไฟล์ของฉัน</a></div>
                    <?php if ($_SESSION['role'] !== 'student'): ?>
                        <div class="col-12"><a href="index.php?page=students_add" class="btn btn-primary w-100 rounded-pill mt-2">➕ เพิ่ม/จัดการรายชื่อ</a></div>
                    <?php endif; ?>
                </div>
            </div>
        </div>
    </div>
</div>