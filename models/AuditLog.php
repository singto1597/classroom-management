<?php
class AuditLog {
    private $pdo;

    public function __construct($pdo) {
        $this->pdo = $pdo;
    }

    public function log($room_id, $user_name, $action, $detail) {
        $stmt = $this->pdo->prepare("INSERT INTO audit_logs (room_id, user_name, action, detail) VALUES (?, ?, ?, ?)");
        return $stmt->execute([$room_id, $user_name, $action, $detail]);
    }
}
?>