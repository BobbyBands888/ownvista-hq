"""Environment config. Every secret comes from GitHub Actions secrets (or a local .env on the Mac)."""
import os

def _load_dotenv():
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

_load_dotenv()

def env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required setting: {name}")
    return v

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_SERVICE_KEY = env("SUPABASE_SERVICE_KEY")
GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_FALLBACK_MODEL = env("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
YOUTUBE_API_KEY = env("YOUTUBE_API_KEY")
DVIDS_API_KEY = env("DVIDS_API_KEY")
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = env("GOOGLE_REFRESH_TOKEN")   # bobbybands888 — Gmail
YOUTUBE_REFRESH_TOKEN = env("YOUTUBE_REFRESH_TOKEN") or GOOGLE_REFRESH_TOKEN  # Ten-Four Tapes channel
SENDER_EMAIL = env("SENDER_EMAIL", "bobbybands888@gmail.com")
REPORT_TO = env("REPORT_TO", SENDER_EMAIL)
FB_PAGE_ID = env("FB_PAGE_ID")
FB_PAGE_TOKEN = env("FB_PAGE_TOKEN")
GITHUB_REPOSITORY = env("GITHUB_REPOSITORY")
GITHUB_TOKEN = env("GITHUB_TOKEN")
DRY_RUN = env("DRY_RUN", "0") == "1"                # 1 = never send/post, just log
