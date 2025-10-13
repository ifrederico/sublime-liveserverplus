# ServerManager.py
import os
import sublime
import threading
from .liveserverplus_lib.server import Server
from .liveserverplus_lib.utils import openInBrowser
from .liveserverplus_lib.logging import info, error
from .liveserverplus_lib.qr_utils import get_local_ip
from .liveserverplus_lib.path_utils import build_base_url, join_base_and_path

class ServerManager:
    """Manages the lifecycle of LiveServerPlus server instances"""
    
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def getInstance(cls):
        """Get or create singleton instance with thread safety"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def __init__(self):
        self.server = None
        self.restart_pending = False
        info("ServerManager initialized")
    
    def isRunning(self):
        """Check if server is currently running"""
        return self.server is not None and self.server.is_alive()
    
    def start(self, folders):
        """Start the live server with given folders"""
        with self._lock:
            if self.isRunning():
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
            if not self.isRunning():
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
            was_running = self.isRunning()
            if was_running:
                self.stop()
            success = self.start(folders)
            return success and was_running
    
    def getServer(self):
        """Get current server instance if running"""
        return self.server if self.isRunning() else None
    
    def getCurrentStatus(self):
        """Get current server status information"""
        if not self.isRunning() or not self.server:
            return 'stopped', None
        
        if hasattr(self.server, 'status'):
            status, port = self.server.status.getCurrentStatus()
            return status or 'running', port
        
        return 'running', getattr(self.server, 'port', None)
        
    def openInBrowser(self, url_path, browser=None):
        """Open a specific path in browser via the server"""
        server = self.getServer()
        if not server:
            info("Cannot open browser - server not running")
            return False

        if not server.settings.openBrowser:
            return False

        protocol = 'http'

        if server.settings.useLocalIp:
            try:
                host = get_local_ip()
            except Exception:
                host = server.settings.host or '127.0.0.1'
        else:
            host = server.settings.host or '127.0.0.1'

        status_port = None
        if hasattr(server, 'status'):
            status_port = server.status.getCurrentStatus()[1]

        port = status_port or server.settings.port
        browser = browser or server.settings.customBrowser

        base_url = build_base_url(protocol, host, port)

        url = join_base_and_path(base_url, url_path)

        info(f"Opening URL in browser: {url}")
        openInBrowser(url, browser)
        return True
    
    def isFileAllowed(self, file_path):
        """Check if file type is allowed by the server settings"""
        server = self.getServer()
        if not server:
            return False
            
        ext = os.path.splitext(file_path)[1].lower()
        return any(ext == allowed_ext.lower()
                  for allowed_ext in server.settings.allowedFileTypes)
                  
    def onFileChange(self, file_path):
        """Proxy for server's file change handler"""
        server = self.getServer()
        if server:
            info(f"File changed, notifying server: {file_path}")
            server.onFileChange(file_path)
            return True
        return False
