<?php
require_once 'models/Note.php';

class NoteController {
    private $noteModel;

    public function __construct() {
        $this->noteModel = new Note();
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
            
            $success_msg = "บันทึกโน้ตสำหรับวันที่ $target_date เรียบร้อย!";
        }
        require 'views/notes/add.php';
    }
}
?>