# liveserverplus_lib/server.py
"""Server implementation module """
import os
import socket
import threading
import time
import sublime
from concurrent.futures import ThreadPoolExecutor

from .websocket import WebSocketHandler
from .file_watcher import FileWatcher
from .settings import ServerSettings
from .status import ServerStatus
from .request_handler import RequestHandler
from .logging import info, error
from .utils import getFreePort
from .connection_manager import ConnectionManager


class Server(threading.Thread):
    """Main server class that handles HTTP requests and WebSocket connections"""
    
    def __init__(self, folders):
        super(Server, self).__init__(daemon=True)
        self.folders = list(folders)
        self.folders_set = set(folders)
        self.settings = ServerSettings()
        self.status = ServerStatus(self.settings)
        self.executor = ThreadPoolExecutor(
            max_workers=self.settings.maxThreads,
            thread_name_prefix='LSP-Worker'
        )
        self.websocket = WebSocketHandler()
        self.websocket.settings = self.settings
        self.file_watcher = None
        self._stop_flag = False
        self.sock = None
        self.request_handler = None

        # Initialize managers

        self.connection_manager = ConnectionManager.getInstance()
        self.connection_manager.configure(self.settings)


    def run(self):
        """Start the server"""
        try:
            info("Server starting...")
            self.status.update('starting')
            self._setupSocket()
            self._setupFileWatcher()
            
            # Create request handler
            self.request_handler = RequestHandler(self)
            
            # Update status
            self.status.update('running', self.settings.port)
            info(f"Server running on {self.settings.host}:{self.settings.port}")
            
            # Main connection loop
            self._acceptConnections()
            
        except Exception as e:
            error(f"Critical server error: {e}")
            import traceback
            error(traceback.format_exc())
            self.status.update('error', error=str(e))

    def _setupSocket(self):
        """Set up the server socket with error handling"""
        import errno
        
        # Clean up any existing socket first
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Add SO_REUSEPORT on systems that support it
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                # Not available on Windows or older systems
                pass
        
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Set socket to non-blocking for shutdown
        self.sock.setblocking(True)
        
        # Optimize socket buffer sizes for better throughput
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # 64KB send buffer
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64KB receive buffer
        except OSError:
            # Some systems don't allow buffer size changes
            pass

        host = self.settings.host
        port = self.settings.port
        
        # Always bind to 0.0.0.0 for network access when host is localhost/127.0.0.1
        bind_host = '0.0.0.0' if host in ['localhost', '127.0.0.1'] else host
        
        # Try binding with increasing wait times
        max_attempts = 3
        attempt = 0
        
        while attempt < max_attempts:
            try:
                self.sock.bind((bind_host, port))
                info(f"Successfully bound to {host}:{port}")
                break
            except OSError as e:
                attempt += 1
                
                if e.errno == errno.EADDRINUSE:
                    if attempt < max_attempts and port != 0:
                        # Wait a bit for the port to be released
                        wait_time = attempt * 0.5
                        info(f"Port {port} is in use, waiting {wait_time}s before retry {attempt}/{max_attempts}")
                        time.sleep(wait_time)
                        continue
                    
                    # Port in use, try to find a nearby port
                    info(f"Port {port} is in use after {attempt} attempts, looking for a nearby port...")
                    fallback_port = None

                    if port != 0:
                        for offset in range(1, 21):
                            candidate = port + offset
                            if candidate > 65535:
                                break
                            try:
                                self.sock.bind((bind_host, candidate))
                                fallback_port = candidate
                                info(f"Port {port} is in use. Using fallback port {candidate}.")
                                break
                            except OSError as bind_error:
                                if bind_error.errno == errno.EADDRINUSE:
                                    continue
                                else:
                                    error(f"Failed to bind to fallback port {candidate}: {bind_error}")
                                    sublime.error_message(
                                        "[LiveServerPlus] Unexpected error while binding to a fallback port.\n"
                                        f"Details: {bind_error}"
                                    )
                                    raise

                    if fallback_port is not None:
                        self.settings._ephemeral_port_cache = fallback_port
                        port = fallback_port
                        break

                    info(f"Port {port} is in use after trying nearby ports, searching for an available port...")
                    free_port = getFreePort(49152, 65535)

                    if free_port is None:
                        # Close socket before raising
                        if self.sock:
                            try:
                                self.sock.close()
                            except:
                                pass
                            self.sock = None
                        error_msg = f"Port {port} is in use and no free port available."
                        self.status.update('error', error=error_msg)
                        error(error_msg)
                        sublime.error_message(f"[LiveServerPlus] {error_msg}\n\nTry choosing a different port or closing other applications using it.")
                        raise OSError(error_msg)

                    try:
                        self.sock.bind((bind_host, free_port))
                        info(f"Port {port} is in use. Using available port {free_port}.")
                        self.settings._ephemeral_port_cache = free_port
                        port = free_port
                        break
                    except OSError as bind_error:
                        # Close socket and reset cache before raising
                        if self.sock:
                            try:
                                self.sock.close()
                            except:
                                pass
                            self.sock = None
                        self.settings._ephemeral_port_cache = None
                        error(f"Failed to bind to available port {free_port}: {bind_error}")
                        sublime.error_message(
                            "[LiveServerPlus] Could not bind to any port.\n"
                            "Please adjust the configured port or close programs using the port."
                        )
                        raise
                else:
                    # Close socket for any other error
                    if self.sock:
                        try:
                            self.sock.close()
                        except:
                            pass
                        self.sock = None
                    error(f"Unexpected error binding to port: {e}")
                    sublime.error_message(
                        "[LiveServerPlus] Unexpected error while binding to the port.\n"
                        f"Details: {e}"
                    )
                    raise
                    
        self.sock.listen(128)  # Increase backlog for better connection handling

    def _setupFileWatcher(self):
        """Set up file watcher based on settings"""
        if self.file_watcher:
            try:
                self.file_watcher.stop()
            except Exception:
                pass

        if self.settings.liveReload:
            info("liveReload enabled - skipping Watchdog file watcher")
            self.file_watcher = None
            return

        info("Starting Watchdog FileWatcher")
        self.file_watcher = FileWatcher(self.folders, self.onFileChange, self.settings)
        self.file_watcher.start()

    def _acceptConnections(self):
        """Main connection acceptance loop"""
        while not self._stop_flag:
            try:
                conn, addr = self.sock.accept()

                if self.connection_manager.addConnection(conn, addr):
                    # Submit to thread pool
                    self.executor.submit(
                        self.request_handler.handleConnection,
                        conn,
                        addr
                    )
                else:
                    # Connection limit reached
                    conn.close()
                    
            except Exception as e:
                if not self._stop_flag:
                    error(f"Error accepting connection: {e}")

    def onFileChange(self, file_path):
        """Handle file changes by notifying WebSocket clients"""
        filename = os.path.basename(file_path)
        info(f"File changed: {filename}")
        self.websocket.notifyClients(file_path)

    def on_file_change(self, file_path):
        return self.onFileChange(file_path)

    def stop(self):
        """Stop the server with controlled cleanup"""
        if self._stop_flag:
            return
            
        info("Initiating server shutdown...")
        self.status.update('stopping')
        self._stop_flag = True

        self._shutdownExecutor()
        self._shutdownFileWatcher()
        self._cleanupConnections()
        self._closeSocket()
        
        self.status.update('stopped')
        info("Server shutdown complete")

    def _shutdownExecutor(self):
        """Shutdown the thread pool executor"""
        info("Shutting down connection executor...")
        self.executor.shutdown(wait=False)

    def _shutdownFileWatcher(self):
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

    def _cleanupConnections(self):
        """Clean up WebSocket and connection threads"""
        info("Closing WebSocket connections...")
        self.websocket.shutdown()
        self.websocket.clients.clear()

        info("Cleaning up connection threads...")

    def _closeSocket(self):
        """Close the main server socket"""
        info("Closing main server socket...")
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
