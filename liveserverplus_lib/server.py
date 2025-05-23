# server.py
"""Server implementation module"""
import os
import socket
import threading
import sublime
import re
from http.client import responses
from concurrent.futures import ThreadPoolExecutor

from .websocket import WebSocketHandler
from .file_watcher import FileWatcher
from .settings import ServerSettings
from .status import ServerStatus
from .logging import debug, info, warning, error
from .utils import (get_mime_type, compress_data, parse_query_string, is_path_safe, 
                   normalize_path, detect_encoding, create_file_reader, stream_compress_data)
from .directory_listing import DirectoryListing
from .error_pages import ErrorPages
from .cache import CacheManager
from .connection_manager import ConnectionManager

class Server(threading.Thread):
    """Main server class that handles HTTP requests and WebSocket connections"""
    
    def __init__(self, folders):
        super(Server, self).__init__(daemon=True)
        self.folders = list(folders)
        self.folders_set = set(folders)
        self.settings = ServerSettings()
        self.status = ServerStatus()
        self.executor = ThreadPoolExecutor(max_workers=self.settings.max_threads)
        self.websocket = WebSocketHandler()
        self.websocket.settings = self.settings
        self.file_watcher = None
        self._stop_flag = False
        self._connection_threads = set()
        self._cleanup_lock = threading.Lock()
        self.sock = None
        
        # Initialize cache and connection managers
        self.cache_manager = CacheManager.get_instance()
        self.cache_manager.configure(self.settings)
        
        self.connection_manager = ConnectionManager.get_instance()
        self.connection_manager.configure(self.settings)

    def cleanup_connection_thread(self, thread):
        """Remove finished connection thread from set"""
        with self._cleanup_lock:
            self._connection_threads.discard(thread)

    ### Common HTTP Response Builder Methods ###
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
    ### End of common methods ###

    def run(self):
        """Start the server"""
        try:
            print("[LiveServerPlus] Server starting...")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            import errno
            from .utils import get_free_port
            
            host = self.settings.host
            port = self.settings.port
            
            # Try to bind to the configured port
            try:
                self.sock.bind((host, port))
                print(f"[LiveServerPlus] Successfully bound to {host}:{port}")
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    # If the port is in use, attempt to find a free port
                    print(f"[LiveServerPlus] Port {port} is in use, searching for free port...")
                    free_port = get_free_port(49152, 65535)
                    if free_port is None:
                        self.status.update('error', port, f"Port {port} is in use and no free port is available.")
                        print(f"[LiveServerPlus] Error: Port {port} is in use and no free port is available.")
                        return
                    else:
                        print(f"[LiveServerPlus] Port {port} is in use. Falling back to free port {free_port}.")
                        self.settings._settings.set('port', free_port)
                        port = free_port
                        self.sock.bind((host, port))
                        print(f"[LiveServerPlus] Successfully bound to {host}:{port}")
                else:
                    print(f"[LiveServerPlus] Unexpected error binding to port: {e}")
                    raise  # Re-raise unexpected OSErrors
            
            self.sock.listen(5)
            
            # Check live_reload setting
            live_reload_settings = self.settings._settings.get("live_reload", {})
            if live_reload_settings.get("enabled", False):
                print("[LiveServerPlus] live_reload.enabled is True => Skipping FileWatcher")
                self.file_watcher = None
            else:
                print("[LiveServerPlus] live_reload.enabled is False => Starting Watchdog FileWatcher")
                self.file_watcher = FileWatcher(self.folders, self.on_file_change, self.settings)
                self.file_watcher.start()
            
            # Update status with the actual port the server is running on
            self.status.update('running', port)
            print(f"[LiveServerPlus] Server running on {host}:{port}")
            
            # Main connection loop
            while not self._stop_flag:
                try:
                    conn, addr = self.sock.accept()
                    if self.connection_manager.add_connection(conn, addr):
                        self.executor.submit(self.handle_connection, conn, addr)
                    else:
                        conn.close()
                except Exception as e:
                    if not self._stop_flag:
                        print(f"[LiveServerPlus] Error accepting connection: {e}")
            
        except Exception as e:
            print(f"[LiveServerPlus] Critical server error: {e}")
            import traceback
            traceback.print_exc()
            self.status.update('error', port, str(e))
            return

    def handle_connection(self, conn, addr):
        """Handle incoming connections with improved error handling and recovery"""
        current_thread = threading.current_thread()
        
        # Set a timeout to prevent hanging threads
        conn.settimeout(30)  # 30 second timeout
        
        try:
            data = conn.recv(8192)
            if not data:
                debug(f"Empty data received from {addr}")
                return
                
            # Try to decode headers with error handling
            try:
                headers_raw = data.decode('utf-8', errors='replace')
                headers = headers_raw.split('\r\n')
            except Exception as e:
                error(f"Error decoding request from {addr}: {e}")
                self._send_response(conn, 400, b"Bad Request", "text/plain")
                return
                
            if not headers:
                warning(f"No headers in request from {addr}")
                self._send_response(conn, 400, b"Bad Request", "text/plain")
                return
                
            # Parse request line
            try:
                request_line = headers[0].split()
                if len(request_line) < 3:
                    warning(f"Malformed request line from {addr}: {headers[0]}")
                    self._send_response(conn, 400, b"Bad Request", "text/plain")
                    return
                    
                method, path, http_version = request_line
                debug(f"Request: {method} {path} from {addr}")
            except Exception as e:
                error(f"Error parsing request line from {addr}: {e}")
                self._send_response(conn, 400, b"Bad Request", "text/plain")
                return
                
            # Handle query parameters
            query_params = parse_query_string(path)
            path = path.split('?')[0]  # Remove query string from path
            
            # Handle WebSocket upgrade
            if any('Upgrade: websocket' in h for h in headers):
                debug(f"WebSocket upgrade request from {addr}")
                try:
                    response = self.websocket.handle_websocket_upgrade(headers)
                    if response:
                        conn.send(response.encode())
                        self.websocket.add_client(conn)  # Use add_client for thread safety
                        self.handle_websocket_connection(conn)
                    else:
                        warning(f"WebSocket upgrade failed for {addr}")
                        self._send_response(conn, 400, b"Bad WebSocket Request", "text/plain")
                except Exception as e:
                    error(f"Error during WebSocket upgrade from {addr}: {e}")
                    self._send_response(conn, 500, b"Internal Server Error", "text/plain")
                return
            
            # Handle HTTP methods
            if method == 'GET':
                # Normalize and validate path
                if not self._validate_path(path):
                    self.send_error(conn, 400, "Bad Request")
                    return
                    
                self.serve_file(conn, path)
            elif method == 'HEAD':
                # HEAD requests should be handled like GET but without the body
                if not self._validate_path(path):
                    self.send_error(conn, 400, "Bad Request")
                    return
                    
                # TODO: Implement proper HEAD handling
                self._send_response(conn, 200, b"", "text/plain")
            elif method == 'OPTIONS':
                # Handle CORS preflight
                headers = [
                    b"HTTP/1.1 204 No Content",
                    b"Allow: GET, HEAD, OPTIONS",
                    b"Access-Control-Allow-Origin: *",
                    b"Access-Control-Allow-Methods: GET, HEAD, OPTIONS",
                    b"Access-Control-Allow-Headers: Content-Type",
                    b"Content-Length: 0",
                    b""
                ]
                conn.send(b"\r\n".join(headers))
            else:
                warning(f"Unsupported method {method} from {addr}")
                self._send_response(conn, 405, f"Method Not Allowed".encode('utf-8'), "text/plain")
                
        except socket.timeout:
            warning(f"Connection timeout for {addr}")
        except ConnectionResetError:
            debug(f"Connection reset by {addr}")
        except BrokenPipeError:
            debug(f"Broken pipe with {addr}")
        except socket.error as e:
            if e.errno not in [9, 57]:  # 9: Bad file descriptor, 57: Socket not connected
                warning(f"Socket error in connection from {addr}: {e}")
        except Exception as e:
            error(f"Unhandled error in connection from {addr}: {e}")
            import traceback
            error(traceback.format_exc())
        finally:
            # IMPORTANT: Remove connection from the manager
            self.connection_manager.remove_connection(conn)
            
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

    def _validate_path(self, path):
        """Validate a path for security concerns"""
        # Check for suspicious patterns
        if '..' in path or '//' in path or '\\' in path:
            warning(f"Suspicious path detected: {path}")
            return False
            
        # Normalize
        clean_path = normalize_path(path.lstrip('/'))
        if not clean_path:
            warning(f"Path normalization failed: {path}")
            return False
            
        return True

    def serve_file(self, conn, path):
        """Serve the requested path, with directory listings or 404 fallback"""
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
        """Check if path is a directory and serve listing if so"""
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
        Serve a file if it exists with improved path security and streaming for large files.
        
        If the file extension is in allowed_file_types (i.e., renderable in-browser),
        serve it inline (with HTML injection if applicable). Otherwise, serve it
        as a download by adding a 'Content-Disposition: attachment' header.
        """
        clean_rel_path = rel_path.lstrip('/')
        
        # Simple path handling
        if '..' not in clean_rel_path and '//' not in clean_rel_path and '\\\\' not in clean_rel_path:
            safe_rel_path = clean_rel_path
        else:
            safe_rel_path = normalize_path(clean_rel_path)
            if not safe_rel_path:
                self.send_error(conn, 400, "Bad Request")
                return False
        
        # Determine the file's extension
        ext = os.path.splitext(safe_rel_path)[1].lower()
        is_renderable = any(ext == allowed_ext.lower() for allowed_ext in self.settings.allowed_file_types)
        
        # Try each folder to find the file
        for folder in self.folders:
            full_path = os.path.join(folder, safe_rel_path)
            
            # Skip checking for path traversal on simple paths
            path_is_safe = True
            if '..' in safe_rel_path or '/' in safe_rel_path or '\\' in safe_rel_path:
                path_is_safe = is_path_safe(folder, full_path, strict=False)
            
            if not path_is_safe:
                error(f"Path traversal attempt detected: {full_path}")
                self.send_error(conn, 403, "Forbidden")
                return True
            
            debug(f"Looking for file: {full_path}")
            if os.path.isfile(full_path):
                debug(f"Found file: {full_path}")
                
                file_size = os.path.getsize(full_path)
                should_stream = file_size > (1024 * 1024)  # Stream files larger than 1MB
                mime_type = get_mime_type(full_path)
                
                if is_renderable:
                    if should_stream and not full_path.lower().endswith(('.html', '.htm')):
                        return self._send_file_streaming(conn, full_path, mime_type, 
                                                        add_cors=self.settings.cors_enabled)
                    else:
                        return self._send_file_contents(conn, full_path)
                else:
                    extra_headers = [
                        f'Content-Disposition: attachment; filename="{os.path.basename(full_path)}"'.encode('utf-8')
                    ]
                    
                    if should_stream:
                        headers = []
                        headers.append(f"HTTP/1.1 200 OK".encode('utf-8'))
                        headers.append(f"Content-Type: {mime_type}".encode('utf-8'))
                        headers.append(f"Content-Length: {file_size}".encode('utf-8'))
                        headers.append(b"Cache-Control: no-cache, no-store, must-revalidate")
                        headers.extend(extra_headers)
                        headers.append(b"")
                        
                        conn.send(b"\r\n".join(headers) + b"\r\n")
                        
                        for chunk in create_file_reader(full_path):
                            conn.send(chunk)
                        return True
                    else:
                        content = self._read_file_from_disk(full_path)
                        if content is None:
                            return False
                            
                        is_compressed = False
                        if self.settings.enable_compression:
                            try:
                                compressed = compress_data(content, mime_type)
                                if len(compressed) < len(content):
                                    content = compressed
                                    is_compressed = True
                            except Exception as e:
                                error(f"Compression error: {e}")
                                
                        return self._send_response(
                            conn,
                            200,
                            content,
                            mime_type,
                            add_cors=self.settings.cors_enabled,
                            compressed=is_compressed,
                            extra_headers=extra_headers
                        )
        
        debug(f"File not found: {safe_rel_path}")
        return False

    def _serve_parent_directory_if_exists(self, conn, path, rel_path):
        """Serve the parent directory if direct file not found but the parent is a directory"""
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
        """Serve file content from Sublime view or disk, optionally injecting WebSocket script"""
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

    def _send_file_streaming(self, conn, file_path, mime_type, add_cors=False):
        """
        Stream a file to the client instead of loading it entirely into memory.
        
        Args:
            conn (socket.socket): The connection to send the response on
            file_path (str): Path to the file to send
            mime_type (str): MIME type of the file
            add_cors (bool): Whether to add CORS headers
            
        Returns:
            bool: True if the send was successful, False otherwise
        """
        try:
            file_size = os.path.getsize(file_path)
            debug(f"Streaming file {file_path} ({file_size} bytes)")
            
            if file_path.lower().endswith(('.html', '.htm')):
                return self._send_file_contents(conn, file_path)
            
            should_compress = self.settings.enable_compression and mime_type not in {
                'image/jpeg', 'image/png', 'image/gif', 'application/pdf',
                'font/woff', 'font/woff2', 'audio/mpeg', 'video/mp4'
            }
            
            headers = []
            headers.append(f"HTTP/1.1 200 OK".encode('utf-8'))
            headers.append(f"Content-Type: {mime_type}".encode('utf-8'))
            headers.append(f"Content-Length: {file_size}".encode('utf-8'))
            headers.append(b"Cache-Control: no-cache, no-store, must-revalidate")
            
            if add_cors and self.settings.cors_enabled:
                headers.extend([
                    b"Access-Control-Allow-Origin: *",
                    b"Access-Control-Allow-Methods: GET, OPTIONS",
                    b"Access-Control-Allow-Headers: Content-Type"
                ])
                
            if should_compress:
                headers.append(b"Content-Encoding: gzip")
                
            headers.append(b"")
            
            conn.send(b"\r\n".join(headers) + b"\r\n")
            
            file_reader = create_file_reader(file_path)
            
            if should_compress:
                for chunk in stream_compress_data(file_reader, mime_type):
                    conn.send(chunk)
            else:
                for chunk in file_reader:
                    conn.send(chunk)
                    
            return True
        except Exception as e:
            error(f"Error streaming file {file_path}: {e}")
            return False

    def _get_sublime_view_content(self, file_path):
        """Return file content if open in Sublime, else None"""
        window = sublime.active_window()
        if not window:
            return None
        for view in window.views():
            if view.file_name() == file_path:
                return view.substr(sublime.Region(0, view.size())).encode('utf-8')
        return None

    def _read_file_from_disk(self, file_path):
        """Read file from disk with encoding detection"""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.settings.max_file_size * 1024 * 1024:
                warning(f"File too large: {file_path}")
                return None

            if file_path.lower().endswith((
                '.html', '.htm', '.css', '.js', '.json',
                '.xml', '.txt', '.md', '.jsx', '.ts', '.tsx', '.svg'
            )):
                encoding = detect_encoding(file_path)
                debug(f"Reading text file {file_path} with encoding {encoding}")
                with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                    return f.read().encode('utf-8')
            else:
                debug(f"Reading binary file {file_path}")
                with open(file_path, 'rb') as f:
                    return f.read()
        except UnicodeDecodeError as e:
            warning(f"Unicode decode error for {file_path}, falling back to binary: {e}")
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            error(f"Error reading file {file_path}: {e}")
            return None

    def inject_websocket_script(self, html_content):
        """
        Inject the WebSocket script right before </body> (case-insensitive),
        or append at the end if no match
        """
        pattern = re.compile(r"</body>", re.IGNORECASE)
        substituted, num_replacements = pattern.subn(self.websocket.INJECTED_CODE, html_content, count=1)
        
        if num_replacements == 0:
            substituted += self.websocket.INJECTED_CODE
        
        return substituted

    def handle_websocket_connection(self, conn):
        """Keep reading from the WebSocket until closed"""
        try:
            while not self._stop_flag:
                try:
                    conn.recv(1024)
                except:
                    break
        finally:
            self.websocket.remove_client(conn)  # Use remove_client for thread safety
            try:
                conn.close()
            except:
                pass

    def send_error(self, conn, code, requested_path=""):
        """Send an HTTP error response or a custom 404 page"""
        message = responses.get(code, 'Unknown Error')
        
        if code == 404:
            error_html = ErrorPages.get_404_page(requested_path, self.folders)
            content = error_html.encode('utf-8')
            self._send_response(conn, 404, content, "text/html")
            return
        
        content = f"Error {code}: {message}".encode('utf-8')
        self._send_response(conn, code, content, "text/html")

    def on_file_change(self, file_path):
        """Handle file changes by notifying the WebSocket clients"""
        filename = os.path.basename(file_path)
        print(f"[LiveServerPlus] File changed: {filename}")
        self.websocket.notify_clients(file_path)
        
    def stop(self):
        """Stop the server with controlled cleanup"""
        import threading
        import time
        
        if self._stop_flag:
            return
            
        info("Initiating server shutdown...")
        self._stop_flag = True

        # Shutdown the thread pool
        info("Shutting down connection executor...")
        self.executor.shutdown(wait=False)  # Don't wait, let Sublime handle termination

        # Handle file watcher shutdown with timeout
        if self.file_watcher:
            info("Stopping file watcher with timeout...")
            
            watcher_stopped = False
            watcher_ref = self.file_watcher
            self.file_watcher = None
            
            def stop_watcher():
                try:
                    watcher_ref._stop_event.set()
                    if hasattr(watcher_ref, 'observer') and watcher_ref.observer:
                        watcher_ref.observer.unschedule_all()
                        watcher_ref.observer.stop()
                        watcher_ref.observer.join(timeout=5)  # Wait up to 5 seconds
                        if watcher_ref.observer.is_alive():
                            warning("File watcher did not stop in time, detaching")
                        else:
                            info("File watcher stopped successfully")
                    nonlocal watcher_stopped
                    watcher_stopped = True
                except Exception as e:
                    error(f"Error during file watcher shutdown: {e}")
            
            watcher_thread = threading.Thread(target=stop_watcher)
            watcher_thread.daemon = True
            watcher_thread.start()
            
            shutdown_timeout = 0.5  # 0.5 seconds
            shutdown_start = time.time()
            
            while not watcher_stopped and (time.time() - shutdown_start) < shutdown_timeout:
                time.sleep(0.05)
            
            if not watcher_stopped:
                warning("File watcher shutdown timed out, continuing with server shutdown")
                
            info("File watcher shutdown complete")

        # Websocket and connection cleanup
        info("Closing WebSocket connections...")
        self.websocket.clients.clear()

        # Socket cleanup
        info("Closing main server socket...")
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

        # Thread cleanup
        info("Cleaning up connection threads...")
        with self._cleanup_lock:
            self._connection_threads.clear()

        self.status.update('stopped')
        info("Server shutdown complete")
