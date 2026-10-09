"""File serving: directory indexes, the dotfile policy (ignoreFiles is
watch-only), Windows path containment, uncompressed responses, streaming,
and the cost of 404 suggestions."""
import itertools
import ntpath
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sublime_stub import fake_sublime  # noqa: E402,F401  (installs the stub)

from liveserverplus_lib import file_server as file_server_module  # noqa: E402
from liveserverplus_lib import path_utils  # noqa: E402
from liveserverplus_lib import text_utils  # noqa: E402
from liveserverplus_lib.error_pages import ErrorPages  # noqa: E402
from liveserverplus_lib.file_server import FileServer  # noqa: E402
from liveserverplus_lib.markdown_renderer import ASSET_URL_PREFIX  # noqa: E402
from liveserverplus_lib.path_utils import (  # noqa: E402
    has_hidden_segment, is_refused_path, relative_to_root, validate_and_secure_path)
from liveserverplus_lib.settings import DEFAULT_ALLOWED_FILE_TYPES, DEFAULT_SETTINGS  # noqa: E402

RELOAD_MARKER = b"<script>/*live-reload*/</script>"

WINDOWS_ROOT = r"C:\Users\me\site"
# Request paths that Windows would join into a UNC share or another drive.
# Opening a UNC path makes an SMB connection that leaks the NTLM hash.
WINDOWS_PAYLOADS = (
    r"/%5C/%5Cattacker%5Cshare%5Cx",
    r"/%5C%2F%5Cattacker%5Cshare",
    r"/%5C%5C%5Cattacker%5Cshare",
    r"/\/\attacker\share\x",
    r"/\\attacker\share\x",
    r"/%255C/%255Cattacker%255Cshare",
    r"/%5C%5C%3F%5CUNC%5Cattacker%5Cshare%5Cx",
    r"/%2F%2Fattacker%2Fshare",
    r"/C:/Windows/win.ini",
    r"/C:%5CWindows%5Cwin.ini",
    r"/D:secret.txt",
)


def make_settings(**overrides):
    values = dict(
        liveReload=False,
        corsEnabled=False,
        renderMarkdownPreview=True,
        logging=False,
        maxFileSize=100,
        enableCompression=True,  # hardcoded in ServerSettings; now unused
        allowedFileTypes=DEFAULT_ALLOWED_FILE_TYPES,
        allowedFileTypesSet=set(DEFAULT_ALLOWED_FILE_TYPES),
        ignorePatterns=list(DEFAULT_SETTINGS["ignoreFiles"]),
        ignoreDirs=list(DEFAULT_SETTINGS["ignoreDirs"]),
    )
    values.update(overrides)
    return types.SimpleNamespace(**values)


class Connection:
    def __init__(self):
        self.data = b""

    def sendall(self, data):
        self.data += data

    def response(self):
        head, _, body = self.data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return lines[0], headers, body


class ServingTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "site"
        self.root.mkdir()
        self.settings = make_settings()
        self.server = FileServer(self.settings)
        self.server.websocket_injector = lambda html: html.replace(
            b"</body>", RELOAD_MARKER + b"</body>")

    def write(self, rel, content="x"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def get(self, url, folders=None):
        conn = Connection()
        served = self.server.serveFile(conn, url, folders or [str(self.root)])
        return served, conn


class DirectoryIndexTests(ServingTestCase):
    def test_nested_index_html_is_served_with_reload_script(self):
        self.write("docs/index.html", "<html><body>DOCS</body></html>")
        served, conn = self.get("/docs/")
        status, headers, body = conn.response()
        self.assertTrue(served)
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b"DOCS", body)
        self.assertIn(RELOAD_MARKER, body)
        self.assertTrue(headers["content-type"].startswith("text/html"))

    def test_index_htm_is_used_when_there_is_no_index_html(self):
        self.write("old/index.htm", "<html><body>OLD</body></html>")
        served, conn = self.get("/old/")
        body = conn.response()[2]
        self.assertTrue(served)
        self.assertIn(b"OLD", body)
        self.assertIn(RELOAD_MARKER, body)

    def test_directory_without_index_gets_a_listing(self):
        self.write("assets/site.css", "a{}")
        served, conn = self.get("/assets/")
        status, _, body = conn.response()
        self.assertTrue(served)
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b"site.css", body)
        self.assertIn(b'href="/"', body)  # parent link, with its trailing slash

    def test_directory_without_trailing_slash_redirects(self):
        self.write("docs/index.html", "<html><body>DOCS</body></html>")
        self.write("my docs/index.html", "<html></html>")
        for url, location in (("/docs", "/docs/"), ("/my%20docs", "/my%20docs/")):
            served, conn = self.get(url)
            status, headers, body = conn.response()
            self.assertTrue(served)
            self.assertEqual(status, "HTTP/1.1 301 Moved Permanently")
            self.assertEqual(headers["location"], location)
            self.assertEqual(body, b"")

    def test_redirect_location_can_never_leave_the_server(self):
        """A Location starting with // would send the browser to another host."""
        (self.root / "evil.com").mkdir()
        served, conn = self.get("/%5Cevil.com")
        self.assertTrue(served)
        self.assertEqual(conn.response()[1]["location"], "/evil.com/")
        # Two leading separators are refused before any redirect is built.
        for url in ("/%2F%2Fevil.com", "/%5C%5Cevil.com", "/%2F%5Cevil.com"):
            served, conn = self.get(url)
            self.assertFalse(served, url)
            self.assertEqual(conn.data, b"", url)

    def test_redirect_keeps_the_query_string(self):
        (self.root / "docs").mkdir()
        conn = Connection()
        served = self.server.serveFile(conn, "/docs", [str(self.root)], query_string="x=1&y=%20z")
        self.assertTrue(served)
        self.assertEqual(conn.response()[1]["location"], "/docs/?x=1&y=%20z")

    def test_query_string_cannot_inject_a_header(self):
        (self.root / "docs").mkdir()
        conn = Connection()
        served = self.server.serveFile(
            conn, "/docs", [str(self.root)], query_string="a=1\r\nSet-Cookie: s=1\x00\x7f\xe9")
        self.assertTrue(served)
        self.assertNotIn(b"\r\nSet-Cookie", conn.data)
        self.assertEqual(conn.response()[1]["location"],
                         "/docs/?a=1%0D%0ASet-Cookie:%20s=1%00%7F%C3%A9")

    def test_root_prefers_an_index_from_any_folder_over_a_listing(self):
        second = self.tmp / "second"
        second.mkdir()
        (second / "index.html").write_text("<html><body>SECOND</body></html>", encoding="utf-8")
        served, conn = self.get("/", [str(self.root), str(second)])
        self.assertTrue(served)
        self.assertIn(b"SECOND", conn.response()[2])


class ServingPolicyTests(ServingTestCase):
    def assertNotServed(self, url):
        served, conn = self.get(url)
        self.assertFalse(served, url)
        self.assertEqual(conn.data, b"", url)

    def test_dotfiles_are_not_served(self):
        self.write(".env", "SECRET=1")
        self.write("config/.npmrc", "token")
        self.assertNotServed("/.env")
        self.assertNotServed("/%2Eenv")
        self.assertNotServed("/config/.npmrc")

    def test_git_directory_and_its_contents_are_not_served(self):
        self.write(".git/config", "[core]")
        self.write(".git/HEAD", "ref: refs/heads/main")
        for url in ("/.git", "/.git/", "/.git/config", "/.git/HEAD"):
            self.assertNotServed(url)

    def assertServed(self, url, expected):
        served, conn = self.get(url)
        status, _, body = conn.response()
        self.assertTrue(served, url)
        self.assertEqual(status, "HTTP/1.1 200 OK", url)
        self.assertIn(expected, body, url)

    def test_ignore_patterns_do_not_affect_serving(self):
        """ignoreFiles is watch-only: pages may load scripts from node_modules."""
        self.write("node_modules/pkg/dist/x.js", "NODE_MODULE")
        self.write("src/__pycache__/m.pyc", b"\0PYC")
        self.assertServed("/node_modules/pkg/dist/x.js", b"NODE_MODULE")
        self.assertServed("/node_modules/", b">pkg<")
        self.assertServed("/src/__pycache__/m.pyc", b"\0PYC")

    def test_custom_ignore_pattern_does_not_refuse_a_file(self):
        self.write("drafts/post.html", "<html><body>DRAFT</body></html>")
        self.settings.ignorePatterns = ["drafts", "*.html"]
        self.assertServed("/drafts/post.html", b"DRAFT")
        self.assertServed("/drafts/", b">post.html<")

    def test_symlink_into_a_dot_directory_is_not_served(self):
        self.write(".secret/key.txt", "k")
        try:
            os.symlink(str(self.root / ".secret"), str(self.root / "public"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertNotServed("/public/key.txt")

    def test_folder_inside_an_ignored_directory_is_still_served(self):
        """Opening node_modules/<pkg>/examples as the project must work."""
        demo = self.tmp / "node_modules" / "pkg" / "examples"
        (demo / "node_modules" / "dep").mkdir(parents=True)
        (demo / "index.html").write_text("<html><body>DEMO</body></html>", encoding="utf-8")
        (demo / "node_modules" / "dep" / "x.js").write_text("DEP", encoding="utf-8")
        served, conn = self.get("/", [str(demo)])
        self.assertTrue(served)
        self.assertIn(b"DEMO", conn.response()[2])
        served, conn = self.get("/node_modules/dep/x.js", [str(demo)])
        self.assertTrue(served)
        self.assertEqual(conn.response()[2], b"DEP")

    def test_listing_omits_hidden_entries_only(self):
        for rel in (".env", ".git/config", "node_modules/a.js", "__pycache__/m.pyc",
                    "src/app.js", "readme.txt"):
            self.write(rel)
        served, conn = self.get("/")
        body = conn.response()[2]
        self.assertTrue(served)
        for name in (b"src", b"readme.txt", b"node_modules", b"__pycache__"):
            self.assertIn(b">" + name + b"<", body)
        for name in (b".env", b".git"):
            self.assertNotIn(b">" + name + b"<", body)

    def test_unknown_types_are_served_inline(self):
        self.write("notes.xyz", "plain")
        self.write("tool.py", "print(1)")
        for url, mime in (("/notes.xyz", "application/octet-stream"), ("/tool.py", "text/x-python")):
            served, conn = self.get(url)
            status, headers, body = conn.response()
            self.assertTrue(served)
            self.assertEqual(status, "HTTP/1.1 200 OK")
            self.assertEqual(headers["content-type"], mime)
            self.assertNotIn("content-disposition", headers)
            self.assertIn(body, (b"plain", b"print(1)"))

    def test_vendored_assets_are_still_served(self):
        served, conn = self.get(ASSET_URL_PREFIX + "/katex/katex.min.js")
        status, headers, body = conn.response()
        self.assertTrue(served)
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(headers["content-type"], "application/javascript")
        self.assertTrue(body)

    def test_404_page_never_lists_a_directory(self):
        self.write(".git/config", "[core]")
        page = ErrorPages.get_404_page("/.git/", [str(self.root)], self.settings)
        self.assertIn("Page Not Found", page)
        self.assertNotIn("config", page)


class UncompressedResponseTests(ServingTestCase):
    def test_javascript_is_sent_uncompressed(self):
        source = b"var x = 1;\n" * 5000
        self.write("app.js", source)
        served, conn = self.get("/app.js")
        _, headers, body = conn.response()
        self.assertTrue(served)
        self.assertNotIn("content-encoding", headers)
        self.assertEqual(body, source)
        self.assertEqual(headers["content-length"], str(len(source)))


class StreamingTests(ServingTestCase):
    def test_large_file_is_streamed_in_full(self):
        payload = os.urandom(file_server_module.STREAMING_THRESHOLD + 512 * 1024)
        self.write("video.mp4", payload)
        served, conn = self.get("/video.mp4")
        status, headers, body = conn.response()
        self.assertTrue(served)
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(headers["content-length"], str(len(payload)))
        self.assertEqual(body, payload)

    def test_read_error_mid_stream_does_not_append_a_404_page(self):
        """Returning False after the headers went out made the handler write a
        404 page into the middle of the body."""
        self.write("video.mp4", b"\0" * (file_server_module.STREAMING_THRESHOLD + 1))

        def failing_reader(path):
            yield b"partial"
            raise OSError("disk went away")

        with mock.patch.object(file_server_module, "createFileReader", failing_reader):
            served, conn = self.get("/video.mp4")
        self.assertTrue(served)
        self.assertTrue(conn.data.endswith(b"\r\n\r\npartial"))


class NotFoundSuggestionTests(ServingTestCase):
    def test_typo_still_gets_a_suggestion(self):
        self.write("index.html", "<html></html>")
        page = ErrorPages.get_404_page("/indx.html", [str(self.root)], self.settings)
        self.assertIn("Did you mean", page)
        self.assertIn('href="/index.html"', page)

    def test_ignored_and_hidden_directories_are_never_walked(self):
        self.write("src/index.html")
        for rel in ("node_modules/pkg/index.html", ".git/index.html",
                    ".sass-cache/index.html", "build/index.html"):
            self.write(rel)
        self.settings.ignorePatterns = list(DEFAULT_SETTINGS["ignoreFiles"]) + ["build"]
        visited = []
        real_walk = os.walk

        def recording_walk(top, *args, **kwargs):
            for root, dirs, files in real_walk(top, *args, **kwargs):
                visited.append(root)
                yield root, dirs, files

        with mock.patch("os.walk", recording_walk):
            page = ErrorPages.get_404_page("/index.htm", [str(self.root)], self.settings)

        self.assertIn('href="/src/index.html"', page)
        for name in ("node_modules", ".git", ".sass-cache", "build"):
            self.assertFalse([root for root in visited if name in root], name)
            self.assertNotIn(name + "/index.html", page)

    def test_project_inside_an_ignored_directory_still_gets_suggestions(self):
        demo = self.tmp / "node_modules" / "pkg" / "examples"
        (demo / "node_modules" / "dep").mkdir(parents=True)
        (demo / "index.html").write_text("", encoding="utf-8")
        (demo / "node_modules" / "dep" / "index.html").write_text("", encoding="utf-8")
        page = ErrorPages.get_404_page("/indx.html", [str(demo)], self.settings)
        self.assertIn('href="/index.html"', page)
        self.assertNotIn("node_modules/dep", page)

    def test_browser_probes_skip_the_suggestion_walk(self):
        self.write("favicon.png")
        self.write("robots.html")
        with mock.patch("liveserverplus_lib.error_pages.find_similar_files",
                        return_value=[("favicon.png", 0.9)]) as finder:
            for url in ("/favicon.ico", "/apple-touch-icon.png",
                        "/apple-touch-icon-precomposed.png", "/robots.txt",
                        "/sitemap.xml", "/.well-known/appspecific/com.chrome.devtools.json"):
                page = ErrorPages.get_404_page(url, [str(self.root)], self.settings)
                self.assertNotIn("Did you mean", page, url)
            finder.assert_not_called()

            ErrorPages.get_404_page("/favicon.icon", [str(self.root)], self.settings)
            finder.assert_called_once()

    def test_walk_stops_after_max_files(self):
        for i in range(50):
            self.write("f%02d.html" % i)
        with mock.patch.object(text_utils, "calculate_similarity", return_value=1.0) as compare:
            text_utils.find_similar_files("/f.html", [str(self.root)], max_files=10)
        self.assertEqual(compare.call_count, 10)

    def test_walk_stops_at_the_time_limit(self):
        for i in range(50):
            self.write("f%02d.html" % i)
        clock = itertools.chain([0.0, 0.05], itertools.repeat(0.5))
        fake_time = types.SimpleNamespace(monotonic=lambda: next(clock))
        with mock.patch.object(text_utils, "time", fake_time), \
                mock.patch.object(text_utils, "calculate_similarity", return_value=1.0) as compare:
            text_utils.find_similar_files("/f.html", [str(self.root)], time_limit=0.1)
        self.assertEqual(compare.call_count, 1)

    def count_entries_visited(self, **kwargs):
        """Run the walk over 50 ignored .jpg files and count entries checked."""
        for i in range(50):
            self.write("photos/img%02d.jpg" % i)
        real_matches = text_utils.matches_ignore
        with mock.patch.object(text_utils, "matches_ignore", side_effect=real_matches) as check, \
                mock.patch.object(text_utils, "calculate_similarity", return_value=1.0) as compare:
            text_utils.find_similar_files("/indx.html", [str(self.root)],
                                          ignore_patterns=["**/*.jpg"], **kwargs)
        self.assertEqual(compare.call_count, 0)
        return check.call_count

    def test_skipped_entries_count_against_the_time_limit(self):
        """Before, the clock was only read for files that were compared."""
        clock = itertools.count(0.0, 0.01)
        fake_time = types.SimpleNamespace(monotonic=lambda: next(clock))
        with mock.patch.object(text_utils, "time", fake_time):
            visited = self.count_entries_visited(time_limit=0.1)
        self.assertLess(visited, 15)

    def test_skipped_entries_count_against_max_entries(self):
        # One entry past the cap is produced before the loop sees the cap.
        self.assertLessEqual(self.count_entries_visited(max_entries=10), 11)

    def test_requested_path_is_escaped(self):
        page = ErrorPages.get_404_page("/<img src=x onerror=alert(1)>", [str(self.root)], self.settings)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img", page)


class _WindowsPath(PureWindowsPath):
    """Windows path whose resolve() records its argument instead of opening it."""

    resolved = []

    def resolve(self, strict=False):
        _WindowsPath.resolved.append(str(self))
        return self


class WindowsPathTests(unittest.TestCase):
    """path_utils with Windows path semantics, on any OS."""

    def setUp(self):
        _WindowsPath.resolved = []
        for patcher in (
            mock.patch.object(path_utils, "os", types.SimpleNamespace(path=ntpath)),
            mock.patch.object(path_utils, "pathlib", types.SimpleNamespace(Path=_WindowsPath)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def assertOnlyLocalPathsResolved(self):
        self.assertTrue(_WindowsPath.resolved)
        for path in _WindowsPath.resolved:
            self.assertEqual(ntpath.splitdrive(path)[0].lower(), "c:", path)

    def test_payloads_are_rejected_before_resolve(self):
        for raw in WINDOWS_PAYLOADS:
            rel_path = unquote(raw.lstrip("/"))  # as FileServer.serveFile does
            self.assertIsNone(validate_and_secure_path(WINDOWS_ROOT, rel_path), raw)
        validate_and_secure_path(WINDOWS_ROOT, "index.html")
        self.assertOnlyLocalPathsResolved()

    def test_ordinary_paths_still_resolve_under_the_root(self):
        self.assertEqual(validate_and_secure_path(WINDOWS_ROOT, "docs/index.html"),
                         WINDOWS_ROOT + r"\docs\index.html")
        self.assertEqual(validate_and_secure_path(WINDOWS_ROOT, "\\docs\\a b.png"),
                         WINDOWS_ROOT + r"\docs\a b.png")
        self.assertOnlyLocalPathsResolved()

    def test_relative_to_root_never_resolves_another_drive_or_share(self):
        """request_handler._send404 joins the raw request path onto each folder."""
        for raw in WINDOWS_PAYLOADS:
            joined = ntpath.join(WINDOWS_ROOT, raw.lstrip("/"))
            if ntpath.splitdrive(joined)[0].lower() != "c:":
                self.assertIsNone(relative_to_root(joined, [WINDOWS_ROOT]), raw)
            else:  # percent-encoded payloads stay a local name under the root
                relative_to_root(joined, [WINDOWS_ROOT])
        self.assertEqual(relative_to_root(WINDOWS_ROOT + r"\docs\a.html", [WINDOWS_ROOT]),
                         r"docs\a.html")
        self.assertOnlyLocalPathsResolved()


class PolicyHelperTests(unittest.TestCase):
    def test_hidden_segment(self):
        for rel in (".env", ".git/config", "a/.cache/b", "a\\.hidden\\b", ".."):
            self.assertTrue(has_hidden_segment(rel), rel)
        for rel in ("", "a.b/c", "index..html", "docs/", "a/b.c"):
            self.assertFalse(has_hidden_segment(rel), rel)

    def test_refused_path(self):
        root = os.path.join(os.sep, "proj")
        for rel in (".env", os.path.join(".git", "config"), os.path.join("a", ".cache", "b")):
            self.assertTrue(is_refused_path(os.path.join(root, rel), root), rel)
        self.assertTrue(is_refused_path(os.path.join(os.sep, "elsewhere", "x"), root))
        for rel in (os.path.join("src", "app.js"), os.path.join("node_modules", "pkg", "x.js")):
            self.assertFalse(is_refused_path(os.path.join(root, rel), root), rel)
        self.assertFalse(is_refused_path(root, root))
        hidden_root = os.path.join(os.sep, "home", ".sites", "blog")
        self.assertFalse(is_refused_path(os.path.join(hidden_root, "index.html"), hidden_root))


if __name__ == "__main__":
    unittest.main()
