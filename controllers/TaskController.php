<?php
require_once 'models/Task.php';

class TaskController {
    private $taskModel;

    public function __construct() {
        $this->taskModel = new Task();
    }

    public function index() {
        $room_id = $_SESSION['room_id'];
        $tasks = $this->taskModel->getAllTasks($room_id); 
        require 'views/tasks/view.php';
    }

    public function create() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง!");
            }
            if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์สั่งงาน!");

            $task_name = trim($_POST['task_name']);
            if (empty($task_name)) {
                abort("ชื่องานห้ามเป็นค่าว่างครับ!");
            }
            $room_id = $_SESSION['room_id'];
            
            $this->taskModel->addTask(
                $room_id, 
                $_POST['task_name'], 
                $_POST['task_detail'], 
                $_POST['due_date']
            );
            
            $success_msg = "เพิ่มงานเรียบร้อยแล้ว!";
        }
        require 'views/tasks/add.php';
    }

    public function action() {
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง! อาจถูกโจมตีแบบ CSRF");
            }
            if ($_SESSION['role'] === 'student') {
                abort("คุณไม่มีสิทธิ์ลบหรือแก้ไขงานครับ!");
            }

            $task_id = (int)$_POST['task_id'];
            $action = $_POST['action'];
            $room_id = $_SESSION['room_id'];

            if ($action == 'mark_done') {
                $this->taskModel->markDone($task_id, $room_id);
            } elseif ($action == 'mark_pending') {
                $this->taskModel->markPending($task_id, $room_id);
            } elseif ($action == 'delete') {
                $this->taskModel->deleteTask($task_id, $room_id);
            }
            
            header("Location: index.php?page=tasks");
            exit();
        }
    }

    public function edit() {
        $room_id = $_SESSION['room_id'];
        
        if (!isset($_GET['id'])) {
            header("Location: index.php?page=tasks");
            exit();
        }
        $task_id = $_GET['id'];

        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
                abort("Token ไม่ถูกต้อง!");
            }
            if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์สั่งงาน!");

            $task_name = trim($_POST['task_name']);
            if (empty($task_name)) {
                abort("ชื่องานห้ามเป็นค่าว่างครับ!");
            }

            $this->taskModel->updateTask(
                $task_id, 
                $room_id, 
                $task_name, 
                $_POST['task_detail'], 
                $_POST['due_date']
            );

            header("Location: index.php?page=tasks");
            exit();
        }

        $task = $this->taskModel->getTaskById($task_id, $room_id);
        if (!$task) {
            abort("ไม่พบข้อมูลงานนี้ อาจจะถูกลบไปแล้ว หรือคุณกำลังพยายามเข้า id ห้องอื่น");
        }

        require 'views/tasks/edit.php';
    }
}
?>