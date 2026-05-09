<?php
require_once 'config/database.php';

// ถ้า Login อยู่แล้ว ให้เด้งไป Dashboard เลย
if (isset($_SESSION['room_id'])) {
    header("Location: index.php");
    exit();
}

$client_id = $_ENV['DISCORD_CLIENT_ID'];
$redirect_uri = urlencode($_ENV['DISCORD_REDIRECT_URI']);
$discord_url = "https://discord.com/oauth2/authorize?client_id={$client_id}&response_type=code&redirect_uri={$redirect_uri}&scope=identify";
?>
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>เข้าสู่ระบบ | Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
    <div class="card shadow border-0 rounded-4 p-4 text-center" style="max-width: 400px; width: 100%;">
        <h2 class="fw-bold text-primary mb-3">Classroom Sync</h2>
        <p class="text-muted mb-4">ระบบจัดการห้องเรียนอัตโนมัติ<br>กรุณาเข้าสู่ระบบด้วย Discord</p>
        <a href="<?= $discord_url ?>" class="btn btn-primary btn-lg rounded-pill fw-bold w-100" style="background-color: #5865F2; border: none;">
            <i class="bi bi-discord"></i> Login with Discord
        </a>
    </div>
</body>
</html>