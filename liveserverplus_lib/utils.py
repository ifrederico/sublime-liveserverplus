# liveserverplus_lib/utils.py
import os
import gzip
import webbrowser
import pathlib
import io
from urllib.parse import urlparse, unquote
from .logging import debug, info, warning, error

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
    '.txt': 'text/plain',
    
    # Development
    '.map': 'application/json',
    '.ts': 'application/typescript',
    '.tsx': 'application/typescript',
    '.jsx': 'application/javascript'
}

# Security-related functions
def normalize_path(path):
    """
    Normalize a path to prevent path traversal attacks.
    
    Args:
        path (str): The path to normalize
        
    Returns:
        str: Normalized path or None if the path is suspicious
    """
    try:
        # Unquote URL encoded characters
        path = unquote(path)
        
        # Handle common problematic patterns
        if '../' in path or '..\\' in path or '//' in path or '\\\\' in path:
            warning(f"Suspicious path detected: {path}")
            return None
            
        # Use pathlib for secure path normalization
        normalized = pathlib.Path(path).resolve()
        
        # Convert to string for consistency
        return str(normalized)
    except Exception as e:
        error(f"Path normalization error: {e}")
        return None

def is_path_safe(base_folder, requested_path, strict=True):
    """
    Verify that a requested path doesn't escape the base folder.
    
    Args:
        base_folder (str): Base directory that should contain the path
        requested_path (str): Requested path to check
        strict (bool): If True, checks if path is strictly a subpath
                      If False, allows the path to be equal to base_folder
        
    Returns:
        bool: True if path is safe, False otherwise
    """
    try:
        base_folder = os.path.abspath(base_folder)
        base_path = pathlib.Path(base_folder).resolve()
        
        # Handle both absolute paths and relative paths
        if os.path.isabs(requested_path):
            full_path = pathlib.Path(requested_path).resolve()
        else:
            full_path = pathlib.Path(os.path.join(base_folder, requested_path)).resolve()
        
        # Check if full_path is within base_path
        if strict:
            # Strict mode: path must be a subpath
            return str(full_path).startswith(str(base_path)) and full_path != base_path
        else:
            # Non-strict mode: path can be equal to base_path
            return str(full_path).startswith(str(base_path))
    except Exception as e:
        error(f"Path safety check error: {e}")
        return False

# File detection and handling
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
        error(f"Error determining MIME type for {path}: {e}")
        return 'application/octet-stream'

def detect_encoding(file_path, sample_size=4096):
    """
    Attempt to detect file encoding by reading a sample.
    
    Args:
        file_path (str): Path to the file
        sample_size (int): Number of bytes to sample
        
    Returns:
        str: Detected encoding or 'utf-8' as fallback
    """
    try:
        # Try to import chardet for encoding detection
        try:
            import chardet
            has_chardet = True
        except ImportError:
            has_chardet = False
            debug("chardet not available for encoding detection, using fallbacks")
        
        # Read a sample of the file
        with open(file_path, 'rb') as f:
            sample = f.read(sample_size)
        
        if has_chardet:
            # Use chardet if available
            result = chardet.detect(sample)
            encoding = result.get('encoding', 'utf-8')
            confidence = result.get('confidence', 0)
            
            if encoding and confidence > 0.7:
                debug(f"Detected encoding for {file_path}: {encoding} (confidence: {confidence:.2f})")
                return encoding
        
        # Fallback detection
        if sample.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'  # UTF-8 with BOM
        elif sample.startswith(b'\xff\xfe'):
            return 'utf-16-le'  # UTF-16 Little Endian
        elif sample.startswith(b'\xfe\xff'):
            return 'utf-16-be'  # UTF-16 Big Endian
        
        # Try to decode as UTF-8
        try:
            sample.decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            # If it's not UTF-8, try ISO-8859-1 as a fallback
            return 'ISO-8859-1'
            
    except Exception as e:
        warning(f"Error detecting encoding for {file_path}: {e}")
        return 'utf-8'

def is_binary_file(file_path):
    """
    Check if file is binary
    
    Args:
        file_path (str): Path to file
        
    Returns:
        bool: True if binary, False otherwise
    """
    try:
        # Quick check based on extension
        ext = os.path.splitext(file_path.lower())[1]
        if ext in {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', 
                  '.exe', '.dll', '.so', '.mp3', '.mp4', '.webm'}:
            return True
            
        # Content-based check
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            # Check for null bytes (common in binary files)
            if b'\x00' in chunk:
                return True
                
            # Check for high concentration of non-ASCII bytes
            non_ascii = sum(1 for b in chunk if b > 127)
            if non_ascii > len(chunk) * 0.3:  # More than 30% non-ASCII
                return True
                
            return False
    except Exception as e:
        warning(f"Error checking if file is binary: {e}")
        return True

def create_file_reader(file_path, chunk_size=8192):
    """
    Create a generator that reads a file in chunks.
    
    Args:
        file_path (str): Path to the file
        chunk_size (int): Size of chunks to read
        
    Returns:
        generator: Generator that yields chunks of the file
    """
    try:
        # Get file size for progress reporting
        file_size = os.path.getsize(file_path)
        bytes_read = 0
        
        # Open file in binary mode
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                    
                bytes_read += len(chunk)
                debug(f"Read {bytes_read}/{file_size} bytes from {os.path.basename(file_path)}")
                yield chunk
    except Exception as e:
        error(f"Error reading file {file_path}: {e}")
        yield b''

# Compression functions
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
    if should_skip_compression(mime_type):
        return data
            
    try:
        return gzip.compress(data, compression_level)
    except Exception as e:
        error(f"Compression error: {e}")
        return data

def stream_compress_data(data_generator, mime_type=None, compression_level=6):
    """
    Compress data from a generator using gzip streaming.
    
    Args:
        data_generator: Generator yielding chunks of data
        mime_type (str): MIME type of the content
        compression_level (int): Compression level (1-9)
        
    Returns:
        generator: Generator yielding compressed chunks
    """
    # Skip compression for already compressed formats
    if should_skip_compression(mime_type):
        for chunk in data_generator:
            yield chunk
        return
    
    try:
        # Create a gzip compressor that writes to an in-memory buffer
        buffer = io.BytesIO()
        compressor = gzip.GzipFile(fileobj=buffer, mode='wb', compresslevel=compression_level)
        
        for chunk in data_generator:
            # Write the chunk to the compressor
            compressor.write(chunk)
            
            # Get the compressed data from the buffer
            buffer.seek(0)
            compressed_chunk = buffer.read()
            
            # If we got compressed data, yield it
            if compressed_chunk:
                yield compressed_chunk
                
                # Reset the buffer for the next chunk
                buffer.seek(0)
                buffer.truncate(0)
        
        # Close the compressor to flush any remaining data
        compressor.close()
        
        # Get any remaining compressed data
        buffer.seek(0)
        final_chunk = buffer.read()
        if final_chunk:
            yield final_chunk
            
    except Exception as e:
        error(f"Streaming compression error: {e}")
        # Fall back to uncompressed data
        for chunk in data_generator:
            yield chunk

def should_skip_compression(mime_type):
    """
    Check if compression should be skipped for this MIME type
    
    Args:
        mime_type (str): MIME type to check
        
    Returns:
        bool: True if compression should be skipped
    """
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
    
    return mime_type in SKIP_COMPRESSION_TYPES

# Browser and network utilities
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
            debug(f"Opening URL in default browser: {url}")
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
                debug(f"Opening URL in {browser_name} on {system}: {url}")
                browser = webbrowser.get(browser_commands[browser_name][system])
                browser.open(url)
                return

        # Fallback to default browser
        warning(f"Browser '{browser_name}' not available on {system}, using default")
        webbrowser.open(url)
        
    except Exception as e:
        error(f"Error opening browser: {e}")
        # Final fallback to default browser
        try:
            webbrowser.open(url)
        except Exception:
            error(f"Failed to open URL: {url}")

def is_valid_port(port):
    """
    Check if port number is valid
    
    Args:
        port (int): Port number to check
        
    Returns:
        bool: True if valid, False otherwise
    """
    return isinstance(port, int) and 1 <= port <= 65535

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
                debug(f"Found free port: {port}")
                return port
        except OSError:
            pass
    
    warning(f"No free ports found in range {start_port}-{max_port}")
    return None

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
        
        # Check if path is outside the root
        if rel_path.startswith('..'):
            warning(f"Path {file_path} is outside of root {root_path}")
            return None
            
        return rel_path
    except ValueError as e:
        error(f"Error computing relative path: {e}")
        return None

# HTTP utilities
def create_response_headers(content_length, content_type, compressed=False, extra_headers=None):
    """
    Create HTTP response headers
    
    Args:
        content_length (int): Length of content
        content_type (str): MIME type
        compressed (bool): Whether content is gzip compressed
        extra_headers (list): Additional headers to include
        
    Returns:
        list: List of header lines
    """
    headers = [
        b"HTTP/1.1 200 OK",
        f"Content-Type: {content_type}".encode('utf-8'),
        f"Content-Length: {content_length}".encode('utf-8'),
        b"Cache-Control: no-cache, no-store, must-revalidate",
        # Security headers
        b"X-Content-Type-Options: nosniff",
        b"X-Frame-Options: SAMEORIGIN",
        b"Referrer-Policy: same-origin"
    ]
    
    if compressed:
        headers.append(b"Content-Encoding: gzip")
        
    if extra_headers:
        headers.extend(extra_headers)
        
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
                    query_dict[key] = unquote(value)
                else:
                    # Handle parameters without values
                    query_dict[pair] = ''
                    
        return query_dict
    except Exception as e:
        error(f"Error parsing query string: {e}")
        return {}