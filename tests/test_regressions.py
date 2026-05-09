import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_PATH = REPO_ROOT / "liveserverplus_lib" / "vendor"
if str(VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(VENDOR_PATH))


class _FakeSettings:
    def get(self, key, default=None):
        return default

    def add_on_change(self, key, callback):
        pass


fake_sublime = types.SimpleNamespace(
    load_settings=lambda name: _FakeSettings(),
    set_timeout=lambda callback, delay=0: callback(),
    set_timeout_async=lambda callback, delay=0: callback(),
    status_message=lambda message: None,
    error_message=lambda message: None,
    message_dialog=lambda message: None,
)
sys.modules.setdefault("sublime", fake_sublime)


class InjectionTests(unittest.TestCase):
    def test_inject_before_tag_preserves_matched_tag(self):
        from liveserverplus_lib.text_utils import inject_before_tag

        html = "<html><head></head><body>Hello</body></html>"

        self.assertEqual(
            inject_before_tag(html, "</body>", "<script></script>"),
            "<html><head></head><body>Hello<script></script></body></html>",
        )


class PathContainmentTests(unittest.TestCase):
    def test_relative_to_root_rejects_sibling_prefix_matches(self):
        from liveserverplus_lib.path_utils import relative_to_root

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            sibling = Path(tmp, "site2")
            root.mkdir()
            sibling.mkdir()
            sibling_file = sibling / "index.html"
            sibling_file.write_text("outside", encoding="utf-8")

            self.assertIsNone(relative_to_root(str(sibling_file), [str(root)]))

    def test_relative_to_root_returns_relative_path_for_contained_file(self):
        from liveserverplus_lib.path_utils import relative_to_root

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            nested = root / "sub"
            nested.mkdir(parents=True)
            file_path = nested / "index.html"
            file_path.write_text("inside", encoding="utf-8")

            self.assertEqual(
                relative_to_root(str(file_path), [str(root)]),
                os.path.join("sub", "index.html"),
            )


class FileServerPathTests(unittest.TestCase):
    def test_encoded_parent_directory_does_not_serve_directory_listing(self):
        from liveserverplus_lib.file_server import FileServer

        settings = types.SimpleNamespace(
            liveReload=False,
            corsEnabled=False,
            renderMarkdownPreview=True,
            allowedFileTypesSet={".html"},
            allowedFileTypes=[".html"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            outside = Path(tmp, "outside")
            root.mkdir()
            outside.mkdir()

            file_server = FileServer(settings)
            directory_calls = []
            file_server._serveDirectory = lambda *args: directory_calls.append(args) or True

            served = file_server.serveFile(None, "/%2e%2e/outside/", [str(root)])

            self.assertFalse(served)
            self.assertEqual(directory_calls, [])

    def test_root_without_index_still_serves_directory_listing(self):
        from liveserverplus_lib.file_server import FileServer

        settings = types.SimpleNamespace(
            liveReload=False,
            corsEnabled=False,
            renderMarkdownPreview=True,
            allowedFileTypesSet={".html"},
            allowedFileTypes=[".html"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            root.mkdir()

            file_server = FileServer(settings)
            directory_calls = []
            file_server._serveDirectory = lambda *args: directory_calls.append(args) or True

            served = file_server.serveFile(None, "/", [str(root)])

            self.assertTrue(served)
            self.assertEqual(len(directory_calls), 1)
            self.assertEqual(directory_calls[0][1], str(root))


class ServerBindTests(unittest.TestCase):
    def test_localhost_bind_helper_only_exposes_explicit_wildcard(self):
        from liveserverplus_lib.server import _bind_host_for_config

        self.assertEqual(_bind_host_for_config("127.0.0.1"), "127.0.0.1")
        self.assertEqual(_bind_host_for_config("localhost"), "127.0.0.1")
        self.assertEqual(_bind_host_for_config("0.0.0.0"), "0.0.0.0")


class WatchdogEventHandlerTests(unittest.TestCase):
    def test_on_created_triggers_same_callback_path_as_modified(self):
        from liveserverplus_lib.file_watcher import WatchdogEventHandler

        calls = []
        watcher = types.SimpleNamespace(
            _stop_event=types.SimpleNamespace(is_set=lambda: False),
            settings=types.SimpleNamespace(allowedFileTypes=[".html"]),
            _matches_ignore=lambda path: False,
            debounced_callback=lambda path: calls.append(path),
        )
        handler = WatchdogEventHandler(watcher)
        event = types.SimpleNamespace(is_directory=False, src_path="/tmp/new.html")

        handler.on_created(event)

        self.assertEqual(calls, ["/tmp/new.html"])


if __name__ == "__main__":
    unittest.main()
