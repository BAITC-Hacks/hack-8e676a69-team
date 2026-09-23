"""
Explicit module-level config, read from env with local-friendly defaults so
this runs on a Windows dev machine without a /data mount. No pydantic-settings
on purpose: these are a handful of constants, a settings class would be
ceremony for no benefit here.
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data/tickets"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("DB_PATH", "./data/app.db"))

CV_URL = os.environ.get("CV_URL", "http://127.0.0.1:8001/analyze")

CV_TIMEOUT = float(os.environ.get("CV_TIMEOUT", "60.0"))

WEB_DIST = Path(os.environ.get("WEB_DIST", "./web/dist"))
