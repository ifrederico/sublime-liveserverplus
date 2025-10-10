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
from .file_utils import get_file_info
from .logging import info, error
from .connection_manager import ConnectionManager
from .constants import IGNORED_SOCKET_ERRORS


class RequestHandler:
    """Handles HTTP requests with proper error handling and cleanup"""
    
    def __init__(self, server):
        self.server = server
        self.settings = server.settings
        self.folders = server.folders
        self.websocket = server.websocket
        self.file_server = FileServer(self.settings)
        self.connection_manager = ConnectionManager.getInstance()
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

            if not header_terminated or not data:
                info(f"Empty or malformed data received from {addr}")
                return

            request = HTTPRequest(bytes(data))
            if not request.is_valid:
                send_error_response(conn, 400)
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
                conn.send(response.encode())
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
                try:
                    data = conn.recv(1024)
                    if not data:
                        break
                    # Could handle WebSocket frames here if needed
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            self.websocket.removeClient(conn)
            
    def _handleGetRequest(self, conn, request):
        """Handle GET requests"""
        path = request.path

        # Basic validation for obvious attacks (full validation happens in file_server)
        if any(pattern in path for pattern in ['..', '//', '\\\\', '\x00']):
            send_error_response(conn, 400, "Bad Request")
            return
            
        # Try to serve file
        if self.file_server.serveFile(conn, path, self.folders):
            return
            
        # Generate 404 page
        self._send404(conn, path)
        
    def _handleHeadRequest(self, conn, request):
        """Handle HEAD requests - properly check if resource exists"""
        path = request.path
        
        # Basic validation for obvious attacks (full validation happens in file_server)
        if any(pattern in path for pattern in ['..', '//', '\\\\', '\x00']):
            send_error_response(conn, 400, "Bad Request")
            return
        
        # Default to index.html for root
        if path == '/':
            path = '/index.html'
            
        rel_path = path.lstrip('/')
        
        # Try to find the resource using centralized file_info
        file_info = None
        for folder in self.folders:
            full_path = os.path.join(folder, rel_path)
            info = get_file_info(full_path)
            if info:
                file_info = info
                break
        
        if not file_info:
            # Send 404 for non-existent resources
            send_error_response(conn, 404)
            return
        
        # Build response with headers only
        response = HTTPResponse(200)
        response.set_header('Content-Type', file_info['mime_type'])
        response.set_header('Content-Length', str(file_info['size']))
        response.set_header('Accept-Ranges', 'bytes')
        
        if self.settings.corsEnabled:
            response.add_cors_headers()
            
        # Send headers only for HEAD request
        response.send_headers_only(conn)
        
    def _send404(self, conn, path):
        """Send 404 error page"""
        try:
            error_html = ErrorPages.get_404_page(path, self.folders, self.settings)
            
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
                if not self.settings.suppressTagWarnings and not self._tag_warning_shown:
                    self._tag_warning_shown = True
                    message = (
                        "Live reload script could not be injected because no </head>, </body>, or </svg> tag was found.\n"
                        "The script was appended at the end of the file.\n\n"
                        "Add the missing tag or set 'donotVerifyTags': true in LiveServerPlus settings to suppress this warning."
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
