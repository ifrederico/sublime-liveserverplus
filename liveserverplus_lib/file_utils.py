# liveserverplus_lib/file_utils.py
"""Centralized file handling utilities"""
import os
import time
from .constants import TEXT_FILE_EXTENSIONS, MIME_TYPES
from .text_utils import extract_file_extension
from .logging import info, error

# Add a cache at module level with size limit
_mime_cache = {}
_MIME_CACHE_MAX_SIZE = 1000  # Maximum number of entries


def is_text_file(file_path):
    """
    Check if a file is likely a text file based on extension.
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        bool: True if likely a text file
    """
    ext = extract_file_extension(file_path)
    return ext in TEXT_FILE_EXTENSIONS

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


def should_compress_file(file_path, mime_type=None):
    """
    Determine if a file should be compressed based on its type.
    
    Args:
        file_path (str): Path to the file
        mime_type (str): Optional pre-determined MIME type
        
    Returns:
        bool: True if file should be compressed
    """
    from .constants import NO_COMPRESS_EXTENSIONS, SKIP_COMPRESSION_TYPES
    
    # Check extension first
    ext = extract_file_extension(file_path)
    if ext in NO_COMPRESS_EXTENSIONS:
        return False
    
    # Check MIME type
    if mime_type is None:
        mime_type = get_mime_type(file_path)
    
    return mime_type not in SKIP_COMPRESSION_TYPES


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


def is_binary_file(file_path):
    """
    Check if file is binary by reading a sample.
    
    Args:
        file_path (str): Path to file
        
    Returns:
        bool: True if binary, False otherwise
    """
    # Quick check based on extension
    ext = extract_file_extension(file_path)
    binary_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', 
                        '.exe', '.dll', '.so', '.mp3', '.mp4', '.webm',
                        '.woff', '.woff2', '.ttf', '.eot', '.otf'}
    
    if ext in binary_extensions:
        return True
    
    # For text file extensions, assume text
    if ext in TEXT_FILE_EXTENSIONS:
        return False
        
    # Content-based check for unknown extensions
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            # Check for null bytes (common in binary files)
            if b'\x00' in chunk:
                return True
                
            # Check for high concentration of non-ASCII bytes
            non_ascii = sum(1 for b in chunk if b > 127)
            if non_ascii > len(chunk) * 0.3:  # More than 30% non-ASCII
                return True
                
            return False
    except Exception as e:
        info(f"Error checking if file is binary: {e}")
        return True


def get_file_encoding(file_path, default='utf-8'):
    """
    Simple encoding detection for text files.
    
    Args:
        file_path (str): Path to the file
        default (str): Default encoding if detection fails
        
    Returns:
        str: Detected or default encoding
    """
    if is_binary_file(file_path):
        return None
        
    try:
        # Check for BOM
        with open(file_path, 'rb') as f:
            sample = f.read(4)
            
        if sample.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        elif sample.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        elif sample.startswith(b'\xfe\xff'):
            return 'utf-16-be'
        
        # For most web files, UTF-8 is a safe bet
        return default
        
    except Exception as e:
        info("Error detecting encoding for {file_path}: {e}")
        return default
