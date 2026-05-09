<?php
require_once 'services/ApiClient.php';

class Student {
    private $api;

    public function __construct() {
        $this->api = new ApiClient();
    }

    // 👥 ดึงรายชื่อทั้งห้อง
    public function getAllStudents($room_id, $discord_id) {
        return $this->api->request('GET', "{$room_id}/students", [
            'headers' => ['X-Discord-Id' => (string)$discord_id]
        ]);
    }

    // 👤 ดึงโปรไฟล์ตัวเอง
    public function getMyProfile($room_id, $discord_id) {
        return $this->api->request('GET', "{$room_id}/students/me", [
            'headers' => ['X-Discord-Id' => (string)$discord_id]
        ]);
    }

    // 🔎 ค้นหานักเรียน (ใช้ค้นหาด้วยเลขที่ หรือชื่อก็ได้)
    public function searchStudents($room_id, $query) {
        return $this->api->request('GET', "{$room_id}/search", [
            'query' => ['q' => $query]
        ]);
    }

    // 🎯 ดึงโปรไฟล์คนอื่น (ด้วยเลขที่)
    public function getStudentByNo($room_id, $student_no) {
        $results = $this->searchStudents($room_id, (string)$student_no);
        return !empty($results) ? $results[0] : null;
    }

    // ➕ เพิ่มนักเรียน (คนเดียว)
    public function addStudent($room_id, $payload) {
        return $this->api->request('POST', "{$room_id}/students", [
            'json' => $payload
        ]);
    }

    // 🚀 เพิ่มนักเรียน (หลายคนพร้อมกัน)
    public function bulkAddStudents($room_id, $students, $user_name) {
        return $this->api->request('POST', "{$room_id}/students/bulk", [
            'json' => [
                'students' => $students,
                'user_name' => $user_name
            ]
        ]);
    }

    // 📝 อัปเดตข้อมูลโปรไฟล์ (รองรับการส่งมาแค่บางฟิลด์)
    public function updateStudent($room_id, $student_no, $payload, $discord_id) {
        return $this->api->request('PATCH', "{$room_id}/students/{$student_no}", [
            'headers' => ['X-Discord-Id' => (string)$discord_id],
            'json' => $payload
        ]);
    }

    public function deleteStudentPermanent($room_id, $student_no, $discord_id, $user_name) {
        return $this->api->request('DELETE', "{$room_id}/students/{$student_no}", [
            'headers' => ['X-Discord-Id' => (string)$discord_id],
            'json' => [
                'user_name' => $user_name
            ]
        ]);
    }

    // 🛑 เปลี่ยนสถานะ Active / Inactive
    public function updateStudentStatus($room_id, $student_no, $status, $discord_id, $user_name) {
        return $this->api->request('PATCH', "{$room_id}/students/{$student_no}/status", [
            'headers' => ['X-Discord-Id' => (string)$discord_id],
            'json' => [
                'status' => $status,
                'user_name' => $user_name
            ]
        ]);
    }
}
?>