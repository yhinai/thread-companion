"""Persistent, explicitly activated refinement with evidence-based promotion."""
import json
import threading
from pathlib import Path
from .codex import CodexAdapter
from .gitops import create_worktree, head, promote, snapshot, verification_fingerprint
from .memory import Memory, digest, render_context
from .process import Cancelled, execute
from .store import identity, now

ACTIVE = {"queued", "running", "stopping"}


class Engine:
    def __init__(self, store, state_dir, adapter=None, recover=False):
        self.store, self.state_dir = store, Path(state_dir).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(store)
        self.adapter = adapter or CodexAdapter(self.state_dir)
        self.lock = threading.RLock()
        self.jobs = {}
        for run in store.list("runs") if recover else []:
            if run["status"] in ACTIVE:
                run.update(status="interrupted", phase="interrupted", summary="Coordinator restarted. Resume to continue from durable evidence.")
                store.put("runs", run)

    def project(self, project_id):
        project = self.store.get("projects", project_id)
        if not project:
            raise ValueError("Project not found")
        return project

    def add_project(self, data):
        for key in ("name", "repo", "vault", "goal"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(key + " is required")
        repo, vault = Path(data["repo"]).expanduser().resolve(), Path(data["vault"]).expanduser().resolve()
        if not repo.is_dir() or not vault.is_dir():
            raise ValueError("Repository and vault must exist")
        head(repo)
        checks = data.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(c, list) and c and all(isinstance(a, str) and a for a in c) for c in checks):
            raise ValueError("Checks must be arrays of command arguments")
        project = {"id": identity(), "name": data["name"], "repo": str(repo), "vault": str(vault),
                   "goal": data["goal"], "notes_folder": data.get("notes_folder", ""), "checks": checks,
                   "auto_review": bool(data.get("auto_review", True)), "auto_apply": True, "created_at": now()}
        self.memory.ingest(project)
        return self.store.put("projects", project)

    def emit(self, run, kind, message, **details):
        return self.store.put("events", {"project_id": run["project_id"], "run_id": run["id"],
                                        "type": kind, "message": message, "at": now(), **details})

    def save(self, run, **changes):
        with self.lock:
            run.update(changes)
            return self.store.put("runs", run)

    def start(self, project_id, task, mode="explore", continuous=False):
        project = self.project(project_id)
        if mode not in ("brief", "review", "explore", "build"):
            raise ValueError("Unsupported mode")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Describe a task or goal")
        if continuous and mode != "explore":
            raise ValueError("Continuous refinement is only available in Explore")
        if mode in ("explore", "build") and not project["checks"]:
            raise ValueError("Configure at least one independent project check before execution")
        with self.lock:
            repo = project["repo"]
            for r in self.store.list("runs"):
                if r["status"] in ACTIVE and self.project(r["project_id"])["repo"] == repo:
                    raise ValueError("This repository already has an active run")
            run = self.store.put("runs", {"id": identity(), "project_id": project_id, "task": task,
                                          "mode": mode, "continuous": continuous, "status": "queued", "phase": "queued",
                                          "cycle": 0, "created_at": now(), "summary": "Preparing context", "parent_id": None})
            self._launch(run)
            return run

    def _launch(self, run):
        stop = threading.Event()
        thread = threading.Thread(target=self._worker, args=(run, stop), daemon=True, name="thread-" + run["id"])
        self.jobs[run["id"]] = (stop, thread)
        thread.start()

    def stop(self, run_id):
        with self.lock:
            run = self.store.get("runs", run_id)
            if not run:
                raise ValueError("Run not found")
            if run_id in self.jobs:
                self.jobs[run_id][0].set()
                self.store.put("runs", dict(run, status="stopping"))
            return run

    def resume(self, run_id):
        old = self.store.get("runs", run_id)
        if not old or old["status"] in ACTIVE:
            raise ValueError("Only inactive runs can be resumed")
        return self.start(old["project_id"], old["task"], old["mode"], old["continuous"])

    def answer(self, question_id, answer):
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("An answer is required")
        question = self.store.get("questions", question_id)
        if not question:
            raise ValueError("Question not found")
        question.update(answer=answer, status="answered")
        self.store.put("questions", question)
        self.store.put("memories", {"id": digest("answer:" + question_id), "project_id": question["project_id"],
                                    "title": question["question"], "kind": "decision", "content": answer,
                                    "status": "active", "authored": False, "scope": "project", "version": 1,
                                    "revision": digest(answer), "source": "answer:" + question_id, "links": []})
        return question

    def status(self, project_id):
        self.project(project_id)
        return {name: self.store.list(name, project_id=project_id) for name in ("runs", "memories", "edges", "questions", "experiments", "events", "evaluations")}

    def check(self, project, cwd, stop):
        evidence = []
        for command in project["checks"]:
            result = execute(command, cwd=cwd, stop=stop)
            evidence.append({"command": command, **result})
        return evidence

    def _worker(self, run, stop):
        project = self.project(run["project_id"])
        try:
            self.save(run, status="running", phase="context")
            while not stop.is_set():
                self.save(run, cycle=run["cycle"] + 1, phase="context")
                context = self.memory.compile(project, run["task"])
                self.emit(run, "context.compiled", "Selected %d relevant memories" % len(context["selected"]), context=context)
                if run["mode"] == "brief":
                    self.save(run, status="complete", phase="complete", summary=render_context(context))
                    break
                if run["mode"] == "review":
                    baseline = self.check(project, project["repo"], stop)
                    result = self.review(project, run, context, project["repo"], baseline, baseline, stop)
                    self.emit(run, "review.completed", result["summary"], review=result, checks=baseline)
                    self.save(run, status="complete", phase="complete", summary=result["summary"])
                    break
                self.save(run, phase="research", summary="Checking direction and researching useful alternatives")
                history = self.store.list("experiments", project_id=project["id"])[-8:]
                questions = self.store.list("questions", project_id=project["id"])
                plan = self.adapter.call("plan", "Inspect the repository and plan useful work toward this goal. "
                    "Search primary internet sources when implementation choices need current information. "
                    "Return actual source URLs and findings; do not invent sources. "
                    "Propose one or two independently executable alternatives. Omit any task blocked by ambiguity; "
                    "queue questions about those tasks and continue independent work. Do not repeat failed experiments "
                    "without new evidence. If no worthwhile work remains, return complete or dead_end. "
                    "Prefer simplicity and maintainability. Do not edit files.\nCONTEXT:\n" + render_context(context) +
                    "\nPAST EXPERIMENTS:\n" + json.dumps(history, default=str) + "\nQUESTIONS:\n" + json.dumps(questions),
                    project["repo"], stop, research=True)
                self.emit(run, "research.completed", plan["summary"], plan=plan)
                for q in plan["questions"]:
                    qid = digest(project["id"] + q["question"].casefold())
                    if not self.store.get("questions", qid):
                        self.store.put("questions", {"id": qid, "project_id": project["id"], "run_id": run["id"], **q,
                                                     "status": "pending", "answer": None})
                if plan["next_action"] != "experiment" or not plan["alternatives"]:
                    state = {"complete": "complete", "dead_end": "dead_end", "waiting": "waiting"}.get(plan["next_action"], "waiting")
                    self.save(run, status=state, phase=state, summary=plan["summary"])
                    break
                self.save(run, phase="baseline")
                baseline = self.check(project, project["repo"], stop)
                accepted = []
                # Both alternatives start from the same main branch; no first-winner bias.
                for alternative in plan["alternatives"][:2]:
                    if stop.is_set():
                        raise Cancelled()
                    experiment = self.experiment(project, run, context, alternative, baseline, stop)
                    if experiment["accepted"]:
                        accepted.append(experiment)
                if not accepted:
                    self.save(run, status="dead_end", phase="dead_end", summary="No candidate passed the fixed checks and independent review. Evidence and branches are preserved.")
                    break
                # Rank candidates conservatively by diff size after verification; simplicity is the user's default.
                best = min(accepted, key=lambda exp: exp["changed_lines"])
                if stop.is_set():
                    raise Cancelled()
                self.memory.ingest(project)
                if not self.memory.current(context):
                    self.emit(run, "experiment.stale", "Project knowledge changed during execution; preserving candidates for a fresh review.")
                    self.save(run, status="waiting", phase="waiting", summary="Source decisions changed. Resume to re-plan against current knowledge; no candidate was applied.")
                    break
                self.save(run, phase="applying")
                applied = promote(project["repo"], best["worktree"], best["commit"])
                best["applied"] = applied
                self.store.put("experiments", best)
                if not applied:
                    self.save(run, status="waiting", phase="waiting", summary="Verified candidate retained. Working branch changed during the experiment; resolve it before applying " + best["commit"][:10])
                    break
                self.emit(run, "experiment.applied", best["review"]["summary"], experiment_id=best["id"], commit=best["commit"])
                for lesson in best["review"]["lessons"]:
                    if not lesson["evidence"].strip():
                        continue
                    skill = self.memory.learn(project, run["id"], lesson["title"], lesson["procedure"],
                                              {"experiment_id": best["id"], "checks": best["checks"], "review": lesson["evidence"]},
                                              [x["memory"]["id"] for x in context["selected"] if x["memory"].get("authored")])
                    self.emit(run, "skill.learned", skill["title"], skill_id=skill["id"], version=skill["version"])
                for item in context["selected"]:
                    if item["memory"]["kind"] == "skill":
                        self.emit(run, "skill.reused", "A prior skill was supplied to this passing run; causality is not established.", skill_id=item["memory"]["id"], experiment_id=best["id"])
                self.save(run, summary=best["review"]["summary"])
                if not run["continuous"]:
                    self.save(run, status="complete", phase="complete")
                    break
                # No duration, iteration, or spending cap. Stop promptly on user request.
                if stop.wait(1):
                    raise Cancelled()
            if stop.is_set():
                self.save(run, status="stopped", phase="stopped", summary="Stopped. Completed evidence and experiment branches are preserved.")
        except Cancelled:
            self.save(run, status="stopped", phase="stopped", summary="Stopped. Completed evidence and experiment branches are preserved.")
        except Exception as exc:
            self.save(run, status="failed", phase="failed", summary=str(exc))
            self.emit(run, "run.failed", str(exc))
        finally:
            try:
                self.write_summary(project, run)
            except Exception as exc:
                self.emit(run, "summary.failed", "Could not write the vault summary: " + str(exc))
            with self.lock:
                self.jobs.pop(run["id"], None)

    def review(self, project, run, context, cwd, baseline, evidence, stop):
        self.save(run, phase="review", summary="Independently reviewing the result against goals and evidence")
        return self.adapter.call("review", "Independently inspect the actual repository. Do not edit files. "
            "Evaluate goal adherence, correctness, simplicity and maintenance. approved means the result meets the "
            "requirements with no known material regression. improved requires a concrete improvement over baseline. "
            "A lesson needs a scoped reusable procedure and specific observed evidence. Do not claim causal transfer "
            "from a single successful run. Report defects honestly.\nCONTEXT:\n" + render_context(context) +
            "\nBASELINE CHECKS:\n" + json.dumps(baseline) + "\nCURRENT CHECKS:\n" + json.dumps(evidence), cwd, stop)

    def experiment(self, project, run, context, alternative, baseline, stop):
        exp = {"id": identity(), "project_id": project["id"], "run_id": run["id"], "cycle": run["cycle"],
               "context_revisions": [{"id": x["memory"]["id"], "version": x["memory"]["version"], "revision": x["memory"]["revision"]} for x in context["selected"]],
               **alternative, "accepted": False, "applied": False, "created_at": now()}
        worktree = create_worktree(project, self.state_dir, exp["id"])
        exp["worktree"] = worktree
        self.store.put("experiments", exp)
        self.save(run, phase="implementing", summary=alternative["title"])
        self.emit(run, "experiment.started", alternative["title"], experiment_id=exp["id"], worktree=worktree)
        fingerprint = verification_fingerprint(worktree["path"])
        implementation = self.adapter.call("work", "Implement this experiment in the current worktree. "
            "You may change architecture and dependencies where justified by the goal, but prefer simplicity. "
            "Preserve tracked evaluation files; propose additional checks separately. Do not commit or merge.\n" +
            json.dumps(alternative) + "\nCONTEXT:\n" + render_context(context), worktree["path"], stop, writable=True)
        self.emit(run, "implementation.completed", implementation["summary"], experiment_id=exp["id"], usage=implementation.get("_usage", {}))
        evidence = self.check(project, worktree["path"], stop)
        self.emit(run, "checks.completed", "%d/%d checks passed" % (sum(e["exit_code"] == 0 for e in evidence), len(evidence)),
                  experiment_id=exp["id"], checks=evidence)
        review = self.review(project, run, context, worktree["path"], baseline, evidence, stop)
        intact = verification_fingerprint(worktree["path"]) == fingerprint
        # Review/check commands must not quietly mutate what was graded.
        from .gitops import git
        changed_lines = 0
        diff = git(worktree["path"], "diff", "--numstat", "HEAD")
        for line in diff.splitlines():
            added, removed, _ = line.split("\t", 2)
            changed_lines += (int(added) if added.isdigit() else 1000) + (int(removed) if removed.isdigit() else 1000)
        # Include new files in the simplicity tie-break, not just tracked modifications.
        for name in git(worktree["path"], "ls-files", "--others", "--exclude-standard").splitlines():
            path = Path(worktree["path"]) / name
            if path.is_file():
                changed_lines += len(path.read_bytes().splitlines())
        if stop.is_set():
            raise Cancelled()
        commit = snapshot(worktree["path"], alternative["title"])
        exp.update(checks=evidence, checks_unchanged=intact, review=review, implementation=implementation,
                   commit=commit, changed_lines=changed_lines,
                   accepted=bool(evidence) and all(e["exit_code"] == 0 for e in evidence) and intact and
                   review["approved"] and review["improved"] and commit != worktree["base"])
        self.store.put("experiments", exp)
        self.emit(run, "experiment.evaluated", review["summary"], experiment_id=exp["id"], accepted=exp["accepted"])
        return exp

    def write_summary(self, project, run):
        folder = Path(project["vault"]) / "Thread" / "Runs"
        folder.mkdir(parents=True, exist_ok=True)
        experiments = self.store.list("experiments", run_id=run["id"])
        text = "# " + run["task"].replace("\n", " ")[:120] + "\n\n"
        text += "Status: **%s** · Cycles: %s\n\n%s\n\n" % (run["status"], run["cycle"], run["summary"])
        for exp in experiments:
            text += "## " + exp["title"] + "\n\n" + exp["hypothesis"] + "\n\n"
            text += "Applied: %s · Branch: `%s`\n\n" % (exp["applied"], exp["worktree"]["branch"])
            if exp.get("review"):
                text += exp["review"]["summary"] + "\n\n"
        text += "\nRun ID: `" + run["id"] + "`\n"
        target = folder / (run["id"] + ".md")
        target.write_text(text, encoding="utf-8")

    def shutdown(self):
        with self.lock:
            jobs = list(self.jobs.values())
        for stop, _ in jobs:
            stop.set()
        for _, thread in jobs:
            thread.join(timeout=6)
