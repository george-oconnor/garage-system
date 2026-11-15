#!/usr/bin/env bash
# Runs ON THE SERVER (piped over SSH by .github/workflows/deploy.yml).
# Pulls the latest master, installs dependencies, applies database migrations
# and restarts the app.
#
# Everything is inside main() so bash reads the whole script before running
# any of it — otherwise a command that reads stdin could swallow the rest of
# the script being piped in over SSH.
set -euo pipefail

APP_DIR=/home/george/garage-system/garage-system
SUPERVISOR_PROGRAM=garage-system
APP_PORT=8007

main() {
    cd "$APP_DIR"
    export FLASK_APP=run.py

    echo "==> Current: $(git rev-parse --short HEAD)"
    git fetch --quiet origin master
    # --ff-only: refuse to deploy if the server checkout has diverged, rather
    # than silently discarding local changes.
    git merge --ff-only origin/master
    echo "==> Deploying: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

    if ! git diff --quiet HEAD@{1} HEAD -- requirements.txt 2>/dev/null; then
        echo "==> requirements.txt changed, installing dependencies"
        venv/bin/pip install --quiet -r requirements.txt
    fi

    # Pre-flight: make sure the new code can actually build the app before we
    # touch the database or restart. If this fails, the old workers keep
    # serving and nothing has changed except the checked-out files.
    echo "==> Pre-flight check"
    venv/bin/python - <<'PY'
import sys
from garagesystem import create_app
from garagesystem.config import DEV_SECRET_KEY
app = create_app()
if app.config['SECRET_KEY'] == DEV_SECRET_KEY:
    sys.exit('!! SECRET_KEY is the public development default. Set it in instance/config.json.')
print('==> App builds OK')
PY

    local current head
    current=$(venv/bin/flask db current 2>/dev/null | awk 'NF {print $1}' | tail -n1)
    head=$(venv/bin/flask db heads 2>/dev/null | awk 'NF {print $1}' | tail -n1)
    if [[ -z "$head" ]]; then
        echo "!! Could not determine migration head" >&2
        exit 1
    fi
    if [[ "$current" != "$head" ]]; then
        echo "==> Migrating database ${current:-<none>} -> $head"
        venv/bin/python scripts/backup_db.py "pre-$head"
        venv/bin/flask db upgrade
    else
        echo "==> Database up to date ($head)"
    fi

    echo "==> Restarting $SUPERVISOR_PROGRAM"
    sudo -n /usr/bin/supervisorctl restart "$SUPERVISOR_PROGRAM"

    echo "==> Waiting for app on :$APP_PORT"
    local code=""
    for _ in $(seq 1 15); do
        code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$APP_PORT/" || true)
        if [[ "$code" =~ ^[23] ]]; then
            echo "==> Up (HTTP $code)"
            return 0
        fi
        sleep 2
    done
    echo "!! App did not come up (last HTTP code: ${code:-none})" >&2
    sudo -n /usr/bin/supervisorctl status "$SUPERVISOR_PROGRAM" || true
    tail -n 30 /var/log/garage-system/std.err.log 2>/dev/null || true
    exit 1
}

main "$@" < /dev/null
