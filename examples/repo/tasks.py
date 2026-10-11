"""A deliberately imperfect fixture for a two-task memory-transfer demonstration."""

def active_tasks(tasks):
    return [task for task in tasks if not task.get("completed", False)]


def summary(tasks):
    return {"total": len(tasks), "active": sum(not task.get("completed", False) for task in tasks)}
