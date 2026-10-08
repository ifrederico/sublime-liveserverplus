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


# ---------------------------------------------------------------------------
# Raw HTML blocks, the CommonMark way (issue #9)
#
# markdown2 decides where a raw HTML block ends by counting matching open and
# close tags. GitHub (cmark-gfm) follows the CommonMark spec instead: a block
# starts at a line that opens with a block-level tag and simply runs until the
# next blank line, with no tag matching at all. Real-world READMEs lean on the
# latter all the time, with mismatched tags in a centred header, a `<details>`
# wrapped around a fenced code block, or a `<p align="center">` indented by two
# spaces, and every one of those made markdown2 lose the plot: either the rest
# of the file came out as raw text, or a `<p>` got wrapped around the HTML with
# `<br />` after every line.
#
# The pass below finds the blocks by the spec's seven start/end conditions and
# hands each one to markdown2's own hash table before its heuristics run. What
# is left for markdown2 is Markdown, which it handles well.
# ---------------------------------------------------------------------------

# Spec section 4.6, condition 6: tag names that open a block outright.
_HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    "colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|"
    "footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|"
    "link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|"
    "section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
)

# Spec's attribute and tag grammar, used by condition 7.
_ATTRIBUTE = (
    r"\s+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?"
)
_OPEN_TAG = r"<[A-Za-z][A-Za-z0-9-]*(?:" + _ATTRIBUTE + r")*\s*/?>"
_CLOSING_TAG = r"</[A-Za-z][A-Za-z0-9-]*\s*>"

# One (start, end) pair per condition, in the order the spec checks them.
# Condition 7 is last and is the only one that may not interrupt a paragraph.
# `end` matches on the line that closes the block; None means "a blank line
# ends it" and the blank line itself is not part of the block.
_HTML_BLOCK_CONDITIONS: Tuple[Tuple["re.Pattern", Optional["re.Pattern"]], ...] = (
    (re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?:\s|>|$)", re.I),
     re.compile(r"</(?:script|pre|style|textarea)>", re.I)),
    (re.compile(r"^ {0,3}<!--"), re.compile(r"-->")),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"^ {0,3}</?(?:" + _HTML_BLOCK_TAGS + r")(?:\s|/?>|$)", re.I), None),
    (re.compile(r"^ {0,3}(?:" + _OPEN_TAG + r"|" + _CLOSING_TAG + r")\s*$"), None),
)
_PARAGRAPH_INTERRUPTING_CONDITIONS = _HTML_BLOCK_CONDITIONS[:-1]

# Lines that end the block before them, so that a condition-7 tag on the next
# line is not a paragraph continuation: an ATX heading, a thematic break or a
# setext underline. Blank lines and fences are handled separately.
_BLOCK_BOUNDARY_RE = re.compile(r"^ {0,3}(?:#{1,6}(?:\s|$)|(?:[-*_]\s*){3,}$|=+\s*$|-+\s*$)")

_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _fence_close_re(fence: str) -> "re.Pattern":
    return re.compile(r"^[ \t]*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")


def _html_block_start(line: str, at_boundary: bool) -> Tuple[bool, Optional["re.Pattern"]]:
    """Tell whether `line` opens a raw HTML block, and what closes it.

    Returns ``(True, end_pattern)`` for a block; ``end_pattern`` is None when
    the block simply runs to the next blank line. Condition 7 is only tried
    when the line does not continue a paragraph.
    """
    conditions = (
        _HTML_BLOCK_CONDITIONS if at_boundary else _PARAGRAPH_INTERRUPTING_CONDITIONS
    )
    for start, end in conditions:
        if start.match(line):
            return True, end
    return False, None


def _find_html_blocks(lines: List[str]) -> List[Tuple[int, int]]:
    """Return ``(first, last)`` line-index ranges of the raw HTML blocks.

    Lines inside fenced code are never HTML, so fences are tracked and
    skipped. The rest follows CommonMark 4.6 closely enough for READMEs:
    start conditions need at most three spaces of indentation; conditions
    1-5 end on the line carrying their terminator (or at the end of the
    document); conditions 6 and 7 end before the next blank line; and
    condition 7 cannot start on a paragraph continuation line.
    """
    blocks: List[Tuple[int, int]] = []
    fence_close: Optional["re.Pattern"] = None
    # True when the previous line finished a block, so the next line may
    # start anything, including a condition-7 block.
    at_boundary = True
    i = 0
    while i < len(lines):
        line = lines[i]

        if fence_close is not None:
            if fence_close.match(line):
                fence_close = None
                at_boundary = True
            i += 1
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence and (fence.group(1)[0] == "~" or "`" not in line[fence.end():]):
            fence_close = _fence_close_re(fence.group(1))
            at_boundary = False
            i += 1
            continue

        if not line.strip():
            at_boundary = True
            i += 1
            continue

        is_block, end = _html_block_start(line, at_boundary)
        if not is_block:
            at_boundary = bool(_BLOCK_BOUNDARY_RE.match(line))
            i += 1
            continue

        first = i
        if end is None:
            while i + 1 < len(lines) and lines[i + 1].strip():
                i += 1
        else:
            while not end.search(lines[i]) and i + 1 < len(lines):
                i += 1
        blocks.append((first, i))
        at_boundary = True
        i += 1

    return blocks


class _GitHubMarkdown(markdown2.Markdown):
    """markdown2 with CommonMark's rules for where a raw HTML block ends."""

    def preprocess(self, text: str) -> str:
        # Safe mode sanitises HTML in a later stage; blocks hashed here
        # would skip it, so leave that configuration to markdown2 itself.
        if "<" in text and not self.safe_mode:
            text = self._hash_commonmark_html_blocks(text)
        return super().preprocess(text)

    def _hash_commonmark_html_blocks(self, text: str) -> str:
        lines = text.split("\n")
        out: List[str] = []
        pos = 0
        for first, last in _find_html_blocks(lines):
            out.extend(lines[pos:first])
            # A block may sit inside a list item, indented to the item's
            # content. markdown2 outdents items before it looks at them, so
            # the block is stored with that indentation removed, which also
            # keeps the content of an indented <pre> as it was written.
            indent = _leading_spaces(lines[first])
            html = "\n".join(
                line[min(indent, _leading_spaces(line)):] for line in lines[first:last + 1]
            )
            key = markdown2._hash_text(html)
            self.html_blocks[key] = html
            # markdown2 recognises a hashed block as a paragraph of its own.
            # The key itself keeps the indentation so that a block inside a
            # list item still reads as part of that item; _form_paragraphs
            # below drops it again once lists have been dealt with.
            out.extend(["", " " * indent + key, ""])
            pos = last + 1
        out.extend(lines[pos:])
        return "\n".join(out)

    def _form_paragraphs(self, text: str) -> str:
        # Lists have been processed by the time paragraphs are formed (each
        # item is outdented and recurses into this method), so a key that is
        # still indented here stands on its own. Outdent it so the stock
        # lookup finds it and emits the block without a <p> around it.
        if self.html_blocks:
            text = _INDENTED_HASH_KEY_RE.sub(self._outdent_known_key, text)
        return super()._form_paragraphs(text)

    def _outdent_known_key(self, match: "re.Match") -> str:
        key = match.group(1)
        return key if key in self.html_blocks else match.group(0)


_INDENTED_HASH_KEY_RE = re.compile(r"^ {1,3}(md5-[0-9a-f]+)[ \t]*$", re.M)


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

        html_body = str(_GitHubMarkdown(extras=extras).convert(source))

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
