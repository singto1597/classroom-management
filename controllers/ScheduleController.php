<?php
require_once 'models/Schedule.php';

class ScheduleController {
    private $scheduleModel;

    public function __construct() {
        $this->scheduleModel = new Schedule();
    }

    public function setDefault() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง!");
            }
            if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์สั่งงาน!");

            $room_id = $_SESSION['room_id'];
            $day = $_POST['day_of_week'];
            
            $this->scheduleModel->saveDefault($room_id, $day, $_POST['attire'], $_POST['subjects']);
            $success_msg = "✅ บันทึกตารางวัน $day เรียบร้อยแล้ว!";
        }
        require 'views/schedules/set.php';
    }

    public function setOverride() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง!");
            }
            if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์สั่งงาน!");

            $room_id = $_SESSION['room_id'];
            $target_date = $_POST['target_date'];
            
            $this->scheduleModel->saveOverride($room_id, $target_date, $_POST['new_attire'], $_POST['note']);
            $success_msg = "🚨 ตั้งข้อยกเว้นสำหรับวันที่ $target_date เรียบร้อยแล้ว!";
        }
        require 'views/schedules/override.php';
    }
}
?>