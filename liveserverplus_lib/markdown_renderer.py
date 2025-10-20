"""Markdown rendering helpers for LiveServerPlus."""

import os
from typing import Iterable, Optional, Tuple

import markdown2

DEFAULT_MARKDOWN_EXTRAS: Tuple[str, ...] = (
    "fenced-code-blocks",
    "tables",
    "strike",
    "break-on-newline",
    "code-friendly",
    "task_list",
)

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
""".strip()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>{css}</style>
</head>
<body data-lsp-markdown-preview="true" data-lsp-scroll-mode="{scroll_mode}">
    <main class="markdown-body">
        {content}
    </main>
</body>
</html>
"""


class MarkdownRenderer:
    """Render Markdown files to styled HTML."""

    def __init__(self, css: str = GITHUB_STYLE_CSS, extras: Optional[Iterable[str]] = None) -> None:
        self.css = css
        self.extras = tuple(extras) if extras is not None else DEFAULT_MARKDOWN_EXTRAS

    def render(self, markdown_text: str, title: Optional[str] = None, scroll_mode: str = "editor") -> str:
        """Convert markdown text into a complete HTML document."""
        document_title = title or "Markdown Preview"
        html_body = markdown2.markdown(markdown_text, extras=self.extras)
        return HTML_TEMPLATE.format(
            title=self._escape_title(document_title),
            css=self.css,
            scroll_mode=self._escape_attr(scroll_mode),
            content=html_body,
        )

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
