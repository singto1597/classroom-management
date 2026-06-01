import json
import logging
import redis.asyncio as aioredis
from core.config import settings
from datetime import date, datetime

logger = logging.getLogger("API_MAIN")

class ActionService:
    @staticmethod
    async def _publish(event_type: str, server_id: int, payload_data: dict):
        """
        ฟังก์ชันหลังบ้าน (Private) สำหรับส่งข้อมูลเข้า Redis จริงๆ
        """
        try:
            redis_client = aioredis.from_url(settings.REDIS_URL)
            
            # ประกอบร่าง Payload พื้นฐาน
            payload = {
                "event": event_type,
                "server_id": server_id,
            }
            # เอาข้อมูลเฉพาะของ Event นั้นๆ ยัดรวมเข้าไป
            payload.update(payload_data)

            # แปลง dict เป็น JSON (ใส่ default=str ไว้เผื่อมีข้อมูลประเภท date/datetime มันจะได้ไม่พัง)
            json_data = json.dumps(payload, default=str)

            # ตะโกนเข้าช่อง classroom_events
            await redis_client.publish("classroom_events", json_data)
            await redis_client.aclose()
            
            logger.info(f"📢 [ActionService] Published {event_type} to server {server_id}")
            
        except Exception as e:
            # ถ้า Redis ล่ม API ต้องไม่พัง แค่เก็บ Log ไว้
            logger.error(f"❌ [ActionService] Redis Publish Error: {e}")

    # ==========================================
    # หมวดหมู่ Functions สำหรับเรียกใช้งาน (Public)
    # ==========================================

    @classmethod
    async def notify_new_task(cls, server_id: int, task_name: str, due_date: date, user_name: str):
        """เรียกใช้เมื่อมีการสร้างงานใหม่"""
        await cls._publish("NEW_TASK", server_id, {
            "task_name": task_name,
            "due_date": due_date,
            "user_name": user_name
        })

    @classmethod
    async def notify_task_done(cls, server_id: int, task_name: str, user_name: str):
        """เรียกใช้เมื่อมีคนกดส่งงาน"""
        await cls._publish("TASK_DONE", server_id, {
            "task_name": task_name,
            "user_name": user_name
        })

    @classmethod
    async def notify_new_note(cls, server_id: int, target_date: date, topic: str, user_name: str):
        """เรียกใช้เมื่อมีการแปะประกาศรายวันใหม่"""
        await cls._publish("NEW_NOTE", server_id, {
            "target_date": target_date,
            "topic": topic,
            "user_name": user_name
        })