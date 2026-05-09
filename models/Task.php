<?php
require_once 'services/ApiClient.php';

class Task {
    private $api;

    public function __construct() {
        $this->api = new ApiClient();
    }

    public function getAllTasks($room_id) {
        return $this->api->request('GET', "{$room_id}/tasks");
    }

    public function getPendingTasks($room_id) {
        return $this->api->request('GET', "{$room_id}/tasks", ['query' => ['status' => 'pending']]);
    }

    public function getDoneTasks($room_id) {
        return $this->api->request('GET', "{$room_id}/tasks", ['query' => ['status' => 'done']]);
    }

    public function getTaskById($task_id, $room_id) {
        return $this->api->request('GET', "{$room_id}/tasks/{$task_id}");
    }

    public function addTask($room_id, $task_name, $task_detail, $due_date) {
        $payload = [
            "task_name" => $task_name,
            "task_detail" => $task_detail,
            "due_date" => $due_date,
            "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'
        ];
        $this->api->request('POST', "{$room_id}/tasks", ['json' => $payload]);
        return true;
    }

    public function updateTask($task_id, $room_id, $task_name, $task_detail, $due_date) {
        $payload = [
            "task_name" => $task_name,
            "task_detail" => $task_detail,
            "due_date" => $due_date,
            "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'
        ];
        $this->api->request('PUT', "{$room_id}/tasks/{$task_id}", ['json' => $payload]);
        return true;
    }

    public function markDone($task_id, $room_id) {
        $payload = ["user_name" => $_SESSION['user_name'] ?? 'Web_Admin'];
        $this->api->request('PATCH', "{$room_id}/tasks/{$task_id}/done", ['json' => $payload]);
        return true;
    }

    public function markPending($task_id, $room_id) {
        $payload = ["status" => "pending", "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'];
        $this->api->request('PATCH', "{$room_id}/tasks/{$task_id}/status", ['json' => $payload]);
        return true;
    }

    public function deleteTask($task_id, $room_id) {
        $payload = ["user_name" => $_SESSION['user_name'] ?? 'Web_Admin'];
        $this->api->request('DELETE', "{$room_id}/tasks/{$task_id}", ['json' => $payload]);
        return true;
    }
}
?>