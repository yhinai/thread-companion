"""Credential-free setup diagnostics; installed tools are not live-run evidence."""
import argparse
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

from .codex import CodexAdapter


def inspect(state_dir, require_atlas=False):
    state = Path(state_dir).expanduser().resolve()
    checks = []

    def add(name, ready, detail):
        checks.append({"name": name, "ready": bool(ready), "detail": detail})

    add("python", sys.version_info >= (3, 9), "Python " + sys.version.split()[0])
    add("git", shutil.which("git") is not None, "Git executable required for isolated experiments.")
    add("codex", CodexAdapter(state).available(), "Executable detection only; authentication and model execution need a real run.")
    add("obsidian", Path("/Applications/Obsidian.app").is_dir() or shutil.which("obsidian") is not None,
        "Desktop installation detection only; enable the plugin and verify its panel in your vault.")
    atlas = bool(os.environ.get("MONGODB_URI"))
    add("storage", atlas or not require_atlas,
        "Atlas configured; use atlas.sh check to verify ping and read/write." if atlas else
        "Local SQLite selected. The hackathon proof requires the organizer Atlas configuration.")
    if atlas or require_atlas:
        add("mongodb_driver", importlib.util.find_spec("pymongo") is not None,
            "Install requirements-atlas.txt in the Python environment running the coordinator.")
    try:
        state.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=state) as probe:
            probe.write(b"thread readiness")
        add("state_directory", True, str(state))
    except OSError:
        add("state_directory", False, "Cannot write the coordinator state directory.")
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
        add("loopback", True, "Local listener permitted; the configured coordinator port may still be occupied.")
    except OSError:
        add("loopback", False, "This host does not permit a local listener; the Obsidian API cannot start here.")
    return {"ready": all(c["ready"] for c in checks), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=".thread")
    parser.add_argument("--require-atlas", action="store_true")
    args = parser.parse_args()
    report = inspect(args.state_dir, args.require_atlas)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
