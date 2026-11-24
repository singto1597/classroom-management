"""โปรเซสเบื้องหลังของระบบ (ไม่ตอบ HTTP) — รันด้วย image เดียวกับ backend

`docker-compose.app.yml` สตาร์ทแต่ละตัวด้วย `command:` ต่างกัน
และ **ทุกตัวต้องมี replica เดียว** (ตัวในลูปใช้ `FOR UPDATE SKIP LOCKED` อยู่แล้ว
แต่ตัวที่รันหนึ่งครั้งต่อรอบเช่น cron ไม่ควรชนกันเอง)

| worker | ไฟล์ | ทำอะไร |
|---|---|---|
| `push_worker` | `workers/push_worker.py` | ส่ง Web Push จาก `push_outbox` (ทุก ~5 วิ) |
| `finance_reminder_worker` | `workers/finance_reminder_worker.py` | เตือนผู้ค้างชำระรายวัน (09:00 Asia/Bangkok, ตรวจทุก 5 นาที) |

⚠️ **worker ใหม่ต้องทนสคีมาที่ยังไม่มา** — ตอน deploy worker กับ backend บูตพร้อมกัน
และ worker อาจ query ก่อน `apply_migrations` จะจบ ⇒ จับ `UndefinedTable` (SQLSTATE 42P01)
log แล้วลองใหม่รอบถัดไป **ห้ามปล่อยให้ process ตาย** (ดู `finance_reminder_worker`)
"""
