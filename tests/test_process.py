import threading
import unittest
from companion.process import execute, Cancelled
from companion.codex import validate, PLAN


class ProcessTests(unittest.TestCase):
    def test_cancel_running_command(self):
        stop = threading.Event()
        timer = threading.Timer(.2, stop.set)
        timer.start()
        with self.assertRaises(Cancelled):
            execute(["python3", "-c", "import time; time.sleep(30)"], stop=stop)
        timer.join()

    def test_schema_rejects_invalid_decisions(self):
        with self.assertRaises(ValueError):
            validate({"summary": "x", "alternatives": [], "questions": [], "sources": [], "next_action": "invented"}, PLAN)
