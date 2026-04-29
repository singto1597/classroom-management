<?php
class Task {
    private $pdo;

    public function __construct($pdo) {
        $this->pdo = $pdo;
    }

    public function getPendingTasks($room_id) {
        $stmt = $this->pdo->prepare("SELECT * FROM tasks WHERE room_id = ? AND status = 'pending' ORDER BY due_date ASC");
        $stmt->execute([$room_id]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    public function getTaskById($task_id, $room_id) {
        $stmt = $this->pdo->prepare("SELECT * FROM tasks WHERE id = ? AND room_id = ?");
        $stmt->execute([$task_id, $room_id]);
        return $stmt->fetch(PDO::FETCH_ASSOC);
    }

    public function addTask($room_id, $task_name, $task_detail, $due_date) {
        $stmt = $this->pdo->prepare("INSERT INTO tasks (room_id, task_name, task_detail, due_date) VALUES (?, ?, ?, ?)");
        return $stmt->execute([$room_id, $task_name, $task_detail, $due_date]);
    }

    public function updateTask($task_id, $room_id, $task_name, $task_detail, $due_date) {
        $stmt = $this->pdo->prepare("UPDATE tasks SET task_name = ?, task_detail = ?, due_date = ? WHERE id = ? AND room_id = ?");
        return $stmt->execute([$task_name, $task_detail, $due_date, $task_id, $room_id]);
    }

    public function markDone($task_id, $room_id) {
        $stmt = $this->pdo->prepare("UPDATE tasks SET status = 'done' WHERE id = ? AND room_id = ?");
        return $stmt->execute([$task_id, $room_id]);
    }

    public function deleteTask($task_id, $room_id) {
        $stmt = $this->pdo->prepare("DELETE FROM tasks WHERE id = ? AND room_id = ?");
        return $stmt->execute([$task_id, $room_id]);
    }
}
?>