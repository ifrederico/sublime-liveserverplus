# liveserverplus_lib/logging.py
import sublime
from datetime import datetime

# Global flag for logging state
_enabled = False

def _on_settings_change():
    """Update logging state when settings change"""
    global _enabled
    settings = sublime.load_settings("LiveServerPlus.sublime-settings")
    _enabled = settings.get("logging", False)

def info(message):
    """Log an info message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[LiveServerPlus {timestamp}] {message}")

def error(message):
    """Log an error message"""
    if _enabled:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[LiveServerPlus ERROR {timestamp}] {message}")

# Backward compatibility - map old functions to new ones
def debug(message):
    """Backward compatibility - maps to info"""
    pass  # Silent ignore for debug messages

def warning(message):
    """Backward compatibility - maps to info"""
    info(message)

# Backward compatibility functions
def set_level(level):
    """No-op function for backward compatibility"""
    pass

def get_logger():
    """Backward compatibility - returns None"""
    return None

# Initialize settings and listener
settings = sublime.load_settings("LiveServerPlus.sublime-settings")
settings.add_on_change("lsp_logging_toggle", _on_settings_change)
_on_settings_change()  # Initialize the flag