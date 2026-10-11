import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from companion.engine import Engine
from companion.server import ApiServer
from companion.store import SQLiteStore


class NoAgent:
    def available(self): return False


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = SQLiteStore(root / "db")
        self.engine = Engine(self.store, root, NoAgent())
        try:
            self.server = ApiServer(("127.0.0.1", 0), self.engine, "test-token")
        except PermissionError:
            self.store.close()
            self.temp.cleanup()
            self.skipTest("Host sandbox denies localhost binding; run HTTP integration tests outside this sandbox")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.store.close()
        self.temp.cleanup()

    def test_authentication_required(self):
        with self.assertRaises(HTTPError) as err:
            urlopen(self.url + "/health")
        self.assertEqual(err.exception.code, 401)

    def test_health_and_project_validation(self):
        headers = {"Authorization": "Bearer test-token"}
        response = json.load(urlopen(Request(self.url + "/health", headers=headers)))
        self.assertEqual(response["backend"], "sqlite-local")
        request = Request(self.url + "/projects", data=b'{}', headers=headers)
        with self.assertRaises(HTTPError) as err:
            urlopen(request)
        self.assertEqual(err.exception.code, 400)

    def test_untrusted_host_rejected_even_with_token(self):
        request = Request(self.url + "/health", headers={"Authorization": "Bearer test-token", "Host": "attacker.example"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request)
        self.assertEqual(err.exception.code, 403)
