<?php
require_once 'models/Schedule.php';
require_once 'models/AuditLog.php';

class ScheduleController {
    private $scheduleModel;
    private $auditModel;

    public function __construct($pdo) {
        $this->scheduleModel = new Schedule($pdo);
        $this->auditModel = new AuditLog($pdo);
    }

    public function setDefault() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $room_id = $_SESSION['room_id'];
            $day = $_POST['day_of_week'];
            
            $this->scheduleModel->saveDefault($room_id, $day, $_POST['attire'], $_POST['subjects']);
            $this->auditModel->log($room_id, $_SESSION['user_name'], "Set Schedule", "ตั้งตารางวัน" . $day);
            $success_msg = "✅ บันทึกตารางวัน $day เรียบร้อยแล้ว!";
        }
        require 'views/schedules/set.php';
    }

    public function setOverride() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $room_id = $_SESSION['room_id'];
            $target_date = $_POST['target_date'];
            
            $this->scheduleModel->saveOverride($room_id, $target_date, $_POST['new_attire'], $_POST['note']);
            $this->auditModel->log($room_id, $_SESSION['user_name'], "Set Override", "ตั้งข้อยกเว้นวันที่ " . $target_date);
            $success_msg = "🚨 ตั้งข้อยกเว้นสำหรับวันที่ $target_date เรียบร้อยแล้ว!";
        }
        require 'views/schedules/override.php';
    }
}
?>