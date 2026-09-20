import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Timezone Configuration (Bangladesh Standard Time: GMT+6)
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Dhaka").strip()

# Meta / Facebook Configuration
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "newgo_learn_secret_2026").strip()
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
FB_GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v21.0").strip()

# Gemini AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()

# Auto-Posting Configuration (AI, Automation, Productivity & Digital Skills)
DEFAULT_POST_TOPIC = os.getenv(
    "DEFAULT_POST_TOPIC",
    "AI Tools & Technologies, Smart Tips & Useful Tricks, AI & Work Automation, Learning Resources, Productivity & Digital Skills, and New Ideas for the Future",
).strip()

# Twice Daily Draft Schedule: Morning 9:00 AM & Evening 6:00 PM (Bangladesh Time)
SCHEDULE_MORNING_HOUR = int(os.getenv("SCHEDULE_MORNING_HOUR", "9"))
SCHEDULE_MORNING_MINUTE = int(os.getenv("SCHEDULE_MORNING_MINUTE", "0"))
SCHEDULE_EVENING_HOUR = int(os.getenv("SCHEDULE_EVENING_HOUR", "18"))
SCHEDULE_EVENING_MINUTE = int(os.getenv("SCHEDULE_EVENING_MINUTE", "0"))

# Google Sheets Content Queue (CSV export URL or Google Sheet link)
GOOGLE_SHEET_CSV_URL = os.getenv("GOOGLE_SHEET_CSV_URL", "").strip()

# Image Service Provider (pollinations / unsplash / pexels)
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations").strip().lower()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()

# Server Configuration
PORT = int(os.getenv("PORT", "8000"))

# Path to Knowledge Base File
KNOWLEDGE_BASE_FILE = BASE_DIR / "knowledge_base.txt"

# Uploads directory for user-uploaded images and videos
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
