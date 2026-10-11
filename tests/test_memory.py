import tempfile
import unittest
from pathlib import Path
from companion.memory import Memory
from companion.store import SQLiteStore


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "data.db")
        self.memory = Memory(self.store)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.project = {"id": "one", "vault": str(self.vault), "goal": "Create a task manager"}
        (self.vault / "Goal.md").write_text('---\ntype: goal\n---\n# Goal\nFollow [[State]].')
        (self.vault / "State.md").write_text('---\ntype: constraint\n---\n# State\nCompletion values must be normalized.')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_graph_links_context_and_revision(self):
        context = self.memory.compile(self.project, "Implement a task list")
        self.assertEqual(len(context["selected"]), 2)
        self.assertEqual(len(self.store.list("edges", active=True)), 1)
        self.assertEqual(self.memory.ingest(self.project)["changed"], 0)
        (self.vault / "State.md").write_text('---\ntype: constraint\n---\n# State\nOnly booleans now.')
        self.assertEqual(self.memory.ingest(self.project)["changed"], 1)
        state = next(n for n in self.store.list("memories") if n["title"] == "State")
        self.assertEqual(state["version"], 2)

    def test_changed_source_invalidates_derived_skill(self):
        self.memory.ingest(self.project)
        source = next(n for n in self.store.list("memories") if n["title"] == "State")
        skill = self.memory.learn(self.project, "run", "Task state review", "Check completion values", {"passed": True}, [source["id"]])
        self.assertEqual(self.store.get("memories", skill["id"])["status"], "validated")
        (self.vault / "State.md").unlink()
        context = self.memory.compile(self.project, "task state review")
        self.assertEqual(self.store.get("memories", skill["id"])["status"], "stale")
        self.assertNotIn(skill["id"], [x["memory"]["id"] for x in context["selected"]])

    def test_project_isolation_and_generated_notes_excluded(self):
        generated = self.vault / "Thread"
        generated.mkdir()
        (generated / "noise.md").write_text("Do not retrieve execution logs")
        self.store.put("memories", {"id": "other", "project_id": "two", "title": "secret", "kind": "goal", "content": "task", "status": "active", "version": 1})
        context = self.memory.compile(self.project, "task")
        self.assertNotIn("other", [x["memory"]["id"] for x in context["selected"]])
        self.assertEqual(len(context["selected"]), 2)

    def test_ambiguous_basename_does_not_create_false_edge(self):
        sub = self.vault / "Other"
        sub.mkdir()
        (sub / "State.md").write_text("# State\nDifferent meaning")
        self.memory.ingest(self.project)
        self.assertEqual(self.store.list("edges", active=True), [])

    def test_folder_escape_rejected(self):
        with self.assertRaises(ValueError):
            self.memory.ingest(dict(self.project, notes_folder=".."))
