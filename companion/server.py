"""Loopback-only authenticated API used by the Obsidian plugin."""
import argparse
import hmac
import json
import os
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from .engine import Engine
from .store import MongoStore, SQLiteStore


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, engine, token):
        self.engine, self.token = engine, token
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self.respond(403, {"error": "Loopback host required"})
            return False
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
            self.respond(401, {"error": "Set the coordinator token in Thread settings"})
            return False
        return True

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        if not self.authorized():
            return
        try:
            body = {}
            if method == "POST":
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 2_000_000:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Expected an object")
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            e = self.server.engine
            if method == "GET" and parts == ["health"]:
                data = {"ok": True, "backend": e.store.backend, "agent": "codex", "codex_available": e.adapter.available(), "version": "0.1.0"}
            elif method == "GET" and parts == ["projects"]:
                data = e.store.list("projects")
            elif method == "POST" and parts == ["projects"]:
                data = e.add_project(body)
            elif len(parts) == 3 and parts[0] == "projects":
                project = e.project(parts[1])
                if method == "GET" and parts[2] == "state":
                    data = e.status(parts[1])
                elif method == "POST" and parts[2] == "sync":
                    data = e.memory.ingest(project)
                elif method == "POST" and parts[2] == "context":
                    data = e.memory.compile(project, body.get("task", project["goal"]))
                elif method == "POST" and parts[2] == "runs":
                    data = e.start(parts[1], body.get("task", ""), body.get("mode", "explore"), body.get("continuous") is True)
                else:
                    return self.respond(404, {"error": "Unknown endpoint"})
            elif len(parts) == 3 and parts[0] == "runs":
                if method == "POST" and parts[2] == "stop":
                    data = e.stop(parts[1])
                elif method == "POST" and parts[2] == "resume":
                    data = e.resume(parts[1])
                elif method == "GET" and parts[2] == "events":
                    data = e.store.list("events", run_id=parts[1])
                else:
                    return self.respond(404, {"error": "Unknown endpoint"})
            elif method == "POST" and len(parts) == 3 and parts[0] == "questions" and parts[2] == "answer":
                data = e.answer(parts[1], body.get("answer", ""))
            else:
                return self.respond(404, {"error": "Unknown endpoint"})
            self.respond(200, data)
        except (ValueError, KeyError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception:
            self.respond(500, {"error": "Coordinator operation failed. Check repository access and storage connectivity."})


def main():
    parser = argparse.ArgumentParser(description="Thread local coordinator")
    parser.add_argument("--state-dir", default=".thread")
    parser.add_argument("--port", type=int, default=47123)
    args = parser.parse_args()
    state = Path(args.state_dir).expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    # Prevent two coordinators from processing the same state directory.
    import fcntl
    lock = (state / "coordinator.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("A coordinator already owns this state directory")
    token_path = state / "token"
    if not token_path.exists():
        fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    token = token_path.read_text().strip()
    uri = os.environ.get("MONGODB_URI")
    store = MongoStore(uri, os.environ.get("MONGODB_DATABASE", "thread")) if uri else SQLiteStore(state / "thread.db")
    engine = Engine(store, state, recover=True)
    server = ApiServer(("127.0.0.1", args.port), engine, token)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print("Thread coordinator: http://127.0.0.1:%s · %s" % (server.server_port, store.backend), flush=True)
    print("Token file: " + str(token_path), flush=True)
    try:
        server.serve_forever()
    finally:
        engine.shutdown()
        server.server_close()
        store.close()
        lock.close()


if __name__ == "__main__":
    main()
