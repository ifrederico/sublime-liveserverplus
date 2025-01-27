import sublime
import sublime_plugin
import webbrowser
import os
from pathlib import Path

# Direct relative imports from the subpackage
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
        
        # If we have an active file, use its directory instead of project folders
        if file_path:
            file_dir = os.path.dirname(file_path)
            folders = [file_dir]
        elif not folders:
            # No folders and no file
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
        
        # Determine URL based on file type
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