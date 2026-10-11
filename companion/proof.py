"""Reproducible demonstration: changed decision → stale skill → learning → transfer.

prepare/change-decision/check are deterministic. learn and evaluate invoke real Codex.
There is intentionally no simulated-success mode.
"""
import argparse
import ast
import fcntl
import json
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from .codex import CodexAdapter
from .engine import Engine
from .evaluation import TransferEvaluation, file_hash
from .gitops import git, head, snapshot
from .memory import digest
from .process import execute
from .store import MongoStore, SQLiteStore, now

LEGACY = """---
type: constraint
---
# Task state
Legacy task completion uses Python truthiness: every nonempty value means complete.
False, zero, null, empty strings and missing values mean active.
Apply this project convention consistently to task lists, summaries and exports.
"""
CANONICAL = """---
type: constraint
---
# Task state
The client contract has changed. Interpret the completed field consistently everywhere.
True, 1, and strings true, 1, yes mean complete. Strings are trimmed and case-insensitive.
False, 0, null, missing values, and strings false, 0, no, or empty mean active.
A string containing the word false must never be treated as complete just because it is nonempty.
The active list, summary counts and CSV export must agree.
"""
LEARNING_TASK = "Update active_tasks in tasks.py to follow the current Task state decision. Extract a small reusable interpreter if appropriate. Do not change summary or add export yet; those are separate upcoming tasks. Verify the exact state semantics, then derive a reusable task-state review procedure from observed results."


def open_store(root, require_atlas=False):
    uri = os.environ.get("MONGODB_URI")
    if require_atlas and not uri:
        raise RuntimeError("MONGODB_URI must point to the organizer-provided Atlas Sandbox for the live hackathon proof")
    return MongoStore(uri, os.environ.get("MONGODB_DATABASE", "thread")) if uri else SQLiteStore(root / "runtime" / "thread.db")


def grader_command(operation, policy="canonical"):
    return [sys.executable, str(Path(__file__).with_name("grading.py").resolve()), "--operation", operation, "--policy", policy]


def prepare(root, store):
    fixture = root / "fixture"
    if fixture.exists():
        raise ValueError("Proof fixture already exists; use another --root to preserve evidence")
    source = Path(__file__).resolve().parents[1] / "examples"
    shutil.copytree(source, fixture)
    repo, vault = fixture / "repo", fixture / "vault"
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    note = vault / "Decisions" / "Task state.md"
    note.write_text(LEGACY)
    (repo / "tasks.py").write_text('''"""Field Notes task state. Follow the project's current decisions."""

def active_tasks(tasks):
    return [task for task in tasks if not task.get("completed", False)]


def summary(tasks):
    raise NotImplementedError("Next task: summary")


def export_active(tasks):
    raise NotImplementedError("Next task: CSV export")
''')
    # Keep ordinary regressions confined to active_tasks during the learning phase.
    (repo / "test_tasks.py").write_text('''import unittest
from tasks import active_tasks

class RegressionTests(unittest.TestCase):
    def test_booleans(self):
        data = [{"id": 1, "completed": False}, {"id": 2, "completed": True}]
        self.assertEqual(active_tasks(data), data[:1])
''')
    git(repo, "init", "-b", "main")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Thread Demo", "-c", "user.email=demo@localhost", "commit", "-m", "Legacy fixture before decision change")
    engine = Engine(store, root / "runtime")
    project = engine.add_project({"name": "Field Notes — learning proof", "repo": str(repo), "vault": str(vault),
        "goal": "Keep task completion behavior consistent with the current project decision; prefer simple maintainable code.",
        "checks": [grader_command("active"), [sys.executable, "-m", "unittest", "discover"]]})
    old_check = execute(grader_command("active", "legacy"), cwd=repo)
    if old_check["exit_code"]:
        raise RuntimeError("Legacy fixture does not satisfy its original contract")
    source_memory = next(m for m in store.list("memories", project_id=project["id"]) if m["title"] == "Task state")
    # Explicit seeded historical data; never represented as a model-generated lesson.
    skill = engine.memory.learn(project, "seeded-history", "Review task state", "For legacy task completion, use Python truthiness consistently. Nonempty strings mean complete.",
        {"origin": "seeded historical procedure, not AI-generated", "checks": [old_check], "policy": "legacy"}, [source_memory["id"]])
    skill["validation"] = "seeded historical procedure with passing legacy checks; no agent review or demonstrated transfer"
    store.put("memories", skill)
    manifest = {"project_id": project["id"], "legacy_skill_id": skill["id"], "legacy_commit": head(repo),
                "source_id": source_memory["id"], "backend": store.backend, "prepared_at": now(),
                "grader_sha256": file_hash(Path(__file__).with_name("grading.py"))}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Prepared a legacy fixture and explicitly seeded historical skill.")
    print("Vault:", vault)
    print("Repository:", repo)
    print("Storage:", store.backend)
    return manifest


def change_decision(root, store, manifest):
    engine = Engine(store, root / "runtime")
    project = engine.project(manifest["project_id"])
    note = Path(project["vault"]) / "Decisions" / "Task state.md"
    note.write_text(CANONICAL)
    result = engine.memory.ingest(project)
    check = execute(grader_command("active"), cwd=project["repo"])
    baseline = json.loads(check["stdout"])
    manifest["decision_changed_at"] = now()
    manifest["baseline"] = baseline
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    old_skill = store.get("memories", manifest["legacy_skill_id"])
    if old_skill["status"] != "stale":
        raise RuntimeError("Changed decision did not invalidate the legacy skill")
    print(json.dumps({"source_changed": result["changed"], "invalidated_skills": result["invalidated"], "baseline": baseline}, indent=2))


def learn(root, store, manifest, stop, model=None):
    engine = Engine(store, root / "runtime", CodexAdapter(root / "runtime", model=model))
    project = engine.project(manifest["project_id"])
    engine.memory.ingest(project)
    if not manifest.get("decision_changed_at"):
        raise ValueError("Run change-decision first")
    if file_hash(Path(__file__).with_name("grading.py")) != manifest["grader_sha256"]:
        raise RuntimeError("Fixed grader changed after proof preparation")
    run = engine.start(project["id"], LEARNING_TASK, "build")
    last = None
    while run["id"] in engine.jobs:
        current = store.get("runs", run["id"])
        if current["phase"] != last:
            print(current["phase"] + ": " + current["summary"][:220], flush=True)
            last = current["phase"]
        if stop.wait(.25):
            engine.stop(run["id"])
            engine.shutdown()
            break
    result = store.get("runs", run["id"])
    manifest["learning_run_id"] = run["id"]
    manifest["learning_status"] = result["status"]
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if result["status"] != "complete":
        raise RuntimeError(result["summary"])
    lessons = [m for m in store.list("memories", project_id=project["id"]) if m["kind"] == "skill" and m["status"] == "validated"]
    if not lessons:
        raise RuntimeError("Implementation finished but no supported reusable skill was learned; no transfer claim can be made")
    # Ensure transfer functions are genuinely fresh, even if a worker edited more than requested.
    path = Path(project["repo"]) / "tasks.py"
    code = path.read_text()
    lines = code.splitlines(keepends=True)
    functions = [n for n in ast.parse(code).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ("summary", "export_active")]
    for node in sorted(functions, key=lambda n: n.lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = ["def %s(tasks):\n    raise NotImplementedError(\"Fresh transfer task\")\n" % node.name]
    path.write_text("".join(lines))
    manifest["transfer_base"] = snapshot(project["repo"], "Prepare unimplemented transfer functions")
    manifest["learned_skills"] = [m["id"] for m in lessons]
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Learning completed. Next: evaluate fresh sessions against three context conditions.")


def check(root, store, manifest):
    engine = Engine(store, root / "runtime")
    project = engine.project(manifest["project_id"])
    engine.memory.ingest(project)
    selected = engine.memory.compile(project, "Review task completion summary and export")
    print(json.dumps({"backend": store.backend, "source": store.get("memories", manifest["source_id"]),
        "legacy_skill": store.get("memories", manifest["legacy_skill_id"]),
        "selected": [{"title": x["memory"]["title"], "version": x["memory"]["version"], "reason": x["reasons"]} for x in selected["selected"]],
        "learning_status": manifest.get("learning_status", "not run")}, indent=2))


def isolated_transfer_project(project, root):
    """A new Git history with no learned implementation for any arm to reuse."""
    repo = root / "isolated-transfer-repo"
    if repo.exists():
        raise ValueError("Isolated fixture already exists; preserve its results instead of overwriting it")
    repo.mkdir()
    (repo / "tasks.py").write_text('''"""Task operations. Completion conventions belong to the project decisions."""

def summary(tasks):
    raise NotImplementedError("Implement task summary")

def export_active(tasks):
    raise NotImplementedError("Implement CSV export")
''')
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git(repo, "init", "-b", "main")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Thread Demo", "-c", "user.email=demo@localhost", "commit", "-m", "Unimplemented transfer operations; no policy or prior implementation")
    return {**project, "repo": str(repo)}, head(repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "change-decision", "learn", "evaluate", "evaluate-isolated", "check"])
    parser.add_argument("--root", default=".thread/proof")
    parser.add_argument("--require-atlas", action="store_true")
    parser.add_argument("--model", help="Explicit Codex model for reproducible comparisons; otherwise inherit CLI configuration")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    lock = (runtime / "coordinator.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Stop the coordinator for this proof before running the standalone proof command")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    store = open_store(root, args.require_atlas)
    try:
        if args.action == "prepare":
            prepare(root, store)
            return
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["backend"] != store.backend:
            raise ValueError("Proof storage changed; prepare a new proof in the selected backend")
        if args.action == "change-decision":
            change_decision(root, store, manifest)
        elif args.action == "learn":
            learn(root, store, manifest, stop, args.model)
        elif args.action == "check":
            check(root, store, manifest)
        else:
            if not manifest.get("transfer_base"):
                raise ValueError("Complete a real learning run before evaluating transfer")
            engine = Engine(store, root / "runtime", CodexAdapter(root / "runtime", model=args.model))
            project, base = engine.project(manifest["project_id"]), manifest["transfer_base"]
            if args.action == "evaluate-isolated":
                project, base = isolated_transfer_project(project, root)
            result = TransferEvaluation(engine).run(project, base, stop,
                repeats=args.repeats, fixture="isolated_unimplemented" if args.action == "evaluate-isolated" else "shared_implementation",
                on_trial=lambda trial: print("%s / %s / %s: %s" % (trial["task"], trial["arm"], trial["repeat"], "PASS" if trial["success"] else "FAIL"), flush=True))
            print(json.dumps(result["summary"], indent=2))
            print("Report:", root / "runtime" / "evaluations" / result["id"] / "report.md")
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print("Proof stopped:", str(exc), file=sys.stderr)
        raise SystemExit(1)
    finally:
        store.close()
        lock.close()


if __name__ == "__main__":
    main()
