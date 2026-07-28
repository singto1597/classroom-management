<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
</head>
<body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary shadow-sm mb-4">
        <div class="container">
            <a class="navbar-brand fw-bold" href="index.php">Classroom-Sync</a>
            
            <div class="d-flex align-items-center gap-3">
                <span class="navbar-text text-light">
                    ห้อง: <?= h($_SESSION['room_name']) ?> (<?= h($_SESSION['role']) ?>)
                </span>
                
                <a href="switch_room.php" class="btn btn-sm btn-warning fw-bold shadow-sm">🔄 สลับห้อง</a>
                <a href="logout.php" class="btn btn-sm btn-danger fw-bold shadow-sm">🚪 ออกระบบ</a>
            </div>
        </div>
    </nav>
    <div class="container">