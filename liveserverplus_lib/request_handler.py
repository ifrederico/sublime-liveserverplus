# liveserverplus_lib/request_handler.py
"""HTTP request handling utilities"""
import os
import socket
import threading
from .http_utils import HTTPRequest, HTTPResponse, send_error_response, send_options_response
from .file_server import FileServer
from .websocket import WebSocketHandler
from .error_pages import ErrorPages
from .text_utils import inject_before_tag
from .file_utils import get_file_info
from .logging import debug, info, warning, error
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
        self.connection_manager = ConnectionManager.get_instance()
        
        # Set websocket injector on file server
        self.file_server.websocket_injector = self._inject_websocket_script
        
    def handle_connection(self, conn, addr):
        """Main connection handler with improved error handling"""
        current_thread = threading.current_thread()
        
        # Set connection timeout
        conn.settimeout(30)  # Use hardcoded 30 second timeout
        
        try:
            # Receive and parse request
            data = conn.recv(8192)
            if not data:
                debug(f"Empty data received from {addr}")
                return
                
            request = HTTPRequest(data)
            if not request.is_valid:
                send_error_response(conn, 400)
                return
                
            debug(f"Request: {request.method} {request.path} from {addr}")
            
            # Route request based on method and type
            if request.is_websocket_upgrade():
                self._handle_websocket_upgrade(conn, request, addr)
            elif request.method == 'GET':
                self._handle_get_request(conn, request)
            elif request.method == 'HEAD':
                self._handle_head_request(conn, request)
            elif request.method == 'OPTIONS':
                send_options_response(conn)
            else:
                send_error_response(conn, 405, "Method Not Allowed")
                
        except socket.timeout:
            warning(f"Connection timeout for {addr}")
        except ConnectionResetError:
            debug(f"Connection reset by {addr}")
        except BrokenPipeError:
            debug(f"Broken pipe with {addr}")
        except socket.error as e:
            if e.errno not in IGNORED_SOCKET_ERRORS:
                warning(f"Socket error from {addr}: {e}")
        except Exception as e:
            error(f"Unhandled error from {addr}: {e}")
            import traceback
            error(traceback.format_exc())
        finally:
            self._cleanup_connection(conn, current_thread)
            
    def _handle_websocket_upgrade(self, conn, request, addr):
        """Handle WebSocket upgrade request"""
        debug(f"WebSocket upgrade request from {addr}")
        
        try:
            # Convert headers dict back to list format for websocket handler
            headers_list = []
            for key, value in request.headers.items():
                headers_list.append(f"{key}: {value}")
                
            response = self.websocket.handle_websocket_upgrade(headers_list)
            if response:
                conn.send(response.encode())
                self.websocket.add_client(conn)
                self._handle_websocket_connection(conn)
            else:
                warning(f"WebSocket upgrade failed for {addr}")
                send_error_response(conn, 400, "Bad WebSocket Request")
        except Exception as e:
            error(f"Error during WebSocket upgrade: {e}")
            send_error_response(conn, 500)
            
    def _handle_websocket_connection(self, conn):
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
            self.websocket.remove_client(conn)
            
    def _handle_get_request(self, conn, request):
        """Handle GET requests"""
        path = request.path
        
        # Basic validation for obvious attacks (full validation happens in file_server)
        if any(pattern in path for pattern in ['..', '//', '\\\\', '\x00']):
            send_error_response(conn, 400, "Bad Request")
            return
            
        # Try to serve file
        if self.file_server.serve_file(conn, path, self.folders):
            return
            
        # Generate 404 page
        self._send_404(conn, path)
        
    def _handle_head_request(self, conn, request):
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
        
        if self.settings.cors_enabled:
            response.add_cors_headers()
            
        # Send headers only for HEAD request
        response.send_headers_only(conn)
        
    def _send_404(self, conn, path):
        """Send 404 error page"""
        try:
            error_html = ErrorPages.get_404_page(path, self.folders, self.settings)
            
            response = HTTPResponse(404)
            response.set_header('Content-Type', 'text/html; charset=utf-8')
            response.set_body(error_html)
            response.add_cache_headers('no-cache')
            
            if self.settings.cors_enabled:
                response.add_cors_headers()
                
            response.send(conn)
        except Exception as e:
            error(f"Error sending 404 page: {e}")
            send_error_response(conn, 404)
            
    def _inject_websocket_script(self, content):
        """Inject WebSocket script into HTML content"""
        if isinstance(content, bytes):
            html_str = content.decode('utf-8', errors='replace')
        else:
            html_str = content
            
        # Use text_utils function for injection
        injected = inject_before_tag(html_str, '</body>', self.websocket.INJECTED_CODE)
        
        return injected.encode('utf-8')
        
    def _cleanup_connection(self, conn, thread):
        """Clean up connection and thread"""
        # Remove from connection manager
        self.connection_manager.remove_connection(conn)
        
        # Remove thread from server's tracking
        if hasattr(self.server, 'cleanup_connection_thread'):
            self.server.cleanup_connection_thread(thread)
            
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