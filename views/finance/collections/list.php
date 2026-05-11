<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold mb-0">โปรเจกต์เก็บเงิน (Collections)</h3>
    <?php if ($_SESSION['role'] !== 'student'): ?>
        <button class="btn btn-primary rounded-pill px-4 shadow-sm fw-bold" data-bs-toggle="modal" data-bs-target="#addCollectionModal">
            <i class="bi bi-plus-circle me-1"></i> สร้างโปรเจกต์ใหม่
        </button>
    <?php endif; ?>
</div>

<div class="row g-4">
    <?php if(empty($collections)): ?>
        <div class="col-12 text-center py-5">
            <h5 class="text-muted">ยังไม่มีโปรเจกต์เก็บเงินในขณะนี้</h5>
        </div>
    <?php endif; ?>

    <?php foreach($collections as $col): ?>
    <div class="col-md-6 col-lg-4">
        <div class="card border-0 shadow-sm rounded-4 h-100 <?= $col['status'] === 'closed' ? 'bg-light opacity-75' : '' ?>">
            <div class="card-body p-4">
                
                <div class="d-flex justify-content-between mb-2 align-items-center">
                    <div>
                        <span class="badge <?= $col['status'] === 'active' ? 'bg-success' : 'bg-secondary' ?> rounded-pill">
                            <?= $col['status'] === 'active' ? 'เปิดรับเงิน' : 'ปิดแล้ว' ?>
                        </span>
                        <small class="text-muted ms-2"><i class="bi bi-calendar-event"></i> กำหนด: <?= $col['due_date'] ? date('d/m/Y', strtotime($col['due_date'])) : '-' ?></small>
                    </div>
                    <?php if ($_SESSION['role'] !== 'student'): ?>
                    <button class="btn btn-sm btn-light text-muted rounded-circle btn-edit-col" 
                            data-id="<?= $col['id'] ?>"
                            data-title="<?= h($col['title']) ?>"
                            data-amount="<?= $col['amount'] ?>"
                            data-duedate="<?= h($col['due_date'] ?? '') ?>"
                            data-status="<?= h($col['status']) ?>"
                            title="ตั้งค่าแคมเปญ">
                        <i class="bi bi-gear-fill"></i>
                    </button>
                    <?php endif; ?>
                </div>

                <h5 class="fw-bold text-dark mt-3 text-truncate" title="<?= h($col['title']) ?>"><?= h($col['title']) ?></h5>
                <h3 class="fw-bold text-primary mb-4">฿<?= number_format($col['amount'], 2) ?><small class="fs-6 text-muted fw-normal"> / คน</small></h3>
                <a href="index.php?page=finance_collections_view&id=<?= $col['id'] ?>" class="btn btn-outline-dark w-100 rounded-pill fw-bold">
                    <i class="bi bi-search me-1"></i> ดูรายละเอียด
                </a>
            </div>
        </div>
    </div>
    <?php endforeach; ?>
</div>

<div class="modal fade" id="addCollectionModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form class="modal-content border-0 shadow rounded-4 ajax-form" id="createCollectionForm">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">สร้างโปรเจกต์เก็บเงินใหม่</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="create_collection">
                <div class="alert alert-info small border-0 rounded-4">
                    <i class="bi bi-info-circle-fill"></i> ระบบจะสร้างบิลเรียกเก็บเงินไปยังนักเรียนที่มีสถานะ Active ทุกคนอัตโนมัติ
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">ชื่อรายการ (เช่น ค่าชีทฟิสิกส์)</label>
                    <input type="text" name="title" class="form-control rounded-pill" required>
                </div>
                <div class="row mb-3">
                    <div class="col-6">
                        <label class="form-label small fw-bold text-muted">ยอดเรียกเก็บ (฿)</label>
                        <input type="number" name="amount" class="form-control rounded-pill" step="0.01" required>
                    </div>
                    <div class="col-6">
                        <label class="form-label small fw-bold text-muted">ครบกำหนด (Due Date)</label>
                        <input type="date" name="due_date" class="form-control rounded-pill" required>
                    </div>
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-primary w-100 rounded-pill py-2 fw-bold">🚀 สร้างรายการและเรียกเก็บทันที</button>
            </div>
        </form>
    </div>
</div>

<div class="modal fade" id="editCollectionModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form class="modal-content border-0 shadow rounded-4 ajax-form" id="editCollectionForm">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">ตั้งค่าโปรเจกต์เก็บเงิน</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="update_collection">
                <input type="hidden" name="collection_id" id="editColId">
                
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">ชื่อรายการ</label>
                    <input type="text" name="title" id="editColTitle" class="form-control rounded-pill" required>
                </div>
                <div class="row mb-3">
                    <div class="col-6">
                        <label class="form-label small fw-bold text-muted">ยอดเรียกเก็บ (฿)</label>
                        <input type="number" name="amount" id="editColAmount" class="form-control rounded-pill" step="0.01" required>
                        <small class="text-danger" style="font-size: 11px;">*แก้ไม่ได้ถ้ามีคนจ่ายแล้ว</small>
                    </div>
                    <div class="col-6">
                        <label class="form-label small fw-bold text-muted">ครบกำหนด</label>
                        <input type="date" name="due_date" id="editColDueDate" class="form-control rounded-pill" required>
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">สถานะ</label>
                    <select name="status" id="editColStatus" class="form-select rounded-pill">
                        <option value="active">🟢 เปิดรับเงิน (Active)</option>
                        <option value="closed">🔴 ปิดแคมเปญ (Closed)</option>
                    </select>
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-warning w-100 rounded-pill py-2 fw-bold text-dark">บันทึกการเปลี่ยนแปลง</button>
            </div>
        </form>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
// 1. จัดการฟอร์ม สร้างแคมเปญ (Create)
document.getElementById('createCollectionForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const btn = this.querySelector('button[type="submit"]');
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> กำลังสร้าง...';
    btn.disabled = true;

    try {
        const response = await fetch('index.php?page=finance_action&format=json', {
            method: 'POST', body: new FormData(this)
        });
        const result = await response.json();
        if (result.status === 'success') {
            Swal.fire('สำเร็จ!', result.message, 'success').then(() => location.reload());
        } else {
            Swal.fire('ผิดพลาด', result.message, 'error');
        }
    } catch (err) {
        Swal.fire('Error', 'เชื่อมต่อ API ไม่ได้', 'error');
    } finally {
        btn.innerHTML = '🚀 สร้างรายการและเรียกเก็บทันที';
        btn.disabled = false;
    }
});

// 2. จัดการดึงข้อมูลใส่ฟอร์ม แก้ไขแคมเปญ (Edit Modal Population)
let editModal;
document.addEventListener("DOMContentLoaded", function() {
    editModal = new bootstrap.Modal(document.getElementById('editCollectionModal'));
});

document.querySelectorAll('.btn-edit-col').forEach(btn => {
    btn.addEventListener('click', function() {
        document.getElementById('editColId').value = this.dataset.id;
        document.getElementById('editColTitle').value = this.dataset.title;
        document.getElementById('editColAmount').value = this.dataset.amount;
        document.getElementById('editColDueDate').value = this.dataset.duedate;
        document.getElementById('editColStatus').value = this.dataset.status;
        
        editModal.show();
    });
});

// 3. จัดการฟอร์ม ส่งข้อมูลแก้ไข (Update)
document.getElementById('editCollectionForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const btn = this.querySelector('button[type="submit"]');
    const oldHtml = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> กำลังบันทึก...';
    btn.disabled = true;

    try {
        const response = await fetch('index.php?page=finance_action&format=json', {
            method: 'POST', body: new FormData(this)
        });
        const result = await response.json();
        
        if (response.ok && result.status === 'success') {
            editModal.hide();
            Swal.fire('สำเร็จ!', result.message, 'success').then(() => location.reload());
        } else {
            Swal.fire('ผิดพลาด', result.message, 'error');
        }
    } catch (err) {
        Swal.fire('Error', 'เชื่อมต่อ API ไม่ได้', 'error');
    } finally {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    }
});
</script>