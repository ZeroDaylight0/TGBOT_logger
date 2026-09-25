from pathlib import Path
import os

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
STATIC_DIR = APP_ROOT / "static"
KEY_PATH = Path(os.environ.get("TG_TRACKER_KEY_PATH", str(APP_ROOT / "tracker.key")))
DB_PATH = Path(os.environ.get("TG_TRACKER_DB_PATH", str(APP_ROOT / "tracker.db")))
HOST = os.environ.get("TG_TRACKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("TG_TRACKER_PORT", "8000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
