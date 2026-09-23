#!/usr/bin/env bash
set -euo pipefail
backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(dirname -- "$backend_dir")"
python_executable="$backend_dir/.venv/bin/python"
if [ ! -x "$python_executable" ]; then
  echo 'Create back/.venv and install back/requirements.txt first; see back/README.md.' >&2
  exit 1
fi
launch_args=(-m uvicorn back.main:app --app-dir "$repository_dir" --host 127.0.0.1 --port 8000)
if [ -f "$backend_dir/.env" ]; then launch_args+=(--env-file "$backend_dir/.env"); fi
exec "$python_executable" "${launch_args[@]}" "$@"
