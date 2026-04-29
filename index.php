<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - Classroom Sync Enterprise</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .dashboard-card {
            transition: transform 0.2s;
        }
        .dashboard-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 .5rem 1rem rgba(0,0,0,.15)!important;
        }
    </style>
</head>
<body class="bg-light">
    <!-- Navbar -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary shadow-sm">
        <div class="container">
            <a class="navbar-brand fw-bold" href="#">🚀 Classroom-Sync Enterprise</a>
            <span class="navbar-text text-light">
                ระบบจัดการห้องเรียนอัจฉริยะ (Prototype)
            </span>
        </div>
    </nav>

    <div class="container mt-5">
        <div class="row text-center mb-4">
            <div class="col-12">
                <h2 class="fw-bold text-secondary">แผงควบคุมหลัก (Control Panel)</h2>
                <p class="text-muted">เลือกเมนูที่ต้องการจัดการด้านล่างนี้</p>
            </div>
        </div>

        <div class="row g-4">
            <!-- หมวดจัดการงาน -->
            <div class="col-md-6 col-lg-4">
                <div class="card h-100 shadow-sm dashboard-card border-0">
                    <div class="card-body text-center">
                        <div class="display-4 mb-3">📝</div>
                        <h5 class="card-title fw-bold">จัดการงานและการบ้าน</h5>
                        <p class="card-text text-muted">เพิ่มงานใหม่ ดูรายการงานค้าง ติ๊กส่งงาน หรือลบงาน</p>
                        <a href="add_task.php" class="btn btn-primary w-100 mb-2">➕ เพิ่มงานใหม่</a>
                        <a href="view.php" class="btn btn-outline-primary w-100">📋 ดูรายการงานค้างทั้งหมด</a>
                    </div>
                </div>
            </div>

            <!-- หมวดตารางเรียน -->
            <div class="col-md-6 col-lg-4">
                <div class="card h-100 shadow-sm dashboard-card border-0">
                    <div class="card-body text-center">
                        <div class="display-4 mb-3">📅</div>
                        <h5 class="card-title fw-bold">ตารางเรียนยืนพื้น</h5>
                        <p class="card-text text-muted">ตั้งค่าตารางเรียนและชุดที่ต้องใส่ประจำวัน (จันทร์-ศุกร์)</p>
                        <a href="schedule.php" class="btn btn-success w-100 mt-3">⚙️ ตั้งค่าตารางเรียน</a>
                    </div>
                </div>
            </div>

            <!-- หมวดโน้ตรายวัน -->
            <div class="col-md-6 col-lg-4">
                <div class="card h-100 shadow-sm dashboard-card border-0">
                    <div class="card-body text-center">
                        <div class="display-4 mb-3">📌</div>
                        <h5 class="card-title fw-bold">โน้ตและของที่ต้องเตรียม</h5>
                        <p class="card-text text-muted">จดบันทึกสิ่งของที่ต้องเอามา หรือประกาศแจ้งเตือนรายวัน</p>
                        <a href="note.php" class="btn btn-warning w-100 mt-3 text-dark">✍️ จัดการโน้ตรายวัน</a>
                    </div>
                </div>
            </div>

            <!-- หมวดข้อยกเว้น -->
            <div class="col-md-6 col-lg-4 offset-lg-2">
                <div class="card h-100 shadow-sm dashboard-card border-0">
                    <div class="card-body text-center">
                        <div class="display-4 mb-3">🚨</div>
                        <h5 class="card-title fw-bold">ข้อยกเว้นฉุกเฉิน</h5>
                        <p class="card-text text-muted">ตั้งค่ากรณีพิเศษ เช่น กีฬาสี งดเรียน เปลี่ยนชุดกะทันหัน</p>
                        <a href="override.php" class="btn btn-danger w-100 mt-3">⚠️ ตั้งค่าข้อยกเว้น</a>
                    </div>
                </div>
            </div>

            <!-- หมวดจำลองระบบแจ้งเตือน -->
            <div class="col-md-6 col-lg-4">
                <div class="card h-100 shadow-sm dashboard-card border-0 bg-dark text-white">
                    <div class="card-body text-center">
                        <div class="display-4 mb-3">⏰</div>
                        <h5 class="card-title fw-bold">จำลองระบบแจ้งเตือน</h5>
                        <p class="card-text text-light opacity-75">ทดสอบการประมวลผลสรุปงานและตารางของวันพรุ่งนี้ (Cron Job)</p>
                        <a href="cron_simulator.php" class="btn btn-outline-light w-100 mt-3">⚡ ทดสอบการแจ้งเตือน</a>
                    </div>
                </div>
            </div>

        </div>
        
        <footer class="mt-5 mb-4 text-center text-muted">
            <small>&copy; 2026 Classroom-Sync Project - OBEC Hackathon Prototype</small>
        </footer>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>