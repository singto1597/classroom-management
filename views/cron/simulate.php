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
        <div class="card-footer bg-light p-3 text-center border-0 rounded-bottom-4">
            <div class="text-muted small">
                <span class="badge bg-dark me-1">API Endpoint</span> สำหรับให้ดึง JSON ไปใช้งาน:<br>
                <code class="text-primary bg-white px-3 py-1 rounded-pill shadow-sm border mt-2 d-inline-block">/index.php?page=cron&format=json</code>
            </div>
        </div>
    </div>

    <?php if(isset($output_payload) && $output_payload['status'] == 'success'): ?>
        <div class="card shadow border-0 rounded-4 mx-auto mt-5 fade-in-up" style="max-width: 650px; background-color: #f0f2f5;">
            <div class="card-header bg-success text-white px-4 py-3 border-0 rounded-top-4 d-flex justify-content-between align-items-center">
                <span class="fw-bold">💬 ตัวอย่างข้อความที่จะส่งเข้าแชท</span>
                <span class="badge bg-white text-success rounded-pill px-3 py-2 shadow-sm">ส่งไปห้อง: <?= $output_payload['room_id'] ?></span>
            </div>
            
            <div class="card-body p-4">
                <div class="chat-bubble p-4 shadow-sm">
                    <div style="font-size: 1.05em; line-height: 1.7; color: #333;">
                        <h5 class="text-primary fw-bold mb-3">📢 @everyone สรุปตารางเรียนและงานของวันพรุ่งนี้</h5>
                        
                        <div class="mb-3">
                            <span class="fw-bold text-dark">📅 วัน<?= $output_payload['day_name'] ?>ที่ <?= $output_payload['target_date'] ?></span><br>
                            <span class="fw-bold text-secondary">👕 ชุดที่ต้องใส่:</span> <?= htmlspecialchars($output_payload['schedule']['attire']) ?><br>
                            <span class="fw-bold text-secondary">📚 วิชาเรียน:</span> <?= htmlspecialchars($output_payload['schedule']['subjects']) ?>
                        </div>
                        
                        <?php if ($output_payload['announcements']['bring_items'] !== "-"): ?>
                            <div class="mb-1"><span class="fw-bold text-danger">🎒 สิ่งที่ต้องเตรียม:</span> <?= htmlspecialchars($output_payload['announcements']['bring_items']) ?></div>
                        <?php endif; ?>
                        
                        <?php if ($output_payload['announcements']['note'] !== "-"): ?>
                            <div class="mb-3"><span class="fw-bold text-warning text-darken">📢 ประกาศ/หมายเหตุ:</span> <?= htmlspecialchars($output_payload['announcements']['note']) ?></div>
                        <?php endif; ?>
                        
                        <hr class="text-muted opacity-25">
                        
                        <?php if (count($output_payload['tasks']) > 0): ?>
                            <div class="fw-bold text-danger mb-2">⚠️ ลิสต์งานค้างทั้งหมด</div>
                            <ul class="list-unstyled mb-0 ms-2">
                            <?php foreach ($output_payload['tasks'] as $t): 
                                $status_badge = "🟢";
                                if ($t['days_left'] < 0) $status_badge = "<span class='text-danger fw-bold'>(เลยกำหนดมา ".abs($t['days_left'])." วัน!)</span>";
                                elseif ($t['days_left'] == 0) $status_badge = "<span class='text-warning text-dark fw-bold'>🔥 (ส่งวันนี้!)</span>";
                                elseif ($t['days_left'] == 1) $status_badge = "<span class='text-warning text-dark fw-bold'>⚠️ (ส่งพรุ่งนี้!)</span>";
                            ?>
                                <li class="mb-1">📌 <?= htmlspecialchars($t['task_name']) ?> <?= $status_badge ?></li>
                            <?php endforeach; ?>
                            </ul>
                        <?php else: ?>
                            <div class="text-success fw-bold">✅ ลิสต์งานค้างทั้งหมด: ไม่มีงานจ้า</div>
                        <?php endif; ?>
                    </div>
                </div>
            </div>
        </div>
        
    <?php elseif(isset($output_payload) && $output_payload['status'] == 'error'): ?>
        <div class="alert alert-danger shadow-sm border-0 rounded-4 mt-4 mx-auto fade-in-up" style="max-width: 650px;">
            <i class="fw-bold">❌ ข้อผิดพลาด:</i> <?= $output_payload['message'] ?>
        </div>
    <?php endif; ?>

    <div class="mt-5 text-center">
        <a href="index.php" class="btn btn-outline-secondary rounded-pill px-4">🏠 กลับหน้า Dashboard</a>
    </div>
</div>