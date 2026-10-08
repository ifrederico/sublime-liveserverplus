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
# Also put the repo root on the path so this file runs standalone
# (python tests/test_regressions.py), not just under pytest's rootdir handling.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _FakeSettings:
    def get(self, key, default=None):
        return default

    def add_on_change(self, key, callback):
        pass


def _load_binary_resource(resource_path):
    prefix = "Packages/LiveServerPlus/"
    if not resource_path.startswith(prefix):
        raise FileNotFoundError(resource_path)
    return (REPO_ROOT / resource_path[len(prefix):]).read_bytes()


fake_sublime = types.SimpleNamespace(
    load_settings=lambda name: _FakeSettings(),
    load_binary_resource=_load_binary_resource,
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


class MarkdownPreviewTests(unittest.TestCase):
    """Covers the opt-in Markdown preview extras (issue #7)."""

    CODE = "```python\nx = 1\n```"
    MERMAID = "```mermaid\ngraph TD; A-->B;\n```"
    MATH = "Value $x^2$ here."

    def _render(self, text, **features):
        from liveserverplus_lib.markdown_renderer import MarkdownRenderer

        return MarkdownRenderer().render(text, **features)

    def test_defaults_inject_no_assets(self):
        """A default preview must stay as light as it was before the extras."""
        html = self._render("\n\n".join([self.CODE, self.MERMAID, self.MATH]))

        self.assertNotIn("<script", html)
        self.assertNotIn("<link", html)

    def test_assets_are_injected_only_when_the_document_uses_them(self):
        """Each bundle is re-parsed on every reload, so it must be lazy."""
        all_on = dict(syntax_highlighting=True, math=True, mermaid=True)

        prose = self._render("Just **text**.", **all_on)
        self.assertNotIn("highlight.min.js", prose)
        self.assertNotIn("katex.min.js", prose)
        self.assertNotIn("mermaid.min.js", prose)

        code_only = self._render(self.CODE, **all_on)
        self.assertIn("highlight.min.js", code_only)
        self.assertNotIn("katex.min.js", code_only)
        self.assertNotIn("mermaid.min.js", code_only)

        mermaid_only = self._render(self.MERMAID, **all_on)
        self.assertIn("mermaid.min.js", mermaid_only)
        self.assertNotIn("highlight.min.js", mermaid_only)

    def test_currency_amounts_are_not_treated_as_math(self):
        from liveserverplus_lib.markdown_renderer import _protect_math

        for text in ("It costs $5 and $10 today.", "From $5.00 to $10.00."):
            _, spans = _protect_math(text)
            self.assertEqual(spans, [], "false positive on: %s" % text)

    def test_dollars_inside_code_are_not_treated_as_math(self):
        from liveserverplus_lib.markdown_renderer import _protect_math

        _, inline = _protect_math("Use `$not_math$` here.")
        self.assertEqual(inline, [])

        _, fenced = _protect_math("```sh\necho $HOME $PATH\n```")
        self.assertEqual(fenced, [])

    def test_display_math_survives_break_on_newline(self):
        """`break-on-newline` would otherwise put <br> inside $$...$$."""
        html = self._render("$$\n\\int_0^1 x^2 dx\n$$", math=True)

        start = html.index("$$")
        end = html.index("$$", start + 2)
        self.assertNotIn("<br", html[start:end])

    def test_math_is_escaped_so_it_cannot_break_the_document(self):
        html = self._render("Compare $a < b$ now.", math=True)

        self.assertIn("$a &lt; b$", html)
        self.assertIn('data-lsp-tex="a &lt; b"', html)

    def test_only_server_identified_spans_are_marked_for_katex(self):
        """KaTeX auto-render would turn "$5 and $10" into math; we must not.

        The browser renders `.lsp-math` nodes and nothing else, so the
        currency heuristic in _protect_math stays authoritative.
        """
        html = self._render("Not math: it costs $5 and $10.", math=True)
        self.assertNotIn('class="lsp-math"', html)
        self.assertIn("<p>Not math: it costs $5 and $10.</p>", html)

        mixed = self._render("Costs $5 but math $x^2$ ok.", math=True)
        self.assertEqual(mixed.count('class="lsp-math"'), 1)
        self.assertIn('data-lsp-tex="x^2"', mixed)

    def test_display_math_is_marked_as_display(self):
        html = self._render("$$\n\\int_0^1 x^2 dx\n$$", math=True)

        self.assertIn('data-lsp-display="1"', html)

    def test_katex_autorender_bundle_is_not_referenced(self):
        html = self._render("Value $x^2$ here.", math=True)

        self.assertIn("katex.min.js", html)
        self.assertNotIn("auto-render", html)

    def test_alerts_and_header_ids_are_always_on(self):
        html = self._render("# Heading\n\n> [!WARNING]\n> Careful.")

        self.assertIn('class="alert warning"', html)
        self.assertIn('id="heading"', html)

    def test_alert_body_leading_break_is_suppressed(self):
        """`break-on-newline` puts a <br> right after the alert title.

        markdown2 emits `<em>Warning</em>\\n<p><br>\\n  Careful.</p>`, and
        that leading break renders as a blank line under the title. It is
        hidden in CSS rather than stripped from the markup so that breaks
        between the body's own lines still work.
        """
        html = self._render("> [!WARNING]\n> Careful.")

        self.assertIn("<p><br", html)
        self.assertIn(
            ".markdown-body .alert > p:first-of-type > br:first-child", html
        )

    def test_alerts_use_an_icon_instead_of_a_side_rule(self):
        """Alerts are marked by an icon in front of the title, not a bar."""
        html = self._render("> [!WARNING]\n> Careful.")

        self.assertNotIn("border-left: 0.25em solid var(--alert-accent", html)
        self.assertIn(".markdown-body .alert > em::before", html)

    def test_every_alert_type_has_its_own_icon(self):
        """A missing --alert-icon renders as an empty box, not a fallback."""
        html = self._render("> [!NOTE]\n> Body.")

        for kind in ("note", "tip", "important", "warning", "caution"):
            marker = ".markdown-body .alert.%s {" % kind
            self.assertIn(marker, html, "no rule for %s" % kind)
            block = html[html.index(marker):]
            block = block[: block.index("}")]
            self.assertIn("--alert-icon: url(\"data:image/svg+xml,", block,
                          "%s has no icon" % kind)
            self.assertIn("--alert-accent:", block, "%s has no accent" % kind)

    def test_alert_icons_are_inlined_rather_than_fetched(self):
        """The preview must keep working offline, like the vendored bundles."""
        html = self._render("> [!TIP]\n> Body.")

        self.assertNotIn("--alert-icon: url(\"http", html)
        self.assertNotIn("--alert-icon: url(\"/", html)


class MarkdownHtmlBlockTests(unittest.TestCase):
    """Raw HTML blocks end where GitHub says they end (issue #9).

    markdown2 finds the end of a raw HTML block by matching open and close
    tags. GitHub follows CommonMark: a block runs from a block-level tag to
    the next blank line, whatever the tags inside it look like.
    """

    # The opening of ghostty's README: a <p> that is never closed inside the
    # <h1>, then a stray </p>. markdown2 lost the rest of the file after it.
    GHOSTTY_HEADER = (
        "<!-- LOGO -->\n"
        "<h1>\n"
        "<p align=\"center\">\n"
        "  <img src=\"logo.png\" alt=\"Logo\" width=\"128\">\n"
        "  <br>Ghostty\n"
        "</h1>\n"
        "  <p align=\"center\">\n"
        "    Fast, native, feature-rich terminal emulator.\n"
        "    <a href=\"#about\">About</a>\n"
        "  </p>\n"
        "</p>\n"
        "\n"
        "## About\n"
        "\n"
        "**`libghostty`** is a [library](https://example.com).\n"
        "\n"
        "| # | Step |\n"
        "|---|------|\n"
        "| 1 | Done |\n"
    )

    def _body(self, text):
        from liveserverplus_lib.markdown_renderer import MarkdownRenderer

        html = MarkdownRenderer().render(text)
        start = html.index('<main class="markdown-body">') + len('<main class="markdown-body">')
        return html[start:html.index("</main>")].strip()

    def test_mismatched_tags_do_not_swallow_the_rest_of_the_document(self):
        body = self._body(self.GHOSTTY_HEADER)

        self.assertIn('<h2 id="about">About</h2>', body)
        self.assertIn("<strong><code>libghostty</code></strong>", body)
        self.assertIn('<a href="https://example.com">library</a>', body)
        self.assertIn("<table>", body)
        self.assertNotIn("## About", body)
        self.assertNotIn("[library](", body)

    def test_html_block_is_passed_through_verbatim(self):
        """No <p> around it and no <br /> from break-on-newline inside it."""
        body = self._body(self.GHOSTTY_HEADER)
        block = body[: body.index("<h2")]

        self.assertNotIn("<br />", block)
        self.assertNotIn("<p><p", block)
        self.assertIn('  <p align="center">\n    Fast, native', block)

    def test_block_ends_at_blank_line_so_markdown_inside_details_renders(self):
        """The common README idiom: <details> wrapped around a code block."""
        body = self._body(
            "<details>\n<summary>Install</summary>\n\n```sh\nnpm install\n```\n\n</details>\n"
        )

        self.assertTrue(body.startswith("<details>\n<summary>Install</summary>"))
        self.assertIn("<pre><code>npm install\n</code></pre>", body)
        self.assertTrue(body.endswith("</details>"))
        self.assertNotIn("<p><details>", body)

    def test_markdown_between_html_blocks_is_rendered(self):
        body = self._body("<div>\n\n*emphasis*\n\n</div>\n")

        self.assertEqual(body, "<div>\n\n<p><em>emphasis</em></p>\n\n</div>")

    def test_indented_block_is_not_wrapped_in_a_paragraph(self):
        body = self._body('  <p align="center">\n    <img src="x.png">\n  </p>\n\n## Next\n')

        self.assertTrue(body.startswith('<p align="center">\n  <img src="x.png">\n</p>'))
        self.assertNotIn("<br />", body)
        self.assertIn('<h2 id="next">Next</h2>', body)

    def test_block_inside_a_list_item_stays_in_the_item(self):
        body = self._body("- item\n\n  <div>x</div>\n\n- next\n")

        self.assertEqual(body.count("<ul>"), 1)
        self.assertLess(body.index("<div>x</div>"), body.index("next"))
        self.assertNotIn("<p><div>", body)

    def test_html_inside_fenced_code_is_still_code(self):
        body = self._body("```html\n<div>\n*x*\n</div>\n```\n")

        self.assertIn("&lt;div&gt;\n*x*\n&lt;/div&gt;", body)
        self.assertNotIn("<div>", body)

    def test_pre_block_keeps_its_blank_lines_and_raw_content(self):
        body = self._body("<pre>\n*a*\n\nb\n</pre>\n\n*c*\n")

        self.assertTrue(body.startswith("<pre>\n*a*\n\nb\n</pre>"))
        self.assertIn("<p><em>c</em></p>", body)

    def test_a_lone_tag_line_cannot_interrupt_a_paragraph(self):
        """Condition 7 of the spec: `<img>` right under text stays in it."""
        self.assertEqual(
            self._body('Some text\n<img src="x.png">\n'),
            '<p>Some text<br />\n<img src="x.png"></p>',
        )
        self.assertEqual(
            self._body('Some text\n\n<img src="x.png">\n\nMore\n'),
            '<p>Some text</p>\n\n<img src="x.png">\n\n<p>More</p>',
        )

    def test_autolinks_and_inline_html_are_untouched(self):
        self.assertEqual(
            self._body("<https://example.com>\n"),
            '<p><a href="https://example.com">https://example.com</a></p>',
        )
        self.assertEqual(
            self._body("Use <kbd>Ctrl</kbd>+<kbd>C</kbd>\n"),
            "<p>Use <kbd>Ctrl</kbd>+<kbd>C</kbd></p>",
        )


class VendorAssetServingTests(unittest.TestCase):
    class _Connection:
        def __init__(self):
            self.data = b""

        def sendall(self, data):
            self.data += data

    def test_vendored_assets_are_available_as_sublime_resources(self):
        from liveserverplus_lib.file_server import VENDOR_ASSET_RESOURCE_ROOT

        for rel in (
            "highlight/highlight.min.js",
            "katex/katex.min.js",
            "katex/katex.min.css",
            "katex/fonts/KaTeX_Main-Regular.woff2",
            "mermaid/mermaid.min.js",
        ):
            resource_path = VENDOR_ASSET_RESOURCE_ROOT + "/" + rel
            self.assertTrue(fake_sublime.load_binary_resource(resource_path))

    def test_packaged_asset_is_served_through_sublime_resource_api(self):
        from liveserverplus_lib.file_server import FileServer

        expected_path = (
            "Packages/LiveServerPlus/liveserverplus_lib/vendor/assets/"
            "katex/katex.min.js"
        )
        payload = b"window.katex = {};"
        calls = []
        original_loader = fake_sublime.load_binary_resource

        def packaged_loader(resource_path):
            calls.append(resource_path)
            if resource_path != expected_path:
                raise FileNotFoundError(resource_path)
            return payload

        fake_sublime.load_binary_resource = packaged_loader
        try:
            connection = self._Connection()
            settings = types.SimpleNamespace(corsEnabled=False)
            served = FileServer(settings)._serveVendorAsset(
                connection, "katex/katex.min.js"
            )
        finally:
            fake_sublime.load_binary_resource = original_loader

        self.assertTrue(served)
        self.assertEqual(calls, [expected_path])
        self.assertIn(b"HTTP/1.1 200 OK", connection.data)
        self.assertIn(b"Content-Type: application/javascript", connection.data)
        self.assertTrue(connection.data.endswith(payload))

    def test_asset_route_rejects_paths_outside_the_resource_root(self):
        from liveserverplus_lib.file_server import _vendor_asset_resource_path

        for rel in (
            "../file_server.py",
            "../../../etc/passwd",
            "katex/../../settings.py",
            "katex/%2e%2e/settings.py",
            "katex\\katex.min.js",
        ):
            self.assertIsNone(_vendor_asset_resource_path(rel))

    def test_asset_url_prefix_matches_between_renderer_and_server(self):
        """The renderer writes these URLs; the file server routes them."""
        from liveserverplus_lib.markdown_renderer import ASSET_URL_PREFIX, MarkdownRenderer

        html = MarkdownRenderer().render(MarkdownPreviewTests.CODE, syntax_highlighting=True)
        self.assertIn(ASSET_URL_PREFIX + "/highlight/highlight.min.js", html)


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

    def test_use_local_ip_binds_all_interfaces_after_opt_in(self):
        from liveserverplus_lib.server import _bind_host_for_config

        self.assertEqual(_bind_host_for_config("127.0.0.1", use_local_ip=True), "0.0.0.0")


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


class QrUrlTests(unittest.TestCase):
    def test_qr_urls_use_lan_ip_for_localhost_server(self):
        from liveserverplus_lib import qr_utils

        original_get_local_ip = qr_utils.get_local_ip
        try:
            qr_utils.get_local_ip = lambda: "192.168.1.20"

            urls = qr_utils.get_server_urls("127.0.0.1", 5500, prefer_local_ip=True)

            self.assertEqual(urls["primary"], "http://192.168.1.20:5500")
            self.assertIn("http://127.0.0.1:5500", urls["all"])
        finally:
            qr_utils.get_local_ip = original_get_local_ip


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

    def test_lan_access_toggle_commands_are_available(self):
        commands = (REPO_ROOT / "Default.sublime-commands").read_text(encoding="utf-8")

        self.assertIn("Live Server Plus: Enable LAN Access", commands)
        self.assertIn("Live Server Plus: Disable LAN Access", commands)


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
