"""เทสต์ของบอท (F5/PR-3) — ใช้ **stdlib `unittest`** โดยเจตนา

⚠️ ทำไมไม่ใช้ pytest: repo นี้ไม่เคยมี test harness ของบอท และ image ของบอท
   (`python:3.12-slim` + `requirements.txt`) **ไม่มี pytest ติดตั้ง** ⇒ ถ้าใช้ pytest
   ต้อง `pip install` ทุกครั้งที่รัน (ต้องมีเน็ต) ทั้งที่เทสต์ชุดนี้ไม่ต้องพึ่งอะไร
   นอก stdlib + discord.py ที่มีอยู่แล้ว ⇒ รันได้ทันที:

   ```
   docker run --rm -e API_KEY=test-api-key -v "$PWD/bot_discord:/app:z" -w /app \
       classroom-classroom-bot:latest python -m unittest discover -s tests -t . -v
   ```

   ⚠️ `-e API_KEY=...` **จำเป็น** ตั้งแต่ M8: `core/config.py` ไม่มีค่า fallback ให้
      `API_KEY` อีกแล้ว (เดิมมีคีย์ปลอมเขียนไว้ในซอร์สสาธารณะ) ⇒ ถ้าไม่ส่งมา
      `import core.config` จะ raise `ValueError` **ตอนเก็บเทสต์** ทำให้เทสต์ทั้งชุด
      error ยกแผงทั้งที่โค้ดที่ทดสอบไม่ได้ผิด — ค่าที่ส่งไปเป็นของปลอมก็ได้ เพราะ
      เทสต์ห้ามต่อ backend จริงอยู่แล้ว (สแตก `api_client` ทั้งหมดใช้ stub)
"""
