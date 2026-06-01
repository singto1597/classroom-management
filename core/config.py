import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/classroom")
API_KEY = os.getenv("API_KEY", "api-key-for-my-bot-1234") 

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")