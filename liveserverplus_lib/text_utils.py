# liveserverplus_lib/text_utils.py
"""Text and string manipulation utilities"""
import re
import os
import time
from typing import Iterable, Iterator, List, Tuple, Optional

from .ignore import matches_ignore

def calculate_similarity(a: str, b: str) -> float:
    """
    Calculate string similarity ratio using Levenshtein distance.
    
    Args:
        a: First string
        b: Second string
        
    Returns:
        float: Similarity ratio between 0 and 1
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
        
    # Make comparison case-insensitive
    a = a.lower()
    b = b.lower()
    
    # Ensure a is the shorter string
    if len(a) > len(b):
        a, b = b, a
        
    # Calculate Levenshtein distance
    distances = range(len(a) + 1)
    for i2, c2 in enumerate(b):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(a):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
        
    # Convert distance to similarity ratio
    return 1 - (distances[-1] / max(len(a), len(b)))


def _walk_entries(directory: str, ignore_dirs: Iterable[str],
                  ignore_patterns: Iterable[str]) -> Iterator[Tuple[str, bool]]:
    """Yield ``(path, wanted)`` for every entry visited under ``directory``.

    ``wanted`` is True only for files worth suggesting. Dotfiles and
    dot-directories are refused by the server; ``ignore_dirs`` names and
    ``ignore_patterns`` matches are served, but suggestions from
    node_modules and the like are noise. Skipped directories are pruned so
    ``os.walk`` never enters them. Patterns are matched against the path
    relative to ``directory``, as the file watcher does.
    """
    prefix_len = len(os.path.join(directory, ''))
    for root, dirs, files in os.walk(directory):
        kept = []
        for name in dirs:
            path = os.path.join(root, name)
            if not (name.startswith('.') or name in ignore_dirs
                    or matches_ignore(path[prefix_len:], ignore_patterns)):
                kept.append(name)
            yield path, False
        dirs[:] = kept
        for name in files:
            path = os.path.join(root, name)
            yield path, not (name.startswith('.')
                             or matches_ignore(path[prefix_len:], ignore_patterns))


def find_similar_files(search_term: str, directories: List[str], 
                      threshold: float = 0.5, max_results: int = 5,
                      ignore_dirs: Iterable[str] = (), ignore_patterns: Iterable[str] = (),
                      max_files: int = 2000, max_entries: int = 20000,
                      time_limit: float = 0.1) -> List[Tuple[str, float]]:
    """
    Find files with names similar to the search term.

    Dotfiles, dot-directories, ``ignore_dirs`` and ``ignore_patterns``
    matches are skipped. The walk stops after comparing ``max_files``
    names, visiting ``max_entries`` entries (skipped ones included) or
    spending ``time_limit`` seconds, whichever comes first, so a 404 stays
    cheap in a large project.
    
    Args:
        search_term: Term to search for
        directories: List of directories to search in
        threshold: Minimum similarity threshold (0-1)
        max_results: Maximum number of results to return
        ignore_dirs: Directory names never walked into
        ignore_patterns: ``ignoreFiles`` glob patterns
        max_files: Maximum number of file names compared
        max_entries: Maximum number of files and directories visited
        time_limit: Maximum seconds spent walking
        
    Returns:
        List of tuples (file_path, similarity_score)
    """
    results = []
    search_name = os.path.basename(search_term).lower()
    ignore_dirs = set(ignore_dirs)
    deadline = time.monotonic() + time_limit
    compared = 0
    entries = (
        (directory, file_path, wanted)
        for directory in directories
        for file_path, wanted in _walk_entries(directory, ignore_dirs, ignore_patterns)
    )
    
    # The budget is checked for every entry, skipped ones too: 40,000
    # ignored images cost time even though none of them is compared.
    for visited, (directory, file_path, wanted) in enumerate(entries):
        if (visited >= max_entries or compared >= max_files
                or time.monotonic() > deadline):
            break
        if not wanted:
            continue
        compared += 1
        similarity = calculate_similarity(search_name, os.path.basename(file_path).lower())
        if similarity >= threshold:
            rel_path = os.path.relpath(file_path, directory)
            results.append((rel_path.replace("\\", "/"), similarity))
            
    # Sort by similarity (highest first) and return top results
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:max_results]


def inject_before_tag(html: str, tag: str, content: str) -> str:
    """
    Inject content before a specific HTML tag (case-insensitive).
    
    Args:
        html: HTML content
        tag: Tag to inject before (e.g., '</body>')
        content: Content to inject
        
    Returns:
        Modified HTML with content injected
    """
    pattern = re.compile(re.escape(tag), re.IGNORECASE)
    substituted, count = pattern.subn(lambda match: content + match.group(0), html, count=1)
    
    # If tag not found, append at end
    if count == 0:
        substituted = html + content
        
    return substituted


def truncate_text(text: str, max_length: int, suffix: str = '...') -> str:
    """
    Truncate text to maximum length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
        
    if max_length <= len(suffix):
        return suffix[:max_length]
        
    return text[:max_length - len(suffix)] + suffix


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted size string
    """
    try:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                if unit == 'B':
                    return f"{size_bytes} {unit}"
                else:
                    return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"
    except Exception:
        return "-"


def sanitize_filename(filename: str, replacement: str = '_') -> str:
    """
    Sanitize a filename by replacing invalid characters.
    
    Args:
        filename: Original filename
        replacement: Character to replace invalid chars with
        
    Returns:
        Sanitized filename
    """
    # Characters invalid in filenames on various systems
    invalid_chars = '<>:"|?*\x00'
    if os.name == 'nt':  # Windows
        invalid_chars += '/\\'
    else:  # Unix-like
        invalid_chars += '\x00'
        
    for char in invalid_chars:
        filename = filename.replace(char, replacement)
        
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = 'unnamed'
        
    return filename


def extract_file_extension(path: str) -> str:
    """
    Extract file extension from path (always lowercase).
    
    Args:
        path: File path
        
    Returns:
        Lowercase file extension with dot (e.g., '.html')
    """
    return os.path.splitext(path)[1].lower()


def escape_html(text: str) -> str:
    """
    Escape HTML special characters.
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text
    """
    return (
        text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def generate_etag(content: bytes) -> str:
    """
    Generate ETag for content.
    
    Args:
        content: Content bytes
        
    Returns:
        ETag string
    """
    import hashlib
    return hashlib.md5(content).hexdigest()


def parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    """
    Parse HTTP Range header.
    
    Args:
        range_header: Range header value (e.g., "bytes=0-1023")
        file_size: Total file size
        
    Returns:
        Tuple of (start, end) or None if invalid
    """
    try:
        if not range_header.startswith('bytes='):
            return None
            
        range_spec = range_header[6:]  # Remove "bytes="
        
        # Handle "start-end", "start-", "-end"
        if '-' not in range_spec:
            return None
            
        parts = range_spec.split('-', 1)
        
        if parts[0]:
            start = int(parts[0])
        else:
            # "-end" means last 'end' bytes
            start = file_size - int(parts[1])
            
        if parts[1]:
            end = int(parts[1])
        else:
            # "start-" means from start to end of file
            end = file_size - 1
            
        # Validate range
        if start < 0 or start >= file_size or end < start:
            return None
            
        return (start, min(end, file_size - 1))
        
    except (ValueError, IndexError):
        return None
