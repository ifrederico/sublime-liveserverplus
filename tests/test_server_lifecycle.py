"""Server lifecycle regressions: ports, shutdown, and HTTP headers.

These start the real Server on a free port and talk to it over sockets,
which covers what the renderer unit tests cannot: that a stop really ends
everything a start began, and that the wire format is honest.
"""
import base64
import gzip
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_PATH = REPO_ROOT / "liveserverplus_lib" / "vendor"
for entry in (str(VENDOR_PATH), str(REPO_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# Settings handed out by the stubbed sublime.load_settings. Tests assign to it.
SETTINGS = {}


class _DictSettings:
    def get(self, key, default=None):
        return SETTINGS.get(key, default)

    def add_on_change(self, key, callback):
        pass

    def clear_on_change(self, key):
        pass


def _raise_not_found(resource_path):
    raise FileNotFoundError(resource_path)


# What the plugin needs from `sublime` while a server runs. Installed per
# test on whichever stub is present, so the module works on its own and
# alongside test_regressions, whose stub calls set_timeout callbacks at
# once (which would recurse through the status-bar spinner).
_STUBS = dict(
    load_settings=lambda name: _DictSettings(),
    load_resource=_raise_not_found,
    load_binary_resource=_raise_not_found,
    set_timeout=lambda callback, delay=0: None,
    set_timeout_async=lambda callback, delay=0: None,
    status_message=lambda message: None,
    error_message=lambda message: None,
    message_dialog=lambda message: None,
    active_window=lambda: None,
)

if "sublime" not in sys.modules:
    sys.modules["sublime"] = types.SimpleNamespace(**_STUBS)

import sublime  # noqa: E402

from liveserverplus_lib.connection_manager import ConnectionManager  # noqa: E402
from liveserverplus_lib.server import Server  # noqa: E402
from liveserverplus_lib.settings import ServerSettings  # noqa: E402

_MISSING = object()


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _worker_threads():
    return [t.name for t in threading.enumerate() if t.name.startswith("LSP-Worker")]


def _wait_until(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class _ServerTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {name: getattr(sublime, name, _MISSING) for name in _STUBS}
        for name, value in _STUBS.items():
            setattr(sublime, name, value)
        ServerSettings._global_ephemeral_port = None
        self.root = tempfile.mkdtemp()
        self.servers = []
        SETTINGS.clear()
        SETTINGS.update({
            "liveReload": True,  # no file watcher: nothing to tear down but sockets
            "openBrowser": False,
            "showOnStatusbar": False,
            "showInfoMessages": False,
            "wait": 0,  # broadcast at once instead of after a debounce timer
        })

    def tearDown(self):
        for server in self.servers:
            server.stop()
            server.join(3)
        for name, value in self._saved.items():
            if value is _MISSING:
                delattr(sublime, name)
            else:
                setattr(sublime, name, value)

    # -- helpers ----------------------------------------------------------

    def _write(self, rel_path, text):
        path = os.path.join(self.root, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _start(self, port):
        SETTINGS["port"] = port
        server = Server([self.root])
        self.servers.append(server)
        server.start()
        _wait_until(lambda: server.status.getCurrentStatus()[0] in ("running", "error"), 8)
        self.assertEqual(server.status.getCurrentStatus()[0], "running")
        return server

    def _request(self, port, raw):
        """Send one raw request and read until the server closes."""
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        sock.sendall(raw)
        data = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        finally:
            sock.close()
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        status = int(lines[0].split()[1])
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return status, headers, body

    def _get(self, port, path, accept_encoding=None):
        extra = "Accept-Encoding: %s\r\n" % accept_encoding if accept_encoding else ""
        return self._request(port, ("GET %s HTTP/1.1\r\nHost: x\r\n%s\r\n" % (path, extra)).encode())

    def _head(self, port, path):
        status, headers, _ = self._request(port, ("HEAD %s HTTP/1.1\r\nHost: x\r\n\r\n" % path).encode())
        return status, headers

    def _ws_connect(self, server):
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((
            "GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % key
        ).encode())
        self.assertIn(b" 101 ", sock.recv(4096))
        self.assertTrue(_wait_until(lambda: len(server.websocket.clients) == 1))
        return sock

    @staticmethod
    def _ws_recv(sock, timeout):
        """Return the next text frame, "<closed>" on EOF, "<timeout>" otherwise."""
        sock.settimeout(timeout)
        try:
            header = sock.recv(2)
            if not header:
                return "<closed>"
            return sock.recv(header[1] & 0x7F).decode()
        except socket.timeout:
            return "<timeout>"
        except OSError:
            return "<closed>"


class PortTests(_ServerTestCase):
    def test_changing_the_port_setting_takes_effect_on_the_next_start(self):
        """Every resolved port used to be cached on the ServerSettings class
        and handed to the next instance, so after the first start the port
        was frozen for the session and "Change Port..." restarted on the
        old one while announcing the new one.
        """
        first, second = _free_port(), _free_port()

        server = self._start(first)
        self.assertEqual(server.port, first)
        server.stop()
        server.join(3)

        server = self._start(second)
        self.assertEqual(server.port, second)

    def test_fallback_port_is_not_remembered_for_the_next_start(self):
        """When the configured port is busy the server moves to the next one.
        That choice stuck for the session too, so once the other program
        had gone the server never came back to the configured port.
        """
        busy = socket.socket()
        busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        taken = busy.getsockname()[1]
        try:
            server = self._start(taken)  # retries for 1.5s, then falls back
            self.assertNotEqual(server.port, taken)
            self.assertEqual(server.settings.port, taken, "the setting itself must stay put")
            server.stop()
            server.join(3)
        finally:
            busy.close()

        server = self._start(taken)
        self.assertEqual(server.port, taken)

    def test_a_random_port_is_kept_across_restarts(self):
        """"port": 0 picks a port once and keeps it, so a tab opened on it
        survives a restart. Only that random port is remembered."""
        SETTINGS["port"] = 0
        first = ServerSettings().port
        self.assertNotEqual(first, 0)
        self.assertEqual(ServerSettings().port, first)

        SETTINGS["port"] = 7777
        self.assertEqual(ServerSettings().port, 7777)


class ShutdownTests(_ServerTestCase):
    def test_stop_ends_the_server_thread(self):
        server = self._start(_free_port())
        server.stop()
        server.join(3)

        self.assertFalse(server.is_alive())

    def test_stop_closes_websocket_clients_so_a_tab_can_reconnect(self):
        """stop() cleared the client set but never closed the sockets. The
        worker thread serving each tab stayed blocked in recv, the browser
        never saw a close, and after a restart (every settings toggle does
        one) live reload was dead in that tab until a manual refresh. Each
        leaked socket also kept its slot in the ConnectionManager singleton.
        """
        server = self._start(_free_port())
        client = self._ws_connect(server)
        server.websocket.notifyClients(os.path.join(self.root, "index.html"))
        self.assertEqual(self._ws_recv(client, 3), "reload")

        server.stop()
        server.join(3)

        self.assertEqual(self._ws_recv(client, 3), "<closed>")
        self.assertTrue(_wait_until(lambda: not _worker_threads()), _worker_threads())
        active = ConnectionManager.getInstance().active_connections
        self.assertTrue(_wait_until(lambda: not active), active)
        client.close()

    def test_broadcast_leaves_the_reader_timeout_alone(self):
        """_broadcast set the socket timeout to None after sending, which is
        why the reader above could block for ever: the 30s timeout that
        would have let it notice the stop was gone after the first reload.
        """
        server = self._start(_free_port())
        client = self._ws_connect(server)
        conn = next(iter(server.websocket.clients))
        self.assertEqual(conn.gettimeout(), 30)

        server.websocket.notifyClients("index.html")
        self.assertEqual(self._ws_recv(client, 3), "reload")

        self.assertEqual(conn.gettimeout(), 30)
        client.close()

    def test_restart_on_the_same_port_serves_every_request(self):
        """ServerManager.stop() runs the shutdown on a background thread and
        the restart commands start the next server 100ms later, so the two
        overlap. Requests in that window must reach the new server, and the
        old accept loop must be gone rather than left to steal them.
        """
        self._write("index.html", "<html><body>hi</body></html>")
        port = _free_port()
        old = self._start(port)
        threading.Thread(target=old.stop, daemon=True).start()
        time.sleep(0.1)
        new = self._start(port)

        for _ in range(5):
            self.assertEqual(self._get(port, "/")[0], 200)
            time.sleep(0.05)

        old.join(3)
        self.assertFalse(old.is_alive())
        self.assertTrue(new.is_alive())


class HttpTests(_ServerTestCase):
    def test_head_resolves_paths_like_get(self):
        """HEAD joined the raw URL onto the folder with no containment check:
        encoded names 404ed, a symlink out of the root answered 200, and on
        Windows an absolute "C:/..." path answered for any file on disk.
        """
        self._write("sub/a b.html", "<p>x</p>")
        outside = tempfile.mkdtemp()
        with open(os.path.join(outside, "secret.txt"), "w") as handle:
            handle.write("s")
        try:
            os.symlink(outside, os.path.join(self.root, "link"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        server = self._start(_free_port())

        status, headers = self._head(server.port, "/sub/a%20b.html")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-length"], str(len("<p>x</p>")))

        self.assertEqual(self._head(server.port, "/link/secret.txt")[0], 404)
        self.assertEqual(self._get(server.port, "/link/secret.txt")[0], 404)

    def test_gzip_only_when_the_client_accepts_it(self):
        """Compressible responses were gzipped whatever the request said,
        so curl, wget and scripts got raw gzip bytes."""
        self._write("index.html", "<html><body>" + "hello " * 400 + "</body></html>")
        server = self._start(_free_port())

        status, headers, body = self._get(server.port, "/index.html")
        self.assertEqual(status, 200)
        self.assertNotIn("content-encoding", headers)
        self.assertTrue(body.startswith(b"<html><body>hello"), body[:40])
        self.assertEqual(headers.get("vary"), "Accept-Encoding")

        _, headers, body = self._get(server.port, "/index.html", accept_encoding="gzip, deflate")
        self.assertEqual(headers.get("content-encoding"), "gzip")
        self.assertTrue(gzip.decompress(body).startswith(b"<html><body>hello"))

    def test_responses_say_connection_close(self):
        """The worker closes the socket after one response. Announcing
        keep-alive invited browsers to reuse a connection that was gone."""
        self._write("index.html", "<html><body>hi</body></html>")
        server = self._start(_free_port())

        _, headers, _ = self._get(server.port, "/")
        self.assertEqual(headers.get("connection"), "close")
        self.assertNotIn("keep-alive", headers)


if __name__ == "__main__":
    unittest.main()
