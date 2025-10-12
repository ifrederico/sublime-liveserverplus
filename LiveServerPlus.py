# LiveServerPlus.py
import sublime
import sublime_plugin
import os
import sys
import time
from pathlib import PurePosixPath

# Ignore fsevents
import warnings
warnings.filterwarnings("ignore", message="Failed to import fsevents")

# Add vendor directory to Python path
PACKAGE_PATH = os.path.dirname(os.path.abspath(__file__))
VENDOR_PATH = os.path.join(PACKAGE_PATH, 'liveserverplus_lib', 'vendor')
if VENDOR_PATH not in sys.path:
    sys.path.insert(0, VENDOR_PATH)

# Now the imports will work
from .liveserverplus_lib.utils import openInBrowser
from .liveserverplus_lib.logging import info, error
from .ServerManager import ServerManager

from .liveserverplus_lib.qr_utils import (get_server_urls, generate_qr_code_base64, HAS_QR_SUPPORT, get_local_ip)


_last_modified = {}

def is_server_running():
    """Check if server is currently running - compatibility function"""
    return ServerManager.getInstance().isRunning()

def live_server_start(folders):
    """Start the live server with given folders - compatibility function"""
    return ServerManager.getInstance().start(folders)

def live_server_stop():
    """Stop the running live server - compatibility function"""
    return ServerManager.getInstance().stop()

def isFileAllowed(file_path):
    """Check if file type is allowed by the server settings - compatibility function"""
    return ServerManager.getInstance().isFileAllowed(file_path)


def _info_messages_enabled():
    manager = ServerManager.getInstance()
    server = manager.getServer()
    if server:
        return server.settings.showInfoMessages
    settings = sublime.load_settings("LiveServerPlus.sublime-settings")
    return bool(settings.get('showInfoMessages', True))


def _status_message(message):
    if _info_messages_enabled():
        sublime.status_message(message)


def _matches_ignore_patterns(file_path, patterns):
    if not patterns:
        return False

    normalized_path = os.path.normpath(file_path).replace('\\', '/')
    path_obj = PurePosixPath(normalized_path)

    for pattern in patterns:
        if not pattern:
            continue
        normalized_pattern = pattern.replace('\\', '/')
        if path_obj.match(normalized_pattern):
            return True
    return False

class LiveServerShowQrCommand(sublime_plugin.WindowCommand):
    """Show QR code for mobile device access"""
    
    def run(self):
        manager = ServerManager.getInstance()
        
        if not manager.isRunning():
            _status_message("Live Server is not running")
            return
        
        if not HAS_QR_SUPPORT:
            sublime.error_message(
                "QR code generation not available.\n\n"
                "The pyqrcode and pypng libraries are missing from the vendor folder."
            )
            return
            
        server = manager.getServer()
        if not server:
            return
            
        # Get server info
        protocol = 'http'
        configured_host = server.settings.host or '127.0.0.1'
        prefer_local = server.settings.useLocalIp or configured_host in ['127.0.0.1', 'localhost', '0.0.0.0']
        host = get_local_ip() if prefer_local else configured_host
        port = server.settings.port

        # Get URLs
        urls = get_server_urls(host, port, protocol=protocol, prefer_local_ip=prefer_local)
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
                base = primary_url.rstrip('/')
                primary_url = f"{base}/{url_path.lstrip('/')}"
        
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
        return ServerManager.getInstance().isRunning()
    
class LiveServerStartCommand(sublime_plugin.WindowCommand):
    """Enhanced start command with folder selection"""
    
    def run(self, folders=None):
        manager = ServerManager.getInstance()
        
        if manager.isRunning():
            _status_message("Live Server is already running")
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
        manager = ServerManager.getInstance()
        if manager.start(folders):
            server = manager.getServer()
            if server and server.settings.openBrowser:
                # Prepare desired path
                target_path = "/"
                view = self.window.active_view()
                if view and view.file_name() and manager.isFileAllowed(view.file_name()):
                    file_path = view.file_name()
                    for folder in folders:
                        if file_path.startswith(folder):
                            rel_path = os.path.relpath(file_path, folder)
                            target_path = rel_path.replace(os.sep, '/')
                            break

                def open_when_ready(path, attempt=0):
                    if not manager.isRunning():
                        return
                    srv = manager.getServer()
                    if not srv:
                        if attempt < 20:
                            sublime.set_timeout(lambda: open_when_ready(path, attempt + 1), 100)
                        return
                    port_ready = False
                    if hasattr(srv, 'status'):
                        status, bound_port = srv.status.getCurrentStatus()
                        port_ready = bool(bound_port)
                    if port_ready or attempt >= 20:
                        manager.openInBrowser(path)
                    else:
                        sublime.set_timeout(lambda: open_when_ready(path, attempt + 1), 100)

                sublime.set_timeout(lambda: open_when_ready(target_path), 150)
                
    def is_enabled(self):
        return not ServerManager.getInstance().isRunning()

class LiveServerStopCommand(sublime_plugin.WindowCommand):
    """Command to stop the Live Server"""
    
    def run(self):
        manager = ServerManager.getInstance()
        
        if not manager.isRunning():
            _status_message("Live Server is not running")
            return
            
        manager.stop()
            
    def is_enabled(self):
        return ServerManager.getInstance().isRunning()

class OpenCurrentFileLiveServerCommand(sublime_plugin.WindowCommand):
    """Command to open the current file in the browser (via Live Server)"""
    
    def run(self):
        manager = ServerManager.getInstance()
        
        if not manager.isRunning():
            _status_message("Live Server is not running")
            return
            
        view = self.window.active_view()
        if not view or not view.file_name():
            _status_message("No file to open")
            return
            
        file_path = view.file_name()
        server = manager.getServer()
        
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
        if not manager.isFileAllowed(file_path):
            dir_path = os.path.dirname(url_path)
            manager.openInBrowser(dir_path)
        else:
            manager.openInBrowser(url_path)
        
    def is_enabled(self):
        manager = ServerManager.getInstance()
        return (
            manager.isRunning() and 
            bool(self.window.active_view() and self.window.active_view().file_name())
        )

class LiveServerChangePortCommand(sublime_plugin.WindowCommand):
    """Change server port via input panel"""
    
    def run(self):
        manager = ServerManager.getInstance()
        
        # Get current port
        current_port = "8080"
        if manager.isRunning():
            server = manager.getServer()
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
        manager = ServerManager.getInstance()
        if manager.isRunning():
            folders = manager.getServer().folders
            manager.stop()
            sublime.set_timeout(lambda: manager.start(folders), 100)
            _status_message(f"Restarting server on port {port}...")
        else:
            _status_message(f"Port changed to {port}")

class LiveServerSetLiveReloadCommand(sublime_plugin.WindowCommand):
    """Enable or disable live reload via Sublime saves."""

    def run(self, value):
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        current_state = bool(settings.get("liveReload", False))
        new_state = bool(value)

        if current_state == new_state:
            status = "enabled" if new_state else "disabled"
            _status_message(f"Live reload {status}")
            return

        manager = ServerManager.getInstance()
        if manager.isRunning():
            folders = manager.getServer().folders
            manager.stop()
            def restart():
                settings.set("liveReload", new_state)
                sublime.save_settings("LiveServerPlus.sublime-settings")
                manager.start(folders)
            sublime.set_timeout(restart, 300)
        else:
            settings.set("liveReload", new_state)
            sublime.save_settings("LiveServerPlus.sublime-settings")

        status = "enabled" if new_state else "disabled"
        _status_message(f"Live reload {status}")

    def _is_web_file(self, view):
        if not view or not view.file_name():
            return False
        ext = os.path.splitext(view.file_name())[1].lower()
        web_extensions = ['.html', '.htm', '.css', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte']
        return ext in web_extensions

    def is_enabled(self, value=True):
        return self._is_web_file(self.window.active_view())

    def is_visible(self, value=True):
        if not self._is_web_file(self.window.active_view()):
            return False
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        current_state = bool(settings.get("liveReload", False))
        return bool(value) != current_state

    def description(self, value=True):
        return "Enable Live Reload" if value else "Disable Live Reload"


class LiveServerPlusListener(sublime_plugin.EventListener):
    """Triggers live reload when Sublime saves files."""

    def __init__(self):
        self._last_change_count = {}

    def _should_trigger(self, manager, server, file_path):
        if not file_path:
            return False
        if _matches_ignore_patterns(file_path, server.settings.ignorePatterns):
            return False

        ignore_exts = getattr(server.settings, 'ignoreExtensions', [])
        lower_path = file_path.lower()
        for ext in ignore_exts:
            if lower_path.endswith(ext.lower()):
                return False

        return manager.isFileAllowed(file_path)

    def on_post_save_async(self, view):
        manager = ServerManager.getInstance()
        server = manager.getServer()
        if not server or not server.settings.liveReload:
            return

        file_path = view.file_name()
        if not self._should_trigger(manager, server, file_path):
            return

        info(f"Live reload (save): {file_path}")
        manager.onFileChange(file_path)

    def on_modified_async(self, view):
        manager = ServerManager.getInstance()
        server = manager.getServer()
        if not server or not server.settings.liveReload:
            return

        if view.is_auto_complete_visible():
            return

        file_path = view.file_name()
        if not self._should_trigger(manager, server, file_path):
            return

        change_count = view.change_count()
        last_count = self._last_change_count.get(view.id(), -1)
        if change_count == last_count:
            return
        self._last_change_count[view.id()] = change_count

        delay_ms = server.settings.waitTimeMs
        timestamp = time.time()
        _last_modified[file_path] = timestamp

        if delay_ms <= 0:
            info(f"Live reload (instant): {file_path}")
            view.run_command('save')
            return

        def check_debounce(v=view, path=file_path, stamp=timestamp):
            if _last_modified.get(path) != stamp:
                return
            info(f"Live reload (debounced): {path}")
            v.run_command('save')

        sublime.set_timeout_async(check_debounce, delay_ms)

class LiveServerContextProvider(sublime_plugin.EventListener):
    """Provides context for key bindings"""
    
    def on_query_context(self, view, key, operator, operand, match_all):
        """Handle context queries for key bindings"""
        
        if key == "liveserver_running":
            running = ServerManager.getInstance().isRunning()
            
            if operator == sublime.OP_EQUAL:
                return running == operand
            elif operator == sublime.OP_NOT_EQUAL:
                return running != operand
                
        return None

def plugin_loaded():
    """Called by Sublime Text when plugin is loaded."""
    info("Plugin loaded")
    # Initialize ServerManager singleton
    ServerManager.getInstance()

def plugin_unloaded():
    """Called by Sublime Text when plugin is unloaded."""
    try:
        info("Plugin unloading")
        manager = ServerManager.getInstance()
        if manager.isRunning():
            # Update status to "stopping" before stopping
            server = manager.getServer()
            if server:
                server.status.update('stopping')  # Changed from 'Server closing'
            manager.stop()
        
        # Clear singleton instance to prevent memory leaks
        ServerManager._instance = None
        info("Plugin unloaded successfully")
    except Exception as e:
        error(f"Error during plugin unload: {e}")
