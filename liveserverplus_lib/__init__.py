# liveserverplus_lib/__init__.py
"""
LiveServerPlus package initialization.
Core classes and utilities for running a development server in Sublime Text.
"""

# Version information
__version__ = '3.3.0'

# Define public API
__all__ = [
    # Main server components
    'Server',
    'WebSocketHandler',
    'FileWatcher',
    'ServerSettings',
    'ServerStatus',
    
    # HTTP utilities
    'HTTPRequest',
    'HTTPResponse',
    'send_error_response',
    'send_options_response',
    
    # File serving
    'FileServer',
    'RequestHandler',
    
    # General utilities
    'get_mime_type',
    'compressData',
    'streamCompressData',
    'detectEncoding',
    'createFileReader',
    'getFreePort',
    'openInBrowser',
    'shouldSkipCompression',
    
    # Text utilities
    'calculate_similarity',
    'find_similar_files',
    'inject_before_tag',
    'format_file_size',
    'extract_file_extension',
    'is_text_file',
    
    # Logging
    'debug', 
    'info', 
    'warning', 
    'error',
    
    # Managers
    'ConnectionManager',
    
    # UI Components
    'DirectoryListing',
    'ErrorPages',
    
    # Constants
    'MIME_TYPES',
    'FILE_ICONS',
    'DEFAULT_SETTINGS',
    'BROWSER_COMMANDS'
]

# Base utilities that don't depend on other modules
from .utils import (compressData, streamCompressData,
                   detectEncoding, createFileReader, getFreePort, 
                   openInBrowser, shouldSkipCompression)
from .settings import ServerSettings
from .status import ServerStatus
from .logging import info, error
from .connection_manager import ConnectionManager

# Constants
from .constants import (MIME_TYPES, FILE_ICONS, DEFAULT_SETTINGS, 
                       BROWSER_COMMANDS)

# Text utilities
from .text_utils import (calculate_similarity, find_similar_files,
                        inject_before_tag, format_file_size,
                        extract_file_extension)

# File utilities - including is_text_file and get_mime_type
from .file_utils import (get_mime_type, isFileAllowed, is_text_file, 
                        should_compress_file)

# HTTP utilities
from .http_utils import HTTPRequest, HTTPResponse, send_error_response, send_options_response

# Components with minimal dependencies
from .file_watcher import FileWatcher
from .websocket import WebSocketHandler
from .directory_listing import DirectoryListing
from .error_pages import ErrorPages

# File serving components
from .file_server import FileServer
from .request_handler import RequestHandler

# Main server class that depends on other components
from .server import Server
