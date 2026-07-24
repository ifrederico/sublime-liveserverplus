"""Markdown rendering helpers for LiveServerPlus."""

import os
import re
from typing import Iterable, List, Optional, Tuple

import markdown2

# URL prefix the dev server maps onto liveserverplus_lib/vendor/assets.
# Kept in sync with FileServer._serveVendorAsset.
ASSET_URL_PREFIX = "/__lsp__/assets"

# Extras that are always on: they need no external assets, add no network
# dependency, and only bring the output closer to how GitHub renders.
BASE_MARKDOWN_EXTRAS: Tuple[str, ...] = (
    "fenced-code-blocks",
    "tables",
    "strike",
    "break-on-newline",
    "code-friendly",
    "task_list",
    "alerts",      # GitHub "> [!NOTE]" callouts
    "header-ids",  # stable anchor targets for headings
)

# Backwards-compatible alias for the previous public name.
DEFAULT_MARKDOWN_EXTRAS: Tuple[str, ...] = BASE_MARKDOWN_EXTRAS

GITHUB_STYLE_CSS = """
:root {
    color-scheme: light dark;
}

body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background-color: var(--body-bg, #0d1117);
    color: var(--body-fg, #c9d1d9);
}

body.light {
    --body-bg: #ffffff;
    --body-fg: #24292f;
    background-color: var(--body-bg);
    color: var(--body-fg);
}

@media (prefers-color-scheme: light) {
    body:not(.dark) {
        --body-bg: #ffffff;
        --body-fg: #24292f;
        background-color: var(--body-bg);
        color: var(--body-fg);
    }
}

.markdown-body {
    box-sizing: border-box;
    min-width: 200px;
    max-width: 960px;
    margin: 0 auto;
    padding: 32px;
    line-height: 1.6;
    word-wrap: break-word;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
    margin-top: 24px;
    font-weight: 600;
    line-height: 1.25;
}

.markdown-body h1 {
    padding-bottom: 0.3em;
    border-bottom: 1px solid rgba(110, 118, 129, 0.4);
}

.markdown-body pre {
    padding: 16px;
    overflow: auto;
    font-size: 85%;
    line-height: 1.45;
    background-color: rgba(110, 118, 129, 0.15);
    border-radius: 6px;
}

.markdown-body code {
    font-family: ui-monospace, SFMono-Regular, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 85%;
    background-color: rgba(110, 118, 129, 0.15);
    border-radius: 6px;
    padding: 0.2em 0.4em;
}

.markdown-body pre code {
    background-color: transparent;
    padding: 0;
}

.markdown-body table {
    border-spacing: 0;
    border-collapse: collapse;
    display: block;
    width: 100%;
    overflow: auto;
}

.markdown-body table th,
.markdown-body table td {
    padding: 6px 13px;
    border: 1px solid rgba(110, 118, 129, 0.4);
}

.markdown-body blockquote {
    margin: 0;
    padding: 0 1em;
    color: rgba(110, 118, 129, 0.85);
    border-left: 0.25em solid rgba(110, 118, 129, 0.5);
}

.markdown-body a {
    color: #58a6ff;
    text-decoration: none;
}

.markdown-body a:hover {
    text-decoration: underline;
}

.markdown-body hr {
    height: 0.25em;
    padding: 0;
    margin: 24px 0;
    background-color: rgba(110, 118, 129, 0.4);
    border: 0;
}

.markdown-body ul,
.markdown-body ol {
    padding-left: 2em;
}

.markdown-body img {
    max-width: 100%;
    display: block;
    margin: 0 auto;
}

.markdown-body .task-list-item {
    list-style-type: none;
}

.markdown-body .task-list-item input {
    margin: 0 0.4em 0.2em -1.6em;
}

/* GitHub-style alert callouts: "> [!NOTE]" and friends.
   The type is announced by an icon in front of the title rather than by a
   rule down the side. Each icon is an inline SVG applied as a mask, so it
   takes its colour from the title via currentColor and costs no request —
   which also keeps the preview working offline, like the rest of the
   vendored assets. */
.markdown-body .alert {
    padding: 8px 16px;
    margin: 16px 0;
    border-radius: 6px;
    background-color: rgba(110, 118, 129, 0.08);
}

.markdown-body .alert > em {
    display: flex;
    align-items: center;
    gap: 0.5em;
    font-style: normal;
    font-weight: 600;
    color: var(--alert-accent, #58a6ff);
    margin-bottom: 4px;
}

.markdown-body .alert > em::before {
    content: "";
    flex: none;
    width: 1em;
    height: 1em;
    background-color: currentColor;
    -webkit-mask-image: var(--alert-icon);
    mask-image: var(--alert-icon);
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
}

.markdown-body .alert > p {
    margin: 0;
}

/* `break-on-newline` turns the newline after the "[!NOTE]" marker into a
   <br>, leaving a blank line between the title and the body. Only that
   leading break is spurious — breaks between body lines are wanted. */
.markdown-body .alert > p:first-of-type > br:first-child {
    display: none;
}

/* Info "i" in a disc. */
.markdown-body .alert.note {
    --alert-accent: #58a6ff;
    --alert-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill-rule='evenodd' d='M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zM8 3.4a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4zM6.9 7.2h2.2v5.4H6.9z'/%3E%3C/svg%3E");
}

/* Four-point spark. */
.markdown-body .alert.tip {
    --alert-accent: #3fb950;
    --alert-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M8 .6l1.9 4.5 4.5 1.9-4.5 1.9L8 13.4l-1.9-4.5L1.6 7l4.5-1.9z'/%3E%3C/svg%3E");
}

/* Speech bubble with "!". */
.markdown-body .alert.important {
    --alert-accent: #a371f7;
    --alert-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill-rule='evenodd' d='M2 1h12a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 14 11H8.6l-4.1 3.4V11H2A1.5 1.5 0 0 1 .5 9.5v-7A1.5 1.5 0 0 1 2 1zm5 2.2h2v4.2H7zm1 5.2a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2z'/%3E%3C/svg%3E");
}

/* Triangle with "!". */
.markdown-body .alert.warning {
    --alert-accent: #d29922;
    --alert-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill-rule='evenodd' d='M8 .9l7.8 13.5H.2zm-1 4.7h2v4.3H7zm1 5.3a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2z'/%3E%3C/svg%3E");
}

/* Octagon with "!", the stop-sign shape. */
.markdown-body .alert.caution {
    --alert-accent: #f85149;
    --alert-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill-rule='evenodd' d='M5.2.5h5.6L15.5 5.2v5.6l-4.7 4.7H5.2L.5 10.8V5.2zM7 3.6h2v4.6H7zm1 5.6a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2z'/%3E%3C/svg%3E");
}

/* Math spans identified server-side. Until (or unless) KaTeX renders them
   these show the original "$...$" source, which stays readable on its own. */
.markdown-body .lsp-math[data-lsp-display="1"] {
    display: block;
    text-align: center;
    margin: 16px 0;
    overflow-x: auto;
}

/* Mermaid renders into this wrapper; keep it visible (as source text)
   even when the diagram script fails to load. */
.markdown-body .mermaid-pre {
    background-color: transparent;
    padding: 0;
}

.markdown-body .mermaid {
    text-align: center;
    overflow-x: auto;
}
""".strip()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>{css}</style>
{head_extra}</head>
<body data-lsp-markdown-preview="true" data-lsp-scroll-mode="{scroll_mode}">
    <main class="markdown-body">
        {content}
    </main>
{body_extra}</body>
</html>
"""

# One pass that walks fenced blocks, inline code, and math together. Because
# regex alternation is ordered, code constructs win over the math patterns, so
# dollar signs inside code are never treated as math.
_PROTECT_RE = re.compile(
    r"(?P<fence>^[ \t]*(?P<ticks>`{3,}|~{3,})[\s\S]*?^[ \t]*(?P=ticks)[ \t]*$)"
    r"|(?P<code>(?P<bt>`+)[\s\S]*?(?P=bt))"
    r"|(?P<display>\$\$[\s\S]+?\$\$)"
    r"|(?P<inline>\$(?![\s$])(?:\\.|[^\\\n$])+?(?<!\s)\$(?!\d))",
    re.MULTILINE,
)

# Deliberately alphanumeric: no character here carries meaning in Markdown, so
# the token survives the conversion untouched.
_MATH_TOKEN = "zqLSPMATH{0}HTAMPSLqz"
_MATH_TOKEN_RE = re.compile(r"zqLSPMATH(\d+)HTAMPSLqz")


def _protect_math(text: str) -> Tuple[str, List[Tuple[str, str, bool]]]:
    """Replace math spans with inert placeholders.

    ``break-on-newline`` inserts ``<br />`` at every single newline, which
    would land inside multi-line ``$$...$$`` blocks and stop KaTeX from
    parsing them. Pulling math out before conversion and restoring it
    afterwards keeps the delimiters intact whatever the extras do.

    Returns the rewritten text plus one ``(original, tex, is_display)``
    entry per span, where ``tex`` has the delimiters stripped.
    """
    spans: List[Tuple[str, str, bool]] = []

    def replace(match: "re.Match") -> str:
        display = match.group("display")
        inline = match.group("inline")
        if display is not None:
            spans.append((display, display[2:-2], True))
        elif inline is not None:
            spans.append((inline, inline[1:-1], False))
        else:
            return match.group(0)  # a code construct: leave it alone
        return _MATH_TOKEN.format(len(spans) - 1)

    return _PROTECT_RE.sub(replace, text), spans


def _restore_math(html: str, spans: List[Tuple[str, str, bool]]) -> str:
    """Put the math back, tagged so the browser renders exactly these spans.

    KaTeX's own auto-render walks the finished document and re-detects
    delimiters with no notion of context, so it happily turns the two
    dollar signs in "it costs $5 and $10" into math. Marking the spans that
    were identified here — where code blocks and currency have already been
    ruled out — keeps this module the single source of truth.

    The visible text keeps its delimiters so that a document still reads
    correctly if KaTeX fails to load; the TeX handed to the renderer lives
    in a data attribute.
    """
    if not spans:
        return html

    def replace(match: "re.Match") -> str:
        index = int(match.group(1))
        if index >= len(spans):
            return match.group(0)
        original, tex, is_display = spans[index]
        return (
            '<span class="lsp-math" data-lsp-display="{0}" data-lsp-tex="{1}">{2}</span>'
        ).format(
            "1" if is_display else "0",
            _escape_html_attr(tex),
            _escape_html_text(original),
        )

    return _MATH_TOKEN_RE.sub(replace, html)


def _escape_html_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_html_attr(value: str) -> str:
    return _escape_html_text(value).replace('"', "&quot;").replace("'", "&#39;")


class MarkdownRenderer:
    """Render Markdown files to styled HTML."""

    def __init__(self, css: str = GITHUB_STYLE_CSS, extras: Optional[Iterable[str]] = None) -> None:
        self.css = css
        self.extras = tuple(extras) if extras is not None else BASE_MARKDOWN_EXTRAS

    def render(
        self,
        markdown_text: str,
        title: Optional[str] = None,
        scroll_mode: str = "editor",
        syntax_highlighting: bool = False,
        math: bool = False,
        mermaid: bool = False,
    ) -> str:
        """Convert markdown text into a complete HTML document."""
        document_title = title or "Markdown Preview"

        extras = list(self.extras)
        if syntax_highlighting and "highlightjs-lang" not in extras:
            # Emits `language-x` classes and, importantly, tells markdown2 to
            # skip its Pygments path so no Python dependency is pulled in.
            extras.append("highlightjs-lang")
        if mermaid and "mermaid" not in extras:
            extras.append("mermaid")

        source = markdown_text
        math_spans: List[str] = []
        if math:
            source, math_spans = _protect_math(source)

        html_body = str(markdown2.markdown(source, extras=extras))

        if math:
            html_body = _restore_math(html_body, math_spans)

        head_extra, body_extra = self._assetTags(
            html_body,
            syntax_highlighting=syntax_highlighting,
            math=math and bool(math_spans),
            mermaid=mermaid,
        )

        return HTML_TEMPLATE.format(
            title=self._escape_title(document_title),
            css=self.css,
            scroll_mode=self._escape_attr(scroll_mode),
            content=html_body,
            head_extra=head_extra,
            body_extra=body_extra,
        )

    @staticmethod
    def _assetTags(html_body: str, syntax_highlighting: bool, math: bool, mermaid: bool):
        """Build the asset tags this specific document actually needs.

        The preview reloads in full on every debounced keystroke, so a script
        that is included is re-parsed on every reload. Emitting each one only
        when its marker is present keeps prose-only documents as light as they
        were before these features existed.
        """
        head: List[str] = []
        body: List[str] = []
        p = ASSET_URL_PREFIX

        if syntax_highlighting and 'class="' in html_body and "language-" in html_body:
            head.append(
                '    <link rel="stylesheet" media="(prefers-color-scheme: light)"'
                ' href="{0}/highlight/github.min.css">'.format(p)
            )
            head.append(
                '    <link rel="stylesheet" media="(prefers-color-scheme: dark)"'
                ' href="{0}/highlight/github-dark.min.css">'.format(p)
            )
            body.append('    <script defer src="{0}/highlight/highlight.min.js"></script>'.format(p))
            body.append(
                "    <script>document.addEventListener('DOMContentLoaded',function(){"
                "if(typeof hljs!=='undefined'){hljs.highlightAll();}});</script>"
            )

        if math:
            head.append('    <link rel="stylesheet" href="{0}/katex/katex.min.css">'.format(p))
            body.append('    <script defer src="{0}/katex/katex.min.js"></script>'.format(p))
            # Render only the spans identified server-side. KaTeX's auto-render
            # extension is deliberately not used: it would re-scan the document
            # and turn things like "$5 and $10" into math.
            # Deferred scripts run before DOMContentLoaded, so katex is defined
            # by the time this fires.
            body.append(
                "    <script>document.addEventListener('DOMContentLoaded',function(){"
                "if(typeof katex==='undefined'){return;}"
                "var nodes=document.querySelectorAll('.lsp-math');"
                "for(var i=0;i<nodes.length;i++){var el=nodes[i];"
                "try{katex.render(el.getAttribute('data-lsp-tex'),el,"
                "{displayMode:el.getAttribute('data-lsp-display')==='1',"
                "throwOnError:false});}catch(e){}}});</script>"
            )

        if mermaid and 'class="mermaid"' in html_body:
            body.append('    <script defer src="{0}/mermaid/mermaid.min.js"></script>'.format(p))
            body.append(
                "    <script>document.addEventListener('DOMContentLoaded',function(){"
                "if(typeof mermaid==='undefined'){return;}"
                "var dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;"
                "mermaid.initialize({startOnLoad:false,theme:dark?'dark':'default'});"
                "mermaid.run({querySelector:'.mermaid'});});</script>"
            )

        head_str = ("\n".join(head) + "\n") if head else ""
        body_str = ("\n".join(body) + "\n") if body else ""
        return head_str, body_str

    @staticmethod
    def _escape_title(title: str) -> str:
        """Basic HTML escaping for the title element."""
        return (
            title.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    @staticmethod
    def _escape_attr(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )


def guess_markdown_title(file_path: str, markdown_text: str) -> str:
    """Try to pick a sensible title based on heading fallback."""
    first_heading = None
    for line in markdown_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            first_heading = stripped.lstrip("#").strip()
            if first_heading:
                break

    if first_heading:
        return first_heading

    return os.path.basename(file_path) or "Markdown Preview"
