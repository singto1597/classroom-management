<div class="max-w-2xl mx-auto" style="max-width: 700px;">
    <div class="d-flex align-items-center mb-4">
        <a href="index.php?page=students" class="btn btn-outline-secondary btn-sm me-3">⬅️</a>
        <h3 class="mb-0 fw-bold">➕ เพิ่มนักเรียนเข้าสู่ระบบ</h3>
    </div>

    <?php if(isset($success_msg)): ?>
        <div class="alert alert-success shadow-sm border-0 rounded-3 mb-4">
            <i class="bi bi-check-circle-fill me-2"></i> <?= $success_msg ?>
        </div>
    <?php endif; ?>
    
    <?php if(isset($error_msg)): ?>
        <div class="alert alert-danger shadow-sm border-0 rounded-3 mb-4">
            <i class="bi bi-exclamation-triangle-fill me-2"></i> <strong>ผิดพลาด:</strong> <?= $error_msg ?>
        </div>
    <?php endif; ?>

    <div class="card shadow-sm border-0 rounded-4 overflow-hidden">
        <div class="card-header bg-white p-0">
            <ul class="nav nav-tabs nav-fill border-0" id="addTab" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active py-3 fw-bold border-0" id="single-tab" data-bs-toggle="tab" data-bs-target="#single" type="button" role="tab">
                        👤 เพิ่มทีละคน
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link py-3 fw-bold border-0 text-primary" id="bulk-tab" data-bs-toggle="tab" data-bs-target="#bulk" type="button" role="tab">
                        🚀 เพิ่มแบบรวดเดียว (Excel)
                    </button>
                </li>
            </ul>
        </div>
        
        <div class="card-body p-4">
            <div class="tab-content" id="addTabContent">
                
                <div class="tab-pane fade show active" id="single" role="tabpanel">
                    <form method="POST" action="index.php?page=students_add">
                        <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                        <input type="hidden" name="action" value="single">
                        
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label class="form-label small fw-bold text-muted">เลขที่</label>
                                <input type="number" name="student_no" class="form-control form-control-lg rounded-3" placeholder="เช่น 1" required>
                            </div>
                            <div class="col-md-8">
                                <label class="form-label small fw-bold text-muted">ชื่อจริง</label>
                                <input type="text" name="first_name" class="form-control form-control-lg rounded-3" placeholder="ไม่ต้องใส่คำนำหน้า" required>
                            </div>
                            <div class="col-12">
                                <label class="form-label small fw-bold text-muted">นามสกุล</label>
                                <input type="text" name="last_name" class="form-control form-control-lg rounded-3" required>
                            </div>
                            <div class="col-12 mt-4">
                                <button type="submit" class="btn btn-primary btn-lg w-100 rounded-pill shadow-sm">บันทึกข้อมูลนักเรียน</button>
                            </div>
                        </div>
                    </form>
                </div>

                <div class="tab-pane fade" id="bulk" role="tabpanel">
                    <div class="alert alert-info border-0 rounded-3 small mb-4">
                        <i class="bi bi-info-circle-fill me-2"></i> 
                        <strong>วิธีใช้งาน:</strong> ก๊อปปี้ข้อมูลจาก Excel มาวางตามรูปแบบ: <br>
                        <code>เลขที่,ชื่อจริง,นามสกุล</code> (หนึ่งคนต่อหนึ่งบรรทัด)
                    </div>
                    
                    <form method="POST" action="index.php?page=students_add">
                        <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                        <input type="hidden" name="action" value="bulk">
                        
                        <div class="mb-3">
                            <label class="form-label small fw-bold text-muted">วางข้อมูลที่นี่</label>
                            <textarea name="bulk_data" class="form-control rounded-3 font-monospace" rows="10" placeholder="1,สมชาย,ใจดี&#10;2,สมหญิง,รักเรียน"></textarea>
                        </div>
                        
                        <button type="submit" class="btn btn-primary btn-lg w-100 rounded-pill shadow-sm">
                            🚀 นำเข้าข้อมูลทั้งหมด
                        </button>
                    </form>
                </div>

            </div>
        </div>
    </div>
    
    <div class="text-center mt-4">
        <p class="text-muted small">ต้องการความช่วยเหลือ? <a href="#" class="text-decoration-none">ดูคู่มือการนำเข้าข้อมูล</a></p>
    </div>
</div>

<style>
    /* ปรับแต่ง Tab ให้ดูทันสมัย */
    .nav-tabs .nav-link {
        color: #6c757d;
        background-color: #f8f9fa;
        transition: all 0.3s ease;
    }
    .nav-tabs .nav-link.active {
        color: #0d6efd !important;
        background-color: #fff !important;
        border-bottom: 3px solid #0d6efd !important;
    }
    .nav-tabs .nav-link:hover:not(.active) {
        background-color: #e9ecef;
        border-color: transparent;
    }
    /* ปรับแต่งฟอนต์สำหรับ Bulk Data */
    textarea.font-monospace {
        font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
        font-size: 0.9rem;
        line-height: 1.6;
    }
</style>