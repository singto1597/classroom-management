<?php
// คำนวณเปอร์เซ็นต์
$total = $data['summary']['total'];
$paid = $data['summary']['paid'];
$percent = $total > 0 ? round(($paid / $total) * 100) : 0;
?>
<div class="card border-0 shadow-sm rounded-4 mb-4">
    <div class="card-body p-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 class="fw-bold mb-0">รายการ: Collection #<?= $data['collection_id'] ?></h4>
            <a href="index.php?page=finance_collections" class="btn btn-sm btn-light rounded-pill"><i class="bi bi-arrow-left"></i> กลับ</a>
        </div>
        
        <h6 class="text-muted fw-bold mb-2">ความคืบหน้า (จ่ายแล้ว <?= $paid ?> จาก <?= $total ?> คน)</h6>
        <div class="progress rounded-pill" style="height: 20px;">
            <div class="progress-bar bg-success" role="progressbar" style="width: <?= $percent ?>%;"><?= $percent ?>%</div>
        </div>
    </div>
</div>

<div class="card border-0 shadow-sm rounded-4 p-0 overflow-hidden">
    <div class="table-responsive">
        <table class="table table-hover align-middle mb-0 custom-table">
            <thead class="table-light">
                <tr class="small text-muted">
                    <th class="ps-4">เลขที่</th>
                    <th>ชื่อ-สกุล</th>
                    <th>สถานะ</th>
                    <th class="text-end pe-4">จัดการ</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach($data['students'] as $s): ?>
                <?php 
                    // คำนวณยอดเงิน
                    $paid_amt = $s['paid_amount'] ?? 0;
                    $total_amt = $s['total_amount'] ?? 0;
                    $remaining = $total_amt - $paid_amt;
                ?>
                <tr>
                    <td class="ps-4 fw-bold text-muted"><?= $s['student_no'] ?></td>
                    <td>
                        <span class="fw-bold d-block"><?= h($s['first_name'] . ' ' . $s['last_name']) ?></span>
                        <?php if($s['nickname']): ?>
                            <small class="text-muted">(<?= h($s['nickname']) ?>)</small>
                        <?php endif; ?>
                    </td>
                    <td>
                        <?php if($s['status'] === 'paid'): ?>
                            <span class="badge bg-success-subtle text-success rounded-pill px-3 py-2"><i class="bi bi-check-circle-fill"></i> จ่ายครบแล้ว</span><br>
                            <small class="text-muted" style="font-size:10px;"><?= date('d/m/Y H:i', strtotime($s['paid_at'])) ?></small>
                        
                        <?php elseif($paid_amt > 0): ?>
                            <span class="badge bg-warning-subtle text-warning rounded-pill px-3 py-2"><i class="bi bi-hourglass-split"></i> ทยอยจ่ายแล้ว ฿<?= number_format($paid_amt) ?></span><br>
                            <small class="text-danger fw-bold" style="font-size:11px;">(ค้างอีก ฿<?= number_format($remaining) ?>)</small>
                        
                        <?php else: ?>
                            <span class="badge bg-danger-subtle text-danger rounded-pill px-3 py-2"><i class="bi bi-clock-fill"></i> ค้างจ่าย</span>
                        <?php endif; ?>
                    </td>
                    <td class="text-end pe-4">
                        <?php if($s['status'] === 'pending' && $_SESSION['role'] !== 'student'): ?>
                            <button class="btn btn-primary btn-sm rounded-pill fw-bold px-3 btn-pay" 
                                    data-pid="<?= $s['payment_id'] ?>" 
                                    data-name="<?= h($s['first_name']) ?>"
                                    data-remain="<?= $remaining ?>">
                                รับเงิน
                            </button>
                        <?php endif; ?>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>

<div class="modal fade" id="payModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <form class="modal-content border-0 shadow rounded-4" id="payForm">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold">บันทึกการรับเงิน: <span id="payName" class="text-primary"></span></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="confirm_payment">
                <input type="hidden" name="payment_id" id="modalPaymentId">

                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">รับเงินเข้าบัญชีห้อง</label>
                    <select name="paid_to_account_id" class="form-select rounded-pill" required>
                        <option value="" disabled selected>-- เลือกกระเป๋าเงิน --</option>
                        <?php foreach($accounts as $acc): ?>
                            <option value="<?= $acc['id'] ?>"><?= h($acc['account_name']) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">จำนวนเงินที่จ่าย (฿)</label>
                    <input type="number" name="paid_amount" class="form-control rounded-pill" step="0.01" required>
                </div>

                <div class="mb-2">
                    <label class="form-label small fw-bold text-muted">URL รูปสลิปโอนเงิน (ถ้ามี)</label>
                    <input type="url" name="slip_image_url" class="form-control rounded-pill" placeholder="https://...">
                </div>
            </div>
            <div class="modal-footer border-0 pt-0">
                <button type="submit" class="btn btn-success w-100 rounded-pill py-2 fw-bold">✅ ยืนยันการรับเงิน</button>
            </div>
        </form>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
// 1. จัดการให้กดปุ่ม "รับเงิน" แล้ว Modal เด้ง
let payModal;
document.addEventListener("DOMContentLoaded", function() {
    payModal = new bootstrap.Modal(document.getElementById('payModal'));
});

document.querySelectorAll('.btn-pay').forEach(btn => {
    btn.addEventListener('click', function() {
        document.getElementById('modalPaymentId').value = this.dataset.pid;
        document.getElementById('payName').innerText = this.dataset.name;
        
        document.querySelector('input[name="paid_amount"]').value = this.dataset.remain;
        
        payModal.show();
    });
});

// 2. ส่งฟอร์มรับเงิน (ยิง AJAX)
document.getElementById('payForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const btn = this.querySelector('button[type="submit"]');
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> กำลังบันทึก...'; 
    btn.disabled = true;

    try {
        const response = await fetch('index.php?page=finance_action&format=json', {
            method: 'POST', body: new FormData(this)
        });
        const result = await response.json();
        
        if (response.ok && result.status === 'success') {
            payModal.hide();
            Swal.fire({ title: 'รับเงินสำเร็จ!', text: result.message, icon: 'success', timer: 1500, showConfirmButton: false })
                .then(() => location.reload());
        } else {
            Swal.fire('ผิดพลาด', result.message, 'error');
        }
    } catch (err) {
        Swal.fire('Error', 'เชื่อมต่อ API ไม่ได้', 'error');
    } finally {
        btn.innerHTML = '✅ ยืนยันการรับเงิน'; 
        btn.disabled = false;
    }
});
</script>