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
    
    <div class="card border-0 shadow-sm rounded-4 p-3 mb-4">
        <form method="GET" action="index.php" class="row g-2 align-items-end">
            <input type="hidden" name="page" value="finance_transactions">
            <div class="col-md-3">
                <label class="small text-muted fw-bold">ประเภท</label>
                <select name="type" class="form-select rounded-pill shadow-none">
                    <option value="">ทั้งหมด</option>
                    <option value="income" <?= ($_GET['type'] ?? '') == 'income' ? 'selected' : '' ?>>รายรับ</option>
                    <option value="expense" <?= ($_GET['type'] ?? '') == 'expense' ? 'selected' : '' ?>>รายจ่าย</option>
                </select>
            </div>
            <div class="col-md-3">
                <label class="small text-muted fw-bold">จากวันที่</label>
                <input type="date" name="start_date" value="<?= h($_GET['start_date'] ?? '') ?>" class="form-control rounded-pill shadow-none">
            </div>
            <div class="col-md-3">
                <label class="small text-muted fw-bold">ถึงวันที่</label>
                <input type="date" name="end_date" value="<?= h($_GET['end_date'] ?? '') ?>" class="form-control rounded-pill shadow-none">
            </div>
            <div class="col-md-3 d-flex gap-2">
                <button type="submit" class="btn btn-primary rounded-pill w-100 fw-bold shadow-sm">ค้นหา</button>
                <a href="index.php?page=finance_transactions" class="btn btn-light rounded-pill w-100 border fw-bold shadow-sm">ล้างค่า</a>
            </div>
        </form>
    </div>

    <div class="d-flex justify-content-between mb-2">
        <select id="limitSelect" class="form-select form-select-sm w-auto rounded-pill shadow-none">
            <option value="10">10 รายการ</option>
            <option value="50" selected>50 รายการ</option>
            <option value="100">100 รายการ</option>
            <option value="200">200 รายการ</option>
        </select>
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
            <tbody id="transactionTableBody">
                <tr><td colspan="5" class="text-center py-4 text-muted">กำลังโหลดข้อมูล...</td></tr>
            </tbody>
        </table>
    </div>

    <div id="paginationContainer" class="d-flex justify-content-center mt-4"></div>
</div>

<script>
let currentPage = 1;

// 1. ฟังก์ชันดึงข้อมูลจาก API
async function loadTransactions(page = 1) {
    currentPage = page;
    const limit = document.getElementById('limitSelect').value;
    const type = document.querySelector('select[name="type"]').value;
    const startDate = document.querySelector('input[name="start_date"]').value;
    const endDate = document.querySelector('input[name="end_date"]').value;

    const tbody = document.getElementById('transactionTableBody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted"><div class="spinner-border text-primary spinner-border-sm me-2"></div>กำลังโหลด...</td></tr>';

    try {
        let url = `index.php?page=finance_transactions&format=json&p=${page}&limit=${limit}`;
        if (type) url += `&type=${type}`;
        if (startDate) url += `&start_date=${startDate}`;
        if (endDate) url += `&end_date=${endDate}`;

        const res = await fetch(url);
        const json = await res.json();

        if (json.status === 'success') {
            renderTable(json.data.items);
            renderPagination(json.data.total_count, limit, page);
        } else {
            throw new Error(json.message || "โหลดข้อมูลไม่ได้");
        }
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-danger">เกิดข้อผิดพลาดในการโหลดข้อมูล</td></tr>';
    }
}

// 2. ฟังก์ชันวาดตาราง
function renderTable(items) {
    const tbody = document.getElementById('transactionTableBody');
    tbody.innerHTML = '';
    
    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">ยังไม่มีประวัติการทำรายการ</td></tr>';
        return;
    }

    items.forEach(t => {
        // จัดการสีและเครื่องหมายบวกลบ
        const amountClass = t.transaction_type === 'income' ? 'text-success' : 'text-danger';
        const amountSign = t.transaction_type === 'income' ? '+' : '-';
        
        // จัดการเรื่องวันที่ให้เหมือนเดิม
        let dateHtml = '—';
        if (t.created_at) {
            // เอา string ที่ได้มาแปลงเป็น Date Object ตรงๆ เลย (ไม่ต้องเติม Z แล้ว)
            // เช็คว่ามี T ไหม ถ้าไม่มีให้ใส่ (บางที DB ส่งมาเป็นเว้นวรรค)
            let rawDate = t.created_at.includes('T') ? t.created_at : t.created_at.replace(' ', 'T');
            const d = new Date(rawDate);
            
            // บวกเพิ่มไป 5 ชั่วโมง
            d.setHours(d.getHours() + 5);
            
            const dateStr = d.toLocaleDateString('en-GB'); 
            const timeStr = d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' });
            dateHtml = `${dateStr}<br>${timeStr} น.`;
        }

        // จัดการ Badge หมวดหมู่
        const catBadge = t.category_name 
            ? `<span class="badge bg-secondary opacity-75">${t.category_name}</span>` 
            : '';
            
        // จัดการชื่อบัญชี (กัน Null)
        const accName = t.account_name || 'ไม่ระบุบัญชี';

        // จัดการปุ่มยกเลิก (Revert)
        const isTransferIncome = (t.transfer_group_id && t.transaction_type === 'income');
        let actionBtn = '';
        
        if (!isTransferIncome) {
            actionBtn = `<button class="btn btn-sm btn-light text-danger rounded-circle btn-revert" 
                            data-id="${t.id}" 
                            data-desc="${t.description}"
                            title="ยกเลิกรายการนี้">
                        <i class="bi bi-arrow-counterclockwise fs-6"></i>
                    </button>`;
        } else {
            actionBtn = `<span class="badge bg-light text-muted opacity-50" title="ยกเลิกได้ที่รายการขาออก">
                            <i class="bi bi-link-45deg"></i> โอนเงิน
                        </span>`;
        }

        // แปลงตัวเลขให้มีลูกน้ำ (Comma) สวยๆ แบบ PHP number_format
        const formattedAmount = parseFloat(t.amount).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2});

        const row = `<tr>
            <td class="small text-muted text-nowrap">${dateHtml}</td>
            <td>
                <span class="d-block fw-bold">${t.description}</span>
                <div class="small">
                    ${catBadge}
                    <span class="text-muted ms-1"><i class="bi bi-person-circle"></i> ${t.recorded_by}</span>
                </div>
            </td>
            <td>
                <span class="badge bg-light text-dark border rounded-pill px-2 py-1">
                    <i class="bi bi-wallet2 text-primary"></i> ${accName}
                </span>
            </td>
            <td class="text-end text-nowrap">
                <span class="fw-bold ${amountClass}">${amountSign} ฿${formattedAmount}</span>
            </td>
            <td class="text-center">${actionBtn}</td>
        </tr>`;
        
        tbody.insertAdjacentHTML('beforeend', row);
    });
}

// 3. ฟังก์ชันวาดปุ่มหน้า
function renderPagination(totalCount, limit, currentPage) {
    const totalPages = Math.ceil(totalCount / limit);
    const container = document.getElementById('paginationContainer');
    container.innerHTML = '';

    if (totalPages <= 1) return;

    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement('button');
        btn.className = `btn btn-sm mx-1 fw-bold ${i === currentPage ? 'btn-primary shadow-sm' : 'btn-light border'}`;
        btn.innerText = i;
        btn.onclick = () => loadTransactions(i);
        container.appendChild(btn);
    }
}

// 4. Event Delegation สำหรับปุ่ม Revert (เพราะปุ่มถูกสร้างใหม่ตลอด)
document.getElementById('transactionTableBody').addEventListener('click', function(e) {
    // หาปุ่มที่ถูกคลิก หรือปุ่มที่เป็นพ่อของไอคอน (กรณีคนกดโดนไอคอน)
    const btn = e.target.closest('.btn-revert');
    if (!btn) return; // ถ้าไม่ได้คลิกที่ปุ่ม Revert ก็ไม่ต้องทำอะไร

    const transId = btn.dataset.id;
    const transDesc = btn.dataset.desc;
    
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
                    Swal.fire('คืนเงินสำเร็จ!', res.message, 'success').then(() => {
                        // โหลดข้อมูลหน้าเดิมใหม่โดยไม่ต้องรีเฟรชหน้าเว็บทั้งหน้า!
                        loadTransactions(currentPage); 
                    });
                } else {
                    Swal.fire('ยกเลิกไม่ได้', res.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error!', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
            }
        }
    });
});

// Event Listeners ตอนเปลี่ยน Filter หรือ Limit
document.getElementById('limitSelect').addEventListener('change', () => loadTransactions(1));
document.querySelector('form').addEventListener('submit', (e) => {
    e.preventDefault(); 
    loadTransactions(1);
});

// โหลดครั้งแรก
loadTransactions(1);
</script>