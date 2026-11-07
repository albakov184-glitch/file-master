import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Свой сервер Telegram Bot API (необязательно). С ним лимит файлов — до 2 ГБ вместо 20/50 МБ.
BOT_API_URL = os.getenv("BOT_API_URL", "").rstrip("/")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "filemaster.db"
WORK_DIR = DATA_DIR / "work"

MB = 1024 * 1024
if BOT_API_URL:
    MAX_DOWNLOAD = int(os.getenv("MAX_FILE_MB", "2000")) * MB
    MAX_UPLOAD = 2000 * MB
else:
    MAX_DOWNLOAD = 20 * MB  # ограничение облачного Bot API на скачивание ботом
    MAX_UPLOAD = 50 * MB  # ограничение облачного Bot API на отправку ботом

WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "900"))
MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "3"))
MAX_MERGE_FILES = 30
MAX_ARCHIVE_FILES_SENT = 30
MAX_ARCHIVE_UNPACKED = 2000 * MB
MAX_PDF_PAGES_RENDER = 200
MAX_OCR_PAGES = 30
OCR_LANGS = os.getenv("OCR_LANGS", "rus+eng")


def human_size(n: int | None) -> str:
    if n is None:
        return "?"
    size = float(n)
    for unit in ("Б", "КБ", "МБ"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
