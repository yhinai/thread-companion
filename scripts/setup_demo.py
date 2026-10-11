"""Create an independent Git fixture and sample vault under a chosen directory."""
import argparse
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("destination", nargs="?", default=".thread/demo")
args = parser.parse_args()
root = Path(args.destination).resolve()
source = Path(__file__).resolve().parents[1] / "examples"
if root.exists():
    raise SystemExit("Destination already exists; choose a new directory to preserve existing work")
root.mkdir(parents=True)
for name in ("repo", "vault"):
    shutil.copytree(source / name, root / name)
repo = root / "repo"
(repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
for command in (["init", "-b", "main"], ["add", "."], ["-c", "user.name=Thread Demo", "-c", "user.email=demo@localhost", "commit", "-m", "Initial demonstration fixture"]):
    subprocess.run(["git", "-C", str(repo), *command], check=True, capture_output=True)
print("Repository:", repo)
print("Vault:", root / "vault")
print('Verification command: ["python3", "-m", "unittest", "discover", "-v"]')
