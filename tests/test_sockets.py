"""Tests that boot the real Server under the stub and talk to it over sockets."""
import gzip
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sublime_stub import REPO_ROOT, FakeSettings, fake_sublime  # noqa: E402,F401  (installs the stub)

from liveserverplus_lib.constants import STREAMING_THRESHOLD  # noqa: E402
from liveserverplus_lib.http_utils import HTTPResponse  # noqa: E402
from liveserverplus_lib.request_handler import (  # noqa: E402
    MAX_REQUEST_HEAD,
    _HeadOnlyConnection,
)
from liveserverplus_lib import server as server_module  # noqa: E402
from liveserverplus_lib.server import Server  # noqa: E402
from liveserverplus_lib.settings import ServerSettings  # noqa: E402
from liveserverplus_lib.websocket import WebSocketHandler  # noqa: E402

# liveReload mode skips the Watchdog observer; port 0 picks a free port;
# wait 0 makes a file change broadcast at once instead of after a debounce.
SERVER_SETTINGS = {
    "liveReload": True,
    "port": 0,
    "wait": 0,
    "showOnStatusbar": False,
    "showInfoMessages": False,
    "openBrowser": False,
}

WS_HANDSHAKE = (
    b"GET /ws HTTP/1.1\r\n"
    b"Host: 127.0.0.1\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n"
    b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
    b"Sec-WebSocket-Version: 13\r\n\r\n"
)
CLOSE_GOING_AWAY = b"\x88\x02" + struct.pack(">H", 1001)

_settings_patch = mock.patch.dict(FakeSettings.values, SERVER_SETTINGS)


def setUpModule():
    _settings_patch.start()


def tearDownModule():
    _settings_patch.stop()


def start_server(folder):
    # A fresh port per server, so one test's server never shares a port
    # (via SO_REUSEPORT) with another's.
    ServerSettings._global_ephemeral_port = None
    server = Server([str(folder)])
    server.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status, port = server.status.getCurrentStatus()
        if status == "running" and port:
            return server, port
        time.sleep(0.01)
    server.stop()
    raise AssertionError("server did not start")


def read_until_closed(sock):
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return data
        data += chunk


def parse_response(data):
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return lines[0], headers, body


def request(port, method, target, extra=b""):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            method.encode() + b" " + target.encode("latin-1")
            + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n" + extra + b"\r\n"
        )
        return parse_response(read_until_closed(sock))


def decoded_body(headers, body):
    if headers.get("content-encoding") == "gzip":
        return gzip.decompress(body)
    return body


def open_websocket(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(WS_HANDSHAKE)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return sock, data


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class WebSocketShutdownTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.threads_before = set(threading.enumerate())
        self.server, self.port = start_server(self._tmp.name)
        self.addCleanup(self.server.stop)

    def _new_workers(self):
        return [
            thread for thread in threading.enumerate()
            if thread not in self.threads_before
            and thread.name.startswith("LSP-Worker")
            and thread.is_alive()
        ]

    def test_stop_sends_close_frame_and_closes_the_socket(self):
        """Clients used to stay connected to a dead server and never reconnect."""
        ws, handshake = open_websocket(self.port)
        self.addCleanup(ws.close)
        self.assertTrue(handshake.startswith(b"HTTP/1.1 101"))
        self.assertTrue(wait_for(lambda: len(self.server.websocket.clients) == 1))

        self.server.stop()

        ws.settimeout(1.0)
        try:
            received = read_until_closed(ws)
        except socket.timeout:
            self.fail("WebSocket client was left open after stop()")
        self.assertEqual(received, CLOSE_GOING_AWAY)

    def test_stop_ends_the_worker_threads_of_websocket_clients(self):
        ws, _ = open_websocket(self.port)
        self.addCleanup(ws.close)
        self.assertTrue(wait_for(lambda: len(self.server.websocket.clients) == 1))
        self.assertTrue(self._new_workers())

        self.server.stop()

        self.assertTrue(
            wait_for(lambda: not self._new_workers()),
            "LSP-Worker threads still alive: %r" % self._new_workers(),
        )
        self.assertEqual(self.server.websocket.clients, set())
        self.assertEqual(self.server.connection_manager.active_connections, set())

    def test_no_reload_is_sent_once_stop_has_begun(self):
        """A reload sent while the port closes strands the tab on an error page."""
        ws, _ = open_websocket(self.port)
        self.addCleanup(ws.close)
        self.assertTrue(wait_for(lambda: len(self.server.websocket.clients) == 1))
        changed = str(Path(self._tmp.name, "index.html"))

        def file_saved_while_stopping():
            # Runs where stop() waits for the watcher: the listening socket is
            # already closed and the clients are not yet.
            self.server.onFileChange(changed)
            self.server.websocket.notifyClients(changed)
            self.server.broadcast_message("reload")

        self.server._shutdownFileWatcher = file_saved_while_stopping
        self.server.stop()

        ws.settimeout(1.0)
        self.assertEqual(read_until_closed(ws), CLOSE_GOING_AWAY)

    def test_oversized_incoming_frame_closes_the_connection(self):
        ws, _ = open_websocket(self.port)
        self.addCleanup(ws.close)
        self.assertTrue(wait_for(lambda: len(self.server.websocket.clients) == 1))

        # Masked text frame claiming a 1 GiB payload.
        ws.sendall(b"\x81\xff" + struct.pack(">Q", 1 << 30) + b"\x00\x00\x00\x00")

        ws.settimeout(1.0)
        try:
            self.assertEqual(ws.recv(1), b"")
        except ConnectionResetError:
            pass
        self.assertTrue(wait_for(lambda: not self.server.websocket.clients))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        root = base / "site"
        root.mkdir()
        (base / "outside-the-root").mkdir()
        (base / "outside-the-root" / "secret.txt").write_text("secret", encoding="utf-8")
        (root / "index.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
        (root / "index..html").write_text("<html><body>Double dot</body></html>", encoding="utf-8")
        cls.big_size = STREAMING_THRESHOLD + 10
        (root / "big.js").write_bytes(b"x" * cls.big_size)
        cls.server, cls.port = start_server(root)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls._tmp.cleanup()

    def test_responses_say_connection_close(self):
        """The server closes after one request, so it must not offer keep-alive."""
        status, headers, _ = request(self.port, "GET", "/index.html")

        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(headers.get("connection"), "close")
        self.assertNotIn("keep-alive", headers)

        built = HTTPResponse(404).build()
        self.assertIn(b"\r\nConnection: close\r\n", built)
        self.assertNotIn(b"Keep-Alive", built)

    def test_websocket_upgrade_response_is_unaffected(self):
        ws, handshake = open_websocket(self.port)
        ws.close()

        status, headers, _ = parse_response(handshake)
        self.assertEqual(status, "HTTP/1.1 101 Switching Protocols")
        self.assertEqual(headers.get("connection"), "Upgrade")
        self.assertEqual(headers.get("upgrade"), "websocket")

    def test_double_dot_inside_a_file_name_is_served(self):
        status, headers, body = request(self.port, "GET", "/index..html")

        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b"Double dot", decoded_body(headers, body))

    def test_parent_segment_cannot_reach_outside_the_root(self):
        """A ".." segment, raw or percent-encoded, never lists anything outside."""
        status, headers, body = request(self.port, "GET", "/../")
        self.assertTrue(status.startswith("HTTP/1.1 4"), status)
        self.assertFalse(
            b"outside-the-root" in decoded_body(headers, body),
            "/../ listed the directory above the root",
        )

        for target in ("/../outside-the-root/", "/%2e%2e/outside-the-root/"):
            status, headers, body = request(self.port, "GET", target)
            self.assertTrue(status.startswith("HTTP/1.1 4"), (target, status))
            self.assertFalse(
                b"secret.txt" in decoded_body(headers, body),
                "%s listed a directory outside the root" % target,
            )

    def test_nul_in_path_is_rejected(self):
        status, _, _ = request(self.port, "GET", "/index.html\x00")

        self.assertEqual(status, "HTTP/1.1 400 Bad Request")

    def _assert_head_matches_get(self, target):
        get_status, get_headers, get_body = request(self.port, "GET", target)
        head_status, head_headers, head_body = request(self.port, "HEAD", target)

        self.assertEqual(head_status, get_status)
        for name in ("content-type", "content-length", "content-encoding"):
            self.assertEqual(head_headers.get(name), get_headers.get(name), name)
        self.assertEqual(int(get_headers["content-length"]), len(get_body))
        self.assertEqual(head_body, b"")
        return get_status, get_headers

    def test_head_matches_get_for_html_with_injected_script(self):
        status, headers = self._assert_head_matches_get("/index.html")

        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertTrue(headers["content-type"].startswith("text/html"))

    def test_head_matches_get_for_a_missing_file(self):
        status, headers = self._assert_head_matches_get("/missing.html")

        self.assertEqual(status, "HTTP/1.1 404 Not Found")
        self.assertTrue(headers["content-type"].startswith("text/html"))

    def test_head_of_a_streamed_file_sends_no_body(self):
        status, headers = self._assert_head_matches_get("/big.js")

        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(int(headers["content-length"]), self.big_size)

    def test_oversized_request_body_is_refused(self):
        status, _, _ = request(
            self.port, "POST", "/index.html", b"Content-Length: 1000000000\r\n"
        )

        self.assertEqual(status, "HTTP/1.1 413 Request Entity Too Large")

    def test_oversized_request_head_is_refused(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            # One byte over the limit and never terminated by a blank line.
            sock.sendall(b"GET /" + b"a" * (MAX_REQUEST_HEAD - 4))
            status, _, _ = parse_response(read_until_closed(sock))

        self.assertEqual(status, "HTTP/1.1 431 Request Header Fields Too Large")


class WebSocketHandlerTests(unittest.TestCase):
    def test_no_debounced_reload_is_scheduled_after_stop_notifying(self):
        handler = WebSocketHandler()
        handler.settings = mock.Mock(fullReload=True, waitTimeMs=50)

        handler.stopNotifying()
        handler.notifyClients("/site/index.html")

        self.assertIsNone(handler._pending_timer)


class _InsteadOfSleep:
    """Stands in for server.py's ``time`` module: sleep() calls ``action``."""

    def __init__(self, action):
        self._action = action

    def sleep(self, seconds):
        self._action()

    def __getattr__(self, name):
        return getattr(time, name)


class ServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ServerSettings._global_ephemeral_port = None
        self.threads_before = set(threading.enumerate())

    def _server(self, **settings):
        with mock.patch.dict(FakeSettings.values, settings):
            server = Server([self._tmp.name])
        self.addCleanup(server.stop)
        statuses = []
        update = server.status.update

        def record(status, *args, **kwargs):
            statuses.append(status)
            update(status, *args, **kwargs)

        server.status.update = record
        return server, statuses

    def _new_threads(self):
        return [t for t in threading.enumerate() if t not in self.threads_before and t.is_alive()]

    def _assert_stopped_cleanly(self, server, statuses, port):
        server.join(5)
        self.assertFalse(server.is_alive())
        self.assertEqual(statuses[-1], "stopped", statuses)
        self.assertNotIn("running", statuses)
        self.assertNotIn("error", statuses)
        self.assertIsNone(server.sock)
        self.assertTrue(wait_for(lambda: not self._new_threads(), 5), self._new_threads())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()

    def test_stop_before_the_socket_is_bound(self):
        """The port used to stay bound, listening, with nobody accepting."""
        server, statuses = self._server(liveReload=False)
        setup_socket = server._setupSocket

        def stop_then_bind():
            server.stop()
            setup_socket()

        server._setupSocket = stop_then_bind
        server.start()

        self._assert_stopped_cleanly(server, statuses, server.settings.port)

    def test_stop_before_the_file_watcher_starts(self):
        """The watcher used to start anyway and outlive the server."""
        server, statuses = self._server(liveReload=False)
        setup_watcher = server._setupFileWatcher

        def stop_then_watch():
            server.stop()
            setup_watcher()

        server._setupFileWatcher = stop_then_watch
        server.start()

        self._assert_stopped_cleanly(server, statuses, server.settings.port)

    def test_stop_while_waiting_for_a_busy_port(self):
        """The retry used to bind a cleared socket and report an error after 'stopped'."""
        blocker = socket.socket()
        self.addCleanup(blocker.close)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy_port = blocker.getsockname()[1]
        server, statuses = self._server(port=busy_port)

        # The first back-off sleep before retrying the busy port stops the server.
        with mock.patch.object(server_module, "time", _InsteadOfSleep(server.stop)):
            server.start()
            server.join(5)

        self.assertEqual(statuses, ["starting", "stopping", "stopped"])
        self.assertIsNone(server.sock)
        self.assertTrue(wait_for(lambda: not self._new_threads(), 5), self._new_threads())

    def test_fallback_port_is_not_reused_for_a_random_port(self):
        """Only a random port (port 0) is kept across restarts, never a fallback."""
        blocker = socket.socket()
        self.addCleanup(blocker.close)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy_port = blocker.getsockname()[1]
        server, _ = self._server(port=busy_port)

        with mock.patch.object(server_module, "time", _InsteadOfSleep(lambda: None)):
            server.start()
            self.assertTrue(wait_for(lambda: server.status.getCurrentStatus()[0] == "running"))

        fallback_port = server.status.getCurrentStatus()[1]
        self.assertNotEqual(fallback_port, busy_port)
        self.assertEqual(server.settings.port, fallback_port)
        self.assertIsNone(ServerSettings._global_ephemeral_port)
        self.assertNotEqual(ServerSettings().port, fallback_port)


class HeadOnlyConnectionTests(unittest.TestCase):
    class _Socket:
        def __init__(self):
            self.data = b""

        def sendall(self, data):
            self.data += data

    def test_forwards_only_the_header_block(self):
        real = self._Socket()
        conn = _HeadOnlyConnection(real)

        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r")
        self.assertEqual(real.data, b"")
        conn.sendall(b"\nbody")
        self.assertEqual(conn.send(b"more"), 4)
        conn.sendall(b"chunks")

        self.assertEqual(real.data, b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n")


class InjectedScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = REPO_ROOT / "liveserverplus_lib" / "templates" / "websocket.html"
        cls.template = path.read_text(encoding="utf-8")

    def test_css_cache_buster_regex_is_not_double_escaped(self):
        """With \\\\? and \\\\d the old parameter was never stripped."""
        self.assertTrue(r"/(&|\?)_cacheOverride=\d+/" in self.template)
        self.assertFalse(r"/(&|\\?)_cacheOverride=\\d+/" in self.template)

    def test_reconnect_does_not_give_up(self):
        self.assertFalse("maxReconnectAttempts" in self.template)
        self.assertTrue("maxReconnectDelay" in self.template)


if __name__ == "__main__":
    unittest.main()
