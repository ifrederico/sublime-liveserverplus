# liveserverplus_lib/file_server.py
"""File serving utilities"""
import os
from .utils import (compress_data, detect_encoding, create_file_reader, 
                   stream_compress_data, should_skip_compression)
from .path_utils import validate_and_secure_path
from .file_utils import (get_mime_type, is_file_allowed, is_text_file, 
                        extract_file_extension, should_compress_file)
from .http_utils import (HTTPResponse, create_file_response, create_error_response)
from .logging import info, error
from .constants import STREAMING_THRESHOLD, LARGE_FILE_THRESHOLD


class FileServer:
    """Handles file serving operations"""
    
    def __init__(self, settings):
        self.settings = settings
        self.websocket_injector = None  # Will be set by RequestHandler
        
    def serve_file(self, conn, path, folders):
        """
        Main entry point for serving files.
        Returns True if file was served, False otherwise.
        """
        # Quick existence check for common case
        if path == '/' or path == '/index.html':
            for folder in folders:
                index_path = os.path.join(folder, 'index.html')
                if os.path.isfile(index_path):
                    return self._serve_file(conn, index_path, 'index.html', folder)
            
        rel_path = path.lstrip('/')
        
        # Try to find and serve the file
        for folder in folders:
            full_path = os.path.join(folder, rel_path)
            
            # Check if it's a directory
            if os.path.isdir(full_path):
                return self._serve_directory(conn, full_path, path, folder)
                
            # Check if it's a file
            if os.path.isfile(full_path):
                return self._serve_file(conn, full_path, rel_path, folder)
                
        return False
        
    def _serve_directory(self, conn, dir_path, url_path, root_path):
        """Serve a directory listing"""
        from .directory_listing import DirectoryListing
        
        try:
            lister = DirectoryListing(settings=self.settings)
            content = lister.generate_listing(dir_path, url_path, root_path)
            
            response = create_file_response(
                content=content,
                mime_type='text/html; charset=utf-8',
                enable_cors=self.settings.cors_enabled
            )
            
            return response.send(conn)
        except Exception as e:
            error(f"Error serving directory: {e}")
            return False
            
    def _serve_file(self, conn, full_path, rel_path, base_folder):
        """Serve a single file with appropriate handling"""
        # Use comprehensive path validation
        if not validate_and_secure_path(base_folder, rel_path):
            return self._send_forbidden(conn)
            
        # Check if file is allowed using centralized function
        is_allowed = is_file_allowed(full_path, self.settings.allowed_file_types)
        
        # Get file size for streaming decision
        try:
            file_size = os.path.getsize(full_path)
            should_stream = file_size > STREAMING_THRESHOLD
        except OSError:
            return False
            
        mime_type = get_mime_type(full_path)
        
        # Handle different serving methods
        if is_allowed:
            if should_stream and not full_path.lower().endswith(('.html', '.htm')):
                return self._stream_file(conn, full_path, mime_type)
            else:
                return self._send_file_contents(conn, full_path, mime_type)
        else:
            # Force download for non-allowed files
            return self._send_as_download(conn, full_path, mime_type, file_size)
        
    def _read_file_from_disk(self, file_path):
        """Read file from disk with encoding detection"""
        try:
            # Check file size limit
            file_size = os.path.getsize(file_path)
            if file_size > self.settings.max_file_size * 1024 * 1024:
                error(f"File too large: {file_path}")
                return None
                
            # Text files - detect encoding
            if is_text_file(file_path):
                encoding = detect_encoding(file_path)
                info(f"Reading text file {file_path} with encoding {encoding}")
                with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                    return f.read().encode('utf-8')
            else:
                # Binary files
                info(f"Reading binary file {file_path}")
                with open(file_path, 'rb') as f:
                    return f.read()
                    
        except Exception as e:
            error(f"Error reading file {file_path}: {e}")
            return None
            
    def _send_file_contents(self, conn, file_path, mime_type):
        """Send file contents with optional WebSocket injection"""
        # Check file size first to avoid loading large files
        try:
            file_size = os.path.getsize(file_path)
            # Large files should be streamed, not loaded into memory
            if file_size > LARGE_FILE_THRESHOLD and not file_path.lower().endswith(('.html', '.htm')):
                return self._stream_file(conn, file_path, mime_type)
        except OSError:
            pass
        
        content = self._read_file_from_disk(file_path)
        if content is None:
            return False
            
        # Inject WebSocket script for HTML files
        if file_path.lower().endswith(('.html', '.htm')) and self.websocket_injector:
            content = self.websocket_injector(content)
            
        # Check if we should compress
        should_compress = (self.settings.enable_compression and 
                        should_compress_file(file_path, mime_type))
        
        if should_compress:
            compressed = compress_data(content, mime_type)
            if len(compressed) < len(content):
                content = compressed
                is_compressed = True
            else:
                is_compressed = False
        else:
            is_compressed = False
            
        response = create_file_response(
            content=content,
            mime_type=mime_type,
            enable_cors=self.settings.cors_enabled,
            is_compressed=is_compressed
        )
        
        return response.send(conn)
        
    def _stream_file(self, conn, file_path, mime_type):
        """Stream large files without loading into memory"""
        try:
            file_size = os.path.getsize(file_path)
            info(f"Streaming file {file_path} ({file_size} bytes)")
            
            # HTML files need injection, so can't stream
            if file_path.lower().endswith(('.html', '.htm')):
                return self._send_file_contents(conn, file_path, mime_type)
            
            response = HTTPResponse(200)
            response.set_header('Content-Type', mime_type)
            response.set_header('Content-Length', str(file_size))
            response.add_cache_headers()
            
            if self.settings.cors_enabled:
                response.add_cors_headers()
                
            should_compress = (self.settings.enable_compression and 
                             should_compress_file(file_path, mime_type))
            
            if should_compress:
                response.add_compression_headers()
                
            # Send headers first
            headers_data = response.build()
            headers_only = headers_data[:headers_data.rfind(b'\r\n\r\n') + 4]
            conn.send(headers_only)
            
            # Stream file contents
            file_reader = create_file_reader(file_path)
            
            if should_compress:
                for chunk in stream_compress_data(file_reader, mime_type):
                    conn.send(chunk)
            else:
                for chunk in file_reader:
                    conn.send(chunk)
                
            return True
            
        except Exception as e:
            error(f"Error streaming file: {e}")
            return False
            
    def _send_as_download(self, conn, file_path, mime_type, file_size):
        """Send file as download with Content-Disposition header"""
        filename = os.path.basename(file_path)
        
        response = HTTPResponse(200)
        response.set_header('Content-Type', mime_type)
        response.set_header('Content-Disposition', f'attachment; filename="{filename}"')
        response.add_cache_headers()
        
        if self.settings.cors_enabled:
            response.add_cors_headers()
            
        # Stream if large, otherwise read into memory
        if file_size > (1024 * 1024):  # 1MB
            response.set_header('Content-Length', str(file_size))
            headers_data = response.build()
            headers_only = headers_data[:headers_data.rfind(b'\r\n\r\n') + 4]
            conn.send(headers_only)
            
            for chunk in create_file_reader(file_path):
                conn.send(chunk)
                
            return True
        else:
            content = self._read_file_from_disk(file_path)
            if content is None:
                return False
                
            response.set_body(content)
            return response.send(conn)
            
    def _send_forbidden(self, conn):
        """Send 403 Forbidden response"""
        response = create_error_response(
            403, 
            body="<h1>403 Forbidden</h1><p>Access denied.</p>"
        )
        return response.send(conn)