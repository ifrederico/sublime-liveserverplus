"""Glob matching for the ``ignoreFiles`` setting.

Patterns follow the gitignore / minimatch convention users expect:

    **      any number of path segments, including none
    *       anything within a single segment
    ?       one character within a segment

A pattern that does not start with ``/`` may match at any directory
boundary, so ``node_modules/**`` and ``**/node_modules/**`` behave the
same. A pattern that names a directory also matches everything inside it,
so ``.git`` ignores ``.git/config``.

``pathlib.PurePath.match`` was used before; it treats ``**`` as a single
segment and anchors on the right, so ``**/node_modules/**`` matched
``node_modules/foo.js`` but not ``node_modules/pkg/dist/foo.js``.
"""
import os
import re
from functools import lru_cache
from typing import Iterable, Optional


def normalize_path(path: str) -> str:
    """Return ``path`` with forward slashes and no redundant segments."""
    if not path:
        return ''
    normalized = os.path.normpath(str(path).replace('\\', '/'))
    return normalized.replace('\\', '/')


@lru_cache(maxsize=512)
def _compile(pattern: str) -> Optional["re.Pattern"]:
    pattern = pattern.replace('\\', '/').strip()
    if not pattern:
        return None

    anchored = pattern.startswith('/')
    pattern = pattern.strip('/')
    while pattern.startswith('**/'):
        pattern = pattern[3:]
        anchored = False
    # A trailing "/**" means "the directory and everything in it", which the
    # directory suffix below already provides.
    while pattern.endswith('/**'):
        pattern = pattern[:-3]
    if not pattern or pattern == '**':
        return re.compile(r'.*')

    parts = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == '*':
            if pattern.startswith('**/', i):
                parts.append('(?:.*/)?')
                i += 3
                continue
            if pattern.startswith('**', i):
                parts.append('.*')
                i += 2
                continue
            parts.append('[^/]*')
        elif char == '?':
            parts.append('[^/]')
        else:
            parts.append(re.escape(char))
        i += 1

    prefix = '^/?' if anchored else '(?:^|.*/)'
    return re.compile(prefix + ''.join(parts) + r'(?:/.*)?$')


def matches_ignore(path: str, patterns: Iterable[str]) -> bool:
    """Return True when ``path`` matches any of ``patterns``.

    ``path`` may be absolute or relative, with either separator.
    """
    if not path or not patterns:
        return False

    normalized = normalize_path(path)
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        compiled = _compile(pattern)
        # Every compiled pattern begins with '^/?', '(?:^|.*/)' or '.*', so
        # match() from position 0 finds everything search() would, without
        # re-scanning from each later position.
        if compiled is not None and compiled.match(normalized):
            return True
    return False


def matches_ignore_under(path: str, roots: Iterable[str], patterns: Iterable[str]) -> bool:
    """Match ``patterns`` against ``path`` relative to the served folder that
    contains it.

    Matching the absolute path would let an unanchored pattern match a
    directory *above* the project, so a project opened at
    ``.../node_modules/some-lib/examples`` would be ignored entirely by the
    default patterns, and an anchored pattern such as ``/dist`` could never
    match at all. A root itself never matches. A path outside every root
    falls back to matching the absolute path.
    """
    if not path or not patterns:
        return False

    from .path_utils import relative_to_root  # local import: path_utils logs

    rel_path = relative_to_root(path, list(roots or ()))
    if rel_path is None:
        return matches_ignore(path, patterns)
    if rel_path == '':
        return False
    return matches_ignore(rel_path, patterns)
