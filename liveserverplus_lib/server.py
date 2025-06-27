# server.py
"""Server implementation module - refactored version"""
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .websocket import WebSocketHandler
from .file_watcher import FileWatcher
from .settings import ServerSettings
from .status import ServerStatus
from .request_handler import RequestHandler
from .logging import info, error
from .utils import get_free_port
from .connection_manager import ConnectionManager


class Server(threading.Thread):
    """Main server class that handles HTTP requests and WebSocket connections"""
    
    def __init__(self, folders):
        super(Server, self).__init__(daemon=True)
        self.folders = list(folders)
        self.folders_set = set(folders)
        self.settings = ServerSettings()
        self.status = ServerStatus()
        self.executor = ThreadPoolExecutor(
            max_workers=self.settings.max_threads,
                thread_name_prefix='LSP-Worker'
            )
        self.websocket = WebSocketHandler()
        self.websocket.settings = self.settings
        self.file_watcher = None
        self._stop_flag = False
        self.sock = None
        self.request_handler = None
        
        # Initialize managers
        
        self.connection_manager = ConnectionManager.get_instance()
        self.connection_manager.configure(self.settings)

    def run(self):
        """Start the server"""
        try:
            info("Server starting...")
            self._setup_socket()
            self._setup_file_watcher()
            
            # Create request handler
            self.request_handler = RequestHandler(self)
            
            # Update status
            self.status.update('running', self.settings.port)
            info(f"Server running on {self.settings.host}:{self.settings.port}")
            
            # Main connection loop
            self._accept_connections()
            
        except Exception as e:
            error(f"Critical server error: {e}")
            import traceback
            error(traceback.format_exc())
            self.status.update('error', self.settings.port, str(e))

    def _setup_socket(self):
        """Set up the server socket with error handling"""
        import errno
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Optimize socket buffer sizes for better throughput
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # 64KB send buffer
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64KB receive buffer

        host = self.settings.host
        port = self.settings.port
        
        try:
            self.sock.bind((host, port))
            info(f"Successfully bound to {host}:{port}")
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                # Port in use, try to find a free port
                info(f"Port {port} is in use, searching for free port...")
                free_port = get_free_port(49152, 65535)
                
                if free_port is None:
                    self.status.update('error', port, f"Port {port} is in use and no free port available.")
                    error(f"Port {port} is in use and no free port available.")
                    raise
                    
                info(f"Port {port} is in use. Using free port {free_port}.")
                self.settings._settings.set('port', free_port)
                self.settings._ephemeral_port_cache = free_port
                self.sock.bind((host, free_port))
                info(f"Successfully bound to {host}:{free_port}")
            else:
                error(f"Unexpected error binding to port: {e}")
                raise
                
        self.sock.listen(5)

    def _setup_file_watcher(self):
        """Set up file watcher based on settings"""
        live_reload_settings = self.settings._settings.get("live_reload", {})
        
        if live_reload_settings.get("enabled", False):
            info("live_reload.enabled is True => Skipping FileWatcher")
            self.file_watcher = None
        else:
            info("live_reload.enabled is False => Starting Watchdog FileWatcher")
            self.file_watcher = FileWatcher(self.folders, self.on_file_change, self.settings)
            self.file_watcher.start()

    def _accept_connections(self):
        """Main connection acceptance loop"""
        while not self._stop_flag:
            try:
                conn, addr = self.sock.accept()
                
                if self.connection_manager.add_connection(conn, addr):
                    # Submit to thread pool
                    self.executor.submit(
                        self.request_handler.handle_connection,
                        conn,
                        addr
                    )
                else:
                    # Connection limit reached
                    conn.close()
                    
            except Exception as e:
                if not self._stop_flag:
                    error(f"Error accepting connection: {e}")

    def on_file_change(self, file_path):
        """Handle file changes by notifying WebSocket clients"""
        filename = os.path.basename(file_path)
        info(f"File changed: {filename}")
        self.websocket.notify_clients(file_path)

    def stop(self):
        """Stop the server with controlled cleanup"""
        if self._stop_flag:
            return
            
        info("Initiating server shutdown...")
        self._stop_flag = True

        self._shutdown_executor()
        self._shutdown_file_watcher()
        self._cleanup_connections()
        self._close_socket()
        
        self.status.update('stopped')
        info("Server shutdown complete")

    def _shutdown_executor(self):
        """Shutdown the thread pool executor"""
        info("Shutting down connection executor...")
        self.executor.shutdown(wait=False)

    def _shutdown_file_watcher(self):
        """Shutdown file watcher with timeout"""
        if not self.file_watcher:
            return
            
        info("Stopping file watcher with timeout...")
        
        watcher_ref = self.file_watcher
        self.file_watcher = None
        
        def stop_watcher():
            try:
                watcher_ref._stop_event.set()
                if hasattr(watcher_ref, 'observer') and watcher_ref.observer:
                    watcher_ref.observer.unschedule_all()
                    watcher_ref.observer.stop()
                    watcher_ref.observer.join(timeout=5)
                    
                    if watcher_ref.observer.is_alive():
                        info("File watcher did not stop in time, detaching")
                    else:
                        info("File watcher stopped successfully")
            except Exception as e:
                error(f"Error during file watcher shutdown: {e}")
        
        # Run in separate thread with timeout
        watcher_thread = threading.Thread(target=stop_watcher)
        watcher_thread.daemon = True
        watcher_thread.start()
        
        # Wait briefly for shutdown
        shutdown_timeout = 0.5
        shutdown_start = time.time()
        
        while watcher_thread.is_alive() and (time.time() - shutdown_start) < shutdown_timeout:
            time.sleep(0.05)
            
        if watcher_thread.is_alive():
            info("File watcher shutdown timed out, continuing with server shutdown")
            
        info("File watcher shutdown complete")

    def _cleanup_connections(self):
        """Clean up WebSocket and connection threads"""
        info("Closing WebSocket connections...")
        self.websocket.clients.clear()
        
        info("Cleaning up connection threads...")

    def _close_socket(self):
        """Close the main server socket"""
        info("Closing main server socket...")
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None