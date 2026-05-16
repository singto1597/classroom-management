<?php
error_reporting(E_ALL);
ini_set('display_errors', '0');

require_once dirname(__DIR__) . '/vendor/autoload.php';

$dotenv = Dotenv\Dotenv::createImmutable(dirname(__DIR__));
$dotenv->load();

session_set_cookie_params([
    'lifetime' => 2592000, // 30 วัน (ตามกฎโปรเจกต์)
    'path'     => '/',
    'secure'   => true,
    'httponly' => true,
    'samesite' => 'Lax'
]);

session_start();

// 🚀 [Dev Mode] จำลอง Session ข้ามการ Login ถ้าอยู่ในโหมด local
//if (isset($_ENV['APP_ENV']) && $_ENV['APP_ENV'] === 'local' && !isset($_SESSION['room_id'])) {
//    $_SESSION['room_id']    = $_ENV['MOCK_ROOM_ID'] ?? '1500761770468315248';
//    $_SESSION['room_name']  = '401 SMTE 20'; // จำลองชื่อห้อง
//    $_SESSION['role']       = 'leader';         // จำลองสิทธิ์แอดมินไปเลย จะได้เทสได้ทุกฟังก์ชัน
//    $_SESSION['user_name']  = 'singto1597';
//    $_SESSION['discord_id'] = $_ENV['MOCK_DISCORD_ID'] ?? '1090855069462843403';
//}

if (empty($_SESSION['csrf_token'])) {
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
}

function h($text) {
    return htmlspecialchars((string)$text, ENT_QUOTES, 'UTF-8');
}

function abort($message) {
    $_SESSION['error_message'] = $message;
    header("Location: index.php?page=error");
    exit();
}
// ❌ ลบการเชื่อมต่อ MySQL (PDO) ทิ้งไปหมดแล้ว! โคตรคลีน!
?>