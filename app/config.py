import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'enterprise_gateway.db'}")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin-secret")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
