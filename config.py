import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v

# Timezone Configuration (Bangladesh Standard Time: GMT+6)
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Dhaka").strip()

# Meta / Facebook Configuration
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "newgo_learn_secret_2026").strip()
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
FB_GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v21.0").strip()

# Gemini AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

# Auto-Posting Configuration (AI Teaching, Exploring, Making & Project Building)
DEFAULT_POST_TOPIC = os.getenv(
    "DEFAULT_POST_TOPIC",
    "AI Teaching & Tutorials, Hands-on Project Building, Exploring Latest AI Breakthroughs, Prompt Engineering, and Practical Workflows",
).strip()

# Twice Daily Draft Schedule: Morning 9:00 AM & Night 8:00 PM (Bangladesh Time)
SCHEDULE_MORNING_HOUR = int(os.getenv("SCHEDULE_MORNING_HOUR", "9"))
SCHEDULE_MORNING_MINUTE = int(os.getenv("SCHEDULE_MORNING_MINUTE", "0"))
SCHEDULE_EVENING_HOUR = int(os.getenv("SCHEDULE_EVENING_HOUR", "20"))
SCHEDULE_EVENING_MINUTE = int(os.getenv("SCHEDULE_EVENING_MINUTE", "0"))

# Image Service Provider (pollinations / huggingface / unsplash / pexels)
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations").strip().lower()
HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN", os.getenv("HF_TOKEN", "")).strip()
POLLINATIONS_MODEL = os.getenv("POLLINATIONS_MODEL", "flux").strip().lower()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()

# Server Configuration
PORT = int(os.getenv("PORT", "8000"))

# Path to Knowledge Base File
KNOWLEDGE_BASE_FILE = BASE_DIR / "knowledge_base.txt"

# Uploads directory for user-uploaded images and videos
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
