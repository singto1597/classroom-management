import asyncpg
import datetime
from typing import List, Dict
from zoneinfo import ZoneInfo

THAI_TZ = ZoneInfo("Asia/Bangkok")

class MaintenanceService:
    @staticmethod
    def _mock_ai_priority(category: str, description: str) -> str:
        """จำลอง AI จัดลำดับความสำคัญ"""
        desc_lower = description.lower()
        critical_keywords = ['ไฟช็อต', 'ไฟรั่ว', 'ควัน', 'ระเบิด', 'สายขาด']
        high_keywords = ['โปรเจกเตอร์', 'แอร์', 'สอนไม่ได้', 'คอม']
        
        if any(kw in desc_lower for kw in critical_keywords) or category == 'electrical':
            return 'Critical'
        if any(kw in desc_lower for kw in high_keywords) or category == 'it':
            return 'High'
        if category in ['furniture', 'general']:
            return 'Medium'
        return 'Low'

    @classmethod
    async def create_ticket(cls, pool: asyncpg.Pool, req_data: dict) -> dict:
        async with pool.acquire() as conn:
            async with conn.transaction():
                loc_id = await conn.fetchval(
                    """INSERT INTO mtn_locations (building, room) 
                       VALUES ($1, $2) ON CONFLICT (building, room) 
                       DO UPDATE SET building = EXCLUDED.building RETURNING id""",
                    req_data['building'], req_data['room']
                )

                # 2. วิเคราะห์ Priority (จำลอง AI)
                priority = cls._mock_ai_priority(req_data['category'], req_data['description'])

                # 3. สร้างรหัส Ticket (TKT-YYYYMMDD-XXXX)
                now = datetime.datetime.now(THAI_TZ)
                date_str = now.strftime("%Y%m%d")
                ticket_id = f"TKT-{date_str}-{datetime.datetime.now().microsecond % 10000:04d}"

                # 4. บันทึก Ticket
                await conn.execute(
                    """INSERT INTO mtn_tickets 
                       (id, location_id, category, description, image_url, priority, reporter_name)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    ticket_id, loc_id, req_data['category'], req_data['description'], 
                    req_data.get('image_url'), priority, req_data['reporter_name']
                )

                # 5. บันทึก Log
                await conn.execute(
                    "INSERT INTO mtn_logs (ticket_id, action, user_name) VALUES ($1, $2, $3)",
                    ticket_id, "Ticket Created", req_data['reporter_name']
                )

                # TODO: ถ้า priority เป็น Critical สามารถเขียนโค้ดยิง Webhook ไป Discord ช่างที่นี่ได้เลย

                return {
                    "ticket_id": ticket_id,
                    "priority": priority,
                    "message": "บันทึกข้อมูลและประเมินความสำคัญเรียบร้อยแล้ว"
                }