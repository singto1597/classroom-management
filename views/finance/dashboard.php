<?php
// 1. สร้าง Array ชื่อเดือน
$thai_months = [
    1 => 'มกราคม', 2 => 'กุมภาพันธ์', 3 => 'มีนาคม', 4 => 'เมษายน',
    5 => 'พฤษภาคม', 6 => 'มิถุนายน', 7 => 'กรกฎาคม', 8 => 'สิงหาคม',
    9 => 'กันยายน', 10 => 'ตุลาคม', 11 => 'พฤศจิกายน', 12 => 'ธันวาคม'
];

// 2. ดึงค่าเดือนและปี (ถ้าไม่มีให้ใช้เดือนปัจจุบัน)
$selected_month = isset($_GET['month']) && $_GET['month'] != '' ? (int)$_GET['month'] : (int)date('n');
$selected_year = isset($_GET['year']) && $_GET['year'] != '' ? (int)$_GET['year'] : (int)date('Y');
?>

<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold mb-0 text-dark" id="dashboard-title">
        📊 สรุปภาพรวมการเงิน <span class="fs-5 text-primary">(เดือน <?= $thai_months[$selected_month] ?> <?= $selected_year + 543 ?>)</span>
    </h3>
    <div class="d-flex gap-2">
        <select id="monthSelector" class="form-select rounded-pill border-0 shadow-sm px-4 fw-bold text-primary">
            <?php for($m=1; $m <= 12; $m++): ?>
                <option value="<?= $m ?>" <?= ($m === $selected_month) ? 'selected' : '' ?>>
                    เดือน <?= $thai_months[$m] ?>
                </option>
            <?php endfor; ?>
        </select>
        <input type="hidden" id="currentYear" value="<?= $selected_year ?>">
    </div>
</div>

<div id="dashboard-data" data-breakdown='<?= htmlspecialchars(json_encode($summary['expense_breakdown']), ENT_QUOTES, 'UTF-8') ?>'>
    
    <div class="row g-4 mb-4">
        <div class="col-md-3">
            <div class="card border-0 shadow-sm rounded-4 h-100 overflow-hidden" style="background: linear-gradient(135deg, #4e73df 0%, #224abe 100%);">
                <div class="card-body p-4 position-relative">
                    <i class="bi bi-wallet2 position-absolute" style="font-size: 5rem; right: -10px; bottom: -15px; opacity: 0.15; color: white;"></i>
                    <h6 class="text-white text-opacity-75 small fw-bold mb-2">เงินคงเหลือรวม</h6>
                    <h2 class="fw-bold mb-0 text-white">฿<?= number_format($summary['net_worth'], 2) ?></h2>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card border-0 shadow-sm rounded-4 h-100 overflow-hidden" style="background: linear-gradient(135deg, #f6c23e 0%, #dda20a 100%);">
                <div class="card-body p-4 position-relative">
                    <i class="bi bi-hourglass-split position-absolute" style="font-size: 5rem; right: -10px; bottom: -15px; opacity: 0.15; color: white;"></i>
                    <h6 class="text-white text-opacity-75 small fw-bold mb-2">ยอดที่เพื่อนค้างจ่ายรวม</h6>
                    <h2 class="fw-bold mb-0 text-white">฿<?= number_format($summary['pending_collection_amount'], 2) ?></h2>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card border-0 shadow-sm rounded-4 h-100 overflow-hidden" style="background: linear-gradient(135deg, #1cc88a 0%, #13855c 100%);">
                <div class="card-body p-4 position-relative">
                    <i class="bi bi-graph-up-arrow position-absolute" style="font-size: 5rem; right: -10px; bottom: -15px; opacity: 0.15; color: white;"></i>
                    <h6 class="text-white text-opacity-75 small fw-bold mb-2">รายรับ (<?= $thai_months[$selected_month] ?>)</h6>
                    <h2 class="fw-bold mb-0 text-white">฿<?= number_format($summary['total_income'], 2) ?></h2>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card border-0 shadow-sm rounded-4 h-100 overflow-hidden" style="background: linear-gradient(135deg, #e74a3b 0%, #be2617 100%);">
                <div class="card-body p-4 position-relative">
                    <i class="bi bi-graph-down-arrow position-absolute" style="font-size: 5rem; right: -10px; bottom: -15px; opacity: 0.15; color: white;"></i>
                    <h6 class="text-white text-opacity-75 small fw-bold mb-2">รายจ่าย (<?= $thai_months[$selected_month] ?>)</h6>
                    <h2 class="fw-bold mb-0 text-white">฿<?= number_format($summary['total_expense'], 2) ?></h2>
                </div>
            </div>
        </div>
    </div>

    <div class="row g-4">
        <div class="col-lg-8">
            <div class="card border-0 shadow-sm rounded-4 p-4 h-100">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h5 class="fw-bold mb-0 text-dark">กระเป๋าเงินห้อง</h5>
                    <a href="index.php?page=finance_accounts" class="btn btn-sm btn-light rounded-pill fw-bold">จัดการบัญชี</a>
                </div>
                <div class="row g-3">
                    <?php if(empty($accounts)): ?>
                        <div class="col-12 text-center text-muted py-3">ยังไม่มีกระเป๋าเงิน</div>
                    <?php endif; ?>
                    <?php foreach ($accounts as $acc): ?>
                    <div class="col-md-6">
                        <div class="p-3 border rounded-4 d-flex justify-content-between align-items-center bg-light">
                            <div>
                                <span class="text-muted d-block small mb-1">ชื่อบัญชี</span>
                                <span class="fw-bold text-dark"><?= h($acc['account_name']) ?></span>
                            </div>
                            <div class="text-end">
                                <span class="text-muted d-block small mb-1">คงเหลือ</span>
                                <span class="text-primary fw-bold fs-5">฿<?= number_format($acc['balance'], 2) ?></span>
                            </div>
                        </div>
                    </div>
                    <?php endforeach; ?>
                </div>
            </div>
        </div>

        <div class="col-lg-4">
            <div class="card border-0 shadow-sm rounded-4 p-4 h-100">
                <h5 class="fw-bold mb-4 text-center text-dark">สัดส่วนรายจ่าย</h5>
                <canvas id="expenseChart"></canvas>
            </div>
        </div>
    </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
let expenseChartInstance = null;

// ฟังก์ชันวาดกราฟ
function renderChart(breakdownData) {
    const canvas = document.getElementById('expenseChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // ทำลายกราฟเก่าทิ้งก่อนวาดใหม่ (ป้องกันบั๊กภาพซ้อน)
    if (expenseChartInstance) {
        expenseChartInstance.destroy();
    }

    // 🔴 แก้บั๊กกราฟหน้าขาว: ให้ตัวหนังสือ Legend ในกราฟเป็นสีเทาเข้ม (เพราะพื้นหลังเป็นสีขาว)
    Chart.defaults.color = '#6c757d'; 

    // ดักบั๊กกรณีเดือนนั้น "ไม่มีรายจ่ายเลย" (กราฟจะได้ไม่หายไปเฉยๆ)
    if (!breakdownData || breakdownData.length === 0) {
        expenseChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['ยังไม่มีรายจ่ายในเดือนนี้'],
                datasets: [{ data: [1], backgroundColor: ['#e3e6f0'], borderWidth: 0 }]
            },
            options: { plugins: { legend: { position: 'bottom' }, tooltip: { enabled: false } }, cutout: '75%' }
        });
        return;
    }

    // วาดกราฟปกติตามข้อมูล
    expenseChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: breakdownData.map(i => i.category_name),
            datasets: [{
                data: breakdownData.map(i => i.total_amount),
                backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796'],
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            plugins: { legend: { position: 'bottom' } },
            cutout: '70%'
        }
    });
}

// วาดกราฟตอนเข้าเว็บครั้งแรก
const initialData = JSON.parse(document.getElementById('dashboard-data').getAttribute('data-breakdown'));
renderChart(initialData);

// 🌟 ระบบ Auto Update ข้อมูลเนียนๆ (ไม่กระตุกจอ)
document.getElementById('monthSelector').addEventListener('change', async function() {
    const month = this.value;
    const year = document.getElementById('currentYear').value; // 🔴 FIX: ส่ง 'ปี' ไปให้ Backend ด้วย!
    
    const container = document.getElementById('dashboard-data');
    const title = document.getElementById('dashboard-title');
    
    // ใส่เอฟเฟกต์เฟดตอนโหลด
    container.style.opacity = '0.4';
    container.style.transition = 'opacity 0.3s ease';
    container.style.pointerEvents = 'none';

    try {
        // ยิง Fetch ดึงข้อมูลของเดือน+ปี นั้นมา
        const response = await fetch(`index.php?page=finance_dashboard&month=${month}&year=${year}`);
        const html = await response.text();
        
        // แปลง HTML ที่ได้กลับมา แล้วดึงมาเฉพาะกล่องข้อมูล
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        // สลับข้อมูล HTML เก่า กับ ใหม่
        const newContent = doc.getElementById('dashboard-data');
        container.innerHTML = newContent.innerHTML;
        container.setAttribute('data-breakdown', newContent.getAttribute('data-breakdown'));
        
        // อัปเดตหัวข้อเดือน
        title.innerHTML = doc.getElementById('dashboard-title').innerHTML;

        // วาดกราฟใหม่
        const newData = JSON.parse(newContent.getAttribute('data-breakdown'));
        renderChart(newData);
        
    } catch(e) {
        console.error('Error loading new data:', e);
    }
    
    // คืนค่าความสว่างให้หน้าจอ
    container.style.opacity = '1';
    container.style.pointerEvents = 'auto';
});
</script>