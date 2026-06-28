import os
from dotenv import load_dotenv

load_dotenv()

LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").lower()
RESEARCHER_BACKEND = os.getenv("RESEARCHER_BACKEND", LLM_BACKEND).lower()
EDITOR_BACKEND = os.getenv("EDITOR_BACKEND", LLM_BACKEND).lower()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_RESEARCHER_MODEL = os.getenv("GEMINI_RESEARCHER_MODEL", "gemini-2.5-flash")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_EDITOR_MODEL = os.getenv("GEMINI_EDITOR_MODEL", "gemini-2.5-flash")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_RESEARCHER_MODEL = os.getenv("OLLAMA_RESEARCHER_MODEL", "qwen2.5:7b")
OLLAMA_EDITOR_MODEL = os.getenv("OLLAMA_EDITOR_MODEL", "qwen2.5:7b")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SENDER_NAME = os.getenv("SENDER_NAME", "LuckyHands Intel Daily")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USER)
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "daniel@luckyhands.com")

LOOKBACK_WINDOW = os.getenv("LOOKBACK_WINDOW", "past 7 days")

APP_NAME = "luckyhands_intel_daily"
DEFAULT_USER_ID = "stakeholder"
