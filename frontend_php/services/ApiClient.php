<?php
use GuzzleHttp\Client;
use GuzzleHttp\Exception\RequestException;

class ApiClient {
    private $client;

    public function __construct() {
        // สร้าง Guzzle Client พร้อมตั้งค่า Default Headers ให้เหมือนฝั่งบอท
        $headers = [
            'X-API-Key' => $_ENV['API_KEY'],
            'Accept'    => 'application/json',
        ];

        // 🚨 ถ้า User Login แล้ว ให้แอบแนบ Discord ID ไปด้วย เผื่อ Backend เช็คสิทธิ์
        if (isset($_SESSION['discord_id'])) {
            $headers['X-Discord-Id'] = (string)$_SESSION['discord_id'];
        }

        $this->client = new Client([
            'base_uri' => rtrim($_ENV['API_BASE_URL'], '/') . '/', // มั่นใจว่ามี / ปิดท้าย
            'headers'  => $headers,
            'timeout'  => 5.0, // รอ 5 วิ ถ้าไม่ตอบกลับคือล่ม
        ]);
    }

    // ฟังก์ชันครอบจักรวาลสำหรับยิง API
    public function request($method, $endpoint, $options = []) {
        try {
            $response = $this->client->request($method, $endpoint, $options);
            return json_decode($response->getBody(), true);
        } catch (RequestException $e) {
            // 🔴 แก้ตรงนี้! เปลี่ยนจาก abort() เป็น throw new Exception()
            if ($e->hasResponse()) {
                $errorBody = json_decode($e->getResponse()->getBody(), true);
                $detail = $errorBody['detail'] ?? 'เกิดข้อผิดพลาดจาก API';
                
                // โยน Error กลับไปให้ Controller จัดการ!
                throw new Exception($detail);
            } else {
                // โยน Error กรณีเซิร์ฟเวอร์ Python ดับ
                throw new Exception("ไม่สามารถเชื่อมต่อกับ Backend ได้: " . $e->getMessage());
            }
        }
    }
}
?>