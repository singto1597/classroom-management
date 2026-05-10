<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);

require_once dirname(__DIR__) . '/vendor/autoload.php';

$dotenv = Dotenv\Dotenv::createImmutable(dirname(__DIR__));
$dotenv->load();

session_set_cookie_params([
    'lifetime' => 0,
    'path'     => '/',
    'secure'   => false, // ถ้าขึ้นโฮสต์จริงมี HTTPS ค่อยแก้เป็น true
    'httponly' => true,
    'samesite' => 'Lax'
]);

session_start();

// จำลอง Session ไปก่อน (เดี๋ยวเราค่อยมาทำ Login ด้วย Discord ทับตรงนี้)
if (!isset($_SESSION['room_id'])) {
    $_SESSION['room_id'] = 1500761770468315248; // 🚨 เปลี่ยนเป็น Discord Server ID ของห้องมึง
    $_SESSION['user_name'] = 'Web_Admin_Demo';
    $_SESSION['role'] = 'leader';
    $_SESSION['discord_id'] = 1090855069462843403; // 🚨 ใส่ Discord ID มึงไว้เทสก่อน
}

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