<?php

class CronController {
    private $pdo;

    public function __construct($pdo) {
        $this->pdo = $pdo;
    }

    public function simulate() {
        $is_api = isset($_GET['format']) && $_GET['format'] == 'json';

        // ===== API Key Auth =====
        if ($is_api) {
            $headers = getallheaders();
            $auth_header = $headers['Authorization'] ?? '';
            $provided_key = str_replace('Bearer ', '', $auth_header);
            $valid_key = $_ENV['CRON_API_KEY'] ?? '';

            if (empty($valid_key) || !hash_equals($valid_key, $provided_key)) {
                http_response_code(401);
                header('Content-Type: application/json; charset=utf-8');
                echo json_encode(["status" => "error", "message" => "Unauthorized"]);
                exit();
            }

            $stmt = $this->pdo->query("SELECT id FROM rooms");
            $room_ids = $stmt->fetchAll(PDO::FETCH_COLUMN);

            $all_payloads = [];
            foreach ($room_ids as $rid) {
                $all_payloads[] = $this->buildPayload($rid);
            }

            header('Content-Type: application/json; charset=utf-8');
            echo json_encode($all_payloads, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
            exit();
        }

        // ===== Web UI =====
        if (!isset($_SESSION['room_id'])) {
            abort("กรุณาเข้าสู่ระบบก่อน");
        }

        $output_payload = null;
        if (isset($_POST['simulate'])) {
            $output_payload = $this->buildPayload($_SESSION['room_id']);
        }

        require 'views/cron/simulate.php';
    }

    private function buildPayload($room_id) {
        date_default_timezone_set('Asia/Bangkok');
        $tomorrow    = new DateTime('tomorrow');
        $target_date = $tomorrow->format('Y-m-d');
        $thai_days   = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
        $day_name    = $thai_days[$tomorrow->format('w')];

        $payload = [
            "status"        => "success",
            "room_id"       => $room_id,
            "target_date"   => $target_date,
            "day_name"      => $day_name,
            "schedule"      => ["attire" => "-", "subjects" => "-"],
            "announcements" => ["bring_items" => "-", "note" => "-"],
            "tasks"         => []
        ];

        try {
            // ตารางเรียนปกติ
            $stmt = $this->pdo->prepare("SELECT attire, subjects FROM default_schedules WHERE room_id = ? AND day_of_week = ?");
            $stmt->execute([$room_id, $day_name]);
            if ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $payload['schedule']['attire']   = $row['attire'];
                $payload['schedule']['subjects'] = $row['subjects'];
            }

            // ข้อยกเว้น (override)
            $stmt = $this->pdo->prepare("SELECT new_attire, note FROM schedule_overrides WHERE room_id = ? AND target_date = ?");
            $stmt->execute([$room_id, $target_date]);
            $override = $stmt->fetch(PDO::FETCH_ASSOC);
            if ($override) {
                $payload['schedule']['attire']      = "🚨 " . $override['new_attire'] . " (กรณีพิเศษ)";
                $payload['announcements']['note']   = $override['note'];
            }

            // โน้ตรายวัน
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
                $t['days_left']  = (int)$today->diff(new DateTime($t['due_date']))->format('%R%a');
                $payload['tasks'][] = $t;
            }

        } catch (PDOException $e) {
            error_log("CronController::buildPayload() error room_id={$room_id}: " . $e->getMessage());
            return [
                "status"  => "error",
                "room_id" => $room_id,
                "message" => "เกิดข้อผิดพลาดภายใน กรุณาลองใหม่อีกครั้ง"
            ];
        }

        return $payload;
    }
}
?>