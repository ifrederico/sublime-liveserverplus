# LiveServerPlus.py
import sublime
import sublime_plugin
import os
import sys

# Ignore fsevents
import warnings
warnings.filterwarnings("ignore", message="Failed to import fsevents")

# Add vendor directory to Python path
PACKAGE_PATH = os.path.dirname(os.path.abspath(__file__))
VENDOR_PATH = os.path.join(PACKAGE_PATH, 'liveserverplus_lib', 'vendor')
if VENDOR_PATH not in sys.path:
    sys.path.insert(0, VENDOR_PATH)

# Now the imports will work
from .liveserverplus_lib.utils import open_in_browser
from .ServerManager import ServerManager

def is_server_running():
    """Check if server is currently running - compatibility function"""
    return ServerManager.get_instance().is_running()

def live_server_start(folders):
    """Start the live server with given folders - compatibility function"""
    return ServerManager.get_instance().start(folders)

def live_server_stop():
    """Stop the running live server - compatibility function"""
    return ServerManager.get_instance().stop()

def is_file_allowed(file_path):
    """Check if file type is allowed by the server settings - compatibility function"""
    return ServerManager.get_instance().is_file_allowed(file_path)

class LiveServerStartCommand(sublime_plugin.WindowCommand):
    """Command to start the Live Server"""
    
    def run(self):
        manager = ServerManager.get_instance()
        
        if manager.is_running():
            sublime.status_message("Live Server is already running")
            return
            
        view = self.window.active_view()
        file_path = view.file_name() if view else None
        
        # Get project folders
        folders = self.window.folders()
        
        # If we have an active file, use its directory
        if file_path:
            file_dir = os.path.dirname(file_path)
            folders = [file_dir]
        elif not folders:
            sublime.error_message("Open a folder or workspace... (File -> Open Folder)")
            return
            
        # Start the server
        if manager.start(folders):
            server = manager.get_server()
            if server and server.settings.browser_open_on_start:
                manager.open_in_browser("/")
                
    def is_enabled(self):
        return not ServerManager.get_instance().is_running()

class LiveServerStopCommand(sublime_plugin.WindowCommand):
    """Command to stop the Live Server"""
    
    def run(self):
        manager = ServerManager.get_instance()
        
        if not manager.is_running():
            sublime.status_message("Live Server is not running")
            return
            
        if manager.stop():
            sublime.status_message("Live Server stopped")
            
    def is_enabled(self):
        return ServerManager.get_instance().is_running()

class OpenCurrentFileLiveServerCommand(sublime_plugin.WindowCommand):
    """Command to open the current file in the browser (via Live Server)"""
    
    def run(self):
        manager = ServerManager.get_instance()
        
        if not manager.is_running():
            sublime.status_message("Live Server is not running")
            return
            
        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file to open")
            return
            
        file_path = view.file_name()
        server = manager.get_server()
        
        # Find relative path from served folders
        rel_path = None
        for folder in server.folders:
            if file_path.startswith(folder):
                rel_path = os.path.relpath(file_path, folder)
                break
                
        # If file is not in served folders, auto-add its directory
        if not rel_path:
            folder = os.path.dirname(file_path)
            if folder not in server.folders_set:
                server.folders.append(folder)
                server.folders_set.add(folder)
            rel_path = os.path.basename(file_path)
        
        # Replace backslashes with forward slashes for URL path
        url_path = rel_path.replace(os.sep, '/')
        
        # For unsupported files, show the directory instead
        if not manager.is_file_allowed(file_path):
            dir_path = os.path.dirname(url_path)
            manager.open_in_browser(dir_path)
        else:
            manager.open_in_browser(url_path)
        
    def is_enabled(self):
        manager = ServerManager.get_instance()
        return (
            manager.is_running() and 
            bool(self.window.active_view() and self.window.active_view().file_name())
        )

def plugin_loaded():
    """Called by Sublime Text when plugin is loaded."""
    # Initialize ServerManager singleton
    ServerManager.get_instance()

def plugin_unloaded():
    """Called by Sublime Text when plugin is unloaded."""
    try:
        manager = ServerManager.get_instance()
        if manager.is_running():
            # Update status to "Server closing" before stopping
            server = manager.get_server()
            if server:
                server.status.update('Server closing')
            manager.stop()
        
        # Clear singleton instance to prevent memory leaks
        ServerManager._instance = None
    except Exception as e:
        print(f"Error during plugin unload: {e}")


# ----------------------------------------------------
# ADDED: Sublime-based Live Reload EventListener
# ----------------------------------------------------
import time

_last_modified = {}

class LiveServerPlusListener(sublime_plugin.EventListener):
    """
    If 'live_reload.enabled' == true, we skip the file watcher
    and use Sublime's events to notify the server immediately
    after a file is changed or saved. If 'false', we do nothing.
    """
    def on_post_save_async(self, view):
        """Immediately notify on file save (no debounce needed)."""
        manager = ServerManager.get_instance()
        server = manager.get_server()
        
        if not server:
            return
        
        # Check if user turned on Sublime-based live reload
        lr_settings = server.settings._settings.get("live_reload", {})
        if not lr_settings.get("enabled", False):
            return  # rely on the file watcher instead

        file_path = view.file_name()
        if not file_path:
            return
        
        # We might skip certain extensions (log files, etc.)
        ignore_exts = lr_settings.get("ignore_exts", [])
        if any(file_path.lower().endswith(ext) for ext in ignore_exts):
            return
        
        # If we got here => immediate reload
        manager.on_file_change(file_path)

    def on_modified_async(self, view):
        """
        If 'delay' > 0, we do a small debounce to avoid reloading
        on every keystroke. If 'delay' == 0, reload immediately.
        """
        manager = ServerManager.get_instance()
        server = manager.get_server()
        
        if not server:
            return
        
        lr_settings = server.settings._settings.get("live_reload", {})
        if not lr_settings.get("enabled", False):
            return  # If disabled, do nothing

        file_path = view.file_name()
        if not file_path:
            return
        
        # Check if extension is ignored
        ignore_exts = lr_settings.get("ignore_exts", [])
        if any(file_path.lower().endswith(ext) for ext in ignore_exts):
            return

        delay_ms = lr_settings.get("delay", 0)
        _last_modified[file_path] = time.time()
        
        if delay_ms <= 0:
            # no debounce, immediate
            manager.on_file_change(file_path)
            return
        
        # Debounce with a callback
        def check_debounce():
            if (time.time() - _last_modified[file_path]) >= (delay_ms / 1000.0):
                manager.on_file_change(file_path)
        
        sublime.set_timeout_async(check_debounce, delay_ms)