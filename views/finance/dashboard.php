<?php
// 1. สร้าง Array ชื่อเดือนภาษาไทย
$thai_months = [
    1 => 'มกราคม', 2 => 'กุมภาพันธ์', 3 => 'มีนาคม', 4 => 'เมษายน',
    5 => 'พฤษภาคม', 6 => 'มิถุนายน', 7 => 'กรกฎาคม', 8 => 'สิงหาคม',
    9 => 'กันยายน', 10 => 'ตุลาคม', 11 => 'พฤศจิกายน', 12 => 'ธันวาคม'
];

// 2. กำหนดเดือน Default เป็นเดือนปัจจุบัน (ถ้ายังไม่ได้เลือก)
$selected_month = isset($_GET['month']) && $_GET['month'] != '' ? (int)$_GET['month'] : (int)date('n');
?>

<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold mb-0 text-white" id="dashboard-title">
        📊 สรุปภาพรวมการเงิน <span class="fs-5 text-warning">(เดือน <?= $thai_months[$selected_month] ?>)</span>
    </h3>
    <div class="d-flex gap-2">
        <select id="monthSelector" class="form-select rounded-pill border-0 shadow-sm px-4 fw-bold">
            <?php for($m=1; $m <= 12; $m++): ?>
                <option value="<?= $m ?>" <?= ($m === $selected_month) ? 'selected' : '' ?>>
                    เดือน <?= $thai_months[$m] ?>
                </option>
            <?php endfor; ?>
        </select>
    </div>
</div>

<div id="dashboard-data" data-breakdown='<?= htmlspecialchars(json_encode($summary['expense_breakdown']), ENT_QUOTES, 'UTF-8') ?>'>
    
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
                <h5 class="fw-bold mb-4 text-center">สัดส่วนรายจ่าย</h5>
                <canvas id="expenseChart"></canvas>
            </div>
        </div>
    </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
let expenseChartInstance = null;

// ฟังก์ชันสำหรับวาดกราฟ
function renderChart(breakdownData) {
    const canvas = document.getElementById('expenseChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // ถ้ามีกราฟเก่าค้างอยู่ ต้องลบทิ้งก่อนวาดใหม่ (ป้องกันบั๊กกราฟซ้อนกัน)
    if (expenseChartInstance) {
        expenseChartInstance.destroy();
    }

    // 🌟 เปลี่ยนสีตัวหนังสือใน Chart.js ทั้งหมดให้เป็นสีขาว (ตามที่ขอ)
    Chart.defaults.color = '#ffffff'; 

    expenseChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: breakdownData.map(i => i.category_name),
            datasets: [{
                data: breakdownData.map(i => i.total_amount),
                backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796'],
                borderWidth: 0, // เอาเส้นขอบออกให้สวยขึ้น
                hoverOffset: 4
            }]
        },
        options: {
            plugins: { 
                legend: { position: 'bottom' } 
            },
            cutout: '70%'
        }
    });
}

// 1. วาดกราฟตอนเข้าหน้าเว็บครั้งแรก
const initialData = JSON.parse(document.getElementById('dashboard-data').getAttribute('data-breakdown'));
renderChart(initialData);

// 2. ดักจับตอนที่เปลี่ยนเดือนใน Dropdown (ทำ AJAX เปลี่ยนข้อมูลแบบเนียนๆ)
document.getElementById('monthSelector').addEventListener('change', async function() {
    const month = this.value;
    const container = document.getElementById('dashboard-data');
    const title = document.getElementById('dashboard-title');
    
    // ทำเอฟเฟกต์จางลง ระหว่างรอข้อมูล
    container.style.opacity = '0.3';
    container.style.transition = 'opacity 0.3s ease';
    container.style.pointerEvents = 'none';

    try {
        // ยิงไปขอข้อมูลหน้า Dashboard ของเดือนใหม่
        const response = await fetch(`index.php?page=finance_dashboard&month=${month}`);
        const html = await response.text();
        
        // แกะเอาเฉพาะส่วนเนื้อหาที่เปลี่ยน (HTML DOM Parsing)
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        // สลับเอาข้อมูลตัวเลขใหม่มาแปะ
        const newContent = doc.getElementById('dashboard-data');
        container.innerHTML = newContent.innerHTML;
        container.setAttribute('data-breakdown', newContent.getAttribute('data-breakdown'));
        
        // อัปเดตหัวข้อ (บอกเดือน)
        title.innerHTML = doc.getElementById('dashboard-title').innerHTML;

        // วาดกราฟใหม่ด้วยข้อมูลเดือนใหม่
        const newData = JSON.parse(newContent.getAttribute('data-breakdown'));
        renderChart(newData);
        
    } catch(e) {
        console.error('Error loading new month data:', e);
    }
    
    // คืนค่าให้สว่างกลับมาเหมือนเดิม
    container.style.opacity = '1';
    container.style.pointerEvents = 'auto';
});
</script>