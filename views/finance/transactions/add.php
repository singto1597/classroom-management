<div class="card border-0 shadow-sm rounded-4 p-4 max-w-lg mx-auto" style="max-width: 600px;">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h4 class="fw-bold mb-0">บันทึกรายการเงิน</h4>
        <a href="index.php?page=finance_transactions" class="btn btn-sm btn-light rounded-pill"><i class="bi bi-arrow-left"></i> กลับ</a>
    </div>

    <ul class="nav nav-pills nav-fill mb-4 bg-light rounded-pill p-1" id="transactionTabs" role="tablist">
        <li class="nav-item" role="presentation">
            <button class="nav-link active rounded-pill fw-bold" id="expense-tab" data-bs-toggle="tab" data-bs-target="#expense" type="button" role="tab">🔴 รายจ่าย</button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link rounded-pill fw-bold" id="income-tab" data-bs-toggle="tab" data-bs-target="#income" type="button" role="tab">🟢 รายรับ</button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link rounded-pill fw-bold" id="transfer-tab" data-bs-toggle="tab" data-bs-target="#transfer" type="button" role="tab">🔵 โอนเงิน</button>
        </li>
    </ul>

    <div class="tab-content" id="transactionTabsContent">
        
        <div class="tab-pane fade show active" id="expense" role="tabpanel">
            <form class="ajax-form" id="transactionForm">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="add_transaction">
                <input type="hidden" name="transaction_type" id="transTypeInput" value="expense">

                <div class="mb-3">
                    <label class="form-label text-muted small fw-bold">จำนวนเงิน (฿)</label>
                    <input type="number" name="amount" class="form-control form-control-lg rounded-4 text-end fs-4" placeholder="0.00" step="0.01" required>
                </div>

                <div class="mb-3">
                    <label class="form-label text-muted small fw-bold">บัญชี/กระเป๋าเงิน</label>
                    <select name="account_id" class="form-select rounded-4" required>
                        <option value="" disabled selected>-- เลือกบัญชี --</option>
                        <?php foreach($accounts as $acc): ?>
                            <option value="<?= $acc['id'] ?>"><?= h($acc['account_name']) ?> (เหลือ ฿<?= number_format($acc['balance'], 2) ?>)</option>
                        <?php endforeach; ?>
                    </select>
                </div>

                <div class="mb-3">
                    <label class="form-label text-muted small fw-bold">หมวดหมู่</label>
                    <select name="category_id" id="categorySelect" class="form-select rounded-4" required>
                        <option value="" disabled selected>-- เลือกหมวดหมู่ --</option>
                    </select>
                </div>

                <div class="mb-4">
                    <label class="form-label text-muted small fw-bold">รายละเอียด (บันทึกช่วยจำ)</label>
                    <input type="text" name="description" class="form-control rounded-4" placeholder="เช่น ซื้อไม้กวาดห้อง" required>
                </div>

                <button type="submit" id="mainSubmitBtn" class="btn btn-danger w-100 py-3 rounded-pill fw-bold shadow-sm">บันทึกรายจ่าย</button>
            </form>
        </div>

        <div class="tab-pane fade" id="income" role="tabpanel"></div>

        <div class="tab-pane fade" id="transfer" role="tabpanel">
            <form class="ajax-form" id="transferForm">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="transfer_money">

                <div class="mb-3">
                    <label class="form-label text-muted small fw-bold">จำนวนเงินที่โอน (฿)</label>
                    <input type="number" name="amount" class="form-control form-control-lg rounded-4 text-end fs-4" placeholder="0.00" step="0.01" required>
                </div>

                <div class="row mb-3">
                    <div class="col-6">
                        <label class="form-label text-muted small fw-bold text-danger">โอนจาก</label>
                        <select name="from_account_id" class="form-select rounded-4" required>
                            <option value="" disabled selected>-- ต้นทาง --</option>
                            <?php foreach($accounts as $acc): ?>
                                <option value="<?= $acc['id'] ?>"><?= h($acc['account_name']) ?></option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    <div class="col-6">
                        <label class="form-label text-muted small fw-bold text-success">เข้าสู่</label>
                        <select name="to_account_id" class="form-select rounded-4" required>
                            <option value="" disabled selected>-- ปลายทาง --</option>
                            <?php foreach($accounts as $acc): ?>
                                <option value="<?= $acc['id'] ?>"><?= h($acc['account_name']) ?></option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                </div>

                <div class="mb-4">
                    <label class="form-label text-muted small fw-bold">รายละเอียด</label>
                    <input type="text" name="description" class="form-control rounded-4" placeholder="เช่น ฝากเงินสดเข้าธนาคารห้อง" required>
                </div>

                <div class="mb-4">
                    <label class="form-label text-muted small fw-bold">URL รูปสลิปหลักฐาน (ถ้ามี)</label>
                    <input type="url" name="slip_image_url" class="form-control rounded-4" placeholder="https://ลิงก์รูปภาพสลิป...">
                </div>

                <button type="submit" class="btn btn-info text-white w-100 py-3 rounded-pill fw-bold shadow-sm">ยืนยันการโอน</button>
            </form>
        </div>

    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
// ข้อมูลหมวดหมู่จาก PHP
const catIncome = <?= json_encode($categories_inc) ?>;
const catExpense = <?= json_encode($categories_exp) ?>;

// ฟังก์ชันสลับหมวดหมู่และปุ่ม ตอนกดเปลี่ยนแท็บ
function updateCategoryDropdown(type) {
    const select = document.getElementById('categorySelect');
    const transTypeInput = document.getElementById('transTypeInput');
    const submitBtn = document.getElementById('mainSubmitBtn');
    const data = type === 'income' ? catIncome : catExpense;
    
    transTypeInput.value = type;
    select.innerHTML = '<option value="" disabled selected>-- เลือกหมวดหมู่ --</option>';
    data.forEach(cat => {
        select.innerHTML += `<option value="${cat.id}">${cat.category_name}</option>`;
    });

    // เปลี่ยนสีและข้อความปุ่มให้เข้ากับโหมด
    if(type === 'income') {
        submitBtn.className = 'btn btn-success w-100 py-3 rounded-pill fw-bold shadow-sm';
        submitBtn.innerHTML = 'บันทึกรายรับ';
    } else {
        submitBtn.className = 'btn btn-danger w-100 py-3 rounded-pill fw-bold shadow-sm';
        submitBtn.innerHTML = 'บันทึกรายจ่าย';
    }
}

// ผูก Event การกด Tab
document.getElementById('expense-tab').addEventListener('click', () => {
    updateCategoryDropdown('expense');
    document.getElementById('expense').appendChild(document.getElementById('transactionForm'));
});

document.getElementById('income-tab').addEventListener('click', () => {
    updateCategoryDropdown('income');
    document.getElementById('income').appendChild(document.getElementById('transactionForm')); // ย้ายฟอร์มตามไป
});

// รันครั้งแรกตั้งต้นเป็น รายจ่าย
updateCategoryDropdown('expense');

// ระบบ AJAX ยิงข้อมูลแบบสมูทๆ
document.querySelectorAll('.ajax-form').forEach(form => {
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // เช็คก่อนว่าโอนเงินกระเป๋าเดียวกันไหม
        if(this.id === 'transferForm' && this.from_account_id.value === this.to_account_id.value) {
            return Swal.fire('ห๊ะ!', 'จะโอนเข้ากระเป๋าตัวเองทำไมครับพี่!', 'warning');
        }

        const btn = this.querySelector('button[type="submit"]');
        const oldText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> กำลังบันทึก...';
        btn.disabled = true;

        try {
            const formData = new FormData(this);
            const response = await fetch('index.php?page=finance_action&format=json', {
                method: 'POST', body: formData
            });
            const result = await response.json();

            if (response.ok && result.status === 'success') {
                Swal.fire('เรียบร้อย!', result.message, 'success').then(() => {
                    window.location.href = 'index.php?page=finance_transactions'; // บันทึกเสร็จเด้งไปหน้าประวัติ
                });
            } else {
                Swal.fire('ผิดพลาด!', result.message, 'error');
            }
        } catch (error) {
            Swal.fire('พัง!', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
        } finally {
            btn.innerHTML = oldText;
            btn.disabled = false;
        }
    });
});
</script>