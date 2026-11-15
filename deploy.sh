#!/usr/bin/env bash
# Runs ON THE SERVER, from the server's checkout. GitHub Actions
# (.github/workflows/deploy.yml) reaches it over SSH with a key that is locked
# to this script in ~/.ssh/authorized_keys (command="...deploy.sh",restrict),
# so that key can't do anything except trigger a deploy.
#
# Pulls the latest master, installs dependencies, applies database migrations
# and restarts the app. If the pull updates this script, it re-runs the new
# version so changes to deploy.sh take effect in the same deploy.
#
# Everything is inside main(), and main is called with `; exit` on the same
# line, so bash has parsed everything it will run before git rewrites this file.
set -euo pipefail

APP_DIR=/home/george/garage-system/garage-system
SUPERVISOR_PROGRAM=garage-system
APP_PORT=8007

main() {
    cd "$APP_DIR"
    export FLASK_APP=run.py

    local before
    if [[ -n "${DEPLOY_REEXEC:-}" ]]; then
        # Second pass after deploy.sh itself changed: the pull already happened.
        before=$DEPLOY_PREV_HEAD
    else
        if [[ -n "${SSH_ORIGINAL_COMMAND+x}" ]]; then
            echo "==> Running as locked-down deploy key"
        fi
        before=$(git rev-parse HEAD)
        echo "==> Current: $(git rev-parse --short HEAD)"
        git fetch --quiet origin master
        # --ff-only: refuse to deploy if the server checkout has diverged,
        # rather than silently discarding local changes.
        git merge --ff-only origin/master

        if ! git diff --quiet "$before" HEAD -- deploy.sh; then
            echo "==> deploy.sh changed, re-running the new version"
            DEPLOY_REEXEC=1 DEPLOY_PREV_HEAD=$before exec "$APP_DIR/deploy.sh"
        fi
    fi
    echo "==> Deploying: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

    if ! git diff --quiet "$before" HEAD -- requirements.txt; then
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

main "$@" < /dev/null; exit $?
