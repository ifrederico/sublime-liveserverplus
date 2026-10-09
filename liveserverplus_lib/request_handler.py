# liveserverplus_lib/request_handler.py
"""HTTP request handling utilities"""
import os
import socket
import threading
import sublime

from .http_utils import HTTPRequest, HTTPResponse, send_error_response, send_options_response
from .file_server import FileServer
from .websocket import WebSocketHandler
from .error_pages import ErrorPages
from .text_utils import inject_before_tag
from .path_utils import relative_to_root
from .logging import info, error
from .constants import IGNORED_SOCKET_ERRORS

# Limits on what a client can make the handler buffer. Only GET, HEAD and
# OPTIONS are served, none of which needs a request body.
MAX_REQUEST_HEAD = 64 * 1024
MAX_REQUEST_BODY = 1024 * 1024


class _HeadOnlyConnection:
    """Socket stand-in that lets HEAD run the exact GET code path.

    Writes are buffered until the blank line that ends the response headers;
    that header block goes to the real socket and everything after it (the
    body, streamed chunks included) is discarded. HEAD therefore reports the
    same status, Content-Type and Content-Length as GET on every route.
    """

    def __init__(self, conn):
        self._conn = conn
        self._pending = bytearray()
        self._headers_sent = False

    def sendall(self, data):
        if self._headers_sent:
            return None
        self._pending.extend(data)
        end = self._pending.find(b"\r\n\r\n")
        if end != -1:
            self._headers_sent = True
            self._conn.sendall(bytes(self._pending[:end + 4]))
            self._pending = None
        return None

    def send(self, data):
        self.sendall(data)
        return len(data)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class RequestHandler:
    """Handles HTTP requests with proper error handling and cleanup"""
    
    def __init__(self, server):
        self.server = server
        self.settings = server.settings
        self.folders = server.folders
        self.websocket = server.websocket
        self.file_server = FileServer(self.settings)
        self.connection_manager = server.connection_manager
        self._tag_warning_shown = False
        
        # Configure websocket injection behaviour
        if self.settings.useWebExt:
            self.file_server.websocket_injector = None
        else:
            self.file_server.websocket_injector = self._injectWebsocketScript
        
    def handleConnection(self, conn, addr):
        """Main connection handler with improved error handling"""
        current_thread = threading.current_thread()
        
        # Set connection timeout
        conn.settimeout(30)  # Use hardcoded 30 second timeout

        try:
            # Receive and parse request
            data = bytearray()
            header_terminated = False

            while True:
                chunk = conn.recv(8192)
                if not chunk:
                    break
                data.extend(chunk)
                if b"\r\n\r\n" in data:
                    header_terminated = True
                    break
                if len(data) > MAX_REQUEST_HEAD:
                    send_error_response(conn, 431)
                    return

            if not header_terminated or not data:
                info(f"Empty or malformed data received from {addr}")
                return

            request = HTTPRequest(bytes(data))
            if not request.is_valid:
                send_error_response(conn, 400)
                return

            if request.content_length > MAX_REQUEST_BODY:
                send_error_response(conn, 413)
                return

            # Read request body if Content-Length indicates more data
            remaining = request.content_length - len(request.body)
            while remaining > 0:
                chunk = conn.recv(min(8192, remaining))
                if not chunk:
                    break
                request.append_body(chunk)
                remaining -= len(chunk)

            info(f"Request: {request.method} {request.path} from {addr}")

            # Route request based on method and type
            if request.is_websocket_upgrade():
                self._handleWebSocketUpgrade(conn, request, addr)
            elif request.method == 'GET':
                self._handleGetRequest(conn, request)
            elif request.method == 'HEAD':
                self._handleHeadRequest(conn, request)
            elif request.method == 'OPTIONS':
                send_options_response(conn)
            else:
                send_error_response(conn, 405, "Method Not Allowed")
                
        except socket.timeout:
            info(f"Connection timeout for {addr}")
        except ConnectionResetError:
            info(f"Connection reset by {addr}")
        except BrokenPipeError:
            info(f"Broken pipe with {addr}")
        except socket.error as e:
            if e.errno not in IGNORED_SOCKET_ERRORS:
                info(f"Socket error from {addr}: {e}")
        except Exception as e:
            error(f"Unhandled error from {addr}: {e}")
            import traceback
            error(traceback.format_exc())
        finally:
            self._cleanupConnection(conn, current_thread)
            
    def _handleWebSocketUpgrade(self, conn, request, addr):
        """Handle WebSocket upgrade request"""
        info(f"WebSocket upgrade request from {addr}")

        try:
            # Convert headers dict back to list format for websocket handler
            headers_list = []
            for key, value in request.headers.items():
                headers_list.append(f"{key}: {value}")

            response = self.websocket.handleWebSocketUpgrade(headers_list)
            if response:
                conn.sendall(response.encode())
                self.websocket.addClient(conn)
                self._handleWebSocketConnection(conn)
            else:
                info(f"WebSocket upgrade failed for {addr}")
                send_error_response(conn, 400, "Bad WebSocket Request")
        except Exception as e:
            error(f"Error during WebSocket upgrade: {e}")
            send_error_response(conn, 500)
            
    def _handleWebSocketConnection(self, conn):
        """Keep WebSocket connection alive"""
        try:
            while not self.server._stop_flag:
                message = self.websocket.read_message(conn)
                if message is None:
                    break
                if not message:
                    continue
                self.websocket._notify_incoming_message(message, conn)
        finally:
            self.websocket.removeClient(conn)
            
    def _handleGetRequest(self, conn, request):
        """Handle GET requests"""
        path = request.path

        # Containment is checked where paths are resolved (path_utils), which
        # rejects ".." segments but still serves names such as "index..html".
        if '\x00' in path:
            send_error_response(conn, 400, "Bad Request")
            return
            
        # Try to serve file
        if self.file_server.serveFile(conn, path, self.folders):
            return
            
        # Generate 404 page
        self._send404(conn, path)
        
    def _handleHeadRequest(self, conn, request):
        """Handle HEAD requests: the GET response without its body"""
        self._handleGetRequest(_HeadOnlyConnection(conn), request)

    def _send404(self, conn, path):
        """Send 404 error page"""
        try:
            # get_404_page lists folder + path when that is a directory, with
            # no containment check of its own; only give it the folders the
            # raw path stays inside, so "/../" cannot list the parent.
            folders = [
                folder for folder in self.folders
                if relative_to_root(os.path.join(folder, path.lstrip('/')), [folder]) is not None
            ]
            error_html = ErrorPages.get_404_page(path, folders, self.settings)
            
            response = HTTPResponse(404)
            response.set_header('Content-Type', 'text/html; charset=utf-8')
            response.set_body(error_html)
            response.add_cache_headers('no-cache')
            
            if self.settings.corsEnabled:
                response.add_cors_headers()
                
            response.send(conn)
        except Exception as e:
            error(f"Error sending 404 page: {e}")
            send_error_response(conn, 404)

    def _injectWebsocketScript(self, content):
        """Inject WebSocket script into HTML content"""
        if not isinstance(content, bytes):
            return content

        if self.settings.useWebExt:
            return content

        try:
            html_str = content.decode('utf-8', errors='replace')
            html_lower = html_str.lower()

            injection_tags = ['</body>', '</head>', '</svg>']
            selected_tag = None
            for tag in injection_tags:
                if tag in html_lower:
                    selected_tag = tag
                    break

            if selected_tag:
                injected = inject_before_tag(html_str, selected_tag, self.websocket.INJECTED_CODE)
            else:
                injected = html_str + self.websocket.INJECTED_CODE
                if self.settings.verifyTags and not self._tag_warning_shown:
                    self._tag_warning_shown = True
                    message = (
                        "Live reload script could not be injected because no </head>, </body>, or </svg> tag was found.\n"
                        "The script was appended at the end of the file.\n\n"
                        "Add the missing tag or set 'verifyTags': false in LiveServerPlus settings to suppress this warning."
                    )
                    sublime.set_timeout(lambda: sublime.message_dialog(f"[LiveServerPlus]\n{message}"), 0)

            return injected.encode('utf-8')
        except:
            # If anything fails, return content unchanged
            return content
        
    def _cleanupConnection(self, conn, thread):
        """Clean up connection and thread"""
        # Remove from connection manager
        self.connection_manager.removeConnection(conn)

        # Close connection
        try:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except (socket.error, OSError):
                pass
            finally:
                conn.close()
        except (socket.error, OSError):
            pass
