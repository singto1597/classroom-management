<?php
// เปิดโหมดโชว์ Error (เอาไว้ตอนทำ Prototype)
error_reporting(E_ALL);
ini_set('display_errors', 1);

// เริ่มต้น Session เพื่อดึงข้อมูลจากระบบโรงเรียน
session_start();

// จำลองการ Login ของระบบโรงเรียน (Mockup)
// ในของจริง คุณครูจะตั้งค่า $_SESSION พวกนี้มาจากหน้าระบบหลักของโรงเรียน
if (!isset($_SESSION['room_id'])) {
    $_SESSION['room_id'] = 2; 
    $_SESSION['room_name'] = 'ม.4/2';
    $_SESSION['user_name'] = 'หัวหน้าห้อง_Demo'; // ชื่อคนที่กำลังล็อกอิน
}

$host = 'localhost';
$dbname = 'ess_classroom_announcement';
$username = 'classroom_user'; 
$password = 'singto25222524'; 


try {
    $pdo = new PDO("mysql:host=$host;dbname=$dbname;charset=utf8mb4", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch(PDOException $e) {
    die("เชื่อมต่อฐานข้อมูลล้มเหลว: " . $e->getMessage());
}

function logAction($pdo, $action, $detail) {
    $room_id = $_SESSION['room_id'];
    $user_name = $_SESSION['user_name'];
    
    $stmt = $pdo->prepare("INSERT INTO audit_logs (room_id, user_name, action, detail) VALUES (?, ?, ?, ?)");
    $stmt->execute([$room_id, $user_name, $action, $detail]);
}
?>

?>