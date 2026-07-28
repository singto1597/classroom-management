<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold mb-0">📜 ประวัติการใช้งานระบบ (Audit Logs)</h3>
</div>

<div class="card shadow-sm border-0 rounded-4 overflow-hidden">
    <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
            <thead class="bg-dark text-white">
                <tr>
                    <th class="ps-4">เวลา (Timestamp)</th>
                    <th>ผู้กระทำ (User)</th>
                    <th>ประเภทแอคชัน (Action)</th>
                    <th>รายละเอียด (Details)</th>
                </tr>
            </thead>
            <tbody>
                <?php if(empty($logs)): ?>
                    <tr><td colspan="4" class="text-center py-4">ยังไม่มีประวัติการทำงานในระบบ</td></tr>
                <?php else: ?>
                    <?php foreach ($logs as $log): 
                        // แต่งสี Badge ตามประเภท Action
                        $badge = 'bg-secondary';
                        if (str_contains($log['action'], 'Task') || str_contains($log['action'], 'Done')) $badge = 'bg-primary';
                        if (str_contains($log['action'], 'Security') || str_contains($log['action'], 'Delete')) $badge = 'bg-danger';
                        if (str_contains($log['action'], 'Add')) $badge = 'bg-success';
                    ?>
                    <tr>
                        <td class="ps-4 text-muted small"><?= h($log['timestamp']) ?></td>
                        <td class="fw-bold text-primary">@<?= h($log['user_name']) ?></td>
                        <td><span class="badge <?= $badge ?>"><?= h($log['action']) ?></span></td>
                        <td><?= h($log['detail']) ?></td>
                    </tr>
                    <?php endforeach; ?>
                <?php endif; ?>
            </tbody>
        </table>
    </div>
</div>