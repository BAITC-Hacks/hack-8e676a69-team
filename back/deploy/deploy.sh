#!/usr/bin/env bash
set -euo pipefail

# The health gate at the end of this script exists because without it a
# broken deploy looks identical to a successful one: systemd will happily
# report "active" for a service that crash-loops on every request.

echo "==> cd /data/app"
cd /data/app

echo "==> git pull --ff-only"
git pull --ff-only

if [ ! -d "back/.venv" ]; then
  echo "==> creating venv"
  # uv is NOT on the non-interactive PATH here, absolute path required.
  /home/azureuser/.local/bin/uv venv --python 3.12 back/.venv
fi

echo "==> installing python deps"
/home/azureuser/.local/bin/uv pip install --python back/.venv/bin/python -r back/requirements.txt

echo "==> building frontend"
cd frontend && npm ci && npm run build && cd ..

echo "==> restarting services"
# The ML teammate runs a separate worker watching /data/app/tickets.
sudo install -m 644 back/deploy/hackalem.service /etc/systemd/system/hackalem.service
sudo systemctl daemon-reload
sudo systemctl restart hackalem

echo "==> waiting for services to come up"
sleep 2

echo "==> health gate"
curl -fsS http://127.0.0.1:8000/health || { echo "FAILED: api health check"; exit 1; }

echo "deployed: $(git rev-parse --short HEAD)"
