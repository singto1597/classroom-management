<div class="container max-w-4xl mx-auto py-4">
    <div class="d-flex align-items-center mb-4">
        <a href="index.php" class="btn btn-outline-secondary btn-sm me-3">⬅️ กลับหน้าหลัก</a>
        <h3 class="mb-0 fw-bold">🗺️ แผนผังโครงสร้างห้องเรียน (Roadmap)</h3>
    </div>

    <?php
    $role_map = [
        'president' => ['emoji' => '👑', 'name' => 'หัวหน้าห้อง', 'color' => 'warning', 'text' => 'dark'],
        'vice_academic' => ['emoji' => '📖', 'name' => 'รองฯ วิชาการ', 'color' => 'primary', 'text' => 'white'],
        'vice_activity' => ['emoji' => '🎭', 'name' => 'รองฯ กิจกรรม', 'color' => 'success', 'text' => 'white'],
        'vice_discipline' => ['emoji' => '⚖️', 'name' => 'รองฯ วินัย', 'color' => 'danger', 'text' => 'white'],
        'vice_reception' => ['emoji' => '🤝', 'name' => 'รองฯ ปฏิคม', 'color' => 'info', 'text' => 'dark'],
        'treasurer' => ['emoji' => '💰', 'name' => 'เหรัญญิก', 'color' => 'warning', 'text' => 'dark'],
        'staff_academic' => ['emoji' => '📝', 'name' => 'กก. วิชาการ', 'color' => 'light', 'text' => 'dark'],
        'staff_activity' => ['emoji' => '🎪', 'name' => 'กก. กิจกรรม', 'color' => 'light', 'text' => 'dark'],
        'staff_discipline' => ['emoji' => '🛡️', 'name' => 'กก. วินัย', 'color' => 'light', 'text' => 'dark'],
        'staff_reception' => ['emoji' => '🎀', 'name' => 'กก. ปฏิคม', 'color' => 'light', 'text' => 'dark'],
    ];

    // จัดกลุ่มจากข้อมูลที่เรา map มา
    $board = ['president' => [], 'vices' => [], 'staffs' => []];
    foreach ($committee_data as $p) {
        $role = $p['role'];
        if ($role === 'president') $board['president'][] = $p;
        elseif (str_starts_with($role, 'vice_') || $role === 'treasurer') $board['vices'][] = $p;
        elseif (str_starts_with($role, 'staff_')) $board['staffs'][] = $p;
    }

    $render_person = function($p) use ($role_map) {
        $detail = $role_map[$p['role']] ?? ['emoji' => '✨', 'name' => $p['role'], 'color' => 'secondary', 'text' => 'white'];
        return "
            <div class='col'>
                <div class='card text-center border-0 bg-{$detail['color']} text-{$detail['text']} shadow-sm h-100 rounded-4' style='min-height: 90px;'>
                    <div class='card-body p-3 d-flex flex-column justify-content-center'>
                        <div class='display-6 mb-2'>{$detail['emoji']}</div>
                        <div class='fw-bold mb-1 fs-5'>{$p['name']}</div>
                        <div class='small opacity-75'>{$detail['name']}</div>
                    </div>
                </div>
            </div>
        ";
    };
    ?>

    <div class="row justify-content-center mb-4">
        <?php foreach ($board['president'] as $p) echo $render_person($p); ?>
    </div>

    <div class="row row-cols-2 row-cols-md-3 row-cols-lg-5 justify-content-center g-3 mb-4">
        <?php foreach ($board['vices'] as $p) echo $render_person($p); ?>
    </div>

    <hr class="my-5 opacity-25">

    <h5 class="text-center text-muted fw-bold mb-3">คณะกรรมการฝ่ายต่างๆ</h5>
    <div class="row row-cols-2 row-cols-md-4 g-3 justify-content-center mb-5">
        <?php foreach ($board['staffs'] as $p) echo $render_person($p); ?>
    </div>

</div>