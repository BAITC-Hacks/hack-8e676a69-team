"""
Atomic JSON file writes.

os.replace is atomic on both POSIX and Windows: the rename either fully
happens or doesn't happen at all, there is no in-between state visible to a
reader. So a reader polling for this file never observes a partially written
(truncated / half-flushed) JSON file - it either sees the old file, or the
complete new one.
"""

import json
import os
import tempfile


def write_json_atomic(path, data: dict) -> None:
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
