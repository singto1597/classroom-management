<?php
class Note {
    private $pdo;
    public function __construct($pdo) { $this->pdo = $pdo; }

    public function saveDailyNote($room_id, $target_date, $bring_items, $announcement) {
        try {
            $this->pdo->beginTransaction();

            $stmt = $this->pdo->prepare("DELETE FROM daily_notes WHERE room_id = ? AND target_date = ?");
            $stmt->execute([$room_id, $target_date]);

            $stmt = $this->pdo->prepare("INSERT INTO daily_notes (room_id, target_date, bring_items, announcement) VALUES (?, ?, ?, ?)");
            $stmt->execute([$room_id, $target_date, $bring_items, $announcement]);

            $this->pdo->commit();
            return true;

        } catch (Exception $e) {
            $this->pdo->rollBack();
            return false;
        }
    }
}
?>