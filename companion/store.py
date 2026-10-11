"""Document storage. SQLite for local development; MongoDB for the hackathon."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return uuid4().hex


class SQLiteStore:
    backend = "sqlite-local"

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS documents (collection TEXT, id TEXT, body TEXT, PRIMARY KEY(collection,id))")
        self.db.commit()

    def put(self, collection, doc):
        doc = dict(doc)
        doc.setdefault("id", identity())
        doc["updated_at"] = now()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?)", (collection, doc["id"], json.dumps(doc)))
            self.db.commit()
        return doc

    def get(self, collection, doc_id):
        with self.lock:
            row = self.db.execute("SELECT body FROM documents WHERE collection=? AND id=?", (collection, doc_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, collection, **filters):
        with self.lock:
            rows = self.db.execute("SELECT body FROM documents WHERE collection=? ORDER BY rowid", (collection,)).fetchall()
        return [doc for (body,) in rows for doc in [json.loads(body)] if all(doc.get(k) == v for k, v in filters.items())]

    def close(self):
        self.db.close()


class MongoStore:
    backend = "mongodb-atlas"

    def __init__(self, uri, database):
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError("Atlas requires pymongo. Install requirements-atlas.txt; no fallback is made when MONGODB_URI is set.") from exc
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.client.admin.command("ping")
        self.db = self.client[database]
        for name in ("projects", "memories", "edges", "runs", "events", "questions", "experiments", "memory_versions", "evaluations"):
            self.db[name].create_index("id", unique=True)
            self.db[name].create_index("project_id")

    def put(self, collection, doc):
        doc = dict(doc)
        doc.setdefault("id", identity())
        doc["updated_at"] = now()
        self.db[collection].replace_one({"id": doc["id"]}, doc, upsert=True)
        return doc

    def get(self, collection, doc_id):
        return self.db[collection].find_one({"id": doc_id}, {"_id": 0})

    def list(self, collection, **filters):
        return list(self.db[collection].find(filters, {"_id": 0}))

    def close(self):
        self.client.close()
