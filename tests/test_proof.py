import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from companion.engine import Engine
from companion.evaluation import TransferEvaluation, arm_context, render_report, summarize
from companion.gitops import head
from companion.memory import Memory
from companion.proof import prepare, change_decision
from companion.store import SQLiteStore
from companion.grading import grade


class NoLearningAdapter:
    """A deliberately unhelpful test double to ensure reports never fabricate lift."""
    name = "deterministic-test-double"
    model = "none"
    def available(self): return True
    def call(self, phase, prompt, cwd, stop, **kwargs):
        return {"summary": "No implementation produced", "changes": [], "_usage": {"input_tokens": 20, "output_tokens": 5}}


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "store.db")
        with contextlib.redirect_stdout(io.StringIO()):
            self.manifest = prepare(self.root, self.store)
        self.engine = Engine(self.store, self.root / "runtime", NoLearningAdapter())
        self.project = self.engine.project(self.manifest["project_id"])

    def tearDown(self):
        self.engine.shutdown()
        self.store.close()
        self.temp.cleanup()

    def test_changed_decision_invalidates_and_baseline_fails(self):
        self.assertTrue(grade(self.project["repo"], "active", "legacy")["success"])
        with contextlib.redirect_stdout(io.StringIO()):
            change_decision(self.root, self.store, self.manifest)
        self.assertEqual(self.manifest["baseline"]["passed"], 11)
        self.assertEqual(self.manifest["baseline"]["total"], 16)
        old = self.store.get("memories", self.manifest["legacy_skill_id"])
        self.assertEqual(old["status"], "stale")
        self.assertTrue(self.store.list("events", type="memory.invalidated"))
        self.assertTrue(self.store.list("memory_versions", memory_id=self.manifest["source_id"]))
        context = self.engine.memory.compile(self.project, "task completion review")
        self.assertNotIn(old["id"], [x["memory"]["id"] for x in context["selected"]])

    def test_frozen_context_detects_changed_source(self):
        context = self.engine.memory.compile(self.project, "completion")
        self.assertTrue(self.engine.memory.current(context))
        with contextlib.redirect_stdout(io.StringIO()):
            change_decision(self.root, self.store, self.manifest)
        self.assertFalse(self.engine.memory.current(context))

    def test_arm_context_isolation(self):
        context = self.engine.memory.compile(self.project, "review task state")
        notes = arm_context(context, "current_notes")
        self.assertFalse(any(x["memory"]["kind"] == "skill" for x in notes["selected"]))
        self.assertTrue(any(x["memory"]["kind"] == "skill" for x in context["selected"]))
        self.assertEqual(arm_context(context, "no_memory")["selected"], [])

    def test_measured_failures_are_not_reported_as_improvement(self):
        evaluation = TransferEvaluation(self.engine).run(self.project, head(self.project["repo"]), threading.Event(), repeats=1)
        self.assertEqual(evaluation["status"], "complete")
        self.assertEqual(len(evaluation["trials"]), 6)
        self.assertTrue(all(not t["success"] for t in evaluation["trials"]))
        self.assertEqual({v["total"] for v in evaluation["summary"].values()}, {2})
        self.assertIn("Equal results are not evidence", render_report(evaluation))
        self.assertIn("deterministic-test-double", render_report(evaluation))
        self.assertTrue(all(t["usage"]["input_tokens"] == 20 for t in evaluation["trials"]))
