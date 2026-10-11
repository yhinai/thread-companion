"""Copy the ready-to-load plugin into a chosen vault; no JS build tool required."""
import argparse
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("vault")
args = parser.parse_args()
vault = Path(args.vault).expanduser().resolve()
if not vault.is_dir():
    raise SystemExit("Vault does not exist")
source = Path(__file__).resolve().parents[1] / "plugin"
destination = vault / ".obsidian" / "plugins" / "thread-companion"
destination.mkdir(parents=True, exist_ok=True)
for name in ("main.js", "styles.css", "manifest.json"):
    shutil.copy2(source / name, destination / name)
print("Installed to", destination)
print("Enable Thread Companion in Obsidian > Settings > Community plugins.")
