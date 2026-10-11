"""Exercise the real HTTP handler without binding a socket in restricted hosts."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from companion.engine import Engine
from companion.server import Handler
from companion.store import SQLiteStore


class Connection:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()
    def makefile(self, *args, **kwargs): return self.input
    def sendall(self, data): self.output.write(data)


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp.name) / "db")
        self.engine = Engine(self.store, self.temp.name, SimpleNamespace(available=lambda: False))
        self.server = SimpleNamespace(engine=self.engine, token="test-token")
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
    def request(self, method, path, body=None, token="test-token", host="127.0.0.1"):
        data = json.dumps(body).encode() if body is not None else b""
        headers = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(data)}\r\n\r\n".encode()
        connection = Connection(headers + data)
        Handler(connection, ('127.0.0.1', 0), self.server)
        response = connection.output.getvalue()
        header, content = response.split(b'\r\n\r\n', 1)
        return int(header.split(b' ')[1]), json.loads(content)
    def test_health_actual_handler(self):
        status, result = self.request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(result['backend'], 'sqlite-local')
    def test_auth_and_host_actual_handler(self):
        self.assertEqual(self.request('GET', '/health', token='bad')[0], 401)
        self.assertEqual(self.request('GET', '/health', host='other.example')[0], 403)
    def test_mutation_validation_and_routes(self):
        self.assertEqual(self.request('POST', '/projects', {})[0], 400)
        self.assertEqual(self.request('POST', '/projects', [1, 2])[0], 400)
        self.assertEqual(self.request('GET', '/unknown')[0], 404)
        self.assertEqual(self.request('GET', '/projects')[1], [])
