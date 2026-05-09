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
    def test_validate_path_allows_double_dot_inside_filename(self):
        from liveserverplus_lib.path_utils import validate_and_secure_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            root.mkdir()
            file_path = root / "index..html"
            file_path.write_text("inside", encoding="utf-8")

            self.assertEqual(
                validate_and_secure_path(str(root), "index..html"),
                str(file_path.resolve()),
            )

    def test_validate_path_rejects_parent_directory_segment(self):
        from liveserverplus_lib.path_utils import validate_and_secure_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            root.mkdir()

            self.assertIsNone(validate_and_secure_path(str(root), "%2e%2e/secret.html"))

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


class BrowserLaunchTests(unittest.TestCase):
    def test_macos_browser_command_uses_open_a_to_foreground_browser(self):
        from liveserverplus_lib.utils import _build_macos_open_command

        command = _build_macos_open_command("Google Chrome", "http://127.0.0.1:5500/index.html")

        self.assertEqual(command, ["open", "-a", "Google Chrome", "http://127.0.0.1:5500/index.html"])

    def test_macos_browser_app_name_resolves_brave_alias(self):
        from liveserverplus_lib.utils import _macos_browser_app_name

        self.assertEqual(_macos_browser_app_name("brave"), "Brave Browser")

    def test_brave_has_browser_command_aliases(self):
        from liveserverplus_lib.constants import BROWSER_COMMANDS

        self.assertEqual(BROWSER_COMMANDS["brave"]["linux"], "brave-browser")
        self.assertEqual(BROWSER_COMMANDS["brave"]["windows"], "brave")

    def test_subprocess_error_log_includes_return_code_and_stderr(self):
        import subprocess

        from liveserverplus_lib.utils import _format_subprocess_error

        exc = subprocess.CalledProcessError(
            returncode=1,
            cmd=["osascript", "-e", "bad script"],
            stderr="Application isn't running",
            output="",
        )

        message = _format_subprocess_error(exc)

        self.assertIn("exit=1", message)
        self.assertIn("Application isn't running", message)


class SettingsCommandTests(unittest.TestCase):
    def test_menus_use_archive_safe_settings_command(self):
        for menu_name in ("Main.sublime-menu", "Context.sublime-menu", "Default.sublime-commands"):
            content = (REPO_ROOT / menu_name).read_text(encoding="utf-8")

            self.assertIn('"command": "live_server_settings"', content)
            self.assertNotIn('${packages}/LiveServerPlus/LiveServerPlus.sublime-settings', content)

    def test_logging_toggle_commands_are_available(self):
        commands = (REPO_ROOT / "Default.sublime-commands").read_text(encoding="utf-8")

        self.assertIn("Live Server Plus: Enable Debug Logging", commands)
        self.assertIn("Live Server Plus: Disable Debug Logging", commands)


class FileWatcherSetupTests(unittest.TestCase):
    def test_setup_observers_does_not_schedule_root_twice(self):
        from liveserverplus_lib.file_watcher import FileWatcher

        class FakeObserver:
            def __init__(self):
                self.paths = []

            def schedule(self, event_handler, path, recursive=False):
                self.paths.append(path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            root.mkdir()
            (root / "index.html").write_text("<h1>test</h1>", encoding="utf-8")

            watcher = FileWatcher.__new__(FileWatcher)
            watcher.folders = [str(root)]
            watcher.settings = types.SimpleNamespace(
                ignorePatterns=[],
                ignoreDirs=[],
                allowedFileTypes=[".html"],
            )
            watcher.event_handler = object()
            watcher._ignore_patterns = []
            watcher._max_directories = 50
            watcher._dir_count = 0
            watcher._using_polling = False

            observer = FakeObserver()
            watcher._setup_observers(observer)

            self.assertEqual(observer.paths.count(str(root)), 1)


class WebSocketTemplateTests(unittest.TestCase):
    def test_reload_preserves_scroll_position(self):
        template = (REPO_ROOT / "liveserverplus_lib" / "templates" / "websocket.html").read_text(encoding="utf-8")

        self.assertIn("function saveScrollPosition()", template)
        self.assertIn("function restoreScrollPosition()", template)
        self.assertIn("saveScrollPosition();\n                        window.location.reload();", template)
        self.assertIn("restoreScrollPosition();", template)


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
