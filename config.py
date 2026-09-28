import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE = Path(__file__).resolve().parent
DATABASE_PATH = os.getenv('DATABASE_PATH', str(BASE / 'data/news.sqlite3'))
COLLECT_MINUTES = int(os.getenv('COLLECT_MINUTES', '30'))
DIGEST_HOUR = int(os.getenv('DIGEST_HOUR', '9'))
DIGEST_MINUTE = int(os.getenv('DIGEST_MINUTE', '0'))
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Moscow')
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
