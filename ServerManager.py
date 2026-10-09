# ServerManager.py
import os
import json
import sublime
import threading
from .liveserverplus_lib.server import Server
from .liveserverplus_lib.utils import openInBrowser
from .liveserverplus_lib.logging import info, error
from .liveserverplus_lib.qr_utils import get_local_ip
from .liveserverplus_lib.path_utils import build_base_url, join_base_and_path

SETTINGS_FILE = 'LiveServerPlus.sublime-settings'
SETTINGS_WATCH_KEY = 'liveserverplus_restart_watch'
SETTINGS_DEBOUNCE_MS = 300


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
        self._scroll_listeners = []
        self._watched_settings = None
        self._settings_check_token = 0
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
                if hasattr(self.server, 'websocket'):
                    self.server.websocket.set_message_handler(self._handle_websocket_message)
                self.server.start()
                self._watch_settings()
                return True
            except Exception as e:
                error(f"Failed to start server: {e}")
                sublime.error_message(f"[LiveServerPlus] Failed to start server: {e}")
                self.server = None
                return False
    
    def stop(self, on_done=None):
        """Stop the running live server.

        ``on_done()`` runs on the main thread once ``Server.stop()`` has
        returned, i.e. once the socket is closed. It is not called when no
        server was running (the return value is False then).
        """
        with self._lock:
            self._unwatch_settings()
            if not self.isRunning():
                info("No server running to stop")
                return False

            server_to_stop = self.server
            self.server = None  # Clear reference immediately

        def stop_server():
            try:
                server_to_stop.stop()
            except Exception as e:
                error(f"Error stopping server: {e}")
            finally:
                if on_done:
                    sublime.set_timeout(on_done, 0)

        try:
            info("Stopping server...")
            # Shut down on the worker thread (Server.stop() blocks briefly),
            # outside the lock so on_done may call start().
            sublime.set_timeout_async(stop_server, 0)
            return True
        except Exception as e:
            error(f"Error stopping server: {e}")
            sublime.error_message(f"[LiveServerPlus] Error stopping server: {e}")
            return False
    
    def restart(self, folders, on_done=None):
        """Stop the server, then start it on ``folders`` once it is fully down.

        ``on_done(success)`` runs on the main thread after the new server was
        started (or failed to). Starts right away if no server was running.
        """
        info("Restarting server...")
        folders = list(folders)

        def start_new_server():
            success = self.start(folders)
            if on_done:
                on_done(success)

        if not self.stop(on_done=start_new_server):
            start_new_server()
    
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

    def broadcastMessage(self, message):
        """Broadcast a custom message to all connected clients."""
        server = self.getServer()
        if not server:
            return False
        server.broadcast_message(message)
        return True

    def _watch_settings(self):
        """Follow settings-file edits while a server runs (one callback at most)."""
        settings = sublime.load_settings(SETTINGS_FILE)
        settings.clear_on_change(SETTINGS_WATCH_KEY)
        settings.add_on_change(SETTINGS_WATCH_KEY, self._on_settings_change)
        self._watched_settings = settings

    def _unwatch_settings(self):
        self._settings_check_token += 1  # drop a pending check
        if self._watched_settings is not None:
            self._watched_settings.clear_on_change(SETTINGS_WATCH_KEY)
            self._watched_settings = None

    def _on_settings_change(self):
        # Sublime can call this several times for one save; check once.
        self._settings_check_token += 1
        token = self._settings_check_token
        sublime.set_timeout(lambda: self._check_settings(token), SETTINGS_DEBOUNCE_MS)

    def _check_settings(self, token):
        """Apply live settings, and restart if a restart-only setting changed."""
        if token != self._settings_check_token:
            return
        server = self.getServer()
        if not server:
            return

        server.settings.refresh()
        if hasattr(server, 'status'):
            server.status.refresh()

        changed = server.settings.changed_restart_keys()
        if not changed:
            return

        info(f"Settings changed ({', '.join(changed)}); restarting server")
        if hasattr(server, 'status'):
            server.status.update('restarting')

        def on_restarted(success):
            if not success:
                sublime.error_message("[LiveServerPlus] Failed to restart server after a settings change.")

        self.restart(server.folders, on_done=on_restarted)

    def registerScrollSyncListener(self, callback):
        """Register callback for incoming markdown scroll events."""
        with self._lock:
            if callback not in self._scroll_listeners:
                self._scroll_listeners.append(callback)

    def _handle_websocket_message(self, message, conn):
        if not message:
            return

        try:
            payload = json.loads(message)
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        if payload.get('type') != 'markdown-scroll':
            return

        listeners_snapshot = []
        with self._lock:
            listeners_snapshot = list(self._scroll_listeners)

        for listener in listeners_snapshot:
            try:
                listener(payload)
            except Exception as exc:
                error(f"Scroll sync listener error: {exc}")
