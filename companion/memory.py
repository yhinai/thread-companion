"""Versioned note ingestion and explainable lexical + graph retrieval."""
import hashlib
import json
import re
from pathlib import Path
from .store import now

TYPES = {"goal", "constraint", "decision", "preference", "skill", "note"}
PRIORITY = {"goal": 7, "constraint": 6, "preference": 4, "decision": 3, "skill": 2, "note": 0}
STOP = set("the a an and or to of in for is it with this that on be as at from by".split())


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def tokens(text):
    return set(re.findall(r"[a-z0-9_]{2,}", text.lower())) - STOP


def parse_note(path, content):
    props = {}
    body = content
    if content.startswith("---\n") and "\n---" in content[4:]:
        front, body = content[4:].split("\n---", 1)
        for line in front.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                props[key.strip()] = value.strip().strip("\"'")
    kind = props.get("type", "note")
    if kind not in TYPES:
        kind = "note"
    heading = re.search(r"^# (.+)$", body, re.M)
    return {
        "title": heading.group(1) if heading else Path(path).stem,
        "kind": kind, "content": body.strip(), "source": path,
        "links": re.findall(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", body),
        "status": "superseded" if props.get("status") == "superseded" else "active",
        "scope": props.get("scope", "project"), "authored": True,
    }


class Memory:
    def __init__(self, store):
        self.store = store

    def ingest(self, project):
        root = Path(project["vault"]).resolve()
        folder = (root / project.get("notes_folder", "")).resolve()
        if root not in (folder, *folder.parents):
            raise ValueError("Notes folder must be inside the vault")
        if not folder.is_dir():
            raise ValueError("Notes folder does not exist")
        found, changed = set(), 0
        invalidated = set()
        invalidation_roots = set()
        stale_ids = []
        for path in sorted(folder.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if any(p.startswith(".") for p in path.relative_to(root).parts) or "Thread" in path.relative_to(root).parts or path.is_symlink():
                continue
            if root not in path.resolve().parents:
                continue
            content = path.read_text(encoding="utf-8")
            doc_id = digest(project["id"] + ":" + rel)
            found.add(doc_id)
            old = self.store.get("memories", doc_id)
            revision = digest(content)
            if old and old["revision"] == revision and old["status"] != "deleted":
                continue
            doc = parse_note(rel, content)
            doc.update(id=doc_id, project_id=project["id"], revision=revision,
                       version=(old or {}).get("version", 0) + 1, observed_at=now())
            if old:
                invalidated.add(doc_id)
                invalidation_roots.add(doc_id)
                self.archive(old)
                self.store.put("events", {"project_id": project["id"], "type": "memory.revised", "memory_id": doc_id, "previous": old})
            self.store.put("memories", doc)
            changed += 1
        for old in self.store.list("memories", project_id=project["id"]):
            if old.get("authored") and old["id"] not in found and old["status"] != "deleted":
                invalidated.add(old["id"])
                invalidation_roots.add(old["id"])
                self.archive(old)
                old["status"] = "deleted"
                self.store.put("memories", old)
        # A changed premise invalidates derived skills transitively, never the authored source.
        edges = self.store.list("edges", project_id=project["id"], active=True)
        while True:
            affected = {e["source"] for e in edges if e["relation"] == "learned_from" and e["target"] in invalidated} - invalidated
            if not affected:
                break
            invalidated.update(affected)
            for memory_id in affected:
                skill = self.store.get("memories", memory_id)
                if skill and not skill.get("authored"):
                    self.archive(skill)
                    skill["status"] = "stale"
                    skill["stale_reason"] = "A supporting source changed; revalidation required"
                    self.store.put("memories", skill)
                    stale_ids.append(memory_id)
                    self.store.put("events", {"project_id": project["id"], "type": "memory.invalidated",
                        "message": "A changed source invalidated " + skill["title"], "memory_id": memory_id,
                        "version": skill["version"], "causes": sorted(invalidation_roots), "at": now()})
        self.rebuild_links(project["id"])
        return {"indexed": len(found), "changed": changed, "invalidated": stale_ids}

    def archive(self, memory):
        self.store.put("memory_versions", {**memory, "id": memory["id"] + ":" + str(memory["version"]),
                                           "memory_id": memory["id"]})

    def current(self, context):
        """Detect a changed/deleted premise between planning and promotion."""
        for item in context["selected"]:
            selected = item["memory"]
            current = self.store.get("memories", selected["id"])
            if not current or current["status"] not in ("active", "validated") or current["revision"] != selected["revision"]:
                return False
        return True

    def rebuild_links(self, project_id):
        notes = self.store.list("memories", project_id=project_id)
        active = [n for n in notes if n["status"] == "active"]
        # Ambiguous short names deliberately do not form an edge.
        lookup = {}
        for n in active:
            for key in {n["title"], Path(n.get("source", "")).stem, n.get("source", "").removesuffix(".md")}:
                lookup.setdefault(key.casefold(), []).append(n["id"])
        live = set()
        for note in active:
            for link in note.get("links", []):
                matches = set(lookup.get(link.casefold(), []))
                if len(matches) != 1:
                    continue
                target = next(iter(matches))
                edge_id = digest(note["id"] + target + "links_to")
                live.add(edge_id)
                self.store.put("edges", {"id": edge_id, "project_id": project_id, "source": note["id"], "target": target, "relation": "links_to", "active": True})
        for edge in self.store.list("edges", project_id=project_id):
            if edge["relation"] == "links_to" and edge["id"] not in live:
                edge["active"] = False
                self.store.put("edges", edge)

    def compile(self, project, task, limit=14000, include_skills=True):
        self.ingest(project)
        notes = [n for n in self.store.list("memories", project_id=project["id"]) if n["status"] in ("active", "validated") and (include_skills or n["kind"] != "skill")]
        terms = tokens(task + " " + project["goal"])
        ranked = {}
        for n in notes:
            overlap = terms & tokens(n["title"] + " " + n["content"])
            score = len(overlap) * 3 + PRIORITY[n["kind"]]
            if n["kind"] == "skill" and not overlap:
                continue
            if score:
                ranked[n["id"]] = {"memory": n, "score": score, "reasons": ["matches: " + ", ".join(sorted(overlap))] if overlap else ["project " + n["kind"]]}
        seeds = {key for key, _ in sorted(ranked.items(), key=lambda kv: kv[1]["score"], reverse=True)[:5]}
        by_id = {n["id"]: n for n in notes}
        for edge in self.store.list("edges", project_id=project["id"], active=True):
            for src, dst in ((edge["source"], edge["target"]), (edge["target"], edge["source"])):
                if src in seeds and dst in by_id:
                    item = ranked.setdefault(dst, {"memory": by_id[dst], "score": 0, "reasons": []})
                    item["score"] += 4
                    item["reasons"].append("linked to " + by_id[src]["title"])
        selected, used = [], 0
        for item in sorted(ranked.values(), key=lambda i: (-i["score"], i["memory"]["id"])):
            size = len(item["memory"]["content"]) + 200
            if used + size > limit:
                continue
            selected.append(item)
            used += size
        return {"project_id": project["id"], "task": task, "goal": project["goal"], "selected": selected,
                "characters": used, "omitted": len(notes) - len(selected), "method": "lexical + typed priority + one-hop graph"}

    def learn(self, project, run_id, title, procedure, evidence, source_ids):
        if not evidence or not procedure.strip():
            raise ValueError("A lesson requires a procedure and passing verification evidence")
        doc_id = digest(project["id"] + ":skill:" + title.casefold())
        old = self.store.get("memories", doc_id)
        sources = []
        for source_id in sorted(set(source_ids)):
            source = self.store.get("memories", source_id)
            if not source or source["project_id"] != project["id"] or source["status"] not in ("active", "validated"):
                raise ValueError("A lesson must reference current sources within its project")
            sources.append({"id": source_id, "revision": source["revision"], "version": source["version"]})
        if old:
            self.archive(old)
        doc = {"id": doc_id, "project_id": project["id"], "title": title, "kind": "skill", "content": procedure,
               "status": "validated", "scope": "project", "authored": False, "source": "run:" + run_id,
               "revision": digest(procedure), "version": (old or {}).get("version", 0) + 1,
               "evidence": evidence, "source_revisions": sources, "validation": "passing project checks + independent agent review; transfer not yet established"}
        self.store.put("memories", doc)
        for edge in self.store.list("edges", project_id=project["id"], source=doc_id):
            if edge["relation"] == "learned_from" and edge["target"] not in source_ids:
                edge["active"] = False
                self.store.put("edges", edge)
        for source in source_ids:
            self.store.put("edges", {"id": digest(doc_id + source), "project_id": project["id"], "source": doc_id,
                                     "target": source, "relation": "learned_from", "active": True})
        return doc


def render_context(context):
    return json.dumps({"goal": context["goal"], "task": context["task"], "memories": [
        {"id": x["memory"]["id"], "kind": x["memory"]["kind"], "title": x["memory"]["title"],
         "content": x["memory"]["content"], "version": x["memory"]["version"], "why": x["reasons"]}
        for x in context["selected"]]}, ensure_ascii=False, indent=2)
