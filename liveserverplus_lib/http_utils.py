# liveserverplus_lib/http_utils.py
"""HTTP utilities for request/response handling"""
import socket
from http.client import responses
from urllib.parse import unquote

from .logging import info, error

class HTTPResponse:
    """Builder for HTTP responses with chainable methods"""
    
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}
        self.body = b""
        # Add standard security headers by default
        self.add_security_headers()
        
    def set_header(self, name, value):
        """Set a response header"""
        self.headers[name] = value
        return self
        
    def set_body(self, body):
        """Set response body"""
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.body = body
        return self
        
    def add_cors_headers(self):
        """Add CORS headers"""
        self.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        })
        return self
        
    def add_compression_headers(self):
        """Add compression headers"""
        self.headers['Content-Encoding'] = 'gzip'
        return self
        
    def add_cache_headers(self, cache_control='no-cache, no-store, must-revalidate'):
        """Add cache control headers"""
        self.headers['Cache-Control'] = cache_control
        return self
        
    def add_security_headers(self):
        """Add security headers"""
        self.headers.update({
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'SAMEORIGIN',
            'Referrer-Policy': 'same-origin'
        })
        self.headers['Connection'] = 'keep-alive'
        self.headers['Keep-Alive'] = 'timeout=5, max=100'
        return self
        
    def build(self):
        """Build the complete HTTP response as bytes"""
        status_message = responses.get(self.status_code, "Unknown")
        
        # Pre-allocate list for better performance
        lines = []
        lines.append(f"HTTP/1.1 {self.status_code} {status_message}")
        
        # Add content length
        self.headers['Content-Length'] = str(len(self.body))
        
        # Build all headers at once
        lines.extend(f"{name}: {value}" for name, value in self.headers.items())
        lines.append("")  # Empty line
        
        # Join once and encode
        header_str = "\r\n".join(lines)
        return header_str.encode('utf-8') + b"\r\n" + self.body
        
    def send(self, conn):
        """Send the response over a connection"""
        try:
            response_data = self.build()
            conn.send(response_data)
            return True
        except Exception as e:
            error(f"Error sending response: {e}")
            return False
            
    def send_headers_only(self, conn):
        """Send only headers (for HEAD requests)"""
        try:
            response_data = self.build()
            # Find the end of headers (empty line)
            headers_end = response_data.find(b'\r\n\r\n')
            if headers_end != -1:
                conn.send(response_data[:headers_end + 4])  # +4 for \r\n\r\n
            else:
                # Fallback if separator not found
                conn.send(response_data)
            return True
        except Exception as e:
            error(f"Error sending headers: {e}")
            return False


class HTTPRequest:
    """HTTP request parser"""
    
    def __init__(self, raw_data):
        self.raw_data = raw_data
        self.method = None
        self.path = None
        self.version = None
        self.headers = {}
        self.query_params = {}
        self.raw_target = None
        self.query_string = ''
        self.body = bytearray()
        self.content_length = 0
        self.is_valid = False
        self._parse()

    def _parse(self):
        """Parse the HTTP request"""
        try:
            header_end = self.raw_data.find(b'\r\n\r\n')
            if header_end == -1:
                return

            header_bytes = self.raw_data[:header_end]
            body_bytes = self.raw_data[header_end + 4:]

            try:
                header_text = header_bytes.decode('iso-8859-1')
            except UnicodeDecodeError:
                header_text = header_bytes.decode('utf-8', errors='replace')

            lines = header_text.split('\r\n')

            if not lines:
                return

            # Parse request line
            request_line = lines[0].split()
            if len(request_line) < 3:
                info(f"Malformed request line: {lines[0]}")
                return

            self.method = request_line[0]
            self.raw_target = request_line[1]
            self.version = request_line[2]

            # Parse query string
            target = self.raw_target
            if '?' in target:
                self.path, self.query_string = target.split('?', 1)
                self._parse_query_string(self.query_string)
            else:
                self.path = target

            # Parse headers
            for line in lines[1:]:
                if not line:
                    break
                if ':' in line:
                    key, value = line.split(':', 1)
                    self.headers[key.strip().lower()] = value.strip()

            self.content_length = int(self.headers.get('content-length', '0') or 0)
            self.body = bytearray(body_bytes)

            self.is_valid = True

        except Exception as e:
            error(f"Error parsing HTTP request: {e}")

    def _parse_query_string(self, query_string):
        """Parse query parameters"""
        from urllib.parse import unquote
        
        if not query_string:
            return
            
        pairs = query_string.split('&')
        for pair in pairs:
            if '=' in pair:
                key, value = pair.split('=', 1)
                self.query_params[key] = unquote(value)
            else:
                self.query_params[pair] = ''
                
    def is_websocket_upgrade(self):
        """Check if this is a WebSocket upgrade request"""
        return (
            self.headers.get('upgrade', '').lower() == 'websocket' and
            'sec-websocket-key' in self.headers
        )
        
    def get_header(self, name, default=None):
        """Get a header value (case-insensitive)"""
        return self.headers.get(name.lower(), default)

    def append_body(self, data):
        if data:
            self.body.extend(data)

    @property
    def body_bytes(self):
        return bytes(self.body)


# Common response builders
def create_error_response(status_code, message=None, body=None):
    """
    Create a standard error response.
    
    Args:
        status_code: HTTP status code
        message: Optional status message
        body: Optional body content (str or bytes)
        
    Returns:
        HTTPResponse object
    """
    if message is None:
        message = responses.get(status_code, 'Unknown Error')
        
    response = HTTPResponse(status_code)
    
    if body is None:
        # Simple text error
        response.set_header('Content-Type', 'text/plain; charset=utf-8')
        response.set_body(f"Error {status_code}: {message}")
    else:
        # Custom body (HTML error pages, etc.)
        if isinstance(body, str):
            response.set_header('Content-Type', 'text/html; charset=utf-8')
        response.set_body(body)
        
    response.add_cache_headers('no-cache')
    return response


def create_file_response(status_code=200, content=b'', mime_type='application/octet-stream', 
                        filename=None, enable_cors=False, is_compressed=False):
    """
    Create a file serving response with appropriate headers.
    
    Args:
        status_code: HTTP status code
        content: File content (bytes)
        mime_type: MIME type
        filename: Optional filename for Content-Disposition
        enable_cors: Whether to add CORS headers
        is_compressed: Whether content is gzip compressed
        
    Returns:
        HTTPResponse object
    """
    response = HTTPResponse(status_code)
    response.set_header('Content-Type', mime_type)
    response.set_body(content)
    
    if filename:
        response.set_header('Content-Disposition', f'attachment; filename="{filename}"')
        
    if enable_cors:
        response.add_cors_headers()
        
    if is_compressed:
        response.add_compression_headers()
        
    response.add_cache_headers()
    return response


def create_options_response(enable_cors=True):
    """
    Create CORS preflight response.
    
    Returns:
        HTTPResponse object
    """
    response = HTTPResponse(204)  # No Content
    response.set_header('Allow', 'GET, HEAD, OPTIONS')
    
    if enable_cors:
        response.add_cors_headers()
        
    return response


def create_redirect_response(location, permanent=False):
    """
    Create a redirect response.
    
    Args:
        location: URL to redirect to
        permanent: Whether this is a permanent redirect
        
    Returns:
        HTTPResponse object
    """
    status = 301 if permanent else 302
    response = HTTPResponse(status)
    response.set_header('Location', location)
    response.add_cache_headers('no-cache')
    return response


# Convenience functions that send directly
def send_error_response(conn, status_code, message=None):
    """Send a simple error response"""
    response = create_error_response(status_code, message)
    return response.send(conn)


def send_options_response(conn):
    """Send CORS preflight response"""
    response = create_options_response()
    return response.send(conn)
