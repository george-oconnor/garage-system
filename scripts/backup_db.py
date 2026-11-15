"""Snapshot the SQLite database to instance/backups/ (keeps the newest 20).

Uses SQLite's online backup API, so it's safe to run while the app is serving
requests. Does nothing (exit 0) if the app is configured for a non-SQLite DB.

    venv/bin/python scripts/backup_db.py [label]
"""
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from garagesystem.config import Config  # noqa: E402

KEEP = 20

uri = Config.SQLALCHEMY_DATABASE_URI
if not uri.startswith('sqlite:///'):
    print('==> Database is not SQLite; skipping backup')
    sys.exit(0)

src_path = uri[len('sqlite:///'):]
if not os.path.exists(src_path):
    print(f'==> No database at {src_path}; nothing to back up')
    sys.exit(0)

backup_dir = os.path.join(os.path.dirname(src_path), 'backups')
os.makedirs(backup_dir, exist_ok=True)
label = f'-{sys.argv[1]}' if len(sys.argv) > 1 else ''
dest_path = os.path.join(backup_dir, f'garage-{datetime.now():%Y%m%d-%H%M%S}{label}.db')

src = sqlite3.connect(src_path)
dest = sqlite3.connect(dest_path)
with dest:
    src.backup(dest)
dest.close()
src.close()
print(f'==> Backed up database to {dest_path}')

backups = sorted(f for f in os.listdir(backup_dir) if f.startswith('garage-') and f.endswith('.db'))
for old in backups[:-KEEP]:
    os.remove(os.path.join(backup_dir, old))
