# liveserverplus_lib/request_handler.py
"""HTTP request handling utilities"""
import os
import socket
import threading
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

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
            elif self._shouldProxy(request):
                self._handleProxyRequest(conn, request)
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

    def _shouldProxy(self, request):
        if request.is_websocket_upgrade():
            return False
        if not self.settings.proxyEnabled:
            return False
        if not self.settings.proxyTarget:
            return False

        path = request.path or '/'
        if path == '/ws':
            return False
        base_uri = self.settings.proxyBaseUri

        if base_uri == '/':
            return True

        if path == base_uri:
            return True

        if path.startswith(base_uri + '/'):
            return True

        return False

    def _handleProxyRequest(self, conn, request):
        """Forward request to configured proxy target."""
        target = self.settings.proxyTarget
        parsed = urlparse(target)

        if not parsed.scheme:
            parsed = urlparse(f"http://{target}")

        if not parsed.hostname:
            info("Proxy target is invalid - missing hostname")
            send_error_response(conn, 502, "Bad Gateway")
            return

        is_https = parsed.scheme == 'https'
        port = parsed.port or (443 if is_https else 80)

        upstream = None
        try:
            connection_cls = HTTPSConnection if is_https else HTTPConnection
            upstream = connection_cls(parsed.hostname, port, timeout=30)

            path_suffix = request.path or '/'
            base_uri = self.settings.proxyBaseUri
            if base_uri != '/' and path_suffix.startswith(base_uri):
                path_suffix = path_suffix[len(base_uri):] or '/'

            if not path_suffix.startswith('/'):
                path_suffix = '/' + path_suffix

            upstream_path = parsed.path or ''
            if not upstream_path.endswith('/') and upstream_path:
                combined_path = f"{upstream_path}{path_suffix}"
            else:
                combined_path = f"{upstream_path.rstrip('/')}{path_suffix}"

            if request.query_string:
                combined_path = f"{combined_path}?{request.query_string}"

            hop_by_hop = {
                'connection',
                'keep-alive',
                'proxy-authenticate',
                'proxy-authorization',
                'te',
                'trailers',
                'transfer-encoding',
                'upgrade'
            }

            headers = {}
            for key, value in request.headers.items():
                if key in hop_by_hop:
                    continue
                headers[key.title()] = value

            headers['Host'] = parsed.netloc or parsed.hostname

            body = request.body_bytes if request.body else None
            if body is not None and request.content_length:
                headers['Content-Length'] = str(len(body))
            elif request.method in ('POST', 'PUT', 'PATCH'):
                headers.setdefault('Content-Length', '0')

            upstream.request(request.method, combined_path, body=body, headers=headers)
            response = upstream.getresponse()

            response_body = response.read()
            status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n".encode('utf-8')
            conn.send(status_line)

            for header, value in response.getheaders():
                lower = header.lower()
                if lower in hop_by_hop or lower == 'content-length':
                    continue
                header_line = f"{header}: {value}\r\n".encode('utf-8')
                conn.send(header_line)

            conn.send(f"Content-Length: {len(response_body)}\r\n".encode('utf-8'))
            conn.send(b"\r\n")

            if response_body:
                conn.sendall(response_body)

        except Exception as exc:
            error(f"Proxy request failed: {exc}")
            send_error_response(conn, 502, "Bad Gateway")
        finally:
            try:
                upstream.close()
            except Exception:
                pass
            
    def _injectWebsocketScript(self, content):
        """Inject WebSocket script into HTML content"""
        if not isinstance(content, bytes):
            return content

        if self.settings.useWebExt:
            return content

        try:
            html_str = content.decode('utf-8', errors='replace')
            injected = inject_before_tag(html_str, '</body>', self.websocket.INJECTED_CODE)
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
