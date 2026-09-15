"""เทสต์ของบอท (F5/PR-3) — ใช้ **stdlib `unittest`** โดยเจตนา

⚠️ ทำไมไม่ใช้ pytest: repo นี้ไม่เคยมี test harness ของบอท และ image ของบอท
   (`python:3.12-slim` + `requirements.txt`) **ไม่มี pytest ติดตั้ง** ⇒ ถ้าใช้ pytest
   ต้อง `pip install` ทุกครั้งที่รัน (ต้องมีเน็ต) ทั้งที่เทสต์ชุดนี้ไม่ต้องพึ่งอะไร
   นอก stdlib + discord.py ที่มีอยู่แล้ว ⇒ รันได้ทันที:

   ```
   docker run --rm -v "$PWD/bot_discord:/app:z" -w /app classroom-classroom-bot:latest \
       python -m unittest discover -s tests -t . -v
   ```
"""
