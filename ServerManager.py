# ServerManager.py
import sublime
import threading
import os
from .liveserverplus_lib.server import Server
from .liveserverplus_lib.utils import open_in_browser
from .liveserverplus_lib.logging import info, error

class ServerManager:
    """Manages the lifecycle of LiveServerPlus server instances"""
    
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        """Get or create singleton instance with thread safety"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def __init__(self):
        self.server = None
        self.restart_pending = False
        info("ServerManager initialized")
    
    def is_running(self):
        """Check if server is currently running"""
        return self.server is not None and self.server.is_alive()
    
    def start(self, folders):
        """Start the live server with given folders"""
        with self._lock:
            if self.is_running():
                info("Server is already running")
                return False
            
            try:
                info(f"Starting server with folders: {folders}")
                self.server = Server(folders)
                self.server.start()
                return True
            except Exception as e:
                error(f"Failed to start server: {e}")
                sublime.error_message(f"[LiveServerPlus] Failed to start server: {e}")
                self.server = None
                return False
    
    def stop(self):
        """Stop the running live server"""
        with self._lock:
            if not self.is_running():
                info("No server running to stop")
                return False
                
            try:
                server_to_stop = self.server
                self.server = None  # Clear reference immediately
                info("Stopping server...")
                # Start shutdown in a daemon thread
                sublime.set_timeout_async(server_to_stop.stop, 0)
                return True
            except Exception as e:
                error(f"Error stopping server: {e}")
                sublime.error_message(f"[LiveServerPlus] Error stopping server: {e}")
                return False
    
    def restart(self, folders):
        """Restart the server with possibly new folders"""
        with self._lock:
            info("Restarting server...")
            was_running = self.is_running()
            if was_running:
                self.stop()
            success = self.start(folders)
            return success and was_running
    
    def get_server(self):
        """Get current server instance if running"""
        return self.server if self.is_running() else None
    
    def get_current_status(self):
        """Get current server status information"""
        if not self.is_running() or not self.server:
            return 'stopped', None
        
        if hasattr(self.server, 'status'):
            status, port = self.server.status.get_current_status()
            return status or 'running', port
        
        return 'running', getattr(self.server, 'port', None)
        
    def open_in_browser(self, url_path, browser=None):
        """Open a specific path in browser via the server"""
        server = self.get_server()
        if not server:
            info("Cannot open browser - server not running")
            return False
        
        host = 'localhost'  # Instead of server.settings.host
        port = server.settings.port
        browser = browser or server.settings.browser
        
        # Ensure path starts with / but doesn't have double //
        if url_path and not url_path.startswith('/'):
            url_path = f"/{url_path}"
            
        url = f"http://{host}:{port}{url_path}"
        info(f"Opening URL in browser: {url}")
        open_in_browser(url, browser)
        return True
    
    def is_file_allowed(self, file_path):
        """Check if file type is allowed by the server settings"""
        server = self.get_server()
        if not server:
            return False
            
        ext = os.path.splitext(file_path)[1].lower()
        return any(ext == allowed_ext.lower() 
                  for allowed_ext in server.settings.allowed_file_types)
                  
    def on_file_change(self, file_path):
        """Proxy for server's file change handler"""
        server = self.get_server()
        if server:
            info(f"File changed, notifying server: {file_path}")
            server.on_file_change(file_path)
            return True
        return False