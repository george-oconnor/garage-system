#!/usr/bin/env bash
# Runs ON THE SERVER (piped over SSH by .github/workflows/deploy.yml).
# Pulls the latest master, installs dependencies and restarts the app.
set -euo pipefail

APP_DIR=/home/george/garage-system/garage-system
SUPERVISOR_PROGRAM=garage-system
APP_PORT=8007

cd "$APP_DIR"

echo "==> Current: $(git rev-parse --short HEAD)"
git fetch --quiet origin master
# --ff-only: refuse to deploy if the server checkout has diverged, rather than
# silently discarding local changes.
git merge --ff-only origin/master
echo "==> Deploying: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

if ! git diff --quiet HEAD@{1} HEAD -- requirements.txt 2>/dev/null; then
    echo "==> requirements.txt changed, installing dependencies"
    venv/bin/pip install --quiet -r requirements.txt
fi

echo "==> Restarting $SUPERVISOR_PROGRAM"
sudo -n /usr/bin/supervisorctl restart "$SUPERVISOR_PROGRAM"

echo "==> Waiting for app on :$APP_PORT"
for i in $(seq 1 15); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$APP_PORT/" || true)
    if [[ "$code" =~ ^[23] ]]; then
        echo "==> Up (HTTP $code)"
        exit 0
    fi
    sleep 2
done
echo "!! App did not come up (last HTTP code: ${code:-none})" >&2
sudo -n /usr/bin/supervisorctl status "$SUPERVISOR_PROGRAM" || true
tail -n 30 /var/log/garage-system/std.err.log 2>/dev/null || true
exit 1
