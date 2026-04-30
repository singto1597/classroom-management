<div class="container mt-5 text-center">
    <div class="card shadow border-danger mx-auto" style="max-width: 500px;">
        <div class="card-header bg-danger text-white">
            <h4 class="mb-0">🚨 พบข้อผิดพลาด!</h4>
        </div>
        <div class="card-body py-5">
            <div class="display-1 mb-3">⚠️</div>
            <h5 class="text-secondary">
                <?= isset($_SESSION['error_message']) ? h($_SESSION['error_message']) : "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ" ?>
            </h5>
            <?php unset($_SESSION['error_message']); // โชว์เสร็จแล้วลบทิ้ง ?>
        </div>
        <div class="card-footer bg-transparent">
            <a href="javascript:history.back()" class="btn btn-outline-danger">🔙 กลับไปหน้าเดิม</a>
            <a href="index.php" class="btn btn-secondary">🏠 กลับหน้าหลัก</a>
        </div>
    </div>
</div>