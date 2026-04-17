import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# App
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "dev-secret-change-in-production")

# Database
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/campaigns.db")

# Uploads directory (for storing uploaded files temporarily)
UPLOADS_DIR = BASE_DIR / os.getenv("UPLOADS_DIR", "data/uploads")

# n8n webhook URLs - up to 3 parallel campaign slots
N8N_WEBHOOK_URLS = {
    1: os.getenv("N8N_WEBHOOK_URL_1", ""),
    2: os.getenv("N8N_WEBHOOK_URL_2", ""),
    3: os.getenv("N8N_WEBHOOK_URL_3", ""),
}

# Callback URL for n8n to post results back
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL", "http://localhost:8000")

# Default campaign settings
DEFAULT_BATCH_SIZE = int(os.getenv("DEFAULT_BATCH_SIZE", "100"))
DEFAULT_MAX_ATTEMPTS = int(os.getenv("DEFAULT_MAX_ATTEMPTS", "2"))
DEFAULT_DAILY_TARGET = int(os.getenv("DEFAULT_DAILY_TARGET", "400"))

# Max upload size (10MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))
