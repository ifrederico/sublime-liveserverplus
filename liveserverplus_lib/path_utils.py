# liveserverplus_lib/path_utils.py
"""Centralized path manipulation utilities for security and consistency"""
import ntpath
import os
import pathlib
from pathlib import PurePath, PureWindowsPath
from urllib.parse import unquote, urljoin, urlunsplit, quote
from .logging import info, error


def validate_and_secure_path(base_folder, requested_path):
    """
    Single comprehensive function to validate and secure a path.
    Combines all security checks into one place.
    
    Args:
        base_folder (str): Base directory that should contain the path
        requested_path (str): Requested path (can be URL path or file path)
        
    Returns:
        str: Full safe path if valid, None otherwise
    """
    try:
        # Step 1: Basic validation - check for obvious attacks
        if not requested_path:
            return None
            
        # Unquote URL encoding
        clean_path = unquote(requested_path)
        
        # Step 2: Clean and normalize the path. "\" is a separator on
        # Windows, so normalize it before anything else: stripping "/" and
        # "\" one after the other turned "\/\host\share" into "/\host\share",
        # which Windows joins as the UNC path \\host\share.
        clean_path = clean_path.replace('\\', '/')
        if clean_path.startswith('//'):
            info(f"Suspicious path pattern detected: {requested_path}")
            return None
        clean_path = clean_path.lstrip('/')

        # Reject path traversal segments without rejecting valid names such
        # as "index..html", and anything that would replace base_folder in
        # the join instead of extending it: a drive ("C:"), a UNC prefix or
        # an absolute path.
        path_parts = clean_path.split('/')
        if ('\x00' in clean_path
                or any(part == '..' for part in path_parts)
                or ':' in path_parts[0]
                or ntpath.splitdrive(clean_path)[0]
                or os.path.isabs(clean_path)
                or ntpath.isabs(clean_path)):
            info(f"Suspicious path pattern detected: {requested_path}")
            return None
        
        # Lexical containment before anything touches the filesystem:
        # resolve() opens the path, and on Windows opening a UNC path makes
        # an SMB connection that leaks the user's NTLM hash.
        try:
            base_norm = os.path.normpath(os.path.abspath(base_folder))
            joined = os.path.normpath(os.path.join(base_norm, clean_path))
            common = os.path.commonpath([base_norm, joined])
        except ValueError:  # different drives on Windows
            common = None
        if common is None or os.path.normcase(common) != os.path.normcase(base_norm):
            info(f"Path escape attempt: {requested_path} is outside {base_folder}")
            return None
        
        # Step 3: Resolve; symlinks can still lead outside base_folder
        try:
            base_path = pathlib.Path(base_folder).resolve()
            full_path = pathlib.Path(joined).resolve()
        except Exception as e:
            info(f"Path resolution failed: {e}")
            return None
        
        # Step 4: Verify the path is within base folder
        try:
            # This will raise ValueError if full_path is not relative to base_path
            full_path.relative_to(base_path)
            return str(full_path)
        except ValueError:
            info(f"Path escape attempt: {requested_path} is outside {base_folder}")
            return None
            
    except Exception as e:
        error(f"Path validation error: {e}")
        return None


def has_hidden_segment(rel_path):
    """Return True when any segment of ``rel_path`` starts with a dot.

    ``.env``, ``.git/config`` and ``a/.cache/b`` are hidden; ``a.b/c`` is not.
    """
    return any(part.startswith('.') for part in rel_path.replace('\\', '/').split('/'))


def is_refused_path(full_path, root):
    """Return True when the server must treat ``full_path`` as missing.

    Below ``root``, dotfiles and anything inside a dot-directory are
    refused; ``root`` itself never is, and anything outside it always is.
    Both paths must be in the same form (both resolved, or both not).
    """
    try:
        rel_path = os.path.relpath(full_path, root)
    except ValueError:  # different drives on Windows
        return True
    # has_hidden_segment also catches "..", i.e. a path outside root.
    return rel_path != '.' and has_hidden_segment(rel_path)


def resolve_served_path(folder, rel_path):
    """Resolve a request path under ``folder`` and apply the serving policy.

    ``rel_path`` is the URL path without its leading slash, already
    unquoted. Returns ``folder`` unchanged for the root (empty
    ``rel_path``), the resolved absolute path otherwise, or None when the
    path escapes ``folder`` or has a segment starting with a dot. Dot
    segments are checked on both the requested and the resolved path, so a
    symlink cannot lead into a dot-directory. Existence is not checked.
    """
    if not rel_path:
        return folder
    if has_hidden_segment(rel_path):
        return None
    safe_path = validate_and_secure_path(folder, rel_path)
    if not safe_path:
        return None
    try:
        real_root = str(pathlib.Path(folder).resolve())
    except Exception as e:
        info(f"Path resolution failed: {e}")
        return None
    if is_refused_path(safe_path, real_root):
        return None
    return safe_path


def relative_to_root(file_path, roots):
    """Return file_path relative to the first containing root, or None.

    ``file_path`` is only resolved when it is on a drive or share that one
    of the roots is on: resolve() opens the path, and on Windows opening a
    UNC path (say one built from a request) makes an SMB connection.
    """
    if not file_path:
        return None

    resolved_roots = []
    drives = set()
    for root in roots or []:
        try:
            resolved_root = pathlib.Path(root).resolve()
        except Exception as e:
            error(f"Error checking path containment for {file_path}: {e}")
            continue
        resolved_roots.append(resolved_root)
        drives.add(os.path.normcase(os.path.splitdrive(root)[0]))
        drives.add(os.path.normcase(os.path.splitdrive(str(resolved_root))[0]))
    if os.path.normcase(os.path.splitdrive(file_path)[0]) not in drives:
        return None

    try:
        resolved_file = pathlib.Path(file_path).resolve()
    except Exception as e:
        error(f"Error resolving file path {file_path}: {e}")
        return None

    for resolved_root in resolved_roots:
        try:
            rel_path = resolved_file.relative_to(resolved_root)
            rel_path_str = str(rel_path)
            return '' if rel_path_str == '.' else rel_path_str
        except ValueError:
            continue
        except Exception as e:
            error(f"Error checking path containment for {file_path}: {e}")
            continue

    return None


def get_relative_path(root_path, file_path):
    """
    Get relative path from root to file.
    
    Args:
        root_path (str): Root directory path
        file_path (str): File path
        
    Returns:
        str: Relative path or None if outside root
    """
    try:
        rel_path = os.path.relpath(file_path, root_path)
        
        # Check if path is outside the root
        if rel_path.startswith('..'):
            info(f"Path {file_path} is outside of root {root_path}")
            return None
            
        return rel_path
    except ValueError as e:
        error(f"Error computing relative path: {e}")
        return None


def normalize_url_path(rel_path, *, is_directory=False):
    """
    Convert a filesystem path to a URL-friendly POSIX path.

    Args:
        rel_path (str | pathlib.PurePath | None): Relative path to normalize.
        is_directory (bool): Append trailing slash when path points to directory.

    Returns:
        str: POSIX-style URL path without a leading slash.
    """
    if not rel_path:
        return ''

    # Handle pathlib objects transparently
    rel_path_str = str(rel_path)

    if '\\' in rel_path_str:
        # Interpret Windows-style separators explicitly
        posix_path = PureWindowsPath(rel_path_str).as_posix()
    else:
        posix_path = PurePath(rel_path_str).as_posix()

    posix_path = posix_path.lstrip('/')

    if is_directory and posix_path and not posix_path.endswith('/'):
        posix_path = f"{posix_path}/"

    return posix_path


def build_base_url(protocol, host, port):
    """
    Build a base server URL (ending with a /) from components.

    Args:
        protocol (str): URL scheme to use (defaults to http when falsy).
        host (str): Hostname or IP address.
        port (int | None): TCP port number.

    Returns:
        str: Normalized base URL suitable for urljoin.
    """
    scheme = protocol or 'http'
    safe_host = host or '127.0.0.1'

    # Wrap IPv6 addresses in brackets per RFC 3986
    if ':' in safe_host and not safe_host.startswith('['):
        safe_host = f"[{safe_host}]"

    if port is not None:
        netloc = f"{safe_host}:{port}"
    else:
        netloc = safe_host

    return urlunsplit((scheme, netloc, '/', '', ''))


def join_base_and_path(base_url, rel_path):
    """
    Join a base server URL with a normalized relative path.

    Args:
        base_url (str): Base URL produced by build_base_url.
        rel_path (str | pathlib.PurePath | None): Relative path to append.

    Returns:
        str: Complete URL with normalized separators.
    """
    if not base_url:
        if rel_path in (None, '', '/'):
            return ''
        return normalize_url_path(rel_path)

    if rel_path in (None, '', '/'):
        return base_url.rstrip('/')

    is_directory = isinstance(rel_path, str) and rel_path.endswith('/')
    normalized = normalize_url_path(rel_path, is_directory=is_directory)

    if not base_url.endswith('/'):
        base_url = f"{base_url}/"

    if not normalized:
        return base_url.rstrip('/')

    encoded_path = quote(normalized, safe='/')

    return urljoin(base_url, encoded_path)
