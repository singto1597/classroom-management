<div class="card border-0 shadow-sm rounded-4 p-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h4 class="fw-bold mb-0 text-danger"><i class="bi bi-exclamation-triangle-fill me-2"></i> สรุปผู้ค้างชำระ (ทวงหนี้รวม)</h4>
            <p class="text-muted mb-0 small">รายชื่อผู้ค้างจ่ายเงินจากทุกโปรเจกต์ที่ยังเปิดรับเงินอยู่</p>
        </div>
    </div>

    <div class="table-responsive">
        <table class="table table-hover align-middle mb-0 custom-table">
            <thead class="table-light">
                <tr class="small text-muted">
                    <th>เลขที่</th>
                    <th>ชื่อนักเรียน</th>
                    <th class="text-center">ค้างจ่าย (บิล)</th>
                    <th class="text-end">ยอดรวม (฿)</th>
                </tr>
            </thead>
            <tbody>
                <?php if(empty($debtors)): ?>
                    <tr><td colspan="4" class="text-center py-5 fw-bold text-success">🎉 ไม่มีใครติดหนี้ห้องเลย! (รวยมาก)</td></tr>
                <?php endif; ?>

                <?php foreach($debtors as $d): ?>
                <tr>
                    <td class="fw-bold text-muted"><?= $d['student_no'] ?></td>
                    <td class="fw-bold"><?= h($d['student_name']) ?></td>
                    <td class="text-center">
                        <span class="badge bg-danger rounded-pill fs-6"><?= $d['overdue_count'] ?> รายการ</span>
                    </td>
                    <td class="text-end fw-bold fs-5 text-danger">
                        ฿<?= number_format($d['total_pending_amount'], 2) ?>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>