# server.py
"""Server implementation module"""
import os
import socket
import threading
import sublime
import re
from http.client import responses

from .websocket import WebSocketHandler
from .file_watcher import FileWatcher
from .settings import ServerSettings
from .status import ServerStatus
from .utils import get_mime_type, compress_data, parse_query_string
from .directory_listing import DirectoryListing
from .error_pages import ErrorPages

class Server(threading.Thread):
    """Main server class that handles HTTP requests and WebSocket connections"""
    
    def __init__(self, folders):
        super(Server, self).__init__()
        self.folders = list(folders)
        self.folders_set = set(folders)
        self.settings = ServerSettings()
        self.status = ServerStatus()
        self.websocket = WebSocketHandler()
        self.websocket.settings = self.settings
        self.file_watcher = None
        self._stop_flag = False
        self._connection_threads = set()
        self._cleanup_lock = threading.Lock()
        self.sock = None

    def cleanup_connection_thread(self, thread):
        """Remove finished connection thread from set"""
        with self._cleanup_lock:
            self._connection_threads.discard(thread)

    # --- Common HTTP Response Builder Methods ---
    def _build_response_headers(self, status_code, content, content_type, add_cors=False, compressed=False, extra_headers=None):
        """
        Build HTTP response headers as a list of bytes.
        
        Args:
            status_code (int): HTTP status code (e.g. 200, 404)
            content (bytes): The content to be sent (used to compute Content-Length)
            content_type (str): The MIME type to send in the Content-Type header
            add_cors (bool): If True, adds CORS headers.
            compressed (bool): If True, adds Content-Encoding header.
            extra_headers (list): Any additional headers (as bytes) to add.
            
        Returns:
            list: List of header lines (as bytes) ready to be joined and sent.
        """
        status_message = responses.get(status_code, "Unknown Error")
        headers = []
        headers.append(f"HTTP/1.1 {status_code} {status_message}".encode('utf-8'))
        headers.append(f"Content-Type: {content_type}".encode('utf-8'))
        headers.append(f"Content-Length: {len(content)}".encode('utf-8'))
        headers.append(b"Cache-Control: no-cache, no-store, must-revalidate")
        if add_cors:
            headers.extend([
                b"Access-Control-Allow-Origin: *",
                b"Access-Control-Allow-Methods: GET, OPTIONS",
                b"Access-Control-Allow-Headers: Content-Type"
            ])
        if compressed:
            headers.append(b"Content-Encoding: gzip")
        if extra_headers:
            headers.extend(extra_headers)
        headers.append(b"")  # Blank line to separate headers from body
        return headers

    def _send_response(self, conn, status_code, content, content_type, add_cors=False, compressed=False, extra_headers=None):
        """
        Send an HTTP response using the common header builder.
        
        Args:
            conn (socket.socket): The connection to send the response on.
            status_code (int): HTTP status code.
            content (bytes): The body of the response.
            content_type (str): MIME type of the response.
            add_cors (bool): If True, include CORS headers.
            compressed (bool): If True, indicate that the content is gzip compressed.
            extra_headers (list): Any extra headers to include.
            
        Returns:
            bool: True if the send was successful, False otherwise.
        """
        headers = self._build_response_headers(status_code, content, content_type, add_cors, compressed, extra_headers)
        headers.append(content)
        try:
            conn.send(b"\r\n".join(headers))
            return True
        except Exception as e:
            print(f"Error sending response: {e}")
            return False
    # --- End of common methods ---

    def run(self):
        """Start the server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            import errno
            from .utils import get_free_port

            host = self.settings.host
            port = self.settings.port

            # Try to bind to the configured port.
            try:
                self.sock.bind((host, port))
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    # If the port is in use, attempt to find a free port.
                    free_port = get_free_port(49152, 65535)
                    if free_port is None:
                        self.status.update('error', port, f"Port {port} is in use and no free port is available.")
                        print(f"Error: Port {port} is in use and no free port is available.")
                        return
                    else:
                        print(f"Port {port} is in use. Falling back to free port {free_port}.")
                        # Update the settings so that later parts of the plugin use the new port.
                        self.settings._settings.set('port', free_port)
                        port = free_port
                        self.sock.bind((host, port))
                else:
                    raise  # Re-raise unexpected OSErrors

            self.sock.listen(5)

            # ------------------------------------------------------
            # ADDED: Check live_reload setting
            # If live_reload.enabled = true, skip the FileWatcher; otherwise start it.
            # ------------------------------------------------------
            live_reload_settings = self.settings._settings.get("live_reload", {})
            if live_reload_settings.get("enabled", False):
                print("[LiveServerPlus] live_reload.enabled is True => Skipping FileWatcher")
                self.file_watcher = None
            else:
                print("[LiveServerPlus] live_reload.enabled is False => Starting FileWatcher")
                self.file_watcher = FileWatcher(self.folders, self.on_file_change, self.settings)
                self.file_watcher.start()
            # ------------------------------------------------------

            # Update status with the actual port the server is running on.
            self.status.update('running', port)

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
            self.status.update('error', port, str(e))
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
            path = path.split('?')[0]  # Remove query string from path
            
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
                self._send_response(conn, 405, f"Error 405: Method Not Allowed".encode('utf-8'), "text/html")
                return

            self.serve_file(conn, path)
        except socket.error as e:
            if e.errno not in [9, 57]:  # 9: Bad file descriptor, 57: Socket not connected
                print(f"Socket error in connection: {e}")
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            self.cleanup_connection_thread(current_thread)
            try:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass
                finally:
                    conn.close()
            except (socket.error, OSError):
                pass

    def serve_file(self, conn, path):
        """Serve the requested path, with directory listings or 404 fallback."""
        if path == '/':
            path = '/index.html'
        rel_path = path.lstrip('/')

        if self._serve_directory_if_applicable(conn, path, rel_path):
            return
        
        if self._serve_allowed_file(conn, path, rel_path):
            return
        
        if self._serve_parent_directory_if_exists(conn, path, rel_path):
            return
        
        self.send_error(conn, 404, requested_path=path)

    def _serve_directory_if_applicable(self, conn, path, rel_path):
        """Check if path is a directory and serve listing if so."""
        for folder in self.folders:
            full_path = os.path.join(folder, rel_path)
            if os.path.isdir(full_path):
                directory_lister = DirectoryListing(settings=self.settings)
                content = directory_lister.generate_listing(
                    dir_path=full_path,
                    url_path=path,
                    root_path=folder
                )
                self._send_response(conn, 200, content, "text/html; charset=utf-8")
                return True
        return False

    def _serve_allowed_file(self, conn, path, rel_path):
        """
        Serve a file if it exists.

        If the file extension is in allowed_file_types (i.e. renderable in-browser),
        serve it inline (with HTML injection if applicable). Otherwise, serve it
        as a download by adding a 'Content-Disposition: attachment' header.
        """
        import os
        from .utils import get_mime_type, compress_data

        # Determine the file's extension
        ext = os.path.splitext(rel_path)[1].lower()
        # is_renderable: file types allowed to be rendered in-browser
        is_renderable = any(ext == allowed_ext.lower() for allowed_ext in self.settings.allowed_file_types)
        
        for folder in self.folders:
            full_path = os.path.join(folder, rel_path)
            if os.path.isfile(full_path):
                if is_renderable:
                    # For renderable files, serve normally (with injection for HTML, etc.)
                    if self._send_file_contents(conn, full_path):
                        return True
                else:
                    # For non-renderable files, serve them as a download.
                    content = self._read_file_from_disk(full_path)
                    if content is None:
                        return False
                    mime_type = get_mime_type(full_path)
                    # Build an extra header to force a download
                    extra_headers = [
                        f'Content-Disposition: attachment; filename="{os.path.basename(full_path)}"'.encode('utf-8')
                    ]
                    is_compressed = False
                    if self.settings.enable_compression:
                        try:
                            compressed = compress_data(content, mime_type)
                            if len(compressed) < len(content):
                                content = compressed
                                is_compressed = True
                        except Exception as e:
                            print(f"Compression error: {e}")
                    return self._send_response(
                        conn,
                        200,
                        content,
                        mime_type,
                        add_cors=self.settings.cors_enabled,
                        compressed=is_compressed,
                        extra_headers=extra_headers
                    )
        return False

    def _serve_parent_directory_if_exists(self, conn, path, rel_path):
        """Serve the parent directory if direct file not found but the parent is a directory."""
        for folder in self.folders:
            parent_dir_path = os.path.dirname(os.path.join(folder, rel_path))
            if os.path.isdir(parent_dir_path):
                directory_lister = DirectoryListing(self.settings)
                content = directory_lister.generate_listing(
                    parent_dir_path, os.path.dirname(path), folder
                )
                self._send_response(conn, 200, content, "text/html; charset=utf-8")
                return True

        return False

    def _send_file_contents(self, conn, file_path):
        """Serve file content from Sublime view or disk, optionally injecting WebSocket script."""
        content = self._get_sublime_view_content(file_path)
        
        if content is None:
            content = self._read_file_from_disk(file_path)
            if content is None:
                return False

        # If HTML, inject the WebSocket script
        if file_path.lower().endswith(('.html', '.htm')):
            html_str = content.decode('utf-8', errors='replace')
            injected_str = self.inject_websocket_script(html_str)
            content = injected_str.encode('utf-8')

        mime_type = get_mime_type(file_path)
        is_compressed = False
        if self.settings.enable_compression:
            try:
                compressed = compress_data(content, mime_type)
                if len(compressed) < len(content):
                    content = compressed
                    is_compressed = True
            except Exception as e:
                print(f"Compression error: {e}")

        return self._send_response(conn, 200, content, mime_type, add_cors=self.settings.cors_enabled, compressed=is_compressed)

    def _get_sublime_view_content(self, file_path):
        """Return file content if open in Sublime, else None."""
        window = sublime.active_window()
        if not window:
            return None
        for view in window.views():
            if view.file_name() == file_path:
                return view.substr(sublime.Region(0, view.size())).encode('utf-8')
        return None

    def _read_file_from_disk(self, file_path):
        """Read from disk, respecting max_file_size."""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.settings.max_file_size * 1024 * 1024:
                print(f"File too large: {file_path}")
                return None

            # Basic text vs binary guess by extension
            if file_path.lower().endswith((
                '.html', '.htm', '.css', '.js', '.json',
                '.xml', '.txt', '.md', '.jsx', '.ts', '.tsx'
            )):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read().encode('utf-8')
            else:
                with open(file_path, 'rb') as f:
                    return f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return None

    def inject_websocket_script(self, html_content):
        """
        Inject the WebSocket script right before </body> (case-insensitive),
        or append at the end if no match.
        """
        pattern = re.compile(r"</body>", re.IGNORECASE)
        substituted, num_replacements = pattern.subn(self.websocket.INJECTED_CODE, html_content, count=1)
        
        if num_replacements == 0:
            substituted += self.websocket.INJECTED_CODE
        
        return substituted

    def handle_websocket_connection(self, conn):
        """Keep reading from the WebSocket until closed."""
        try:
            while not self._stop_flag:
                try:
                    conn.recv(1024)
                except:
                    break
        finally:
            self.websocket.clients.discard(conn)
            try:
                conn.close()
            except:
                pass

    def send_error(self, conn, code, requested_path=""):
        """Send an HTTP error response or a custom 404 page."""
        message = responses.get(code, 'Unknown Error')
        
        if code == 404:
            error_html = ErrorPages.get_404_page(requested_path, self.folders)
            content = error_html.encode('utf-8')
            self._send_response(conn, 404, content, "text/html")
            return
        
        # Otherwise, standard error
        content = f"Error {code}: {message}".encode('utf-8')
        self._send_response(conn, code, content, "text/html")

    def on_file_change(self, file_path):
        """Handle file changes by notifying the WebSocket clients."""
        print(f"File changed: {file_path}")
        self.websocket.notify_clients(file_path)
        
    def stop(self):
        """Stop the server with graceful cleanup."""
        if self._stop_flag:
            return
            
        print("Initiating server shutdown...")
        self._stop_flag = True

        if self.file_watcher:
            print("Stopping file watcher...")
            self.file_watcher.stop()
            self.file_watcher.join(timeout=5)
            if self.file_watcher.is_alive():
                print("Warning: File watcher didn't stop cleanly")
            else:
                print("File watcher stopped")

        print("Closing WebSocket connections...")
        active_clients = list(self.websocket.clients)
        for client in active_clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except (socket.error, OSError):
                pass
            try:
                client.close()
            except (socket.error, OSError):
                pass
        self.websocket.clients.clear()

        print("Closing main server socket...")
        if self.sock:
            try:
                self.sock.settimeout(1)
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass
                try:
                    self.sock.close()
                except (socket.error, OSError):
                    pass
            except Exception:
                pass

        print("Waiting for connection threads to finish...")
        with self._cleanup_lock:
            active_threads = list(self._connection_threads)
        
        for thread in active_threads:
            thread.join(timeout=2)
            if thread.is_alive():
                print(f"Warning: Connection thread didn't stop cleanly")

        self.status.update('stopped')
        print("Server shutdown complete")