<div class="row mb-4 align-items-center">
    <div class="col">
        <h3 class="fw-bold mb-0">⚙️ ตั้งค่าระบบการเงิน</h3>
        <p class="text-muted small mb-0">จัดการกระเป๋าเงินกองกลางและหมวดหมู่รายรับ/รายจ่าย</p>
    </div>
</div>

<div class="row g-4">
    <div class="col-lg-6">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-header bg-white border-0 pt-4 px-4 d-flex justify-content-between align-items-center">
                <h5 class="fw-bold mb-0"><i class="bi bi-wallet2 text-primary me-2"></i> กระเป๋าเงินห้อง</h5>
                <button class="btn btn-sm btn-primary rounded-pill px-3 shadow-sm fw-bold" data-bs-toggle="modal" data-bs-target="#addAccountModal">
                    <i class="bi bi-plus-circle"></i> เพิ่มบัญชี
                </button>
            </div>
            <div class="card-body p-4">
                <?php if(empty($accounts)): ?>
                    <p class="text-center text-muted py-3">ยังไม่มีกระเป๋าเงิน</p>
                <?php else: ?>
                    <ul class="list-group list-group-flush rounded-4 shadow-sm border">
                        <?php foreach($accounts as $acc): ?>
                        <li class="list-group-item d-flex justify-content-between align-items-center p-3">
                            <div>
                                <h6 class="fw-bold mb-0 text-dark"><?= h($acc['account_name']) ?></h6>
                                <small class="text-muted">คงเหลือ: ฿<?= number_format($acc['balance'], 2) ?></small>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-sm btn-light text-primary rounded-circle me-1 btn-edit-account" 
                                        data-id="<?= $acc['id'] ?>" data-name="<?= h($acc['account_name']) ?>" title="แก้ไขชื่อ">
                                    <i class="bi bi-pencil-square"></i>
                                </button>
                                <button class="btn btn-sm btn-light text-danger rounded-circle btn-delete-account" 
                                        data-id="<?= $acc['id'] ?>" title="ลบบัญชี">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </div>
                        </li>
                        <?php endforeach; ?>
                    </ul>
                <?php endif; ?>
            </div>
        </div>
    </div>

    <div class="col-lg-6">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-header bg-white border-0 pt-4 px-4 d-flex justify-content-between align-items-center">
                <h5 class="fw-bold mb-0"><i class="bi bi-tags text-success me-2"></i> หมวดหมู่รายการ</h5>
                <button class="btn btn-sm btn-success rounded-pill px-3 shadow-sm fw-bold" data-bs-toggle="modal" data-bs-target="#addCategoryModal">
                    <i class="bi bi-plus-circle"></i> เพิ่มหมวดหมู่
                </button>
            </div>
            <div class="card-body p-4">
                <div class="row">
                    <div class="col-6 border-end">
                        <h6 class="fw-bold text-success text-center mb-3">รายรับ</h6>
                        <?php if(empty($categories_inc)): ?>
                            <p class="text-center text-muted small">ไม่มีข้อมูล</p>
                        <?php else: ?>
                            <div class="d-flex flex-wrap gap-2 justify-content-center">
                                <?php foreach($categories_inc as $cat): ?>
                                    <div class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-3 py-2 d-flex align-items-center gap-2">
                                        <span class="fs-6"><?= h($cat['category_name']) ?></span>
                                        <i class="bi bi-pencil-fill text-muted btn-edit-category" 
                                           data-id="<?= $cat['id'] ?>" data-name="<?= h($cat['category_name']) ?>" style="font-size: 12px; cursor: pointer;"></i>
                                        <i class="bi bi-x-circle-fill text-danger btn-delete-category" 
                                           data-id="<?= $cat['id'] ?>" style="font-size: 12px; cursor: pointer;"></i>
                                    </div>
                                <?php endforeach; ?>
                            </div>
                        <?php endif; ?>
                    </div>
                    
                    <div class="col-6">
                        <h6 class="fw-bold text-danger text-center mb-3">รายจ่าย</h6>
                        <?php if(empty($categories_exp)): ?>
                            <p class="text-center text-muted small">ไม่มีข้อมูล</p>
                        <?php else: ?>
                            <div class="d-flex flex-wrap gap-2 justify-content-center">
                                <?php foreach($categories_exp as $cat): ?>
                                    <div class="badge bg-danger-subtle text-danger border border-danger-subtle rounded-pill px-3 py-2 d-flex align-items-center gap-2">
                                        <span class="fs-6"><?= h($cat['category_name']) ?></span>
                                        <i class="bi bi-pencil-fill text-muted btn-edit-category" 
                                           data-id="<?= $cat['id'] ?>" data-name="<?= h($cat['category_name']) ?>" style="font-size: 12px; cursor: pointer;"></i>
                                        <i class="bi bi-x-circle-fill text-danger btn-delete-category" 
                                           data-id="<?= $cat['id'] ?>" style="font-size: 12px; cursor: pointer;"></i>
                                    </div>
                                <?php endforeach; ?>
                            </div>
                        <?php endif; ?>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="modal fade" id="addAccountModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form id="addAccountForm" class="modal-content border-0 shadow rounded-4 ajax-form">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">เพิ่มกระเป๋าเงินใหม่</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="add_account">
                <div class="mb-3">
                    <label class="form-label small text-muted">ชื่อกระเป๋าเงิน</label>
                    <input type="text" name="account_name" class="form-control rounded-pill" placeholder="เช่น เงินสด, บัญชีห้อง" required>
                </div>
                <div class="mb-3">
                    <label class="form-label small text-muted">เงินตั้งต้น (฿)</label>
                    <input type="number" name="initial_balance" class="form-control rounded-pill" value="0" step="0.01">
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-primary w-100 rounded-pill py-2 fw-bold shadow-sm">บันทึกข้อมูล</button>
            </div>
        </form>
    </div>
</div>

<div class="modal fade" id="addCategoryModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form id="addCategoryForm" class="modal-content border-0 shadow rounded-4 ajax-form">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">เพิ่มหมวดหมู่ใหม่</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="add_category">
                <div class="mb-3">
                    <label class="form-label small text-muted">ประเภทหมวดหมู่</label>
                    <select name="category_type" class="form-select rounded-pill" required>
                        <option value="income">🟢 รายรับ (Income)</option>
                        <option value="expense">🔴 รายจ่าย (Expense)</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label small text-muted">ชื่อหมวดหมู่</label>
                    <input type="text" name="category_name" class="form-control rounded-pill" placeholder="เช่น ค่าอุปกรณ์, ค่าพานไหว้ครู" required>
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-success w-100 rounded-pill py-2 fw-bold shadow-sm">เพิ่มหมวดหมู่</button>
            </div>
        </form>
    </div>
</div>

<div class="modal fade" id="editModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form id="editForm" class="modal-content border-0 shadow rounded-4 ajax-form">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">แก้ไขข้อมูล</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" id="editAction">
                <input type="hidden" name="account_id" id="editAccountId">
                <input type="hidden" name="category_id" id="editCategoryId">
                <div class="mb-3">
                    <label class="form-label small text-muted">ชื่อที่ต้องการเปลี่ยน</label>
                    <input type="text" name="account_name" id="editNameInput" class="form-control rounded-pill" required>
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-warning w-100 rounded-pill py-2 fw-bold shadow-sm">💾 บันทึกการเปลี่ยนแปลง</button>
            </div>
        </form>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
// 1. จัดการการ Submit ฟอร์มทั้งหมดที่มีคลาส .ajax-form (ครอบคลุม Create และ Edit)
document.querySelectorAll('.ajax-form').forEach(form => {
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        const btn = this.querySelector('button[type="submit"]');
        const oldHtml = btn.innerHTML;
        
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> กำลังบันทึก...';
        btn.disabled = true;

        try {
            const formData = new FormData(this);
            const response = await fetch('index.php?page=finance_action&format=json', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                Swal.fire({
                    title: 'สำเร็จ!', 
                    text: result.message, 
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                Swal.fire('ผิดพลาด', result.message || 'เกิดข้อผิดพลาดบางอย่าง', 'error');
            }
        } catch (err) {
            Swal.fire('Error', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
        } finally {
            btn.innerHTML = oldHtml;
            btn.disabled = false;
        }
    });
});

// 2. จัดการการลบ (Delete) พร้อมคำเตือน
document.addEventListener('click', async function(e) {
    if (e.target.closest('.btn-delete-account') || e.target.closest('.btn-delete-category')) {
        const btn = e.target.closest('button') || e.target.closest('i');
        const id = btn.dataset.id;
        const isAcc = btn.classList.contains('btn-delete-account');
        const action = isAcc ? 'delete_account' : 'delete_category';
        const idKey = isAcc ? 'account_id' : 'category_id';

        const result = await Swal.fire({
            title: 'ยืนยันการลบ?',
            text: "หากลบแล้วจะไม่สามารถย้อนกลับได้ และรายการที่มีประวัติการใช้งานจะลบไม่ได้",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ลบทันที',
            cancelButtonText: 'ยกเลิก'
        });

        if (result.isConfirmed) {
            const formData = new FormData();
            formData.append('action', action);
            formData.append(idKey, id);
            formData.append('csrf_token', '<?= $_SESSION['csrf_token'] ?>');

            // ใช้ฟังก์ชัน submitFormData ส่ง API
            submitFormData(formData); 
        }
    }
});

// 3. จัดการเปิด Modal แก้ไข (Edit) แล้วดึงค่าเก่ามาใส่
document.addEventListener('click', function(e) {
    const editBtn = e.target.closest('.btn-edit-account') || e.target.closest('.btn-edit-category');
    if (editBtn) {
        const id = editBtn.dataset.id;
        const name = editBtn.dataset.name;
        const isAcc = editBtn.classList.contains('btn-edit-account');

        // ตั้งค่าตัวแปรในฟอร์มให้ตรงกับ Action
        document.getElementById('editAction').value = isAcc ? 'edit_account' : 'edit_category';
        document.getElementById('editAccountId').value = isAcc ? id : '';
        document.getElementById('editCategoryId').value = isAcc ? '' : id;
        document.getElementById('editNameInput').value = name;
        
        // สลับชื่อ Name ของ Input ให้ตรงกับที่ Backend ต้องการ
        document.getElementById('editNameInput').name = isAcc ? 'account_name' : 'category_name';

        new bootstrap.Modal(document.getElementById('editModal')).show();
    }
});

// 4. ฟังก์ชันช่วยส่งข้อมูลสำหรับปุ่ม Delete
async function submitFormData(formData) {
    try {
        const response = await fetch('index.php?page=finance_action&format=json', { method: 'POST', body: formData });
        const res = await response.json();
        if (response.ok && res.status === 'success') {
            Swal.fire('สำเร็จ!', res.message, 'success').then(() => location.reload());
        } else {
            Swal.fire('ผิดพลาด', res.message, 'error');
        }
    } catch (err) { 
        Swal.fire('Error', 'เชื่อมต่อ API ไม่ได้', 'error'); 
    }
}
</script>