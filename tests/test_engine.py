import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from companion.engine import Engine
from companion.gitops import git
from companion.store import SQLiteStore


class FixtureAdapter:
    """Deterministic test double. Never used by the application or represented as AI."""
    def __init__(self, tamper=False, waiting=False):
        self.tamper, self.waiting = tamper, waiting
        self.calls = []

    def available(self):
        return True

    def call(self, phase, prompt, cwd, stop, **kwargs):
        self.calls.append((phase, prompt))
        if phase == "plan":
            return {"summary": "Normalize task completion", "alternatives": [] if self.waiting else [
                {"title": "Normalize completion", "task": "Fix completion interpretation", "hypothesis": "String false should remain active"}],
                "questions": [{"question": "Which state format is authoritative?", "blocks": "state conversion"}] if self.waiting else [],
                "sources": [], "next_action": "waiting" if self.waiting else "experiment"}
        if phase == "work":
            if self.tamper:
                (Path(cwd) / "test_task.py").write_text("# deleted checks\n")
            (Path(cwd) / "task.py").write_text('def active(value):\n    return str(value).strip().lower() not in ("true", "1", "yes")\n')
            return {"summary": "Normalized completion", "changes": ["task.py"]}
        return {"summary": "The task state behavior is improved", "approved": True, "improved": True, "findings": [], "next_task": "",
                "lessons": [{"title": "Task completion review", "procedure": "Check string false and boolean true separately", "evidence": "Fixed check passes"}]}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".gitignore").write_text("__pycache__/\n")
        (self.repo / "task.py").write_text("def active(value):\n    return not bool(value)\n")
        (self.repo / "test_task.py").write_text('import unittest\nfrom task import active\nclass TestState(unittest.TestCase):\n    def test_false_string(self): self.assertTrue(active("false"))\n    def test_true(self): self.assertFalse(active(True))\n')
        git(self.repo, "init", "-b", "main")
        git(self.repo, "add", ".")
        git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "baseline")
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "Goal.md").write_text('---\ntype: goal\n---\n# Task state\nNormalize string false completion.')
        self.store = SQLiteStore(self.root / "store.db")
        self.adapter = FixtureAdapter()
        self.engine = Engine(self.store, self.root / "state", self.adapter)
        self.project = self.engine.add_project({"name": "Fixture", "repo": str(self.repo), "vault": str(self.vault),
                                               "goal": "Normalize task completion", "checks": [["python3", "-m", "unittest", "discover"]]})

    def tearDown(self):
        self.engine.shutdown()
        self.store.close()
        self.temp.cleanup()

    def run_and_wait(self, mode="explore", continuous=False):
        run = self.engine.start(self.project["id"], "Fix task completion", mode, continuous)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.store.get("runs", run["id"])
            if result["status"] not in {"queued", "running", "stopping"}:
                # Wait for report persistence too.
                while run["id"] in self.engine.jobs and time.monotonic() < deadline:
                    time.sleep(.01)
                return result
            time.sleep(.02)
        self.fail("Run did not finish")

    def test_full_loop_applies_verified_change_and_persists_lesson(self):
        run = self.run_and_wait()
        self.assertEqual(run["status"], "complete", run["summary"])
        self.assertIn('str(value)', (self.repo / "task.py").read_text())
        experiments = self.store.list("experiments")
        self.assertTrue(experiments[0]["applied"])
        self.assertEqual(experiments[0]["checks"][0]["exit_code"], 0)
        skills = [n for n in self.store.list("memories") if n["kind"] == "skill"]
        self.assertEqual(len(skills), 1)
        context = self.engine.memory.compile(self.project, "Review task completion in summary")
        self.assertIn(skills[0]["id"], [x["memory"]["id"] for x in context["selected"]])
        self.assertTrue((self.vault / "Thread" / "Runs" / (run["id"] + ".md")).exists())

    def test_modified_tests_reject_promotion_and_learning(self):
        self.adapter.tamper = True
        run = self.run_and_wait()
        self.assertEqual(run["status"], "dead_end")
        self.assertIn("bool(value)", (self.repo / "task.py").read_text())
        self.assertFalse(self.store.list("experiments")[0]["checks_unchanged"])
        self.assertEqual([n for n in self.store.list("memories") if n["kind"] == "skill"], [])

    def test_brief_does_not_start_agent(self):
        run = self.run_and_wait("brief")
        self.assertEqual(run["status"], "complete")
        self.assertEqual(self.adapter.calls, [])

    def test_question_answer_becomes_retrievable_decision(self):
        self.adapter.waiting = True
        run = self.run_and_wait(continuous=True)
        self.assertEqual(run["status"], "waiting")
        q = self.store.list("questions")[0]
        self.engine.answer(q["id"], "Use the canonical state format")
        context = self.engine.memory.compile(self.project, "canonical state")
        self.assertTrue(any("canonical" in x["memory"]["content"] for x in context["selected"]))

    def test_restart_marks_incomplete_run_interrupted(self):
        self.store.put("runs", {"id": "old", "project_id": self.project["id"], "status": "running"})
        Engine(self.store, self.root / "state", self.adapter)
        self.assertEqual(self.store.get("runs", "old")["status"], "running")
        Engine(self.store, self.root / "state", self.adapter, recover=True)
        self.assertEqual(self.store.get("runs", "old")["status"], "interrupted")

    def test_dirty_worktree_is_preserved(self):
        (self.repo / "personal.txt").write_text("unsaved user work")
        run = self.run_and_wait()
        self.assertEqual(run["status"], "failed")
        self.assertEqual((self.repo / "personal.txt").read_text(), "unsaved user work")

    def test_continuous_stops_at_dead_end_without_iteration_cap(self):
        run = self.run_and_wait(continuous=True)
        self.assertEqual(run["cycle"], 2)
        self.assertEqual(run["status"], "dead_end")
