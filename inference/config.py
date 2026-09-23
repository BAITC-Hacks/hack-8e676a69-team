from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
from back.config import Settings

REQUESTS_DIR = Settings.from_env().tickets_dir
CACHE_DIR = Path(__file__).resolve().parent / "cache"
SUPERVISOR_MAX_THREADS_POOL = 2
