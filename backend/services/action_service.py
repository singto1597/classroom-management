import json
import logging
import time
import asyncpg
import redis.asyncio as aioredis
from core.config import settings
from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, ForbiddenError
from core.rbac import require_permission
from datetime import date, datetime
import asyncio
import sys

logger = logging.getLogger("API_MAIN")

action_logger = AuditLogger(service_name="ACTION")

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
    async def notify_new_task(cls, server_id: int, task_name: str, task_detail: str, due_date: date, user_name: str):
        """เรียกใช้เมื่อมีการสร้างงานใหม่"""
        await cls._publish("NEW_TASK", server_id, {
            "task_name": task_name,
            "task_detail": task_detail,
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

    @classmethod
    async def notify_custom_message(cls, server_id: int, title: str, message: str, user_name: str):
        """เรียกใช้เมื่อส่งข้อความประกาศตรงจากหน้าเว็บ"""
        await cls._publish("CUSTOM_MESSAGE", server_id, {
            "title": title,
            "message": message,
            "user_name": user_name
        })

    @classmethod
    async def send_custom_message(
        cls,
        pool: asyncpg.Pool,
        room_id: int,
        title: str,
        message: str,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        user_id: int,
    ) -> dict:
        """
        🆕 Web → Discord: ผู้ใช้พิมพ์ประกาศแล้วกดส่ง
        - ตรวจห้อง + ตรวจสิทธิ์ (membership) → ได้ server_id → publish CUSTOM_MESSAGE ผ่าน Redis
        - เขียน audit log (ใน transaction เดียวกัน) ว่าใครส่งข้อความอะไรไปห้องไหน
        """
        start_time = time.time()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    room = await conn.fetchrow(
                        "SELECT id, server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                        room_id,
                    )
                    if not room:
                        raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")
                    # 🔒 กันคนนอกห้อง (ไม่ใช่สมาชิก active) ยิงข้อความข้ามห้อง
                    await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

                    server_id = room["server_id"]
                    exec_time = int((time.time() - start_time) * 1000)
                    await action_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=room_id, entity_type="MESSAGE",
                        new_values={"title": title, "message": message, "user_name": user_name},
                        endpoint_or_command="send_custom_message", execution_time_ms=exec_time,
                    )

            if server_id:
                await cls.notify_custom_message(
                    server_id=server_id, title=title, message=message, user_name=user_name,
                )

            return {"status": "success", "message": "ส่งข้อความประกาศไปยัง Discord เรียบร้อยแล้ว"}
        except Exception as e:
            async with pool.acquire() as fallback_conn:
                exec_time = int((time.time() - start_time) * 1000)
                safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id
                await action_logger.log(
                    conn=fallback_conn, action="CREATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=safe_room_id, entity_type="MESSAGE",
                    status="failed", error_detail=str(e),
                    endpoint_or_command="send_custom_message", execution_time_ms=exec_time,
                )
            raise e

if __name__ == "__main__":
    async def run_test():
        # เช็คว่าใส่พารามิเตอร์มาครบ 3 ตัวมั้ย (Server ID, หัวข้อ, ข้อความ)
        if len(sys.argv) < 4:
            print("⚠️ วิธีใช้งาน: python -m services.action_service <Server_ID> <หัวข้อ> <ข้อความ>")
            print("💡 ตัวอย่าง: python -m services.action_service 1234567890123456789 'ประกาศด่วน' 'พรุ่งนี้เรียนออนไลน์'")
            return

        try:
            # ดึงข้อมูลจากพารามิเตอร์ (ดัก int ไว้เผื่อพิมพ์ผิด)
            target_server_id = int(sys.argv[1])
            custom_title = sys.argv[2]
            custom_message = sys.argv[3]
        except ValueError:
            print("❌ Error: Server ID ต้องเป็นตัวเลขเท่านั้นนะเว้ย!")
            return
        
        print(f"🚀 กำลังส่งประกาศไปที่ Server {target_server_id} | หัวข้อ: [{custom_title}]...")
        
        await ActionService.notify_custom_message(
            server_id=target_server_id,
            title=custom_title,
            message=custom_message,
            user_name="Terminal"
        )
        
        print("✅ ส่งคำสั่งเข้า Redis สำเร็จ! ลองเช็คใน Discord ดูเลย")

    # สั่งให้ Event Loop ของ asyncio รันฟังก์ชันด้านบน
    asyncio.run(run_test())