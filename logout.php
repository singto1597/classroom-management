<?php
require_once 'config/database.php';
// ล้างบาง Session ทุกอย่างทิ้งให้หมด
session_destroy();
// เด้งกลับไปหน้า Login
header("Location: login.php");
exit();
?>