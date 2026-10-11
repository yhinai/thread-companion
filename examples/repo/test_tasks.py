import unittest
from tasks import active_tasks, summary


class TaskTests(unittest.TestCase):
    def test_boolean_compatibility(self):
        items = [{"id": 1, "completed": False}, {"id": 2, "completed": True}]
        self.assertEqual(active_tasks(items), [items[0]])
        self.assertEqual(summary(items), {"total": 2, "active": 1})

    def test_missing_state_is_active(self):
        self.assertEqual(active_tasks([{"id": 1}]), [{"id": 1}])
