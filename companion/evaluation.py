"""Paired fresh-session comparisons; reports actual results without a presumed lift."""
import copy
import hashlib
import json
import random
import time
from pathlib import Path
from .gitops import git, verification_fingerprint
from .memory import render_context
from .process import execute
from .store import identity, now

ARMS = ("no_memory", "current_notes", "notes_and_skill")
TASKS = {
    "summary": "Implement summary(tasks) in tasks.py. Return a dictionary with total and active task counts. Preserve the task-state conventions of this project. Handle empty input. Do not edit other functions or files.",
    "export": "Implement export_active(tasks) in tasks.py. Return CSV text with id,title headers and one row per active task, in input order. Preserve the task-state conventions of this project. Use correct CSV escaping. Do not edit other functions or files.",
}


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arm_context(context, arm):
    result = copy.deepcopy(context)
    if arm == "no_memory":
        result["selected"] = []
    elif arm == "current_notes":
        result["selected"] = [x for x in result["selected"] if x["memory"]["kind"] != "skill"]
    elif arm != "notes_and_skill":
        raise ValueError("Unknown evaluation arm")
    result["characters"] = sum(len(x["memory"]["content"]) for x in result["selected"])
    return result


class TransferEvaluation:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store
        self.grader = Path(__file__).with_name("grading.py").resolve()

    def run(self, project, base, stop, repeats=3, seed=17, on_trial=None):
        if repeats < 1:
            raise ValueError("At least one repeat required")
        # Freeze knowledge once so a note edit cannot silently change an arm mid-comparison.
        frozen_context = self.engine.memory.compile(project, "Review task completion semantics for summary and export")
        skills = [x for x in frozen_context["selected"] if x["memory"]["kind"] == "skill"]
        if not skills:
            raise ValueError("Learn a validated task-state review skill before measuring transfer")
        evaluation = self.store.put("evaluations", {"id": identity(), "project_id": project["id"], "status": "running",
            "created_at": now(), "backend": self.store.backend, "adapter": self.engine.adapter.name,
            "model": getattr(self.engine.adapter, "model", None) or "inherited Codex configuration",
            "base_commit": base, "seed": seed, "repeats": repeats, "grader_sha256": file_hash(self.grader),
            "context": frozen_context, "trials": [], "protocol": "one fresh agent invocation per arm/task/repeat; same repository commit and task prompt; token use measured, not equalized"})
        schedule = [(task, repeat, arm) for task in TASKS for repeat in range(repeats) for arm in ARMS]
        random.Random(seed).shuffle(schedule)
        try:
            for task, repeat, arm in schedule:
                if stop.is_set():
                    from .process import Cancelled
                    raise Cancelled()
                trial = {"id": identity(), "task": task, "repeat": repeat, "arm": arm}
                path = self.engine.state_dir / "evaluations" / evaluation["id"] / trial["id"]
                path.parent.mkdir(parents=True, exist_ok=True)
                git(project["repo"], "worktree", "add", "--detach", str(path), base)
                trial["worktree"] = str(path)
                context = arm_context(frozen_context, arm)
                context["task"] = TASKS[task]
                prompt = TASKS[task] + "\nUse only this task, repository, and supplied context. Do not search outside the working repository "
                prompt += "for vaults, earlier runs, benchmark assets, or grader implementations. Do not run external research for this controlled trial.\n"
                prompt += "CONTEXT:\n" + render_context(context)
                trial["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
                trial["memory_ids"] = [x["memory"]["id"] for x in context["selected"]]
                fingerprint = verification_fingerprint(path)
                started = time.monotonic()
                result = self.engine.adapter.call("work", prompt, str(path), stop, writable=True)
                trial["seconds"] = round(time.monotonic() - started, 2)
                trial["usage"] = result.get("_usage", {})
                trial["summary"] = result["summary"]
                trial["integrity"] = file_hash(self.grader) == evaluation["grader_sha256"] and verification_fingerprint(path) == fingerprint
                import sys
                checked = execute([sys.executable, str(self.grader), "--repo", str(path), "--operation", task], stop=stop, timeout=30)
                trial["integrity"] = trial["integrity"] and file_hash(self.grader) == evaluation["grader_sha256"] and verification_fingerprint(path) == fingerprint
                try:
                    trial["grade"] = json.loads(checked["stdout"])
                except ValueError:
                    trial["grade"] = {"success": False, "error": "grader did not return JSON"}
                trial["success"] = trial["integrity"] and checked["exit_code"] == 0 and trial["grade"].get("success", False)
                trial["patch"] = git(path, "diff", "HEAD")
                evaluation["trials"].append(trial)
                self.store.put("evaluations", evaluation)
                if on_trial:
                    on_trial(trial)
                if not trial["integrity"]:
                    raise RuntimeError("Evaluation integrity changed; comparison aborted")
            evaluation["status"] = "complete"
        except BaseException as exc:
            evaluation["status"] = "interrupted" if stop.is_set() else "failed"
            evaluation["error"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            evaluation["summary"] = summarize(evaluation["trials"])
            self.store.put("evaluations", evaluation)
            report = self.engine.state_dir / "evaluations" / evaluation["id"] / "report.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(render_report(evaluation), encoding="utf-8")
        return evaluation


def summarize(trials):
    summary = {}
    for arm in ARMS:
        group = [t for t in trials if t["arm"] == arm]
        summary[arm] = {"passed": sum(bool(t["success"]) for t in group), "total": len(group),
                        "seconds": round(sum(t["seconds"] for t in group), 2),
                        "input_tokens": sum(t.get("usage", {}).get("input_tokens", 0) for t in group),
                        "output_tokens": sum(t.get("usage", {}).get("output_tokens", 0) for t in group),
                        "usage_reported": sum(bool(t.get("usage")) for t in group)}
    return summary


def render_report(evaluation):
    lines = ["# Thread transfer evaluation", "", "Status: **%s**" % evaluation["status"],
             "Storage: `%s` · Agent: `%s` · Model: `%s`" % (evaluation["backend"], evaluation["adapter"], evaluation["model"]), "",
             "Base commit: `%s`" % evaluation["base_commit"], "Grader: `%s`" % evaluation["grader_sha256"], "",
             evaluation["protocol"], "", "| Context | Tasks passed | Seconds | Input tokens | Output tokens |", "|---|---:|---:|---:|---:|"]
    for arm, result in evaluation["summary"].items():
        lines.append("| %s | %d/%d | %s | %d | %d |" % (arm, result["passed"], result["total"], result["seconds"], result["input_tokens"], result["output_tokens"]))
    lines += ["", "## Interpretation", "", "This is a small, custom demonstration, not a general agent benchmark. "
              "Compare current_notes with notes_and_skill to estimate the incremental effect of a learned skill; "
              "no_memory also measures access to project-specific requirements. More tokens or time can explain differences. "
              "Equal results are not evidence of a skill benefit. Trial order is randomized and raw results are preserved. "
              "The same base commit, task prompt, grader and agent configuration are used across arms. "
              "Repository/provider instructions may still supply background knowledge. Prompt isolation is not a security boundary.", ""]
    if evaluation.get("error"):
        lines += ["Execution error: " + evaluation["error"], ""]
    return "\n".join(lines)
