# liveserverplus_lib/logging.py
import sublime
from datetime import datetime

# Constants for backward compatibility
DEBUG = 'debug'
INFO = 'info'
WARNING = 'warning'
ERROR = 'error'

# Global flag for logging state
_enabled = False

def _on_settings_change():
    """Update logging state when settings change"""
    global _enabled
    settings = sublime.load_settings("LiveServerPlus.sublime-settings")
    _enabled = settings.get("logging", False)

def debug(message):
    """Log a debug message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[DEBUG][{timestamp}] LiveServerPlus: {message}")

def info(message):
    """Log an info message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[INFO][{timestamp}] LiveServerPlus: {message}")

def warning(message):
    """Log a warning message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[WARNING][{timestamp}] LiveServerPlus: {message}")

def error(message):
    """Log an error message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[ERROR][{timestamp}] LiveServerPlus: {message}")

def set_level(level):
    """No-op function for backward compatibility"""
    pass

# Backward compatibility functions
def get_logger():
    """Backward compatibility - returns None"""
    return None

# Initialize settings and listener
settings = sublime.load_settings("LiveServerPlus.sublime-settings")
settings.add_on_change("lsp_logging_toggle", _on_settings_change)
_on_settings_change()  # Initialize the flag