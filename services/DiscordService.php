<?php

class DiscordService {
    private $client;

    public function __construct() {
        $this->client = new \GuzzleHttp\Client();
    }

    /**
     * สร้าง URL สำหรับส่ง User ไป Login กับ Discord
     */
    public function buildAuthUrl(): string {
        $client_id    = $_ENV['DISCORD_CLIENT_ID'];
        $redirect_uri = urlencode($_ENV['DISCORD_REDIRECT_URI']);
        return "https://discord.com/oauth2/authorize?client_id={$client_id}&response_type=code&redirect_uri={$redirect_uri}&scope=identify";
    }

    /**
     * เอา Authorization Code ไปแลก Access Token กับ Discord
     */
    public function exchangeCodeForToken(string $code): string {
        $response = $this->client->post('https://discord.com/api/oauth2/token', [
            'form_params' => [
                'client_id'     => $_ENV['DISCORD_CLIENT_ID'],
                'client_secret' => $_ENV['DISCORD_CLIENT_SECRET'],
                'grant_type'    => 'authorization_code',
                'code'          => $code,
                'redirect_uri'  => $_ENV['DISCORD_REDIRECT_URI'],
            ]
        ]);

        $data = json_decode($response->getBody(), true);

        if (empty($data['access_token'])) {
            throw new \RuntimeException("Discord ไม่ส่ง access_token กลับมา");
        }

        return $data['access_token'];
    }

    /**
     * เอา Access Token ไปดึงข้อมูล User จาก Discord
     * คืน array ['id' => '...', 'name' => '...']
     */
    public function getUserInfo(string $access_token): array {
        $response = $this->client->get('https://discord.com/api/users/@me', [
            'headers' => ['Authorization' => "Bearer {$access_token}"]
        ]);

        $data = json_decode($response->getBody(), true);

        return [
            'id'   => $data['id'],
            'name' => $data['global_name'] ?? $data['username'],
        ];
    }
}