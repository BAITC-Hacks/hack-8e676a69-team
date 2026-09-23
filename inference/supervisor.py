import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from .config import REQUESTS_DIR, SUPERVISOR_MAX_THREADS_POOL
except ImportError:  # Allows `python app/main.py`.
    from config import REQUESTS_DIR, SUPERVISOR_MAX_THREADS_POOL


class Supervisor:
    def __init__(self, pipelines, request_dir=REQUESTS_DIR, max_workers=SUPERVISOR_MAX_THREADS_POOL):
        self.pipelines = pipelines
        self.request_dir = Path(request_dir)
        self.max_workers = max_workers

    def pending(self):
        self.request_dir.mkdir(parents=True, exist_ok=True)
        return [folder for folder in self.request_dir.iterdir()
                if folder.is_dir() and (folder / "request.json").is_file()
                and not (folder / "response.json").exists()]

    @staticmethod
    def _write(path, data):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def execute(self, folder):
        try:
            request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
            action = request.get("action")
            if action not in self.pipelines:
                raise ValueError(f"unknown action: {action!r}")
            response = {"status": "done", "result": self.pipelines[action].infer(request)}
        except Exception as error:
            response = {"status": "error", "error": str(error)}
        self._write(folder / "response.json", response)
        return folder.name, response["status"]

    def run_once(self):
        folders = self.pending()
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(as_completed([pool.submit(self.execute, folder) for folder in folders]))
