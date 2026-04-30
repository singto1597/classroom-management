<style>
    .task-item {
        transition: all 0.4s cubic-bezier(0.4, 0.0, 0.2, 1);
        overflow: hidden;
        transform-origin: center center;
    }

    .task-hide {
        opacity: 0 !important;
        transform: scale(0.5) !important;
        width: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        pointer-events: none;
    }
</style>

<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="mb-0">📋 รายการงาน</h3>
    <div class="btn-group shadow-sm">
        <button type="button" class="btn btn-sm btn-primary filter-btn" data-filter="pending">กำลังทำ</button>
        <button type="button" class="btn btn-sm btn-outline-success filter-btn" data-filter="done">เสร็จแล้ว</button>
        <button type="button" class="btn btn-sm btn-outline-dark filter-btn" data-filter="all">ทั้งหมด</button>
    </div>
</div>

<div class="row align-items-stretch" id="task-container">
    <?php 
    $today = new DateTime();
    foreach($tasks as $task): 
        $is_done = ($task['status'] === 'done'); 
        
        $due_date = new DateTime($task['due_date']);
        $interval = $today->diff($due_date);
        $days_left = (int)$interval->format('%R%a');
        
        if ($is_done) {
            $badge_class = 'bg-secondary';
            $status_text = "ส่งแล้ว 🎉";
            $card_style = "opacity: 0.75; background-color: #f8f9fa;"; 
            $text_strike = "text-decoration-line-through text-muted"; 
        } else {
            $card_style = "";
            $text_strike = "";
            $badge_class = 'bg-success';
            $status_text = "เหลืออีก {$days_left} วัน";
            
            if ($days_left < 0) {
                $badge_class = 'bg-danger';
                $status_text = "เลยกำหนดมา " . abs($days_left) . " วัน!";
            } elseif ($days_left == 0) {
                $badge_class = 'bg-warning text-dark';
                $status_text = "ส่งวันนี้!";
            } elseif ($days_left == 1) {
                $badge_class = 'bg-warning text-dark';
                $status_text = "ส่งพรุ่งนี้!";
            }
        }
    ?>
        <div class="col-md-4 mb-3 task-item" data-status="<?= h($task['status']) ?>">
            <div class="card shadow-sm h-100" style="<?= $card_style ?>; min-width: 280px;"> 
                <div class="card-body">
                    <h5 class="card-title <?= $text_strike ?>">📌 <?= h($task['task_name']) ?></h5>
                    <h6 class="card-subtitle mb-2 text-muted">กำหนดส่ง: <?= h($task['due_date']) ?></h6>
                    <p class="card-text <?= $text_strike ?>"><?= h($task['task_detail']) ?></p>
                    <span class="badge <?= $badge_class ?>"><?= $status_text ?></span>
                </div>
                
                <?php if ($_SESSION['role'] !== 'student'): ?>
                <div class="card-footer bg-transparent border-top-0 d-flex justify-content-between align-items-center">
                    <form method="POST" action="index.php?page=task_action" class="d-inline">
                        <input type="hidden" name="task_id" value="<?= h($task['id']) ?>">
                        <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                        <?php if ($is_done): ?>
                            <input type="hidden" name="action" value="mark_pending">
                            <button type="submit" class="btn btn-sm btn-outline-warning" title="เผื่อมือลั่น">🔄 ยังไม่เสร็จ</button>
                        <?php else: ?>
                            <input type="hidden" name="action" value="mark_done">
                            <button type="submit" class="btn btn-sm btn-outline-success">✅ เสร็จแล้ว</button>
                        <?php endif; ?>
                    </form>

                    <div>
                        <a href="index.php?page=tasks_edit&id=<?= h($task['id']) ?>" class="btn btn-sm btn-outline-primary">✏️</a>
                        <form method="POST" action="index.php?page=task_action" class="d-inline" onsubmit="return confirm('ลบงานนี้ทิ้งเลยไหม?');">
                            <input type="hidden" name="task_id" value="<?= h($task['id']) ?>">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="csrf_token" value="<?= $_SESSION['csrf_token'] ?>">
                            <button type="submit" class="btn btn-sm btn-outline-danger">🗑️</button>
                        </form>
                    </div>
                </div>
                <?php endif; ?>
            </div>
        </div>
    <?php endforeach; ?>
    
    <div id="empty-state" class="col-12 d-none transition-all">
        <div class="alert alert-success mt-2 text-center shadow-sm">🎉 ไม่มีงานในหมวดหมู่นี้เลย</div>
    </div>
</div>

<div class="mt-4 text-center">
    <a href="index.php?page=tasks_add" class="btn btn-primary me-2 shadow-sm">➕ เพิ่มงานใหม่</a>
    <a href="index.php" class="btn btn-secondary shadow-sm">🏠 กลับหน้าหลัก</a>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const filterBtns = document.querySelectorAll('.filter-btn');
    const taskItems = document.querySelectorAll('.task-item');
    const emptyState = document.getElementById('empty-state');

    function applyFilter(filterType) {
        let visibleCount = 0;

        filterBtns.forEach(btn => {
            const btnType = btn.getAttribute('data-filter');
            btn.className = `btn btn-sm filter-btn btn-outline-${btnType === 'pending' ? 'primary' : (btnType === 'done' ? 'success' : 'dark')}`;
            if (btnType === filterType) {
                btn.classList.replace(`btn-outline-${btnType === 'pending' ? 'primary' : (btnType === 'done' ? 'success' : 'dark')}`, `btn-${btnType === 'pending' ? 'primary' : (btnType === 'done' ? 'success' : 'dark')}`);
            }
        });

        taskItems.forEach(item => {
            const itemStatus = item.getAttribute('data-status');
            
            if (filterType === 'all' || filterType === itemStatus) {
                item.classList.remove('task-hide');
                visibleCount++;
            } else {
                item.classList.add('task-hide');
            }
        });


        setTimeout(() => {
            if (visibleCount === 0 && taskItems.length > 0) {
                emptyState.classList.remove('d-none');
            } else {
                emptyState.classList.add('d-none');
            }
        }, 300);
    }

    filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            applyFilter(e.target.getAttribute('data-filter'));
        });
    });

    applyFilter('pending');
});
</script>