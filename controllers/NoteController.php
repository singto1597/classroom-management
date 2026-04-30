<?php
require_once 'models/Note.php';
require_once 'models/AuditLog.php';

class NoteController {
    private $noteModel;
    private $auditModel;

    public function __construct($pdo) {
        $this->noteModel = new Note($pdo);
        $this->auditModel = new AuditLog($pdo);
    }

    public function create() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง!");
            }

            if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์สั่งงาน!");

            $room_id = $_SESSION['room_id'];
            $target_date = $_POST['target_date'];
            
            $this->noteModel->saveDailyNote($room_id, $target_date, $_POST['bring_items'], $_POST['announcement']);
            $this->auditModel->log($room_id, $_SESSION['user_name'], "Add Note", "บันทึกโน้ตวันที่ " . $target_date);
            
            $success_msg = "บันทึกโน้ตสำหรับวันที่ $target_date เรียบร้อย!";
        }
        require 'views/notes/add.php';
    }
}
?>