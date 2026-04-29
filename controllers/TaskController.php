<?php
require_once 'models/Task.php';
require_once 'models/AuditLog.php';

class TaskController {
    private $taskModel;
    private $auditModel;
    private $pdo;

    public function __construct($pdo) {
        $this->pdo = $pdo;
        $this->taskModel = new Task($pdo);
        $this->auditModel = new AuditLog($pdo);
    }

    public function index() {
        $room_id = $_SESSION['room_id'];
        $tasks = $this->taskModel->getPendingTasks($room_id);
        
        require 'views/tasks/view.php';
    }

    public function create() {
        $success_msg = null;
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $room_id = $_SESSION['room_id'];
            $this->taskModel->addTask($room_id, $_POST['task_name'], $_POST['task_detail'], $_POST['due_date']);
            
            $this->auditModel->log($room_id, $_SESSION['user_name'], "Add Task", "เพิ่มงาน: " . $_POST['task_name']);
            $success_msg = "เพิ่มงานเรียบร้อยแล้ว!";
        }
        require 'views/tasks/add.php';
    }

    public function action() {
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $task_id = $_POST['task_id'];
            $action = $_POST['action'];
            $room_id = $_SESSION['room_id'];

            $task = $this->taskModel->getTaskById($task_id, $room_id);
            if (!$task) die("ไม่พบงานนี้!");

            if ($action == 'mark_done') {
                $this->taskModel->markDone($task_id, $room_id);
                $this->auditModel->log($room_id, $_SESSION['user_name'], "Mark Done", "ส่งงาน: " . $task['task_name']);
            } elseif ($action == 'delete') {
                $this->taskModel->deleteTask($task_id, $room_id);
                $this->auditModel->log($room_id, $_SESSION['user_name'], "Delete Task", "ลบงาน: " . $task['task_name']);
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
            $task_name = $_POST['task_name'];
            $task_detail = $_POST['task_detail'];
            $due_date = $_POST['due_date'];

            $this->taskModel->updateTask($task_id, $room_id, $task_name, $task_detail, $due_date);

            $this->auditModel->log($room_id, $_SESSION['user_name'], "Edit Task", "แก้ไขงาน: " . $task_name);

            header("Location: index.php?page=tasks");
            exit();
        }

        $task = $this->taskModel->getTaskById($task_id, $room_id);
        
        if (!$task) {
            die("<div class='alert alert-danger text-center mt-5'>ไม่พบข้อมูลงานนี้ อาจจะถูกลบไปแล้ว หรือคุณกำลังพยายามเข้า id ห้องอื่น</div>");
        }

        require 'views/tasks/edit.php';
    }
}
?>