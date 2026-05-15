<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold mb-0 text-dark">📊 สรุปภาพรวมการเงิน</h3>
    <form method="GET" class="d-flex gap-2">
        <input type="hidden" name="page" value="finance_dashboard">
        <select name="month" class="form-select rounded-pill border-0 shadow-sm px-3">
            <?php for($m=1; $m <= 12; $m++): ?>
                <option value="<?= $m ?>" <?= ($summary['period'] == date('Y-').sprintf('%02d', $m)) ? 'selected' : '' ?>>เดือน <?= $m ?></option>
            <?php endfor; ?>
        </select>
        <button type="submit" class="btn btn-dark rounded-pill px-3 shadow-sm"><i class="bi bi-filter"></i></button>
    </form>
</div>

<div class="row g-4 mb-4 text-white">
    <div class="col-md-3">
        <div class="card border-0 shadow-sm rounded-4 bg-primary p-4 h-100">
            <h6 class="opacity-75 small">เงินคงเหลือรวม</h6>
            <h3 class="fw-bold mb-0">฿<?= number_format($summary['net_worth'], 2) ?></h3>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card border-0 shadow-sm rounded-4 p-4 h-100" style="background: #ff9800;">
            <h6 class="opacity-75 small">ยอดที่เพื่อนค้างจ่ายรวม</h6>
            <h3 class="fw-bold mb-0">฿<?= number_format($summary['pending_collection_amount'], 2) ?></h3>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card border-0 shadow-sm rounded-4 bg-success p-4 h-100">
            <h6 class="opacity-75 small">รายรับเดือนนี้</h6>
            <h3 class="fw-bold mb-0">฿<?= number_format($summary['total_income'], 2) ?></h3>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card border-0 shadow-sm rounded-4 bg-danger p-4 h-100">
            <h6 class="opacity-75 small">รายจ่ายเดือนนี้</h6>
            <h3 class="fw-bold mb-0">฿<?= number_format($summary['total_expense'], 2) ?></h3>
        </div>
    </div>
</div>

<div class="row g-4">
    <div class="col-lg-8">
        <div class="card border-0 shadow-sm rounded-4 p-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h5 class="fw-bold mb-0">กระเป๋าเงินห้อง</h5>
                <a href="index.php?page=finance_accounts" class="btn btn-sm btn-light rounded-pill">จัดการบัญชี</a>
            </div>
            <div class="row g-3">
                <?php foreach ($accounts as $acc): ?>
                <div class="col-md-6">
                    <div class="p-3 border rounded-4 d-flex justify-content-between align-items-center">
                        <div>
                            <span class="text-muted d-block small">ชื่อบัญชี</span>
                            <span class="fw-bold"><?= h($acc['account_name']) ?></span>
                        </div>
                        <div class="text-end">
                            <span class="text-muted d-block small">คงเหลือ</span>
                            <span class="text-primary fw-bold">฿<?= number_format($acc['balance'], 2) ?></span>
                        </div>
                    </div>
                </div>
                <?php endforeach; ?>
            </div>
        </div>
    </div>

    <div class="col-lg-4">
        <div class="card border-0 shadow-sm rounded-4 p-4 h-100">
            <h5 class="fw-bold mb-4 text-center">สัดส่วนรายจ่ายเดือนนี้</h5>
            <canvas id="expenseChart"></canvas>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const ctx = document.getElementById('expenseChart').getContext('2d');
const breakdown = <?= json_encode($summary['expense_breakdown']) ?>;

new Chart(ctx, {
    type: 'doughnut',
    data: {
        labels: breakdown.map(i => i.category_name),
        datasets: [{
            data: breakdown.map(i => i.total_amount),
            backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796'],
            hoverOffset: 4
        }]
    },
    options: {
        plugins: { legend: { position: 'bottom' } },
        cutout: '70%'
    }
});
</script>