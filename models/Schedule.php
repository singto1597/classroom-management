<?php
class Schedule {
    private $pdo;
    public function __construct($pdo) { $this->pdo = $pdo; }

    public function saveDefault($room_id, $day_of_week, $attire, $subjects) {
        try {
            $this->pdo->beginTransaction();

            $stmt = $this->pdo->prepare("DELETE FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
            $stmt->execute([$room_id, $day_of_week]);

            $stmt = $this->pdo->prepare("INSERT INTO default_schedules (room_id, day_of_week, attire, subjects) VALUES (?, ?, ?, ?)");
            $stmt->execute([$room_id, $day_of_week, $attire, $subjects]);

            $this->pdo->commit();
            return true;

        } catch (Exception $e) {
            $this->pdo->rollBack();
            return false;
        }
    }

    public function saveOverride($room_id, $target_date, $new_attire, $note) {
        try {
            $this->pdo->beginTransaction();

            $stmt = $this->pdo->prepare("DELETE FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
            $stmt->execute([$room_id, $target_date]);

            $stmt = $this->pdo->prepare("INSERT INTO schedule_overrides (room_id, target_date, new_attire, note) VALUES (?, ?, ?, ?)");
            $stmt->execute([$room_id, $target_date, $new_attire, $note]);

            $this->pdo->commit();
            return true;

        } catch (Exception $e) {
            $this->pdo->rollBack();
            return false;
        }
    }
}
?>