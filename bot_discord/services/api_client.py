import aiohttp
from core.config import API_BASE_URL, API_KEY

class APIException(Exception):
    """Custom Exception สำหรับดัก Error จาก Backend"""
    pass

class APIClient:
    def __init__(self):
        self.session = None

    async def init_session(self):
        """เปิด Session ค้างไว้เพื่อความเร็ว (ไม่ต้องเปิด-ปิดใหม่ทุก Request)"""
        headers = {"X-API-Key": API_KEY}
        self.session = aiohttp.ClientSession(headers=headers)

    async def close(self):
        if self.session:
            await self.session.close()

    async def request(self, method: str, endpoint: str, **kwargs):
        """ฟังก์ชันครอบจักรวาลสำหรับยิง API"""
        url = f"{API_BASE_URL}{endpoint}"
        async with self.session.request(method, url, **kwargs) as response:
            data = await response.json()
            
            # ถ้า Backend ตอบกลับมาเป็น Error (เช่น 404, 401)
            if response.status >= 400:
                error_detail = data.get("detail", "เกิดข้อผิดพลาดจาก Backend")
                raise APIException(error_detail)
                
            return data

# สร้าง Instance แบบ Singleton ไว้ให้ไฟล์อื่นดึงไปใช้
api_client = APIClient()