<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>เข้าสู่ระบบ | Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
    <div class="card shadow border-0 rounded-4 p-4 text-center" style="max-width: 400px; width: 100%;">
        <h2 class="fw-bold text-primary mb-3">Classroom Sync</h2>
        <p class="text-muted mb-4">ระบบจัดการห้องเรียนอัตโนมัติ<br>กรุณาเข้าสู่ระบบด้วย Discord</p>
        <a href="<?= h($discord_url) ?>" class="btn btn-lg rounded-pill fw-bold w-100 text-white"
           style="background-color: #5865F2; border: none;">
            <i class="bi bi-discord me-2"></i>Login with Discord
        </a>
    </div>
</body>
</html>