from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
REQUESTS_DIR = ROOT_DIR / "requests"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
SUPERVISOR_MAX_THREADS_POOL = 10
