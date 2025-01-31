# LiveServerPlus.py
import sublime
import sublime_plugin
import os

# Direct relative imports from your subpackage
from .liveserverplus_lib.server import Server
from .liveserverplus_lib.utils import open_in_browser

# Global server instance
server_instance = None

def is_server_running():
    """Check if server is currently running"""
    global server_instance
    return server_instance is not None and server_instance.is_alive()

def live_server_start(folders):
    """Start the live server with given folders"""
    global server_instance
    
    if is_server_running():
        return False
    
    try:
        server_instance = Server(folders)
        server_instance.start()
        return True
    except Exception as e:
        sublime.error_message(f"Failed to start server: {e}")
        server_instance = None
        return False

def live_server_stop():
    """Stop the running live server"""
    global server_instance
    
    if server_instance and server_instance.is_alive():
        server_instance.stop()
        server_instance = None
        return True
    return False

def is_file_allowed(file_path):
    """Check if file type is allowed by the server settings"""
    if not server_instance:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return any(ext == allowed_ext.lower() 
              for allowed_ext in server_instance.settings.allowed_file_types)

class LiveServerStartCommand(sublime_plugin.WindowCommand):
    """Command to start the Live Server"""
    
    def run(self):
        if is_server_running():
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
        if live_server_start(folders):
            if server_instance and server_instance.settings.browser_open_on_start:
                url = f"http://{server_instance.settings.host}:{server_instance.settings.port}/"
                browser = server_instance.settings.browser
                open_in_browser(url, browser)
                
    def is_enabled(self):
        return not is_server_running()

class LiveServerStopCommand(sublime_plugin.WindowCommand):
    """Command to stop the Live Server"""
    
    def run(self):
        if not is_server_running():
            sublime.status_message("Live Server is not running")
            return
            
        if live_server_stop():
            sublime.status_message("Live Server stopped")
            
    def is_enabled(self):
        return is_server_running()

class OpenCurrentFileLiveServerCommand(sublime_plugin.WindowCommand):
    """Command to open the current file in the browser (via Live Server)"""
    
    def run(self):
        if not is_server_running():
            sublime.status_message("Live Server is not running")
            return
            
        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("No file to open")
            return
            
        file_path = view.file_name()
        
        # Find relative path from served folders
        rel_path = None
        for folder in server_instance.folders:
            if file_path.startswith(folder):
                rel_path = os.path.relpath(file_path, folder)
                break
                
        # If file is not in served folders, auto-add its directory
        if not rel_path:
            folder = os.path.dirname(file_path)
            if folder not in server_instance.folders_set:
                server_instance.folders.append(folder)
                server_instance.folders_set.add(folder)
            rel_path = os.path.basename(file_path)
        
        if is_file_allowed(file_path):
            url = f"http://{server_instance.settings.host}:{server_instance.settings.port}/{rel_path.replace(os.sep, '/')}"
        else:
            # For unsupported files, show the directory
            dir_path = os.path.dirname(rel_path)
            url = f"http://{server_instance.settings.host}:{server_instance.settings.port}/{dir_path.replace(os.sep, '/')}"
        
        browser = server_instance.settings.browser
        open_in_browser(url, browser)
        
    def is_enabled(self):
        return (
            is_server_running() and 
            bool(self.window.active_view() and self.window.active_view().file_name())
        )

def plugin_loaded():
    """Called by Sublime Text when plugin is loaded."""
    pass

def plugin_unloaded():
    """Called by Sublime Text when plugin is unloaded."""
    if is_server_running():
        live_server_stop()


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
        if not (server_instance and server_instance.is_alive()):
            return
        
        # Check if user turned on Sublime-based live reload
        lr_settings = server_instance.settings._settings.get("live_reload", {})
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
        server_instance.on_file_change(file_path)

    def on_modified_async(self, view):
        """
        If 'delay' > 0, we do a small debounce to avoid reloading
        on every keystroke. If 'delay' == 0, reload immediately.
        """
        if not (server_instance and server_instance.is_alive()):
            return
        
        lr_settings = server_instance.settings._settings.get("live_reload", {})
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
            server_instance.on_file_change(file_path)
            return
        
        # Debounce with a callback
        def check_debounce():
            if (time.time() - _last_modified[file_path]) >= (delay_ms / 1000.0):
                server_instance.on_file_change(file_path)
        
        sublime.set_timeout_async(check_debounce, delay_ms)