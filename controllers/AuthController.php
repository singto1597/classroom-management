<?php
require_once 'services/DiscordService.php';
require_once 'services/ApiClient.php';

class AuthController {
    private $discord;
    private $api;

    public function __construct() {
        $this->discord = new DiscordService();
        $this->api     = new ApiClient();
    }

    /**
     * หน้า Login — ถ้า Login อยู่แล้วให้เด้งไป Dashboard
     */
    public function showLogin(): void {
        if (isset($_SESSION['room_id'])) {
            header("Location: index.php");
            exit();
        }

        $discord_url = $this->discord->buildAuthUrl();
        require 'views/auth/login.php';
    }

    /**
     * Discord OAuth Callback — จุดหลักของ Auth Flow ทั้งหมด
     */
    public function handleCallback(): void {
        if (!isset($_GET['code'])) {
            abort("❌ เกิดข้อผิดพลาด: ไม่ได้รับรหัสยืนยันจาก Discord");
        }

        try {
            // Step 1: แลก Code → Access Token
            $access_token = $this->discord->exchangeCodeForToken($_GET['code']);

            // Step 2: ดึงข้อมูล User จาก Discord
            $user = $this->discord->getUserInfo($access_token);

            // 🚨 เพิ่ม 2 บรรทัดนี้เพื่อแก้บั๊ก Timing Issue (API Header)
            $_SESSION['discord_id'] = $user['id'];
            $this->api = new ApiClient(); // รีเซ็ตเพื่อให้อ่าน Session ไปสร้าง Header ใหม่

            // Step 3: ถามว่า User อยู่ห้องไหนบ้าง
            $rooms = $this->api->request('GET', "{$user['id']}/rooms");

            // Step 4: Routing ตาม Logic
            $this->routeAfterLogin($user, $rooms);

        } catch (Exception $e) {
            abort("Login ผิดพลาด: " . $e->getMessage());
        }
    }

    /**
     * เลือกห้องเรียน (ใช้ทั้ง GET แสดงหน้า และ POST รับ Form)
     */
    public function selectRoom(): void {
        // Guard: ห้ามเข้าตรงๆ ถ้าไม่มี temp session
        if (!isset($_SESSION['temp_rooms'])) {
            header("Location: login.php");
            exit();
        }

        if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['selected_room_id'])) {
            if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== ($_SESSION['csrf_token'] ?? '')) {
                abort('Token CSRF ไม่ถูกต้อง');
            }
            $this->commitRoomSelection($_POST['selected_room_id'], $_SESSION['temp_rooms']);
        }

        // แสดงหน้าเลือกห้อง
        $rooms = $_SESSION['temp_rooms'];
        require 'views/auth/select_room.php';
    }

    /**
     * สลับห้องเรียน — ดึงห้องใหม่จาก API แล้วพาไปหน้าเลือก
     */
    public function switchRoom(): void {
        if (!isset($_SESSION['discord_id'])) {
            header("Location: logout.php");
            exit();
        }

        try {
            $rooms = $this->api->request('GET', "{$_SESSION['discord_id']}/rooms");

            // เซ็ต temp session แล้วล้างห้องเดิม
            $_SESSION['temp_rooms']      = $rooms;
            $_SESSION['temp_user_name']  = $_SESSION['user_name'];
            $_SESSION['temp_discord_id'] = $_SESSION['discord_id'];
            unset($_SESSION['room_id'], $_SESSION['room_name'], $_SESSION['role']);

            header("Location: select_room.php");
            exit();

        } catch (Exception $e) {
            // API พัง → บังคับ logout ปลอดภัยสุด
            header("Location: logout.php");
            exit();
        }
    }

    /**
     * Logout — ล้าง Session แล้วพากลับหน้า Login
     */
    public function logout(): void {
        session_destroy();
        header("Location: login.php");
        exit();
    }

    // ─────────────────────────────────────────────
    // Private Helpers
    // ─────────────────────────────────────────────

    /**
     * ตัดสินใจว่าจะพา User ไปไหนหลัง Login สำเร็จ
     */
    private function routeAfterLogin(array $user, ?array $rooms): void {
        if (empty($rooms)) {
            abort("คุณยังไม่ได้ลงทะเบียนในระบบ! ไปพิมพ์ /sync_me ในเซิร์ฟเวอร์ดิสคอร์ดของห้องเรียนก่อนนะ");
        }

        if (count($rooms) === 1) {
            // มีห้องเดียว → Login อัตโนมัติ
            $this->setRoomSession($rooms[0], $user['name'], $user['id']);
            header("Location: index.php");
            exit();
        }

        // มีหลายห้อง → พาไปเลือก
        $_SESSION['temp_rooms']      = $rooms;
        $_SESSION['temp_user_name']  = $user['name'];
        $_SESSION['temp_discord_id'] = $user['id'];
        header("Location: select_room.php");
        exit();
    }

    /**
     * ยืนยันการเลือกห้องจาก Form แล้วเซ็ต Session จริง
     */
    private function commitRoomSelection(string $selected_id, array $rooms): void {
        foreach ($rooms as $room) {
            if ($room['server_id'] == $selected_id) {
                $this->setRoomSession(
                    $room,
                    $_SESSION['temp_user_name'],
                    $_SESSION['temp_discord_id']
                );
                unset($_SESSION['temp_rooms'], $_SESSION['temp_user_name'], $_SESSION['temp_discord_id']);
                header("Location: index.php");
                exit();
            }
        }
        // ถ้าหา room_id ไม่เจอในรายการ (มีคนแก้ค่า POST) → ไม่ทำอะไร แค่แสดงหน้าเลือกใหม่
    }

    /**
     * เซ็ต Session ที่ใช้ทั่วทั้งระบบ
     */
    private function setRoomSession(array $room, string $user_name, string $discord_id): void {
        $_SESSION['room_id']    = $room['server_id'];
        $_SESSION['room_name']  = $room['room_name'];
        $_SESSION['role']       = $room['role'];
        $_SESSION['user_name']  = $user_name;
        $_SESSION['discord_id'] = $discord_id;
    }
}
?>