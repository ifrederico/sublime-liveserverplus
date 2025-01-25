"""Server implementation module"""
import os
import socket
import threading
import sublime
from http.client import responses

from .websocket import WebSocketHandler
from .file_watcher import FileWatcher
from .settings import ServerSettings
from .status import ServerStatus
from .utils import get_mime_type, compress_data, parse_query_string
from .directory_listing import DirectoryListing

class Server(threading.Thread):
    """Main server class that handles HTTP requests and WebSocket connections"""
    
    def __init__(self, folders):
        super(Server, self).__init__()
        self.folders = list(folders)
        self.folders_set = set(folders)
        self.settings = ServerSettings()
        self.status = ServerStatus()
        self.websocket = WebSocketHandler()
        self.file_watcher = None
        self._stop_flag = False
        self._connection_threads = set()
        self._cleanup_lock = threading.Lock()
        self.sock = None

    def cleanup_connection_thread(self, thread):
        """Remove finished connection thread from set"""
        with self._cleanup_lock:
            self._connection_threads.discard(thread)

        
    def run(self):
        """Start the server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.settings.host, self.settings.port))
            self.sock.listen(5)
            
            # Start file watcher
            self.file_watcher = FileWatcher(
                self.folders,
                self.on_file_change,
                self.settings
            )
            self.file_watcher.start()
            
            # Update status
            self.status.update('running', self.settings.port)
            
            while not self._stop_flag:
                try:
                    conn, addr = self.sock.accept()
                    thread = threading.Thread(
                        target=self.handle_connection,
                        args=(conn, addr),
                        daemon=True
                    )
                    thread.start()
                    with self._cleanup_lock:
                        self._connection_threads.add(thread)

                except Exception as e:
                    if not self._stop_flag:
                        print(f"Error accepting connection: {e}")
                        
        except Exception as e:
            self.status.update('error', self.settings.port, str(e))
            return

    def handle_connection(self, conn, addr):
        """Handle incoming connections with proper cleanup"""
        current_thread = threading.current_thread()
        try:
            data = conn.recv(8192)
            if not data:
                return
                
            headers = data.decode('utf-8', errors='replace').split('\r\n')
            if not headers:
                return
                
            request_line = headers[0].split()
            if len(request_line) < 3:
                return
                
            method, path = request_line[0], request_line[1]
            query_params = parse_query_string(path)
            path = path.split('?')[0]  # Remove query string
            
            # Handle WebSocket upgrade
            if any('Upgrade: websocket' in h for h in headers):
                response = self.websocket.handle_websocket_upgrade(headers)
                if response:
                    conn.send(response.encode())
                    self.websocket.clients.add(conn)
                    self.handle_websocket_connection(conn)
                return
                
            # Handle HTTP request
            if method != 'GET':
                self.send_error(conn, 405)
                return
                
            self.serve_file(conn, path)
            
        except socket.error as e:
            # Only print for unexpected socket errors
            if e.errno not in [9, 57]:  # 9: Bad file descriptor, 57: Socket not connected
                print(f"Socket error in connection: {e}")
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            self.cleanup_connection_thread(current_thread)
            try:
                try:
                    # Try an orderly shutdown first
                    conn.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass  # Ignore shutdown errors
                finally:
                    conn.close()
            except (socket.error, OSError):
                pass  # Ignore close errors

    def serve_file(self, conn, path):
        """Serve file content with proper encoding"""
        if path == '/':
            path = '/index.html'
        rel_path = path.lstrip('/')

        # Check if this is a resource file (CSS, JS)
        is_resource = path.lower().endswith(('.css', '.js'))
        
        # Check if file type is allowed
        ext = os.path.splitext(rel_path)[1].lower()
        is_allowed = is_resource or any(ext == allowed_ext.lower() 
                                      for allowed_ext in self.settings.allowed_file_types)
        
        for folder in self.folders:
            full_path = os.path.join(folder, rel_path)
            
            # Check if path is a directory
            if os.path.isdir(full_path):
                content = DirectoryListing.generate_listing(full_path, path, folder)
                headers = [
                    b"HTTP/1.1 200 OK",
                    b"Content-Type: text/html; charset=utf-8",
                    f"Content-Length: {len(content)}".encode('utf-8'),
                    b"Cache-Control: no-cache, no-store, must-revalidate",
                    b"",
                    content
                ]
                conn.send(b"\r\n".join(headers))
                return
            
            # If file exists but isn't allowed, show its directory
            if os.path.isfile(full_path) and not is_allowed:
                dir_path = os.path.dirname(full_path)
                dir_url = os.path.dirname(path)
                content = DirectoryListing.generate_listing(dir_path, dir_url, folder)
                headers = [
                    b"HTTP/1.1 200 OK",
                    b"Content-Type: text/html; charset=utf-8",
                    f"Content-Length: {len(content)}".encode('utf-8'),
                    b"Cache-Control: no-cache, no-store, must-revalidate",
                    b"",
                    content
                ]
                conn.send(b"\r\n".join(headers))
                return

            # Only proceed with file serving if the file type is allowed
            if is_allowed:
                file_path = os.path.join(folder, rel_path)
                content = None
                
                # Check open files first
                window = sublime.active_window()
                if window:
                    for view in window.views():
                        if view.file_name() == file_path:
                            content = view.substr(sublime.Region(0, view.size()))
                            if file_path.lower().endswith(('.html', '.htm')):
                                content = content.replace('</body>', self.websocket.INJECTED_CODE)
                            content = content.encode('utf-8')
                            break
                
                # If not found in open files, try reading from disk
                if content is None and os.path.isfile(file_path):
                    try:
                        # Check file size
                        file_size = os.path.getsize(file_path)
                        if file_size > self.settings.max_file_size * 1024 * 1024:
                            print(f"File too large: {file_path}")
                            continue

                        # For text files
                        if file_path.lower().endswith(('.html', '.htm', '.css', '.js', '.json', '.xml', '.txt', '.md')):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            # Inject WebSocket code for HTML files
                            if file_path.lower().endswith(('.html', '.htm')):
                                content = content.replace('</body>', self.websocket.INJECTED_CODE)
                                
                            # Convert to bytes
                            content = content.encode('utf-8')
                        else:
                            # For binary files
                            with open(file_path, 'rb') as f:
                                content = f.read()
                    except Exception as e:
                        print(f"Error reading file {file_path}: {e}")
                        continue
                
                if content is not None:
                    mime_type = get_mime_type(file_path)
                    
                    # Handle compression if enabled
                    is_compressed = False
                    if self.settings.enable_compression and isinstance(content, bytes):
                        try:
                            compressed = compress_data(content, mime_type)
                            if len(compressed) < len(content):
                                content = compressed
                                is_compressed = True
                        except Exception as e:
                            print(f"Compression error: {e}")
                    
                    # Send headers and content
                    headers = [
                        b"HTTP/1.1 200 OK",
                        f"Content-Type: {mime_type}".encode('utf-8'),
                        f"Content-Length: {len(content)}".encode('utf-8'),
                        b"Cache-Control: no-cache, no-store, must-revalidate",
                        b"X-Content-Type-Options: nosniff",
                    ]
                    
                    if self.settings.cors_enabled:
                        headers.extend([
                            b"Access-Control-Allow-Origin: *",
                            b"Access-Control-Allow-Methods: GET, OPTIONS",
                            b"Access-Control-Allow-Headers: Content-Type"
                        ])
                    
                    if is_compressed:
                        headers.append(b"Content-Encoding: gzip")
                    
                    headers.extend([b"", content])
                    
                    try:
                        conn.send(b"\r\n".join(headers))
                    except Exception as e:
                        print(f"Error sending response: {e}")
                    return
        
        # If we get here, show directory listing for the parent directory if it exists
        if is_resource:
            # For CSS/JS files, just return empty content with 200 OK
            headers = [
                b"HTTP/1.1 200 OK",
                b"Content-Type: text/plain",
                b"Content-Length: 0",
                b"Cache-Control: no-cache, no-store, must-revalidate",
                b"",
                b""
            ]
            conn.send(b"\r\n".join(headers))
        else:
            # Try to show the parent directory instead of 404
            for folder in self.folders:
                dir_path = os.path.dirname(os.path.join(folder, rel_path))
                if os.path.isdir(dir_path):
                    content = DirectoryListing.generate_listing(dir_path, os.path.dirname(path), folder)
                    headers = [
                        b"HTTP/1.1 200 OK",
                        b"Content-Type: text/html; charset=utf-8",
                        f"Content-Length: {len(content)}".encode('utf-8'),
                        b"Cache-Control: no-cache, no-store, must-revalidate",
                        b"",
                        content
                    ]
                    conn.send(b"\r\n".join(headers))
                    return
                    
            # Only show 404 if we can't find any valid directory to show
            self.send_error(conn, 404)

    def handle_websocket_connection(self, conn):
        """Handle WebSocket connection after upgrade"""
        try:
            while not self._stop_flag:
                try:
                    # Keep connection alive and handle incoming messages
                    conn.recv(1024)
                except:
                    break
        finally:
            self.websocket.clients.discard(conn)
            try:
                conn.close()
            except:
                pass

    def handle_websocket_connection(self, conn):
        """Handle WebSocket connection after upgrade"""
        try:
            while not self._stop_flag:
                try:
                    # Keep connection alive and handle incoming messages
                    conn.recv(1024)
                except:
                    break
        finally:
            self.websocket.clients.discard(conn)
            try:
                conn.close()
            except:
                pass

    def send_error(self, conn, code):
        """Send HTTP error response"""
        message = responses.get(code, 'Unknown Error')
        content = f"Error {code}: {message}".encode('utf-8')
            
        headers = [
            f"HTTP/1.1 {code} {responses.get(code, 'Error')}".encode(),
            b"Content-Type: text/html",
            f"Content-Length: {len(content)}".encode(),
            b"Cache-Control: no-cache",
            b"",
            content
        ]
        conn.send(b"\r\n".join(headers))

    def on_file_change(self, file_path):
        """Handle file changes"""
        print(f"File changed: {file_path}")
        self.websocket.notify_clients(file_path)
        
    def stop(self):
        """Stop the server with graceful cleanup"""
        if self._stop_flag:
            return  # Already stopping
            
        print("Initiating server shutdown...")
        self._stop_flag = True

        # Stop file watcher first
        if self.file_watcher:
            print("Stopping file watcher...")
            self.file_watcher.stop()
            self.file_watcher.join(timeout=5)  # Wait up to 5 seconds
            if self.file_watcher.is_alive():
                print("Warning: File watcher didn't stop cleanly")
            else:
                print("File watcher stopped")

        # Close WebSocket connections
        print("Closing WebSocket connections...")
        active_clients = list(self.websocket.clients)
        for client in active_clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except (socket.error, OSError):
                pass  # Ignore shutdown errors
            try:
                client.close()
            except (socket.error, OSError):
                pass  # Ignore close errors
        self.websocket.clients.clear()

        # Close main socket
        print("Closing main server socket...")
        if self.sock:
            try:
                # Set a short timeout to prevent hanging
                self.sock.settimeout(1)
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass  # Ignore shutdown errors
                try:
                    self.sock.close()
                except (socket.error, OSError):
                    pass  # Ignore close errors
            except Exception as e:
                pass  # Ignore all socket errors during shutdown

        # Wait for connection threads to finish
        print("Waiting for connection threads to finish...")
        with self._cleanup_lock:
            active_threads = list(self._connection_threads)
        
        for thread in active_threads:
            thread.join(timeout=2)  # Give each thread 2 seconds to finish
            if thread.is_alive():
                print(f"Warning: Connection thread didn't stop cleanly")

        self.status.update('stopped')
        print("Server shutdown complete")