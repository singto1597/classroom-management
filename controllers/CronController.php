<?php

class CronController {
    private $pdo;

    public function __construct($pdo) {
        $this->pdo = $pdo;
    }

    public function simulate() {
        $room_id = $_SESSION['room_id'];
        
        date_default_timezone_set('Asia/Bangkok');
        $tomorrow = new DateTime('tomorrow');
        $target_date = $tomorrow->format('Y-m-d');
        
        $thai_days = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
        $day_name = $thai_days[$tomorrow->format('w')];

        $payload = [
            "status" => "success",
            "room_id" => $room_id,
            "target_date" => $target_date,
            "day_name" => $day_name,
            "schedule" => [
                "attire" => "-",
                "subjects" => "-"
            ],
            "announcements" => [
                "bring_items" => "-",
                "note" => "-"
            ],
            "tasks" => []
        ];

        try {
            $stmt = $this->pdo->prepare("SELECT attire, subjects FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
            $stmt->execute([$room_id, $day_name]);
            if ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $payload['schedule']['attire'] = $row['attire'];
                $payload['schedule']['subjects'] = $row['subjects'];
            }

            $stmt = $this->pdo->prepare("SELECT new_attire, note FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
            $stmt->execute([$room_id, $target_date]);
            if ($override = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $payload['schedule']['attire'] = "🚨 " . $override['new_attire'] . " (กรณีพิเศษ)";
                $payload['announcements']['note'] = $override['note'];
            }

            $stmt = $this->pdo->prepare("SELECT bring_items, announcement FROM daily_notes WHERE room_id = ? AND target_date = ?");
            $stmt->execute([$room_id, $target_date]);
            if ($note_data = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $payload['announcements']['bring_items'] = $note_data['bring_items'];
                if (!$override && $note_data['announcement']) {
                    $payload['announcements']['note'] = $note_data['announcement']; 
                }
            }

            $stmt = $this->pdo->prepare("SELECT task_name, due_date FROM tasks WHERE room_id = ? AND status = 'pending' ORDER BY due_date ASC");
            $stmt->execute([$room_id]);
            $today = new DateTime('today');
            
            while ($t = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $due = new DateTime($t['due_date']);
                $diff = (int)$today->diff($due)->format('%R%a');
                
                $t['days_left'] = $diff;
                $payload['tasks'][] = $t;
            }

        } catch (PDOException $e) {
            $payload = [
                "status" => "error",
                "message" => "เกิดข้อผิดพลาด: " . $e->getMessage()
            ];
        }


        if (isset($_GET['format']) && $_GET['format'] == 'json') {
            header('Content-Type: application/json; charset=utf-8');
            echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
            exit(); 
        }

        if (isset($_POST['simulate'])) {
            $output_payload = $payload; 
        }
        
        require 'views/cron/simulate.php';
    }
}
?>