<?php
require_once 'services/ApiClient.php';

class Note {
    private $api;

    public function __construct() {
        $this->api = new ApiClient();
    }

    public function saveDailyNote($room_id, $target_date, $bring_items, $announcement) {
        $payload = [
            "target_date" => $target_date,
            "bring_items" => $bring_items,
            "announcement" => $announcement,
            "user_name" => $_SESSION['user_name'] ?? 'Web_Admin'
        ];
        $this->api->request('POST', "{$room_id}/notes", ['json' => $payload]);
        return true;
    }
}
?>