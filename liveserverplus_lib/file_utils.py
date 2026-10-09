# liveserverplus_lib/file_utils.py
"""Centralized file handling utilities"""
import os
import time
from .constants import MIME_TYPES
from .text_utils import extract_file_extension
from .logging import info, error

# Add a cache at module level with size limit
_mime_cache = {}
_MIME_CACHE_MAX_SIZE = 1000  # Maximum number of entries


def get_mime_type(file_path):
    """Get MIME type for file path with caching and cache limit."""
    if not file_path:
        return 'application/octet-stream'
    
    # Check cache first
    if file_path in _mime_cache:
        return _mime_cache[file_path]
    
    # Clear cache if it's too large
    if len(_mime_cache) > _MIME_CACHE_MAX_SIZE:
        # Clear oldest half of entries
        info(f"Clearing MIME cache, size: {len(_mime_cache)}")
        items = list(_mime_cache.items())
        _mime_cache.clear()
        # Keep the newest half
        for path, mime in items[len(items)//2:]:
            _mime_cache[path] = mime
    
    ext = extract_file_extension(file_path)
    mime_type = MIME_TYPES.get(ext, 'application/octet-stream')
    
    # Cache the result
    _mime_cache[file_path] = mime_type
    return mime_type


def isFileAllowed(file_path, allowed_extensions_set):
    """
    Check if file extension is in allowed set.
    
    Args:
        file_path (str): Path to the file
        allowed_extensions_set: Set of allowed extensions for O(1) lookup
        
    Returns:
        bool: True if file is allowed
    """
    ext = extract_file_extension(file_path)
    return ext in allowed_extensions_set


def get_file_info(file_path):
    """
    Get standardized file information.
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        dict: File information or None if error
    """
    try:
        if not os.path.exists(file_path):
            return None
            
        stat_info = os.stat(file_path)
        is_dir = os.path.isdir(file_path)
        
        return {
            'path': file_path,
            'name': os.path.basename(file_path),
            'size': stat_info.st_size if not is_dir else 0,
            'modified': stat_info.st_mtime,
            'is_directory': is_dir,
            'extension': extract_file_extension(file_path) if not is_dir else '',
            'mime_type': get_mime_type(file_path) if not is_dir else 'text/html'
        }
    except Exception as e:
        error(f"Error getting file info for {file_path}: {e}")
        return None


def find_index_file(directory_path):
    """
    Look for index.html or index.htm in a directory.
    
    Args:
        directory_path (str): Path to directory
        
    Returns:
        str: Path to index file or None if not found
    """
    for index_name in ['index.html', 'index.htm']:
        index_path = os.path.join(directory_path, index_name)
        if os.path.isfile(index_path):
            return index_path
    return None
