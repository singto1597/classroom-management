<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Classroom Sync</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary shadow-sm mb-4">
        <div class="container">
            <a class="navbar-brand fw-bold" href="index.php">Classroom-Sync</a>
            <span class="navbar-text text-light">ห้อง: <?= h($_SESSION['room_name']) ?></span>
        </div>
    </nav>
    <div class="container">
        <!-- เนื้อหาแต่ละหน้าจะถูกแทรกตรงนี้ -->