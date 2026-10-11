"""Isolated experiments and compare-and-swap promotion of tested commits."""
from pathlib import Path
from .process import execute


def git(repo, *args):
    result = execute(["git", "-C", str(repo), *args], timeout=30)
    if result["exit_code"]:
        raise RuntimeError(result["stderr"].strip() or "Git command failed")
    return result["stdout"].strip()


def head(repo):
    return git(repo, "rev-parse", "HEAD")


def clean(repo):
    return not git(repo, "status", "--porcelain")


def create_worktree(project, state_dir, experiment_id):
    repo = project["repo"]
    if not clean(repo):
        raise RuntimeError("Repository has uncommitted work. Commit or stash it before starting an isolated experiment.")
    base = head(repo)
    branch = "thread/" + experiment_id
    path = Path(state_dir) / "worktrees" / experiment_id
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-b", branch, str(path), base)
    return {"path": str(path), "base": base, "branch": branch}


def snapshot(path, title):
    if clean(path):
        return head(path)
    git(path, "add", "-A")
    git(path, "-c", "user.name=Thread", "-c", "user.email=thread@localhost", "commit", "-m", "Thread: " + title[:120])
    return head(path)


def promote(repo, worktree, commit):
    if not clean(repo) or head(repo) != worktree["base"]:
        return False
    git(repo, "merge", "--ff-only", commit)
    return True


def verification_fingerprint(repo):
    """Detect test/config changes. This is tamper detection, not a security sandbox."""
    import hashlib
    files = git(repo, "ls-files").splitlines()
    checks = {}
    for name in files:
        path = Path(name)
        if any("test" in part.lower() or part in ("checks", ".github") for part in path.parts) or path.name in ("package.json", "pyproject.toml", "Makefile"):
            full = Path(repo) / path
            if full.is_file():
                checks[name] = hashlib.sha256(full.read_bytes()).hexdigest()
    return checks
