<div class="row mb-4">
    <div class="col-md-12">
        <div class="card border-0 shadow-sm rounded-4 bg-primary text-white p-4">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <h2 class="fw-bold mb-0">สวัสดี! คุณ<?= h($_SESSION['user_name']) ?></h2>
                    <p class="mb-0 opacity-75">ยินดีต้อนรับสู่ระบบจัดการห้องเรียน <?= h($_SESSION['room_name']) ?></p>
                </div>
                <div class="text-end">
                    <span class="badge bg-white text-primary rounded-pill px-3 py-2">
                        สถานะ: <?= h($_SESSION['role']) ?>
                    </span>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="row g-4">
    <div class="col-lg-7">
        <div class="card h-100 shadow-sm border-0 rounded-4">
            <div class="card-header bg-white border-0 pt-4 px-4">
                <h5 class="fw-bold mb-0"><i class="bi bi-journal-check text-primary me-2"></i> ระบบงานและตารางเรียน</h5>
            </div>
            <div class="card-body p-4">
                <div class="row g-3">
                    <div class="col-sm-6"><a href="index.php?page=tasks" class="btn btn-primary w-100 py-3 fw-bold shadow-sm">📋 ดูรายการงานทั้งหมด</a></div>
                    <div class="col-sm-6"><a href="index.php?page=tasks_add" class="btn btn-outline-primary w-100 py-3 shadow-sm">➕ เพิ่มงานใหม่</a></div>
                    <div class="col-sm-6"><a href="index.php?page=notes" class="btn btn-light border w-100 py-3 shadow-sm">📌 โน้ตรายวัน/ประกาศ</a></div>
                    <div class="col-sm-6"><a href="index.php?page=cron" class="btn btn-dark w-100 py-3 shadow-sm">⏰ ทดสอบระบบแจ้งเตือน</a></div>
                </div>
                
                <hr class="my-4 opacity-10">
                
                <h6 class="fw-bold mb-3 text-muted">⚙️ ตั้งค่าระบบห้องเรียน</h6>
                <div class="d-flex gap-2">
                    <a href="index.php?page=schedules_set" class="btn btn-sm btn-outline-secondary px-3 shadow-sm">ตารางเรียนยืนพื้น</a>
                    <a href="index.php?page=schedules_override" class="btn btn-sm btn-outline-danger px-3 shadow-sm">ตั้งข้อยกเว้นฉุกเฉิน</a>
                </div>
            </div>
        </div>
    </div>

    <div class="col-lg-5">
        <div class="card h-100 shadow-sm border-0 rounded-4">
            <div class="card-header bg-white border-0 pt-4 px-4">
                <h5 class="fw-bold mb-0"><i class="bi bi-people text-success me-2"></i> ฐานข้อมูลนักเรียน</h5>
            </div>
            <div class="card-body p-4">
                <div class="d-grid gap-3">
                    <a href="index.php?page=students" class="btn btn-success py-3 fw-bold shadow-sm">📑 ดูรายชื่อนักเรียนทั้งห้อง</a>
                    <a href="index.php?page=students_me" class="btn btn-outline-success py-3 shadow-sm">🪪 ข้อมูลโปรไฟล์ของฉัน</a>
                    
                    <?php if ($_SESSION['role'] !== 'student'): ?>
                        <a href="index.php?page=students_add" class="btn btn-light border py-3 shadow-sm">➕ เพิ่มรายชื่อนักเรียนใหม่</a>
                        <a href="index.php?page=students_export" class="btn btn-link text-muted mt-2 text-decoration-none">📊 Export ข้อมูลเป็น Excel</a>
                    <?php endif; ?>
                </div>
            </div>
        </div>
    </div>

    <div class="col-12 mt-3">
        <a href="index.php?page=roadmap" class="text-decoration-none">
            <div class="card shadow-sm border-0 rounded-4 bg-dark text-white" style="transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'">
                <div class="card-body p-4 d-flex align-items-center justify-content-between">
                    <div class="d-flex align-items-center gap-3">
                        <div class="display-4 mb-0">🗺️</div>
                        <div>
                            <h4 class="fw-bold mb-1 text-white">Class Roadmap & Committee</h4>
                            <p class="mb-0 text-light opacity-75">ดูแผนคณะกรรมการห้อง</p>
                        </div>
                    </div>
                    <div>
                        <i class="bi bi-arrow-right-circle-fill text-white fs-1 opacity-75"></i>
                    </div>
                </div>
            </div>
        </a>
    </div>
</div>