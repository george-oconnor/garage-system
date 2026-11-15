# Garage System

A Flask app for tracking cars, service history, mileage, NCT tests and running
costs. Live at <https://garage-system.georgeoc.com>.

## Local development

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt     # Windows: venv\Scripts\pip
export FLASK_APP=run.py
venv/bin/flask db upgrade                    # create/upgrade the local DB
venv/bin/python run.py                       # http://localhost:8080
```

On Windows, `start.ps1` runs the app from a `.venv` in the repo root.

### Configuration

Settings are read from `instance/config.json` (gitignored), falling back to
environment variables for some keys. With no config, the app uses a SQLite
database at `instance/garage.db` and a development secret key.

| Key | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session/cookie signing. **Must** be set outside development: the fallback is public, so the app refuses to start with it unless `SYSTEM` is `DEVELOPMENT` |
| `SQLALCHEMY_DATABASE_URI` | Database URL (env: `DATABASE_URL`); defaults to SQLite |
| `SYSTEM` | Environment name, defaults to `DEVELOPMENT`; e.g. `PRODUCTION` (also the Sentry environment) |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | Error reporting (optional) |
| `REDIS_URL` | Redis for the RQ task queue (optional) |
| `VEHICLE_LOOKUP_PROVIDER` | `regcheck` or `vehicledataglobal` |
| `VEHICLE_LOOKUP_USERNAME` | regcheck.org.uk username (optional) |
| `VEHICLEDATAGLOBAL_API_KEY`, `_ENDPOINT`, `_PACKAGE` | VehicleDataGlobal lookup (optional) |
| `MSGRAPH_TENANT_ID`, `_CLIENT_ID`, `_CLIENT_SECRET`, `MSGRAPH_SENDER` | Password-reset emails via Microsoft Graph (optional) |

## Features beyond the basics

- **Whiteboard** (`/board`): a drag-and-drop board of garage jobs (To do, Waiting on
  parts, In progress, Done). Reminder cards are added automatically when the next
  service, the NCT, motor tax, insurance or a maintenance schedule item is due
  within 30 days or 1,000 km, or when shelf stock runs low (`garagesystem/board/utils.py`).
  A finished card can be logged as a service event, prefilled from the card, with its
  parts turned into line items.
- **Maintenance schedule** (per car): items with their own km and/or month interval.
  Tick an item on an event to reset it.
- **Motor tax and insurance renewals**: Tax and Insurance events have a "valid until"
  date, shown on the car's Insights panel.
- **Fuel log** (per car): fill-ups give L/100km (full tank to full tank) and fuel's
  share of the running cost per km. Odometer readings also go into the mileage log.
- **Full history PDF** (car page, **History PDF**): every event, NCT record,
  schedule and mileage history, with the uploaded NCT certificates (and optionally
  invoices) appended.
- **Shelf** (`/shelf`): parts and consumables in stock. Pick one when adding a line
  item and its quantity is taken off the shelf. Removing the line item puts it back.

## Tests

```bash
venv/bin/pip install pytest
venv/bin/python -m pytest
```

Tests run against an in-memory SQLite database and don't touch `instance/`.

## Database migrations

Schema changes are managed with Flask-Migrate (Alembic), and the migration
scripts in `migrations/versions/` are committed to the repo. The history starts
from a single baseline revision (`ebc449beb634`) describing the schema as of
November 2026.

**When you change a model in `garagesystem/models.py`:**

```bash
export FLASK_APP=run.py
venv/bin/flask db upgrade                       # bring your local DB to head first
venv/bin/flask db migrate -m "describe the change"
# review the generated file in migrations/versions/ — autogenerate isn't perfect
venv/bin/flask db upgrade                       # apply it locally and test
venv/bin/flask db check                         # should say "No new upgrade operations detected"
```

Commit the model change and the migration file together. The deploy applies the
migration to production automatically (see below).

Notes:

- Migrations run in batch mode (`render_as_batch=True`) because SQLite can't
  `ALTER` most column changes in place. Batch mode recreates the table instead,
  so new non-nullable columns need a `server_default`.
- Never edit a migration that has already been deployed. Write a new one.
- Don't run `flask db migrate` on the server. Migrations are generated in
  development and committed.

## Deployment

Production runs on a Hetzner server behind Cloudflare:
nginx (`nginx.conf`) proxies to gunicorn on port 8007, managed by supervisor
(`supervisor.conf`). The app lives in `/home/george/garage-system/garage-system`.
The repo copies of the nginx and supervisor configs are for reference only. The
deploy doesn't install them.

### How a deploy works

Every push to `master` runs the **Deploy** GitHub Actions workflow
(`.github/workflows/deploy.yml`). You can also start it by hand from the Actions
tab (**Run workflow**). The workflow SSHes into the server and runs `deploy.sh`
from the server's checkout. The deploy key is locked to that script, so it
can't be used for anything else (see [One-time server setup](#one-time-server-setup-already-done)).
`deploy.sh`:

1. **Fast-forwards** the server checkout to `origin/master`. If the server has
   local commits or has otherwise diverged, the deploy stops here without
   changing anything. If the pull changed `deploy.sh` itself, the new version is
   re-run, so changes to the deploy script take effect in the same deploy.
2. **Installs dependencies**, but only if `requirements.txt` changed.
3. **Pre-flight check:** builds the app with the new code and confirms
   `SECRET_KEY` isn't the development default. If this fails (import error, bad
   config, default key), the deploy stops before touching the database or
   restarting, so the running app keeps serving the old code.
4. **Migrates the database** if its revision differs from the migration head. It
   first snapshots the SQLite DB with `scripts/backup_db.py`, then runs
   `flask db upgrade`. If the DB is already at head, this step is skipped.
5. **Restarts** the app with `supervisorctl restart garage-system`.
6. **Health-checks** that the app answers on `localhost:8007`. If it doesn't, the
   run fails and prints supervisor status and the end of the error log.

Deploys don't overlap: a push made while a deploy is running waits for it to
finish. To push without deploying, put `[skip ci]` in the commit message.

### Rules

- **Make all changes through GitHub.** Don't commit or edit tracked files on the
  server, because the next deploy will refuse to fast-forward. If that happens,
  get the change onto `master`, then on the server run
  `git fetch && git reset --hard origin/master`.
- Uploads (`garagesystem/static/{car_images,invoices,nct_certs}/`), `instance/`
  (config, DB, backups) and `flask_session/` are gitignored, so deploys never
  touch them.

### Database backups

`scripts/backup_db.py [label]` snapshots the SQLite database to
`instance/backups/garage-<timestamp>[-label].db` using SQLite's online backup
API, so it's safe to run while the app is up. It keeps the newest 20 snapshots.
Deploys run it automatically before applying migrations. To run it by hand:

```bash
cd ~/garage-system/garage-system
venv/bin/python scripts/backup_db.py manual
```

To restore a backup, stop the app, copy the snapshot over `instance/garage.db`,
and start the app again:

```bash
sudo supervisorctl stop garage-system
cp instance/backups/garage-<timestamp>.db instance/garage.db
sudo supervisorctl start garage-system
```

If the restored snapshot is from before a migration, also roll back the code to
the matching commit. Otherwise the next deploy will re-apply the migration.

### One-time server setup (already done)

For reference, in case the server is rebuilt:

- **SSH deploy key:** an ed25519 key whose public half is in
  `~george/.ssh/authorized_keys`, locked to the deploy script:

  ```
  command="/home/george/garage-system/garage-system/deploy.sh",restrict ssh-ed25519 AAAA... github-actions-deploy
  ```

  `command=` makes every login with this key run `deploy.sh`, whatever command
  was requested. `restrict` turns off port forwarding, agent forwarding, X11 and
  terminals. When this is in place, the deploy log shows
  `Running as locked-down deploy key`. The private half lives only in the
  GitHub secret.
- **Sudoers:** `/etc/sudoers.d/garage-deploy` lets `george` run
  `supervisorctl restart garage-system` and `supervisorctl status garage-system`
  without a password.
- **Git access:** the server checkout can `git fetch` from GitHub without
  prompting.
- **GitHub Actions secrets:**

  | Secret | Value |
  | --- | --- |
  | `SSH_HOST` | Server's public IPv4 address (not the Cloudflare IP) |
  | `SSH_USER` | `george` |
  | `SSH_PRIVATE_KEY` | Private half of the deploy key |
  | `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan -t ed25519 <host>` with the IPv4 address |

- **Database:** a database from before migrations were tracked was moved onto
  the baseline with `flask db stamp --purge head`, then confirmed with
  `flask db check`. A brand-new database just needs `flask db upgrade`.
