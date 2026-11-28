"""Settings. Secrets live only in .env (never in code). Tune thresholds here."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

VERSION = "V10"
PORT = int(os.environ.get("PORT", "8081"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "app.db"

# Uploads
MAX_UPLOAD_MB = 15
ALLOWED_FORMATS = {"JPEG", "PNG", "MPO", "HEIF"}

# Image pipeline
DETECT_EDGE = 1000          # long edge used to find the page
STORE_EDGE = 1600           # long edge of the saved scan
OCR_EDGE = 2200             # long edge used for reading text
JPEG_QUALITY = 65

# Name matching (tune here)
ACCEPT_SCORE = 85
TIE_MARGIN = 8
MIN_TEXT_CHARS = 20
SINGLE_NAME_PENALTY = 5     # points off when only a surname or first name matched
ELIMINATION_ENABLED = True
ELIMINATION_MIN_SCORE = 60
HOTEL_TAG = "Hotel"         # only this tag counts for the "who is missing" check

# Email (phase 6)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "") or SMTP_USER
MAIL_TO = [a.strip() for a in os.environ.get("MAIL_TO_COMMANDER", "").split(",") if a.strip()]
MAX_ATTACH_MB = float(os.environ.get("MAX_ATTACH_MB", "20"))
ATTACH_MARGIN_MB = 2.0
