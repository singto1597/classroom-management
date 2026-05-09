<?php
require_once 'config/database.php'; 

$page = isset($_GET['page']) ? $_GET['page'] : 'dashboard';
$is_api = isset($_GET['format']) && $_GET['format'] == 'json';
$is_file_download = ($page === 'students_export' && $_SERVER['REQUEST_METHOD'] === 'POST');

if (!isset($_SESSION['room_id']) && $page !== 'error') {
    header("Location: login.php");
    exit();
}

if (!$is_api && !$is_file_download) {  // ← เพิ่ม condition
    require 'views/layouts/header.php'; 
}

switch ($page) {
    case 'dashboard':
        require 'views/dashboard.php';
        break;

    case 'tasks':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController();
        $controller->index();
        break;
    case 'tasks_add':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController();
        $controller->create();
        break;
    case 'tasks_edit':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController();
        $controller->edit();
        break;
    case 'task_action':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController();
        $controller->action();
        break;

    case 'notes':
        require_once 'controllers/NoteController.php';
        $controller = new NoteController();
        $controller->create();
        break;

    case 'schedules_set':
        require_once 'controllers/ScheduleController.php';
        $controller = new ScheduleController();
        $controller->setDefault();
        break;
    case 'schedules_override':
        require_once 'controllers/ScheduleController.php';
        $controller = new ScheduleController();
        $controller->setOverride();
        break;

    case 'cron':
        require_once 'controllers/CronController.php';
        $controller = new CronController();
        $controller->simulate();
        break;
        
    case 'error':
        require 'views/errors/error.php';
        break;


    case 'students':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->index();
        break;
    case 'students_me':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->myProfile();
        break;
    case 'students_add':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->add();
        break;
    case 'students_edit':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->edit();
        break;
    case 'students_action':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->action();
        break;
    case 'students_export':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->export();
        break;
    
    case 'students_profile':
        require_once 'controllers/StudentController.php';
        $controller = new StudentController();
        $controller->profile();
        break;

    case 'logs':
        require_once 'controllers/LogController.php';
        $controller = new LogController();
        $controller->index();
        break;

    default:
        echo "<div class='text-center mt-5'><h1>404 Not Found</h1><p>หาหน้านี้ไม่เจอจ้า</p></div>";
        break;
}

if (!$is_api && !$is_file_download) {  // ← เพิ่ม condition
    require 'views/layouts/footer.php'; 
}
?>