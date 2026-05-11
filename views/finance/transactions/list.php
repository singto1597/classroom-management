<div class="card border-0 shadow-sm rounded-4 p-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h4 class="fw-bold mb-0">ประวัติการทำรายการ</h4>
            <p class="text-muted mb-0 small">รายการรับ จ่าย และโอนเงินทั้งหมดของห้อง</p>
        </div>
        <a href="index.php?page=finance_transactions_add" class="btn btn-primary rounded-pill px-4 shadow-sm fw-bold">
            <i class="bi bi-plus-lg me-1"></i> บันทึกรายการ
        </a>
    </div>

    <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
                <tr class="small text-muted text-nowrap">
                    <th>วันที่-เวลา</th>
                    <th>รายการ</th>
                    <th>กระเป๋าเงิน</th>
                    <th class="text-end">จำนวนเงิน</th>
                    <th class="text-center">จัดการ</th>
                </tr>
            </thead>
            <tbody>
                <?php if(empty($transactions)): ?>
                    <tr><td colspan="5" class="text-center py-4 text-muted">ยังไม่มีประวัติการทำรายการ</td></tr>
                <?php endif; ?>

                <?php foreach ($transactions as $t): ?>
                <tr>
                    <td class="small text-muted text-nowrap">
                        <?= date('d/m/Y', strtotime($t['created_at'])) ?><br>
                        <?= date('H:i', strtotime($t['created_at'])) ?> น.
                    </td>
                    <td>
                        <span class="d-block fw-bold"><?= h($t['description']) ?></span>
                        <div class="small">
                            <?php if($t['category_name']): ?>
                                <span class="badge bg-secondary opacity-75"><?= h($t['category_name']) ?></span>
                            <?php endif; ?>
                            <span class="text-muted ms-1"><i class="bi bi-person-circle"></i> <?= h($t['recorded_by']) ?></span>
                        </div>
                    </td>
                    <td>
                        <span class="badge bg-light text-dark border rounded-pill px-2 py-1">
                            <i class="bi bi-wallet2 text-primary"></i> <?= h($t['account_name'] ?? 'ไม่ระบุบัญชี') ?>
                        </span>
                    </td>
                    <td class="text-end text-nowrap">
                        <?php if ($t['transaction_type'] === 'income'): ?>
                            <span class="fw-bold text-success">+ ฿<?= number_format($t['amount'], 2) ?></span>
                        <?php else: ?>
                            <span class="fw-bold text-danger">- ฿<?= number_format($t['amount'], 2) ?></span>
                        <?php endif; ?>
                    </td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-light text-danger rounded-circle btn-revert" 
                                data-id="<?= $t['id'] ?>" 
                                data-desc="<?= h($t['description']) ?>"
                                title="ยกเลิกรายการนี้">
                            <i class="bi bi-arrow-counterclockwise fs-6"></i>
                        </button>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
document.querySelectorAll('.btn-revert').forEach(btn => {
    btn.addEventListener('click', function() {
        const transId = this.dataset.id;
        const transDesc = this.dataset.desc;
        
        Swal.fire({
            title: 'ต้องการยกเลิก?',
            html: `คุณกำลังจะยกเลิกรายการ:<br><b>"${transDesc}"</b><br><br><span class="text-danger small">ยอดเงินจะถูกคืนกลับกระเป๋าเดิม หากเป็นรายการรับเงินจากเพื่อน สถานะบิลเพื่อนจะถูกตีกลับเป็น "ค้างจ่าย" ทันที</span>`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ยืนยันการยกเลิก',
            cancelButtonText: 'ปิด'
        }).then(async (result) => {
            if (result.isConfirmed) {
                const formData = new FormData();
                formData.append('action', 'revert_transaction');
                formData.append('transaction_id', transId);
                formData.append('csrf_token', '<?= $_SESSION['csrf_token'] ?>');

                try {
                    const response = await fetch('index.php?page=finance_action&format=json', {
                        method: 'POST', body: formData
                    });
                    const res = await response.json();
                    
                    if (response.ok && res.status === 'success') {
                        Swal.fire('คืนเงินสำเร็จ!', res.message, 'success').then(() => location.reload());
                    } else {
                        Swal.fire('ยกเลิกไม่ได้', res.message, 'error');
                    }
                } catch (error) {
                    Swal.fire('Error!', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
                }
            }
        });
    });
});
</script>