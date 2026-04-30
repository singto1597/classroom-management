<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);

require_once dirname(__DIR__) . '/vendor/autoload.php';

$dotenv = Dotenv\Dotenv::createImmutable(dirname(__DIR__));
$dotenv->load();

session_start();

if (!isset($_SESSION['room_id'])) {
    $_SESSION['room_id'] = 2; 
    $_SESSION['room_name'] = 'ม.4/2';
    $_SESSION['user_name'] = 'หัวหน้าห้อง_Demo';
    $_SESSION['role'] = 'student';
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

$host = $_ENV['DB_HOST'];
$dbname = $_ENV['DB_NAME'];
$username = $_ENV['DB_USER'];
$password = $_ENV['DB_PASS'];

try {
    $pdo = new PDO("mysql:host=$host;dbname=$dbname;charset=utf8mb4", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch(PDOException $e) {
    abort("เชื่อมต่อฐานข้อมูลล้มเหลว: " . $e->getMessage());
}
?>