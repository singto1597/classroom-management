<?php
require_once 'services/ApiClient.php';

class LogController {
    public function index() {
        if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์เข้าดูประวัติของระบบ!");
        
        $api = new ApiClient();
        try {
            // ดึงข้อมูล Log จาก FastAPI
            $logs = $api->request('GET', "{$_SESSION['room_id']}/logs");
        } catch (Exception $e) {
            $logs = [];
            $error_msg = $e->getMessage();
        }
        
        require 'views/logs/index.php';
    }
}
?>