import os
import gzip
import webbrowser
from urllib.parse import urlparse

MIME_TYPES = {
    # Web
    '.html': 'text/html',
    '.htm': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.mjs': 'application/javascript',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.wasm': 'application/wasm',
    
    # Images
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.webp': 'image/webp',
    
    # Fonts
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.eot': 'application/vnd.ms-fontobject',
    
    # Media
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.ogg': 'audio/ogg',
    
    # Documents
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    
    # Development
    '.map': 'application/json',
    '.ts': 'application/typescript',
    '.tsx': 'application/typescript',
    '.jsx': 'application/javascript'
}

def get_mime_type(path):
    """
    Get MIME type for file path with better error handling
    
    Args:
        path (str): File path
        
    Returns:
        str: MIME type or 'application/octet-stream' if unknown
    """
    if not path:
        return 'application/octet-stream'
        
    try:
        ext = os.path.splitext(path.lower())[1]
        return MIME_TYPES.get(ext, 'application/octet-stream')
    except Exception as e:
        print(f"Error determining MIME type for {path}: {e}")
        return 'application/octet-stream'

def compress_data(data, mime_type=None, compression_level=6):
    """
    Compress data using gzip, skipping already compressed formats
    
    Args:
        data (bytes): Data to compress
        mime_type (str): MIME type of the content
        compression_level (int): Compression level (1-9)
        
    Returns:
        bytes: Compressed data or original data if compression is skipped
    """
    # Skip compression for already compressed formats
    SKIP_COMPRESSION_TYPES = {
        # Images
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'image/x-icon',
        
        # Audio/Video
        'audio/mpeg',
        'audio/mp4',
        'video/mp4',
        'video/webm',
        'audio/ogg',
        
        # Archives
        'application/zip',
        'application/x-rar-compressed',
        'application/x-7z-compressed',
        
        # PDFs
        'application/pdf',
        
        # Fonts
        'font/woff',
        'font/woff2',
    }
    
    try:
        # Skip compression if mime type is in skip list
        if mime_type in SKIP_COMPRESSION_TYPES:
            return data
            
        return gzip.compress(data, compression_level)
    except Exception as e:
        print(f"Compression error: {e}")
        return data

def open_in_browser(url, browser_name=None):
    """
    Open URL in specified browser or system default
    
    Args:
        url (str): URL to open
        browser_name (str, optional): Browser to use ('chrome', 'firefox', 'safari', 'edge')
    """
    import webbrowser
    import platform

    try:
        if not browser_name:
            # Use default browser
            webbrowser.open(url)
            return

        # Handle specific browsers based on platform
        system = platform.system().lower()
        browser_name = browser_name.lower()
        
        browser_commands = {
            'chrome': {
                'darwin': 'google chrome',
                'linux': 'google-chrome',
                'windows': 'chrome'
            },
            'firefox': {
                'darwin': 'firefox',
                'linux': 'firefox',
                'windows': 'firefox'
            },
            'safari': {
                'darwin': 'safari'
            },
            'edge': {
                'darwin': 'microsoft-edge',
                'linux': 'microsoft-edge',
                'windows': 'msedge'
            }
        }

        # Get browser command for current platform
        if browser_name in browser_commands:
            if system in browser_commands[browser_name]:
                browser = webbrowser.get(browser_commands[browser_name][system])
                browser.open(url)
                return

        # Fallback to default browser
        print(f"Browser '{browser_name}' not available on {system}, using default")
        webbrowser.open(url)
        
    except Exception as e:
        print(f"Error opening browser: {e}")
        # Final fallback to default browser
        webbrowser.open(url)

def is_valid_port(port):
    """
    Check if port number is valid
    
    Args:
        port (int): Port number to check
        
    Returns:
        bool: True if valid, False otherwise
    """
    return isinstance(port, int) and 1 <= port <= 65535

def get_relative_path(root_path, file_path):
    """
    Get relative path from root to file
    
    Args:
        root_path (str): Root directory path
        file_path (str): File path
        
    Returns:
        str: Relative path or None if outside root
    """
    try:
        rel_path = os.path.relpath(file_path, root_path)
        return None if rel_path.startswith('..') else rel_path
    except ValueError:
        return None

def is_binary_file(file_path):
    """
    Check if file is binary
    
    Args:
        file_path (str): Path to file
        
    Returns:
        bool: True if binary, False otherwise
    """
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\0' in chunk
    except Exception:
        return True

def get_free_port(start_port=8000, max_port=9000):
    """
    Find first available port in range
    
    Args:
        start_port (int): Port to start checking from
        max_port (int): Maximum port to check
        
    Returns:
        int: First available port or None if none found
    """
    import socket
    
    for port in range(start_port, max_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('localhost', port))
                return port
        except OSError:
            continue
    return None

def create_response_headers(content_length, content_type, compressed=False):
    """
    Create HTTP response headers
    
    Args:
        content_length (int): Length of content
        content_type (str): MIME type
        compressed (bool): Whether content is gzip compressed
        
    Returns:
        list: List of header lines
    """
    headers = [
        b"HTTP/1.1 200 OK",
        f"Content-Type: {content_type}".encode(),
        f"Content-Length: {content_length}".encode(),
        b"Cache-Control: no-cache, no-store, must-revalidate",
        b"Access-Control-Allow-Origin: *"
    ]
    
    if compressed:
        headers.append(b"Content-Encoding: gzip")
        
    return headers

def parse_query_string(path):
    """
    Parse query string from path
    
    Args:
        path (str): URL path with query string
        
    Returns:
        dict: Dictionary of query parameters
    """
    try:
        parsed = urlparse(path)
        query_dict = {}
        
        if parsed.query:
            pairs = parsed.query.split('&')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    query_dict[key] = value
                    
        return query_dict
    except Exception:
        return {}