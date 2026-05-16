<style>
    /* เพิ่มลูกเล่นเวลาเอาเมาส์ชี้ ให้รู้ว่ากล่องนี้กดได้ */
    .export-option-card {
        transition: all 0.2s ease-in-out;
        cursor: pointer;
    }
    .export-option-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        border-color: #b0c4de !important; /* เปลี่ยนสีขอบนิดหน่อยให้ดูมีมิติ */
    }
    /* ขยายขนาด Checkbox ให้ใหญ่ขึ้นติ๊กง่ายๆ */
    .export-checkbox {
        width: 1.5em;
        height: 1.5em;
        cursor: pointer;
    }
</style>

<div class="card-body p-4">
    <form method="POST" action="index.php?page=students_export">
        <input type="hidden" name="csrf_token" value="<?= h($_SESSION['csrf_token']) ?>">
        
        <!-- ตัวเลือกที่ 1: Core -->
        <label class="d-flex align-items-center mb-3 p-3 bg-light rounded border export-option-card w-100" for="cat_core">
            <div class="me-3">
                <input class="form-check-input m-0 export-checkbox" type="checkbox" name="categories[]" value="core" id="cat_core" checked>
            </div>
            <div>
                <span class="d-block fw-bold text-primary fs-6">🔵 ข้อมูลส่วนตัว (Core)</span>
                <span class="d-block text-muted small fw-normal">เลขที่, รหัส, ชื่อ, วันเกิด</span>
            </div>
        </label>
        
        <!-- ตัวเลือกที่ 2: Academic -->
        <label class="d-flex align-items-center mb-3 p-3 bg-light rounded border export-option-card w-100" for="cat_academic">
            <div class="me-3">
                <input class="form-check-input m-0 export-checkbox" type="checkbox" name="categories[]" value="academic" id="cat_academic">
            </div>
            <div>
                <span class="d-block fw-bold text-warning text-dark fs-6">🟡 วิชาการ (Academic)</span>
                <span class="d-block text-muted small fw-normal">บทบาท, เวร, คณะ, สอวน.</span>
            </div>
        </label>

        <!-- ตัวเลือกที่ 3: Health -->
        <label class="d-flex align-items-center mb-3 p-3 bg-light rounded border export-option-card w-100" for="cat_health">
            <div class="me-3">
                <input class="form-check-input m-0 export-checkbox" type="checkbox" name="categories[]" value="health" id="cat_health">
            </div>
            <div>
                <span class="d-block fw-bold text-danger fs-6">🔴 สุขภาพ (Health)</span>
                <span class="d-block text-muted small fw-normal">กรุ๊ปเลือด, โรคประจำตัว, แพ้อาหาร</span>
            </div>
        </label>

        <!-- ตัวเลือกที่ 4: Contact -->
        <label class="d-flex align-items-center mb-3 p-3 bg-light rounded border export-option-card w-100" for="cat_contact">
            <div class="me-3">
                <input class="form-check-input m-0 export-checkbox" type="checkbox" name="categories[]" value="contact" id="cat_contact">
            </div>
            <div>
                <span class="d-block fw-bold text-info text-dark fs-6">🟣 ติดต่อ (Contact)</span>
                <span class="d-block text-muted small fw-normal">เบอร์โทร, เบอร์ผู้ปกครอง, LINE, IG</span>
            </div>
        </label>

        <!-- ตัวเลือกที่ 5: Address -->
        <label class="d-flex align-items-center mb-4 p-3 bg-light rounded border export-option-card w-100" for="cat_address">
            <div class="me-3">
                <input class="form-check-input m-0 export-checkbox" type="checkbox" name="categories[]" value="address" id="cat_address">
            </div>
            <div>
                <span class="d-block fw-bold text-secondary fs-6">🟤 ที่อยู่ (Address)</span>
                <span class="d-block text-muted small fw-normal">ที่อยู่ทั้งหมด, รหัสไปรษณีย์</span>
            </div>
        </label>

        <button type="submit" class="btn btn-success btn-lg w-100 rounded-pill shadow-sm fw-bold">
            ⬇️ ดาวน์โหลดไฟล์ Excel
        </button>
    </form>
</div>