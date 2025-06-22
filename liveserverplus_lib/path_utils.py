# liveserverplus_lib/path_utils.py
"""Centralized path manipulation utilities for security and consistency"""
import os
import pathlib
from urllib.parse import unquote
from .logging import warning, error


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
            warning(f"Suspicious path pattern detected: {requested_path}")
            return None
        
        # Step 2: Clean and normalize the path
        # Remove leading slashes/backslashes
        clean_path = clean_path.lstrip('/').lstrip('\\')
        
        # Step 3: Join with base folder and resolve
        try:
            base_path = pathlib.Path(base_folder).resolve()
            full_path = pathlib.Path(base_folder, clean_path).resolve()
        except Exception as e:
            warning(f"Path resolution failed: {e}")
            return None
        
        # Step 4: Verify the path is within base folder
        try:
            # This will raise ValueError if full_path is not relative to base_path
            full_path.relative_to(base_path)
            return str(full_path)
        except ValueError:
            warning(f"Path escape attempt: {requested_path} is outside {base_folder}")
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
            warning(f"Path {file_path} is outside of root {root_path}")
            return None
            
        return rel_path
    except ValueError as e:
        error(f"Error computing relative path: {e}")
        return None