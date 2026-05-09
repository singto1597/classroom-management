<?php
require_once 'models/Student.php';

class StudentController {
    private $studentModel;

    public function __construct() {
        $this->studentModel = new Student();
    }

    // 📍 หน้า 1: ตารางรายชื่อนักเรียนทั้งหมด
    public function index() {
        $room_id = $_SESSION['room_id'];
        $discord_id = $_SESSION['discord_id'];
        
        try {
            $students = $this->studentModel->getAllStudents($room_id, $discord_id);
        } catch (Exception $e) {
            $error_msg = $e->getMessage();
            $students = [];
        }
        require 'views/students/list.php';
    }

    // 📍 หน้า 2: โปรไฟล์ของฉัน
    public function myProfile() {
        $room_id = $_SESSION['room_id'];
        $discord_id = $_SESSION['discord_id'];
        
        try {
            $profile = $this->studentModel->getMyProfile($room_id, $discord_id);
        } catch (Exception $e) {
            abort("เกิดข้อผิดพลาด: " . $e->getMessage());
        }
        require 'views/students/my_profile.php';
    }

    public function profile() {
        $room_id = $_SESSION['room_id'];
        $student_no = $_GET['no'] ?? null;
        
        if (!$student_no) {
            header("Location: index.php?page=students");
            exit();
        }

        try {
            $profile = $this->studentModel->getStudentByNo($room_id, $student_no);
            if (!$profile) abort("ไม่พบข้อมูลนักเรียนเลขที่ {$student_no}");
        } catch (Exception $e) {
            abort($e->getMessage());
        }

        require 'views/students/profile.php';
    }

    public function edit() {
        $room_id = $_SESSION['room_id'];
        $discord_id = $_SESSION['discord_id'];
        $student_no = $_GET['no'] ?? null;
        
        if (!$student_no) {
            header("Location: index.php?page=students");
            exit();
        }

        $myProfile = $this->studentModel->getMyProfile($room_id, $discord_id);
        if ($_SESSION['role'] === 'student' && $student_no != $myProfile['student_no']) {
            abort("🛑 ด่านตรวจความปลอดภัย: คุณไม่มีสิทธิ์แก้ไขโปรไฟล์ของคนอื่นครับ!");
        }

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) abort("Token ไม่ถูกต้อง!");

            $payload = $_POST;
            unset($payload['csrf_token']);
            foreach ($payload as $key => $value) {
                if (trim($value) === '') $payload[$key] = null;
            }

            try {
                $this->studentModel->updateStudent($room_id, $student_no, $payload, $discord_id);
                $_SESSION['success_msg'] = "อัปเดตข้อมูลสำเร็จ!";
                header("Location: index.php?page=students_me"); 
                exit();
            } catch (Exception $e) {
                abort("อัปเดตผิดพลาด: " . $e->getMessage());
            }
        }

        try {
            $profile = $this->studentModel->getStudentByNo($room_id, $student_no);
            if (!$profile) abort("ไม่พบข้อมูลนักเรียนเลขที่ {$student_no}");
        } catch (Exception $e) {
            abort($e->getMessage());
        }

        require 'views/students/edit.php';
    }

    // 📍 หน้า 3: ฟอร์มเพิ่มนักเรียน (รองรับทั้ง เดี่ยว และ Bulk)
    public function add() {
        if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์เพิ่มนักเรียน!");
        
        $room_id = $_SESSION['room_id'];
        $success_msg = null;
        $error_msg = null;

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) abort("Token ไม่ถูกต้อง!");

            try {
                if ($_POST['action'] === 'single') {
                    $payload = [
                        "student_no" => (int)$_POST['student_no'],
                        "first_name" => trim($_POST['first_name']),
                        "last_name" => trim($_POST['last_name']),
                        "user_name" => $_SESSION['user_name']
                    ];
                    $this->studentModel->addStudent($room_id, $payload);
                    $success_msg = "✅ เพิ่มนักเรียนเลขที่ {$_POST['student_no']} สำเร็จ!";
                } 
                elseif ($_POST['action'] === 'bulk') {
                    // แปลงข้อความจาก Textarea ให้เป็น Array แบบที่ FastAPI ต้องการ
                    $lines = explode("\n", trim($_POST['bulk_data']));
                    $students = [];
                    foreach ($lines as $line) {
                        $parts = explode(',', $line);
                        if (count($parts) >= 3) {
                            $students[] = [
                                "student_no" => (int)trim($parts[0]),
                                "first_name" => trim($parts[1]),
                                "last_name" => trim($parts[2])
                            ];
                        }
                    }
                    $this->studentModel->bulkAddStudents($room_id, $students, $_SESSION['user_name']);
                    $success_msg = "🚀 เพิ่มข้อมูลรวดเดียว " . count($students) . " คน สำเร็จ!";
                }
            } catch (Exception $e) {
                $error_msg = $e->getMessage();
            }
        }
        require 'views/students/add.php';
    }

    public function action() {
        if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์จัดการสถานะ!");

        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) abort("Token ไม่ถูกต้อง!");

            $room_id = $_SESSION['room_id'];
            $discord_id = $_SESSION['discord_id'];
            $student_no = (int)$_POST['student_no'];
            $action_type = $_POST['action_type']; 

            try {
                if ($action_type === 'soft_delete') {
                    $this->studentModel->updateStudentStatus($room_id, $student_no, 'inactive', $discord_id, $_SESSION['user_name']);
                } elseif ($action_type === 'restore') {
                    $this->studentModel->updateStudentStatus($room_id, $student_no, 'active', $discord_id, $_SESSION['user_name']);
                } elseif ($action_type === 'hard_delete') {
                    // 🚨 ต้องไปสร้างฟังก์ชันนี้เพิ่มใน models/Student.php ด้วยนะ
                    $this->studentModel->deleteStudentPermanent($room_id, $student_no, $discord_id, $_SESSION['user_name']);
                }
                
                header("Location: index.php?page=students");
                exit();
            } catch (Exception $e) {
                abort("จัดการผิดพลาด: " . $e->getMessage());
            }
        }
    }

    public function export() {
        if ($_SESSION['role'] === 'student') abort("คุณไม่มีสิทธิ์ Export ข้อมูล!");

        // ถ้ามีการกดปุ่มดาวน์โหลด (POST)
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $room_id = $_SESSION['room_id'];
            $discord_id = $_SESSION['discord_id'];
            $categories = $_POST['categories'] ?? []; // รับค่าจาก Checkbox

            // แปลงหมวดหมู่ให้เป็นชื่อคอลัมน์ (เหมือนลอจิกในบอท)
            $field_map = [
                'core' => ['student_no', 'student_id', 'prefix', 'first_name', 'last_name', 'nickname', 'birthday'],
                'academic' => ['class_role', 'cleaning_duty', 'olympic_camp', 'target_faculty', 'portfolio'],
                'health' => ['blood_group', 'shirt_size', 'food_allergy', 'congenital_disease'],
                'contact' => ['phone_number', 'phone_number_parent', 'phone_number_parent_relation', 'line_id', 'ig_username', 'email'],
                'address' => ['address_house_no', 'address_road', 'address_sub_district', 'address_district', 'address_province', 'address_post_code']
            ];

            $fields = [];
            foreach ($categories as $cat) {
                if (isset($field_map[$cat])) {
                    $fields = array_merge($fields, $field_map[$cat]);
                }
            }

            if (empty($fields)) {
                abort("กรุณาเลือกข้อมูลอย่างน้อย 1 หมวดหมู่ครับ!");
            }

            try {
                $client = new \GuzzleHttp\Client();
                // ระวังเรื่อง URL: เช็คให้ชัวร์ว่า API_BASE_URL มี / ปิดท้ายหรือไม่
                $base_url = rtrim($_ENV['API_BASE_URL'], '/') . '/'; 
                $response = $client->post($base_url . "{$room_id}/export", [
                    'headers' => [
                        'X-API-Key' => $_ENV['API_KEY'],
                        'X-Discord-Id' => (string)$discord_id
                    ],
                    'json' => [
                        'fields' => $fields,
                        'user_name' => $_SESSION['user_name']
                    ]
                ]);
                if (ob_get_level()) ob_end_clean();
                header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
                header('Content-Disposition: attachment; filename="students_' . $room_id . '.xlsx"');
                header('Cache-Control: max-age=0');
                
                echo $response->getBody()->getContents();
                exit();

            } catch (Exception $e) {
                abort("Export ผิดพลาด: " . $e->getMessage());
            }
        }

        // ถ้าเป็น GET Request (แค่กดเข้ามาดูหน้าเว็บ) ให้โชว์ไฟล์ UI ด้านล่างนี้
        require 'views/students/export.php';
    }
}
?>