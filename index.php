<?php
require_once 'config/database.php';

$page = isset($_GET['page']) ? $_GET['page'] : 'dashboard';

$is_api = isset($_GET['format']) && $_GET['format'] == 'json';

if (!$is_api) {
    require 'views/layouts/header.php'; 
}

switch ($page) {
    case 'dashboard':
        require 'views/dashboard.php';
        break;

    case 'tasks':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController($pdo);
        $controller->index();
        break;
    case 'tasks_add':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController($pdo);
        $controller->create();
        break;
    case 'tasks_edit':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController($pdo);
        $controller->edit();
        break;
    case 'task_action':
        require_once 'controllers/TaskController.php';
        $controller = new TaskController($pdo);
        $controller->action();
        break;

    case 'notes':
        require_once 'controllers/NoteController.php';
        $controller = new NoteController($pdo);
        $controller->create();
        break;

    case 'schedules_set':
        require_once 'controllers/ScheduleController.php';
        $controller = new ScheduleController($pdo);
        $controller->setDefault();
        break;
    case 'schedules_override':
        require_once 'controllers/ScheduleController.php';
        $controller = new ScheduleController($pdo);
        $controller->setOverride();
        break;

    case 'cron':
        require_once 'controllers/CronController.php';
        $controller = new CronController($pdo);
        $controller->simulate();
        break;

    default:
        echo "<div class='text-center mt-5'><h1>404 Not Found</h1><p>หาหน้านี้ไม่เจอจ้า</p></div>";
        break;
}

if (!$is_api) {
    require 'views/layouts/footer.php'; 
}
?>