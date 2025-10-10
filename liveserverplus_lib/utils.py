# liveserverplus_lib/utils.py
"""General utilities - cleaned up version with imports from new modules"""
import os
import gzip
import webbrowser
import io
import platform
from urllib.parse import urlparse, unquote
from .logging import info, error
from .constants import SKIP_COMPRESSION_TYPES, BROWSER_COMMANDS

# Import from new centralized modules
from .file_utils import get_mime_type, is_binary_file

# File detection and handlin
def detectEncoding(file_path, sample_size=4096):
    """Simple encoding detection - just return UTF-8"""
    return 'utf-8'

def createFileReader(file_path, chunk_size=8192):
    """
    Create a generator that reads a file in chunks.
    
    Args:
        file_path (str): Path to the file
        chunk_size (int): Size of chunks to read
        
    Returns:
        generator: Generator that yields chunks of the file
    """
    f = None
    try:
        # Get file size for progress reporting
        file_size = os.path.getsize(file_path)
        bytes_read = 0
        
        # Open file in binary mode
        f = open(file_path, 'rb')
        
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
                
            bytes_read += len(chunk)
            # Only log for large files to reduce noise
            if file_size > 1024 * 1024:  # > 1MB
                info(f"Read {bytes_read}/{file_size} bytes from {os.path.basename(file_path)}")
            yield chunk
            
    except Exception as e:
        error(f"Error reading file {file_path}: {e}")
        # Always yield something to prevent hanging
        yield b''
    finally:
        # Ensure file is always closed
        if f:
            try:
                f.close()
            except Exception:
                pass
            
# Compression functions
def compressData(data, mime_type=None, compression_level=6):
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
    if shouldSkipCompression(mime_type):
        return data
            
    try:
        return gzip.compress(data, compression_level)
    except Exception as e:
        error(f"Compression error: {e}")
        return data

def streamCompressData(data_generator, mime_type=None, compression_level=6):
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
    if shouldSkipCompression(mime_type):
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

def shouldSkipCompression(mime_type):
    """
    Check if compression should be skipped for this MIME type
    
    Args:
        mime_type (str): MIME type to check
        
    Returns:
        bool: True if compression should be skipped
    """
    return mime_type in SKIP_COMPRESSION_TYPES

# Browser and network utilities
def openInBrowser(url, browser_name=None):
    """
    Open URL in specified browser or system default
    
    Args:
        url (str): URL to open
        browser_name (str, optional): Browser to use ('chrome', 'firefox', 'safari', 'edge')
    """
    try:
        if not browser_name:
            # Use default browser
            info(f"Opening URL in default browser: {url}")
            webbrowser.open(url)
            return

        # Handle specific browsers based on platform
        system = platform.system().lower()
        browser_name = browser_name.lower()

        if system == 'darwin':  # macOS
            # Use osascript for reliable browser control on macOS
            browser_map = {
                'chrome': 'Google Chrome',
                'firefox': 'Firefox',
                'safari': 'Safari',
                'edge': 'Microsoft Edge'
            }
            
            if browser_name in browser_map:
                app_name = browser_map[browser_name]
                info(f"Opening URL in {app_name} on macOS: {url}")
                
                import subprocess
                try:
                    # Use AppleScript to open URL in specific browser
                    script = f'tell application "{app_name}" to open location "{url}"'
                    subprocess.run(['osascript', '-e', script], check=True)
                    return
                except subprocess.CalledProcessError:
                    info(f"Failed to open {app_name}, falling back to default browser")
                    
        else:
            if browser_name == 'edge' and system == 'windows':
                info(f"Opening URL in Microsoft Edge on Windows: {url}")
                try:
                    os.startfile(f"microsoft-edge:{url}")  # type: ignore[attr-defined]
                    return
                except OSError:
                    info("Failed to launch Edge via protocol handler, falling back to default")

            # Use the existing BROWSER_COMMANDS for other platforms
            if browser_name in BROWSER_COMMANDS and system in BROWSER_COMMANDS[browser_name]:
                info(f"Opening URL in {browser_name} on {system}: {url}")
                try:
                    browser = webbrowser.get(BROWSER_COMMANDS[browser_name][system])
                    browser.open(url)
                    return
                except Exception as e:
                    info(f"Failed to use {browser_name}: {e}")

        # Fallback to default browser
        info(f"Browser '{browser_name}' not available, using default")
        webbrowser.open(url)
        
    except Exception as e:
        error(f"Error opening browser: {e}")
        # Final fallback to default browser
        try:
            webbrowser.open(url)
        except Exception:
            error(f"Failed to open URL: {url}")

def isValidPort(port):
    """
    Check if port number is valid
    
    Args:
        port (int): Port number to check
        
    Returns:
        bool: True if valid, False otherwise
    """
    return isinstance(port, int) and 1 <= port <= 65535

def getFreePort(start_port=8000, max_port=9000):
    """
    Find a random available port in range
    
    Args:
        start_port (int): Port to start checking from
        max_port (int): Maximum port to check
        
    Returns:
        int: First available port or None if none found
    """
    import socket
    import random
    
    # Create a list of ports to check in random order
    port_range = list(range(start_port, max_port))
    random.shuffle(port_range)
    
    for port in port_range:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('localhost', port))
                info(f"Found free port: {port}")
                return port
        except OSError:
            pass
    
    info(f"No free ports found in range {start_port}-{max_port}")
    return None

# HTTP utilities
def createResponseHeaders(content_length, content_type, compressed=False, extra_headers=None):
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

def parseQueryString(path):
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
