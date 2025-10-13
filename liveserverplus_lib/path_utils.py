# liveserverplus_lib/path_utils.py
"""Centralized path manipulation utilities for security and consistency"""
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
        
        # Check for suspicious patterns
        if any(pattern in clean_path for pattern in ['..', '//', '\\\\', '\x00']):
            info(f"Suspicious path pattern detected: {requested_path}")
            return None
        
        # Step 2: Clean and normalize the path
        # Remove leading slashes/backslashes
        clean_path = clean_path.lstrip('/').lstrip('\\')
        
        # Step 3: Join with base folder and resolve
        try:
            base_path = pathlib.Path(base_folder).resolve()
            full_path = pathlib.Path(base_folder, clean_path).resolve()
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
