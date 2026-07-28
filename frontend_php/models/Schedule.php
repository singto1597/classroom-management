<?php
require_once 'services/ApiClient.php';

class Schedule {
    private $api;

    public function __construct() {
        $this->api = new ApiClient();
    }

    public function saveDefault($room_id, $day_of_week, $attire, $subjects) {
        $payload = [
            "day_of_week" => $day_of_week,
            "attire" => $attire,
            "subjects" => $subjects,
            "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'
        ];
        $this->api->request('POST', "{$room_id}/schedule/default", ['json' => $payload]);
        return true;
    }

    public function saveOverride($room_id, $target_date, $new_attire, $note) {
        $payload = [
            "target_date" => $target_date,
            "new_attire" => $new_attire,
            "note" => $note,
            "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'
        ];
        // เช็คให้ชัวร์ว่าตรงกับ Endpoint ที่ออกแบบไว้ใน FastAPI
        $this->api->request('POST', "{$room_id}/schedule/override", ['json' => $payload]); 
        return true;
    }
}
?>