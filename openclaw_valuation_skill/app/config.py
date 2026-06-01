import os
from dotenv import load_dotenv

load_dotenv()

UPSTREAM_API_BASE = os.getenv("UPSTREAM_API_BASE", "http://127.0.0.1:9001/api").rstrip("/")
FEISHU_BOT_WEBHOOK = os.getenv("FEISHU_BOT_WEBHOOK", "").strip()
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9100"))
