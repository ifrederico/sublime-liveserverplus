# liveserverplus_lib/__init__.py
"""
LiveServerPlus package initialization.
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
    'compress_data',
    'log', 
    'DEBUG',
    'INFO',
    'WARNING',
    'ERROR',
    'CacheManager',
    'ConnectionManager'
]

# Base utilities that don't depend on other modules
from .utils import get_mime_type, compress_data
from .settings import ServerSettings
from .status import ServerStatus
from .logging import debug, info, warning, error, DEBUG, INFO, WARNING, ERROR
from .cache import CacheManager
from .connection_manager import ConnectionManager

# Create simplified log function for backward compatibility
def log(level, message):
    """Log a message with the specified level"""
    if level == 'debug':
        debug(message)
    elif level == 'info':
        info(message)
    elif level == 'warn' or level == 'warning':
        warning(message)
    elif level == 'error':
        error(message)
    else:
        info(message)

# Components with minimal dependencies
from .file_watcher import FileWatcher
from .websocket import WebSocketHandler
from .directory_listing import DirectoryListing
from .error_pages import ErrorPages

# Main server class that depends on other components
from .server import Server