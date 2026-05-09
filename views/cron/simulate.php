<style>
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    .fade-in-up { animation: fadeIn 0.4s ease-out forwards; }
    .chat-bubble { background-color: #ffffff; border-radius: 15px; border: 1px solid #e0e0e0; }
</style>

<div class="container py-4">
    <div class="card shadow-sm border-0 rounded-4 mx-auto mb-4" style="max-width: 650px;">
        <div class="card-header bg-gradient bg-primary text-white p-4 text-center border-0 rounded-top-4">
            <h3 class="fw-bold mb-0">⏰ ระบบจำลองแจ้งเตือน (Cron Simulator)</h3>
        </div>
        <div class="card-body p-4 text-center">
            <p class="text-muted mb-4 fs-5">ทดสอบประมวลผลข้อมูล เพื่อจำลองการส่งข้อความสรุปตารางเรียน<br>และงานค้างเข้ากลุ่มแชทในเวลา 19:00 น.</p>
            
            <form method="POST" action="index.php?page=cron">
                <button type="submit" name="simulate" class="btn btn-primary btn-lg rounded-pill px-5 py-3 shadow-sm fw-bold transition-all" style="font-size: 1.2rem;">
                    กดเพื่อจำลองการทำงาน (19:00 น.)
                </button>
            </form>
        </div>
    </div>

    <?php if(isset($output_payload) && isset($output_payload['date'])): ?>
        <div class="card shadow border-0 rounded-4 mx-auto mt-5 fade-in-up" style="max-width: 650px; background-color: #f0f2f5;">
            <div class="card-header bg-success text-white px-4 py-3 border-0 rounded-top-4 d-flex justify-content-between align-items-center">
                <span class="fw-bold">💬 ตัวอย่างข้อความที่จะส่งเข้าแชท</span>
                <span class="badge bg-white text-success rounded-pill px-3 py-2 shadow-sm">ดึงจาก API สำเร็จ!</span>
            </div>
            
            <div class="card-body p-4">
                <div class="chat-bubble p-4 shadow-sm">
                    <div style="font-size: 1.05em; line-height: 1.7; color: #333;">
                        <h5 class="text-primary fw-bold mb-3">📢 @everyone สรุปตารางเรียนและงานของวันพรุ่งนี้</h5>
                        
                        <div class="mb-3">
                            <span class="fw-bold text-dark">📅 วัน<?= htmlspecialchars($output_payload['day']) ?>ที่ <?= htmlspecialchars($output_payload['date']) ?></span><br>
                            <span class="fw-bold text-secondary">👕 ชุดที่ต้องใส่:</span> <?= htmlspecialchars($output_payload['attire']) ?><br>
                            <span class="fw-bold text-secondary">📚 วิชาเรียน:</span> <?= htmlspecialchars($output_payload['subjects']) ?>
                        </div>
                        
                        <?php if ($output_payload['bring'] !== "-"): ?>
                            <div class="mb-1"><span class="fw-bold text-danger">🎒 สิ่งที่ต้องเตรียม:</span> <?= htmlspecialchars($output_payload['bring']) ?></div>
                        <?php endif; ?>
                        
                        <?php if ($output_payload['note'] !== "-"): ?>
                            <div class="mb-3"><span class="fw-bold text-warning text-darken">📢 ประกาศ/หมายเหตุ:</span> <?= htmlspecialchars($output_payload['note']) ?></div>
                        <?php endif; ?>
                        
                        <hr class="text-muted opacity-25">
                        
                        <?php if (!empty($output_payload['tasks_due'])): ?>
                            <div class="fw-bold text-danger mb-2">⚠️ ลิสต์งานค้างทั้งหมด</div>
                            <ul class="list-unstyled mb-0 ms-2">
                            <?php foreach ($output_payload['tasks_due'] as $t): ?>
                                <li class="mb-1"><?= htmlspecialchars($t['display_text']) ?></li>
                            <?php endforeach; ?>
                            </ul>
                        <?php else: ?>
                            <div class="text-success fw-bold">✅ ลิสต์งานค้างทั้งหมด: ไม่มีงานจ้า</div>
                        <?php endif; ?>
                    </div>
                </div>
            </div>
        </div>
        
    <?php elseif(isset($output_payload) && isset($output_payload['status']) && $output_payload['status'] == 'error'): ?>
        <div class="alert alert-danger shadow-sm border-0 rounded-4 mt-4 mx-auto fade-in-up" style="max-width: 650px;">
            <i class="fw-bold">❌ ข้อผิดพลาด:</i> <?= htmlspecialchars($output_payload['message']) ?>
        </div>
    <?php endif; ?>

    <div class="mt-5 text-center">
        <a href="index.php" class="btn btn-outline-secondary rounded-pill px-4">🏠 กลับหน้า Dashboard</a>
    </div>
</div>