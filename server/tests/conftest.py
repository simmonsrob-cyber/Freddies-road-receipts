import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="receipt-test-"))
os.environ["SMTP_USER"] = os.environ["SMTP_PASSWORD"] = os.environ["MAIL_TO_COMMANDER"] = ""
