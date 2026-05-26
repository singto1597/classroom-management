<div class="card border-0 shadow-sm rounded-4 p-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h4 class="fw-bold mb-0 text-danger"><i class="bi bi-exclamation-triangle-fill me-2"></i> สรุปผู้ค้างชำระ (ทวงหนี้รวม)</h4>
            <p class="text-muted mb-0 small">รายชื่อผู้ค้างจ่ายเงินจากทุกโปรเจกต์ที่ยังเปิดรับเงินอยู่ สามารถกดเคลียร์หนี้รวบยอดได้ที่นี่</p>
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
                    <th class="text-end pe-4">จัดการ</th>
                </tr>
            </thead>
            <tbody>
                <?php if(empty($debtors)): ?>
                    <tr><td colspan="5" class="text-center py-5 fw-bold text-success">🎉 ไม่มีใครติดหนี้ห้องเลย! (รวยมาก)</td></tr>
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
                    <td class="text-end pe-4">
                        <button class="btn btn-primary btn-sm rounded-pill fw-bold px-3 btn-clear-debt" 
                                data-sid="<?= $d['student_id'] ?>" 
                                data-name="<?= h($d['student_name']) ?>">
                            <i class="bi bi-wallet2 me-1"></i> เคลียร์หนี้
                        </button>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>

<div class="modal fade" id="batchPayModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered modal-lg">
        <form class="modal-content border-0 shadow rounded-4" id="batchPayForm">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold mb-0">บันทึกรับเงินรวบยอด: <span id="batchPayName" class="text-primary"></span></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body pb-2">
                <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                <input type="hidden" name="action" value="batch_pay_debt">
                <input type="hidden" name="student_id" id="batchStudentId">

                <div class="mb-4">
                    <label class="form-label small fw-bold text-muted mb-2">เลือกรายการบิลที่ต้องการจ่าย</label>
                    <div id="debtChecklist" class="list-group rounded-4 shadow-sm border overflow-hidden">
                        </div>
                </div>

                <div class="row g-3 mb-3">
                    <div class="col-md-6">
                        <label class="form-label small fw-bold text-muted">รับเงินเข้าบัญชีห้อง</label>
                        <select name="paid_to_account_id" class="form-select rounded-pill" required>
                            <option value="" disabled selected>-- เลือกกระเป๋าเงิน --</option>
                            <?php foreach($accounts as $acc): ?>
                                <option value="<?= $acc['id'] ?>"><?= h($acc['account_name']) ?> (เหลือ ฿<?= number_format($acc['balance'], 2) ?>)</option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label small fw-bold text-muted">URL รูปสลิปโอนเงิน (ถ้ามี)</label>
                        <input type="url" name="slip_image_url" class="form-control rounded-pill" placeholder="https://...">
                    </div>
                </div>
            </div>
            <div class="modal-footer border-0 pt-3 pb-3 bg-light rounded-bottom-4 d-flex justify-content-between align-items-center">
                <div class="fw-bold text-dark">
                    ยอดรวมที่เลือกชำระ: <span id="totalSelectedAmount" class="text-danger fs-4 ms-1">฿0.00</span>
                </div>
                <button type="submit" class="btn btn-success rounded-pill px-4 py-2 fw-bold shadow-sm">
                    <i class="bi bi-check-circle-fill me-1"></i> ยืนยันการรับเงิน
                </button>
            </div>
        </form>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
let batchPayModal;
// 🌟 1. ตัวแปรเก็บความทรงจำ (เก็บ Collection ID ที่เพิ่งเลือกล่าสุด)
let lastSelectedMemory = null; 

document.addEventListener("DOMContentLoaded", function() {
    batchPayModal = new bootstrap.Modal(document.getElementById('batchPayModal'));
});

// 2. กดปุ่มเคลียร์หนี้ -> โหลดข้อมูล
document.querySelectorAll('.btn-clear-debt').forEach(btn => {
    btn.addEventListener('click', async function() {
        const studentId = this.dataset.sid;
        const studentName = this.dataset.name;
        
        document.getElementById('batchStudentId').value = studentId;
        document.getElementById('batchPayName').innerText = studentName;
        
        // แสดงสถานะหมุนรอโหลดข้อมูล
        document.getElementById('debtChecklist').innerHTML = `
            <div class="text-center py-5 text-muted small">
                <span class="spinner-border spinner-border-sm me-2" role="status"></span> กำลังดึงรายการค้างชำระของเพื่อน...
            </div>`;
        
        // Auto-select บัญชีกระเป๋าแรกเพื่อความสะดวก
        const accountSelect = document.querySelector('#batchPayForm select[name="paid_to_account_id"]');
        if (accountSelect && accountSelect.options.length > 1) {
            accountSelect.selectedIndex = 1; 
        }

        batchPayModal.show();

        const formData = new FormData();
        formData.append('action', 'get_student_debts');
        formData.append('student_id', studentId);
        formData.append('csrf_token', '<?= $_SESSION['csrf_token'] ?>');

        try {
            const response = await fetch('index.php?page=finance_action&format=json', { method: 'POST', body: formData });
            const result = await response.json();

            if (response.ok && result.status === 'success') {
                let html = '';
                const debts = result.data.debts ?? [];

                if (debts.length === 0) {
                    html = '<div class="list-group-item text-center py-4 text-muted fw-bold">ไม่พบรายการค้างชำระคงเหลือจ้า</div>';
                } else {
                    debts.forEach(d => {
                        // ===============================================
                        // 🌟 ลอจิก Auto-Select โคตรฉลาด!
                        // ===============================================
                        let isChecked = false;
                        if (lastSelectedMemory === null) {
                            // ถ้าเพิ่งเข้าเว็บมาครั้งแรก ยังไม่เคยจ่ายให้ใครเลย -> ติ๊กให้หมดทุกรายการ!
                            isChecked = true; 
                        } else {
                            // ถ้าเคยจ่ายให้คนอื่นไปแล้ว -> เช็คว่า Collection ID นี้ อยู่ในความทรงจำไหม?
                            isChecked = lastSelectedMemory.includes(d.collection_id.toString());
                        }

                        // เตรียม Attribute ต่างๆ ตามสถานะที่ถูกติ๊ก
                        const checkedState = isChecked ? 'checked' : '';
                        const inputDisabledState = isChecked ? '' : 'disabled';
                        
                        let rowClasses = 'list-group-item d-flex gap-3 align-items-center py-3 border-start-0 border-end-0 transition-all ';
                        rowClasses += isChecked ? '' : 'bg-light';
                        let rowStyle = isChecked ? 'background-color: #f0fdf4;' : '';
                        // ===============================================

                        html += `
                        <label class="${rowClasses}" style="${rowStyle}">
                            <input class="form-check-input flex-shrink-0 fs-4 debt-checkbox" type="checkbox" name="payment_ids[]" value="${d.payment_id}" data-cid="${d.collection_id}" ${checkedState}>
                            <div class="d-flex w-100 justify-content-between align-items-center">
                                <div>
                                    <h6 class="mb-1 fw-bold text-dark">${d.title}</h6>
                                    <span class="badge bg-danger-subtle text-danger rounded-pill px-2">ยอดเต็ม: ฿${parseFloat(d.amount).toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
                                </div>
                                <div class="text-end" style="width: 140px;">
                                    <div class="input-group input-group-sm">
                                        <span class="input-group-text bg-white border-end-0 text-muted">฿</span>
                                        <input type="number" name="pay_amounts[${d.payment_id}]" class="form-control text-end debt-amount-input fw-bold border-start-0 ps-0" value="${d.amount}" step="0.01" min="0.01" max="${d.amount}" ${inputDisabledState} required>
                                    </div>
                                </div>
                            </div>
                        </label>`;
                    });
                }
                document.getElementById('debtChecklist').innerHTML = html;
                calculateTotal(); // คำนวณยอดเงินรวมเริ่มต้น
                bindCheckboxAndInputEvents(); 
            } else {
                document.getElementById('debtChecklist').innerHTML = `<div class="text-center py-4 text-danger fw-bold">${result.message || 'เกิดข้อผิดพลาดจาก API'}</div>`;
            }
        } catch (e) {
            document.getElementById('debtChecklist').innerHTML = '<div class="text-center py-4 text-danger fw-bold">ไม่สามารถติดต่อเซิร์ฟเวอร์ดึงข้อมูลได้</div>';
        }
    });
});

// 3. ฟังก์ชันผูก Event ให้ Checkbox
function bindCheckboxAndInputEvents() {
    document.querySelectorAll('.debt-checkbox').forEach(cb => {
        cb.addEventListener('change', function() {
            const rowItem = this.closest('.list-group-item');
            const input = rowItem.querySelector('.debt-amount-input');
            
            input.disabled = !this.checked; 
            
            if (this.checked) {
                rowItem.classList.remove('bg-light');
                rowItem.style.backgroundColor = '#f0fdf4'; 
            } else {
                rowItem.classList.add('bg-light');
                rowItem.style.backgroundColor = '';
            }

            calculateTotal();
        });
    });

    document.querySelectorAll('.debt-amount-input').forEach(input => {
        input.addEventListener('input', calculateTotal);
    });
}

// 4. ฟังก์ชันคำนวณเงินรวม
function calculateTotal() {
    let total = 0;
    document.querySelectorAll('.debt-checkbox:checked').forEach(cb => {
        const input = cb.closest('.list-group-item').querySelector('.debt-amount-input');
        total += parseFloat(input.value) || 0;
    });
    document.getElementById('totalSelectedAmount').innerText = '฿' + total.toLocaleString('en-US', {minimumFractionDigits: 2});
}

// 5. สั่งส่งฟอร์ม
document.getElementById('batchPayForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const checkedItems = document.querySelectorAll('.debt-checkbox:checked');
    if (checkedItems.length === 0) {
        return Swal.fire('อ๊ะ!', 'กรุณาเลือกติ๊กรายการบิลที่ต้องการชำระเงินอย่างน้อย 1 รายการก่อนครับ', 'warning');
    }

    // 🌟 จดจำการตั้งค่าก่อนกดยืนยัน! ดึง Collection ID ของทุกอันที่ติ๊กไปเก็บไว้ใน Array
    lastSelectedMemory = Array.from(checkedItems).map(cb => cb.dataset.cid.toString());

    const btn = this.querySelector('button[type="submit"]');
    const oldText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> กำลังตัดยอดบัญชี...'; 
    btn.disabled = true;

    try {
        const response = await fetch('index.php?page=finance_action&format=json', {
            method: 'POST', 
            body: new FormData(this)
        });
        const result = await response.json();
        
        if (response.ok && result.status === 'success') {
            batchPayModal.hide();
            // 🌟 แก้ไข: เปลี่ยน location.reload() เป็นพ่น Alert อย่างเดียว
            // เพราะถ้ารีเฟรชหน้าเว็บ ตัวแปร lastSelectedMemory จะโดนรีเซ็ตหายไป!
            Swal.fire({ title: 'สำเร็จ!', text: result.message, icon: 'success', timer: 1500, showConfirmButton: false });
            
            // แอบซ่อนปุ่มของคนที่เพิ่งจ่ายเสร็จ (ให้ดูเหมือนอัปเดต Real-time โดยไม่ต้องรีเฟรชหน้า)
            const studentId = document.getElementById('batchStudentId').value;
            const rowBtn = document.querySelector(`.btn-clear-debt[data-sid="${studentId}"]`);
            if(rowBtn) {
                rowBtn.classList.replace('btn-primary', 'btn-success');
                rowBtn.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> จ่ายแล้ว';
                rowBtn.disabled = true;
            }

        } else {
            Swal.fire('พบข้อผิดพลาด', result.message || 'บันทึกรายการไม่สำเร็จ', 'error');
        }
    } catch (err) {
        Swal.fire('พังพินาศ!', 'ไม่สามารถเชื่อมต่อระบบ API คอนโทรลเลอร์ได้', 'error');
    } finally {
        btn.innerHTML = oldText; 
        btn.disabled = false;
    }
});
</script>