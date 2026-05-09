<?php
require_once 'config/database.php';
require_once 'services/ApiClient.php';

if (!isset($_GET['code'])) {
    die("❌ เกิดข้อผิดพลาด: ไม่ได้รับรหัสยืนยันจาก Discord");
}

$code = $_GET['code'];
$client = new \GuzzleHttp\Client();

try {
    // 1. เอา Code ไปแลก Access Token จาก Discord
    $tokenResponse = $client->post('https://discord.com/api/oauth2/token', [
        'form_params' => [
            'client_id' => $_ENV['DISCORD_CLIENT_ID'],
            'client_secret' => $_ENV['DISCORD_CLIENT_SECRET'],
            'grant_type' => 'authorization_code',
            'code' => $code,
            'redirect_uri' => $_ENV['DISCORD_REDIRECT_URI']
        ]
    ]);
    $tokenData = json_decode($tokenResponse->getBody(), true);
    $access_token = $tokenData['access_token'];

    // 2. เอา Access Token ไปดึงข้อมูลส่วนตัว (Discord ID และชื่อ)
    $userResponse = $client->get('https://discord.com/api/users/@me', [
        'headers' => [ 'Authorization' => "Bearer {$access_token}" ]
    ]);
    $userData = json_decode($userResponse->getBody(), true);
    
    $discord_id = $userData['id'];
    $discord_name = $userData['global_name'] ?? $userData['username'];

    // 3. 🚨 ยิงไปถาม FastAPI ของมึง ว่าไอ้หมอนี่อยู่ห้องไหนบ้าง?!
    $api = new ApiClient();
    $rooms = $api->request('GET', "{$discord_id}/rooms"); 

    // 4. ลอจิกคัดกรอง (Routing Logic)
    if (empty($rooms)) {
        abort("คุณยังไม่ได้ลงทะเบียนในระบบ! ไปพิมพ์ /sync_me ในเซิร์ฟเวอร์ดิสคอร์ดของห้องเรียนก่อนนะ");
    } 
    elseif (count($rooms) == 1) {
        // มีห้องเดียว โคตรโชคดี ล็อกอินให้ออโต้เลย
        $_SESSION['room_id'] = $rooms[0]['server_id'];
        $_SESSION['room_name'] = $rooms[0]['room_name'];
        $_SESSION['role'] = $rooms[0]['role'];
        $_SESSION['user_name'] = $discord_name;
        $_SESSION['discord_id'] = $discord_id;
        
        header("Location: index.php");
        exit();
    } 
    else {
        // มีหลายห้อง เอาข้อมูลห้องเก็บไว้ชั่วคราว แล้วพาไปหน้าเลือกห้อง
        $_SESSION['temp_rooms'] = $rooms;
        $_SESSION['temp_user_name'] = $discord_name;
        $_SESSION['temp_discord_id'] = $discord_id;
        
        header("Location: select_room.php");
        exit();
    }

} catch (Exception $e) {
    abort("Login ผิดพลาด: " . $e->getMessage());
}
?>