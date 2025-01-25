# __init__.py

"""
StartServer package initialization.
Core classes and utilities for running a development server in Sublime Text.
"""

# Version information
__version__ = '2.0.0'

# Define public API
__all__ = [
    'Server',
    'WebSocketHandler',
    'FileWatcher',
    'ServerSettings',
    'ServerStatus',
    'get_mime_type',
    'compress_data'
]

# Base utilities that don't depend on other modules
from .utils import get_mime_type, compress_data
from .settings import ServerSettings
from .status import ServerStatus

# Components with minimal dependencies
from .file_watcher import FileWatcher
from .websocket import WebSocketHandler
from .directory_listing import DirectoryListing
from .error_pages import ErrorPages

# Main server class that depends on other components
from .server import Server