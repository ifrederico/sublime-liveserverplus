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
from .liveserverplus_lib.logging import info, error
from .ServerManager import ServerManager

from .liveserverplus_lib.qr_utils import (get_server_urls, generate_qr_code_base64, HAS_QR_SUPPORT, get_local_ip)

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

class LiveServerShowQrCommand(sublime_plugin.WindowCommand):
    """Show QR code for mobile device access"""
    
    def run(self):
        manager = ServerManager.get_instance()
        
        if not manager.is_running():
            sublime.status_message("Live Server is not running")
            return
        
        if not HAS_QR_SUPPORT:
            sublime.error_message(
                "QR code generation not available.\n\n"
                "The pyqrcode and pypng libraries are missing from the vendor folder."
            )
            return
            
        server = manager.get_server()
        if not server:
            return
            
        # Get server info
        host = server.settings.host
        port = server.settings.port
        
        # Get URLs
        urls = get_server_urls(host, port)
        primary_url = urls['primary']
        
        # FIX: Get current file path and append to URL
        view = self.window.active_view()
        if view and view.file_name():
            file_path = view.file_name()
            
            # Find relative path from served folders
            rel_path = None
            for folder in server.folders:
                if file_path.startswith(folder):
                    rel_path = os.path.relpath(file_path, folder)
                    break
            
            # If we found a relative path, append it to the URL
            if rel_path:
                # Convert to URL format (forward slashes)
                url_path = rel_path.replace(os.sep, '/')
                primary_url = f"{primary_url}/{url_path}"
        
        # Generate PNG QR code
        qr_base64 = generate_qr_code_base64(primary_url)
        
        if not qr_base64:
            sublime.error_message("Failed to generate QR code")
            return
        
        # Show popup
        self._show_qr_popup(primary_url, qr_base64, port)
    
    def _show_qr_popup(self, url, qr_base64, port):
        """Display the QR code popup"""
        local_ip = get_local_ip()
        
        # Extract just the filename for display
        display_file = url.split('/')[-1] if '/' in url else "root"
        
        html = f"""<div style="padding: 20px; text-align: center;">
            <h3 style="margin: 0 0 15px 0;">📱 Mobile Preview</h3>
            <p style="font-size: 0.9em; color: #666;">Current file: <strong>{display_file}</strong></p>
            <p style="font-family: monospace; word-break: break-all; margin: 15px 0; font-size: 0.85em;">{url}</p>
            <img src="data:image/png;base64,{qr_base64}" width="200" height="200">
            <p style="margin-top: 20px; font-size: 0.9em; color: #666;">ESC to close</p>
        </div>"""
        
        view = self.window.active_view()
        if view:
            # Simple center: middle of visible region
            visible = view.visible_region()
            center = (visible.begin() + visible.end()) // 2
            
            view.show_popup(
                html,
                flags=0,
                location=center,
                max_width=300,
                max_height=400
            )
            info(f"QR popup shown for {url}")
    
    def is_enabled(self):
        """Only enable when server is running"""
        return ServerManager.get_instance().is_running()
    
class LiveServerStartCommand(sublime_plugin.WindowCommand):
    """Enhanced start command with folder selection"""
    
    def run(self, folders=None):
        manager = ServerManager.get_instance()
        
        if manager.is_running():
            sublime.status_message("Live Server is already running")
            return
        
        # If folders explicitly passed, use them
        if folders:
            self._start_server(folders)
            return
            
        # Get all possible folders
        all_folders = self._get_all_folders()
        
        if not all_folders:
            sublime.error_message("Open a folder or workspace... (File -> Open Folder)")
            return
        
        # If only one folder, start immediately
        if len(all_folders) == 1:
            self._start_server([all_folders[0]['path']])
            return
            
        # Show quick panel for multiple folders
        items = []
        for folder in all_folders:
            items.append([
                folder['name'],
                folder['path']
            ])
        
        # Add "All Folders" option at the top
        items.insert(0, ["All Folders", "Serve all open folders"])
        
        def on_select(index):
            if index == -1:
                return
            elif index == 0:
                # Serve all folders
                paths = [f['path'] for f in all_folders]
                self._start_server(paths)
            else:
                # Serve selected folder
                self._start_server([all_folders[index - 1]['path']])
        
        self.window.show_quick_panel(items, on_select)
    
    def _get_all_folders(self):
        """Get all folders from window and current file"""
        folders = []
        
        # Add project folders
        for folder in self.window.folders():
            folders.append({
                'name': os.path.basename(folder),
                'path': folder
            })
        
        # Add current file's folder if not already included
        view = self.window.active_view()
        if view and view.file_name():
            file_dir = os.path.dirname(view.file_name())
            if not any(f['path'] == file_dir for f in folders):
                folders.append({
                    'name': os.path.basename(file_dir) + " (current file)",
                    'path': file_dir
                })
        
        return folders
    
    def _start_server(self, folders):
        """Start server with given folders"""
        manager = ServerManager.get_instance()
        if manager.start(folders):
            server = manager.get_server()
            if server and server.settings.browser_open_on_start:
                # Try to open the current file instead of root
                view = self.window.active_view()
                if view and view.file_name() and manager.is_file_allowed(view.file_name()):
                    # Get relative path from the current file
                    file_path = view.file_name()
                    rel_path = None
                    for folder in folders:
                        if file_path.startswith(folder):
                            rel_path = os.path.relpath(file_path, folder)
                            break
                    if rel_path:
                        manager.open_in_browser(rel_path.replace(os.sep, '/'))
                    else:
                        manager.open_in_browser("/")
                else:
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

class LiveServerChangePortCommand(sublime_plugin.WindowCommand):
    """Change server port via input panel"""
    
    def run(self):
        manager = ServerManager.get_instance()
        
        # Get current port
        current_port = "8080"
        if manager.is_running():
            server = manager.get_server()
            if server:
                current_port = str(server.settings.port)
        else:
            settings = sublime.load_settings("LiveServerPlus.sublime-settings")
            current_port = str(settings.get('port', 8080))
        
        # Show input panel
        self.window.show_input_panel(
            "Live Server Port:",
            current_port,
            self.on_port_input,
            None,
            None
        )
    
    def on_port_input(self, port_str):
        """Handle port input"""
        port_str = port_str.strip()
        if port_str == "0":
            port = 0 # Random port
        else:
            try:
                port = int(port_str)
            except ValueError:
                sublime.error_message("Invalid port number")
                return
            
            if not (1 <= port <= 65535):
                sublime.error_message("Port must be between 1 and 65535, or 0 for random")
                return
        
        # Update settings
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        settings.set('port', port)
        sublime.save_settings("LiveServerPlus.sublime-settings")
        
        # Restart server if running
        manager = ServerManager.get_instance()
        if manager.is_running():
            folders = manager.get_server().folders
            manager.stop()
            sublime.set_timeout(lambda: manager.start(folders), 100)
            sublime.status_message(f"Restarting server on port {port}...")
        else:
            sublime.status_message(f"Port changed to {port}")

class LiveServerToggleLiveReloadCommand(sublime_plugin.WindowCommand):
    """Toggle live reload on/off"""
    
    def run(self):
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        live_reload = settings.get("live_reload", {})
        current_state = live_reload.get("enabled", False)
        
        # Toggle the state
        live_reload["enabled"] = not current_state
        settings.set("live_reload", live_reload)
        sublime.save_settings("LiveServerPlus.sublime-settings")
        
        # Show status message
        status = "enabled" if live_reload["enabled"] else "disabled"
        
        # If server is running, stop it and inform user to restart
        manager = ServerManager.get_instance()
        if manager.is_running():
            manager.stop()
            sublime.status_message(f"Live reload {status}. Server stopped - please restart the server for changes to take effect.")
            
            # Show an alert dialog for better visibility
            sublime.message_dialog(
                f"Live reload has been {status}.\n\n"
                "The server has been stopped. Please start it again for the changes to take effect."
            )
        else:
            sublime.status_message(f"Live reload {status}")
    
    def is_enabled(self):
        """Always enabled when editing web files"""
        view = self.window.active_view()
        if not view or not view.file_name():
            return False
            
        ext = os.path.splitext(view.file_name())[1].lower()
        web_extensions = ['.html', '.htm', '.css', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte']
        return ext in web_extensions
    
    def description(self):
        """Dynamic menu text based on current state"""
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        live_reload = settings.get("live_reload", {})
        is_enabled = live_reload.get("enabled", False)
        
        if is_enabled:
            return "Disable Live Reload"
        else:
            return "Enable Live Reload"

class LiveServerContextProvider(sublime_plugin.EventListener):
    """Provides context for key bindings"""
    
    def on_query_context(self, view, key, operator, operand, match_all):
        """Handle context queries for key bindings"""
        
        if key == "liveserver_running":
            running = ServerManager.get_instance().is_running()
            
            if operator == sublime.OP_EQUAL:
                return running == operand
            elif operator == sublime.OP_NOT_EQUAL:
                return running != operand
                
        return None

def plugin_loaded():
    """Called by Sublime Text when plugin is loaded."""
    info("Plugin loaded")
    # Initialize ServerManager singleton
    ServerManager.get_instance()

def plugin_unloaded():
    """Called by Sublime Text when plugin is unloaded."""
    try:
        info("Plugin unloading")
        manager = ServerManager.get_instance()
        if manager.is_running():
            # Update status to "stopping" before stopping
            server = manager.get_server()
            if server:
                server.status.update('stopping')  # Changed from 'Server closing'
            manager.stop()
        
        # Clear singleton instance to prevent memory leaks
        ServerManager._instance = None
        info("Plugin unloaded successfully")
    except Exception as e:
        error(f"Error during plugin unload: {e}")


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
    def __init__(self):
        self._last_change_count = {}

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
        info(f"File saved, triggering reload: {file_path}")
        manager.on_file_change(file_path)

    def on_modified_async(self, view):
        """
        If 'delay' > 0, we do a small debounce to avoid reloading
        on every keystroke. If 'delay' == 0, reload immediately.
        """
        # Skip if file hasn't actually changed
        change_count = view.change_count()
        last_count = self._last_change_count.get(view.id(), -1)
        if change_count == last_count:
            return
        self._last_change_count[view.id()] = change_count
        
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
            info(f"File modified, auto-saving and triggering immediate reload: {file_path}")
            view.run_command('save')  # Auto-save the file
            # The on_post_save_async will handle the reload
            return
        
        # Debounce with a callback
        def check_debounce():
            if (time.time() - _last_modified[file_path]) >= (delay_ms / 1000.0):
                info(f"File modified, auto-saving and triggering debounced reload: {file_path}")
                view.run_command('save')  # Auto-save the file
                # The on_post_save_async will handle the reload
        
        sublime.set_timeout_async(check_debounce, delay_ms)