"""Fixed external acceptance checks for the Field Notes proof.

This file lives outside experimental repositories. Evaluations fingerprint it before
and after every trial. These small checks are demonstration evidence, not a broad benchmark.
"""
import argparse
import csv
import importlib.util
import io
import json
from pathlib import Path


def records():
    return [
        {"id": "a", "title": "Write notes", "completed": False},
        {"id": "b", "title": "Read notes", "completed": True},
        {"id": "c", "title": "Review, then ship", "completed": "false"},
        {"id": "d", "title": "Done", "completed": "true"},
        {"id": "e", "title": "Zero", "completed": "0"},
        {"id": "f", "title": "One", "completed": "1"},
        {"id": "g", "title": "No", "completed": " NO "},
        {"id": "h", "title": "Yes", "completed": " YES "},
        {"id": "i", "title": "Unset"},
        {"id": "j", "title": "Null", "completed": None},
        {"id": "k", "title": "Empty", "completed": ""},
        {"id": "l", "title": "Number zero", "completed": 0},
        {"id": "m", "title": "Number one", "completed": 1},
    ]


CANONICAL_ACTIVE = {"a", "c", "e", "g", "i", "j", "k", "l"}
LEGACY_ACTIVE = {"a", "i", "j", "k", "l"}


def grade(repo, operation, policy="canonical"):
    spec = importlib.util.spec_from_file_location("thread_trial_tasks", Path(repo) / "tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    active = CANONICAL_ACTIVE if policy == "canonical" else LEGACY_ACTIVE
    data = records()
    cases = []
    # Singletons expose individual semantics; mixed inputs catch aggregate errors.
    inputs = [[]] + [[record] for record in data] + [data, list(reversed(data))]
    for index, items in enumerate(inputs):
        expected = [item for item in items if item["id"] in active]
        try:
            if operation == "active":
                actual = module.active_tasks([dict(x) for x in items])
                passed = actual == expected
            elif operation == "summary":
                actual = module.summary([dict(x) for x in items])
                passed = actual == {"total": len(items), "active": len(expected)}
            elif operation == "export":
                raw = module.export_active([dict(x) for x in items])
                reader = csv.DictReader(io.StringIO(raw))
                actual = list(reader)
                passed = reader.fieldnames == ["id", "title"] and actual == [{"id": x["id"], "title": x["title"]} for x in expected]
            else:
                raise ValueError("Unknown operation")
            cases.append({"case": index, "passed": passed})
        except Exception as exc:
            cases.append({"case": index, "passed": False, "error": type(exc).__name__})
    return {"operation": operation, "policy": policy, "passed": sum(c["passed"] for c in cases), "total": len(cases),
            "success": all(c["passed"] for c in cases), "cases": cases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--operation", choices=["active", "summary", "export"], required=True)
    parser.add_argument("--policy", choices=["legacy", "canonical"], default="canonical")
    args = parser.parse_args()
    try:
        result = grade(args.repo, args.operation, args.policy)
    except Exception as exc:
        result = {"success": False, "error": type(exc).__name__}
    print(json.dumps(result))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
