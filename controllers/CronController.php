<?php
require_once 'services/ApiClient.php';

class CronController {

    public function __construct() {
    }

    public function simulate() {
        if (!isset($_SESSION['room_id'])) {
            abort("กรุณาเข้าสู่ระบบก่อน");
        }

        $output_payload = null;
        
        if (isset($_POST['simulate'])) {
            $room_id = $_SESSION['room_id'];
            date_default_timezone_set('Asia/Bangkok');
            
            $tomorrow = new DateTime('tomorrow');
            $target_date = $tomorrow->format('Y-m-d');

            try {
                $api = new ApiClient();
                $output_payload = $api->request('GET', "{$room_id}/summary", [
                    'query' => ['target_date' => $target_date]
                ]);
            } catch (Exception $e) {
                $output_payload = [
                    "status" => "error",
                    "message" => "ไม่สามารถดึงข้อมูลจาก Backend ได้ กรุณาตรวจสอบ API"
                ];
            }
        }

        require 'views/cron/simulate.php';
    }
}
?>