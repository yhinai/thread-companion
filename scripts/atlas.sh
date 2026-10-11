#!/bin/bash
# Load this project's private Atlas configuration without printing credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo 'Atlas configuration is missing: .env' >&2
  exit 1
fi
set -a
source .env
set +a
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run: python3 -m venv .venv' >&2
  exit 1
fi
if ! .venv/bin/python -c 'import pymongo' 2>/dev/null; then
  echo 'Run: .venv/bin/python -m pip install -r requirements-atlas.txt' >&2
  exit 1
fi
case "${1:-check}" in
  check)
    .venv/bin/python - <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from pymongo import MongoClient

report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'connected': False}
try:
    with MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=15000, connectTimeoutMS=10000) as client:
        client.admin.command('ping')
        db = client[os.environ.get('MONGODB_DATABASE', 'thread')]
        marker = {'_id': uuid4().hex, 'application': 'Thread Companion', 'checked_at': report['checked_at']}
        db.connection_checks.insert_one(marker)
        if db.connection_checks.find_one({'_id': marker['_id']}) != marker:
            raise RuntimeError('Round-trip mismatch')
        report.update(connected=True, database=db.name, read_write_verified=True)
except Exception as exc:
    # Driver errors can include connection details. Keep credentials out of output.
    report['error_type'] = type(exc).__name__
    report['next_step'] = 'Check cluster readiness, local networking, Atlas IP access and database credentials.'
Path('.thread').mkdir(exist_ok=True)
Path('.thread/atlas-connection.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
sys.exit(0 if report['connected'] else 1)
PY
    ;;
  server)
    shift
    exec .venv/bin/python -m companion.server "$@"
    ;;
  proof)
    shift
    exec .venv/bin/python -m companion.proof "$@" --require-atlas
    ;;
  doctor)
    shift
    exec .venv/bin/python -m companion.doctor "$@" --require-atlas
    ;;
  *)
    echo 'Usage: bash scripts/atlas.sh [check | doctor <args> | server <args> | proof <args>]' >&2
    exit 2
    ;;
esac
