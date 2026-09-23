"""Claim ready CSV tickets, infer once, atomically publish strict JSON."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def claim(folder):
    """OS locks release after a crash. Keep the inode to avoid unlink/relock races."""
    lock = folder / '.inference.lock'
    if lock.is_symlink():
        yield False
        return
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


class Supervisor:
    def __init__(self, pipeline, request_dir=None, max_workers=2):
        if request_dir is None:
            from back.config import Settings
            request_dir = Settings.from_env().tickets_dir
        self.pipeline = pipeline
        self.request_dir = Path(request_dir).resolve()
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers

    def pending(self):
        return sorted(folder for folder in self.request_dir.iterdir()
            if folder.is_dir() and not folder.is_symlink() and folder.resolve().parent == self.request_dir
            and (folder / 'data.csv').is_file() and not (folder / 'data.csv').is_symlink()
            and not (folder / 'response.json').exists() and not (folder / 'response.json').is_symlink())

    @staticmethod
    def _write(path, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        temporary = path.with_name('response.json.tmp')
        if temporary.is_symlink() or path.is_symlink():
            raise ValueError('Response files cannot be symlinks')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def execute(self, folder):
        folder = Path(folder)
        if folder.is_symlink() or folder.resolve().parent != self.request_dir:
            return folder.name, 'skipped'
        try:
            with claim(folder) as acquired:
                if not acquired or (folder / 'response.json').exists():
                    return folder.name, 'skipped'
                if (folder / 'data.csv').is_symlink():
                    return folder.name, 'skipped'
                try:
                    response = self.pipeline.infer(folder / 'data.csv')
                    json.dumps(response, allow_nan=False)
                    status = 'done'
                except Exception as exc:
                    logger.exception('Inference failed for ticket %s', folder.name)
                    response = {'error': {'code': 'inference_failed',
                        'message': str(exc) if isinstance(exc, ValueError) else 'Model inference failed; check worker logs.'}}
                    status = 'error'
                self._write(folder / 'response.json', response)
                logger.info('Ticket %s: %s', folder.name, status)
                return folder.name, status
        except FileNotFoundError:
            return folder.name, 'expired'
        except (OSError, ValueError):
            # A broken ticket/permission must not stop processing other tickets.
            logger.exception('Could not publish ticket %s', folder.name)
            return folder.name, 'publish_error'

    def run_once(self):
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(self.execute, self.pending()))
