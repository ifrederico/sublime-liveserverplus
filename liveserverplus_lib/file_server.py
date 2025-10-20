# liveserverplus_lib/file_server.py
"""File serving utilities"""
import os
from urllib.parse import unquote
from .utils import (compressData, detectEncoding, createFileReader, 
                   streamCompressData, shouldSkipCompression)
from .path_utils import validate_and_secure_path
from .file_utils import (get_mime_type, isFileAllowed, should_compress_file)
from .http_utils import (HTTPResponse, create_file_response, create_error_response)
from .logging import info, error
from .constants import STREAMING_THRESHOLD, LARGE_FILE_THRESHOLD
from .markdown_renderer import MarkdownRenderer, guess_markdown_title


class FileServer:
    """Handles file serving operations"""
    
    def __init__(self, settings):
        self.settings = settings
        self.websocket_injector = None  # Will be set by RequestHandler
        self.markdown_renderer = MarkdownRenderer()
        
    def serveFile(self, conn, path, folders):
        """
        Main entry point for serving files.
        Returns True if file was served, False otherwise.
        """
        # Quick existence check for common case
        if path == '/' or path == '/index.html':
            for folder in folders:
                index_path = os.path.join(folder, 'index.html')
                if os.path.isfile(index_path):
                    return self._serveFile(conn, index_path, 'index.html', folder)
            
        rel_path = unquote(path.lstrip('/'))
        
        # Try to find and serve the file
        for folder in folders:
            full_path = os.path.join(folder, rel_path)
            
            # Check if it's a directory
            if os.path.isdir(full_path):
                return self._serveDirectory(conn, full_path, path, folder)
                
            # Check if it's a file
            if os.path.isfile(full_path):
                return self._serveFile(conn, full_path, rel_path, folder)
                
        return False
        
    def _serveDirectory(self, conn, dir_path, url_path, root_path):
        """Serve a directory listing"""
        from .directory_listing import DirectoryListing
        
        try:
            lister = DirectoryListing(settings=self.settings)
            content = lister.generate_listing(dir_path, url_path, root_path)
            
            response = create_file_response(
                content=content,
                mime_type='text/html; charset=utf-8',
                enable_cors=self.settings.corsEnabled
            )
            
            return response.send(conn)
        except Exception as e:
            error(f"Error serving directory: {e}")
            return False

    def _serveMarkdown(self, conn, file_path):
        """Render and serve Markdown documents as HTML."""
        if getattr(self.settings, 'logging', False):
            info(f"Rendering Markdown preview: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as handle:
                markdown_source = handle.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as handle:
                    markdown_source = handle.read()
            except OSError as exc:
                error(f"Error reading markdown file {file_path}: {exc}")
                return False
        except OSError as exc:
            error(f"Error reading markdown file {file_path}: {exc}")
            return False

        title = guess_markdown_title(file_path, markdown_source)

        try:
            scroll_mode = getattr(self.settings, 'markdownScrollSyncMode', 'editor')
            html_doc = self.markdown_renderer.render(markdown_source, title=title, scroll_mode=scroll_mode)
        except Exception as exc:
            error(f"Markdown rendering failed for {file_path}: {exc}")
            return False

        html_bytes = html_doc.encode('utf-8')

        if self.websocket_injector:
            html_bytes = self.websocket_injector(html_bytes)

        response = create_file_response(
            content=html_bytes,
            mime_type='text/html; charset=utf-8',
            enable_cors=self.settings.corsEnabled
        )

        return response.send(conn)
            
    def _serveFile(self, conn, full_path, rel_path, base_folder):
        """Serve a single file with appropriate handling"""
        if getattr(self.settings, 'logging', False):
            info(f"Serving file: {full_path}")
        # Use comprehensive path validation and retrieve sanitized path
        safe_path = validate_and_secure_path(base_folder, rel_path)
        if not safe_path:
            return self._sendForbidden(conn)
        full_path = safe_path

        file_ext = os.path.splitext(full_path)[1].lower()

        if file_ext == '.md' and self.settings.renderMarkdownPreview:
            return self._serveMarkdown(conn, full_path)
            
        # Check if file is allowed using centralized function with optimized set
        is_allowed = isFileAllowed(full_path, self.settings.allowedFileTypesSet)
        
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
                return self._streamFile(conn, full_path, mime_type)
            else:
                return self._sendFileContents(conn, full_path, mime_type)
        else:
            # Force download for non-allowed files
            return self._sendAsDownload(conn, full_path, mime_type, file_size)
        
    def _readFileFromDisk(self, file_path):
        """Read file from disk in binary mode"""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.settings.maxFileSize * 1024 * 1024:
                error(f"File too large: {file_path}")
                return None
                
            with open(file_path, 'rb') as f:
                content = f.read()

            return content
                    
        except Exception as e:
            error(f"Error reading file {file_path}: {e}")
            return None
            
    def _sendFileContents(self, conn, file_path, mime_type):
        """Send file contents with optional WebSocket injection"""
        # Check file size first to avoid loading large files
        try:
            file_size = os.path.getsize(file_path)
            # Large files should be streamed, not loaded into memory
            if file_size > LARGE_FILE_THRESHOLD and not file_path.lower().endswith(('.html', '.htm')):
                return self._streamFile(conn, file_path, mime_type)
        except OSError:
            pass
        
        content = self._readFileFromDisk(file_path)
        if content is None:
            return False
            
        # Inject WebSocket script for HTML files FIRST (before compression)
        if file_path.lower().endswith(('.html', '.htm')) and self.websocket_injector:
            if getattr(self.settings, 'logging', False):
                info(f"Injecting WebSocket code into {file_path}")
            content = self.websocket_injector(content)

        # Apply compression if enabled and appropriate
        is_compressed = False
        if getattr(self.settings, 'enableCompression', False) and should_compress_file(file_path, mime_type):
            try:
                compressed = compressData(content, mime_type)
                # Only use compressed version if it's actually smaller
                if len(compressed) < len(content):
                    content = compressed
                    is_compressed = True
            except Exception as e:
                if getattr(self.settings, 'logging', False):
                    error(f"Compression failed for {file_path}: {e}")

        response = create_file_response(
            content=content,
            mime_type=mime_type,
            enable_cors=self.settings.corsEnabled,
            is_compressed=is_compressed
        )
        
        return response.send(conn)
        
    def _streamFile(self, conn, file_path, mime_type):
        """Stream large files without loading into memory"""
        try:
            file_size = os.path.getsize(file_path)
            info(f"Streaming file {file_path} ({file_size} bytes)")
            
            # HTML files need injection, so can't stream
            if file_path.lower().endswith(('.html', '.htm')):
                return self._sendFileContents(conn, file_path, mime_type)
            
            response = HTTPResponse(200)
            response.set_header('Content-Type', mime_type)
            response.set_header('Content-Length', str(file_size))
            response.add_cache_headers()
            
            if self.settings.corsEnabled:
                response.add_cors_headers()
                
            # Skip compression for dev server
            should_compress = False
                
            # Send headers first
            headers_data = response.build()
            headers_only = headers_data[:headers_data.rfind(b'\r\n\r\n') + 4]
            conn.send(headers_only)
            
            # Stream file contents
            file_reader = createFileReader(file_path)
            
            for chunk in file_reader:
                conn.send(chunk)
                
            return True
            
        except Exception as e:
            error(f"Error streaming file: {e}")
            return False
            
    def _sendAsDownload(self, conn, file_path, mime_type, file_size):
        """Send file as download with Content-Disposition header"""
        filename = os.path.basename(file_path)
        
        response = HTTPResponse(200)
        response.set_header('Content-Type', mime_type)
        response.set_header('Content-Disposition', f'attachment; filename="{filename}"')
        response.add_cache_headers()
        
        if self.settings.corsEnabled:
            response.add_cors_headers()
            
        # Stream if large, otherwise read into memory
        if file_size > (1024 * 1024):  # 1MB
            response.set_header('Content-Length', str(file_size))
            headers_data = response.build()
            headers_only = headers_data[:headers_data.rfind(b'\r\n\r\n') + 4]
            conn.send(headers_only)
            
            for chunk in createFileReader(file_path):
                conn.send(chunk)
                
            return True
        else:
            content = self._readFileFromDisk(file_path)
            if content is None:
                return False
                
            response.set_body(content)
            return response.send(conn)
            
    def _sendForbidden(self, conn):
        """Send 403 Forbidden response"""
        response = create_error_response(
            403, 
            body="<h1>403 Forbidden</h1><p>Access denied.</p>"
        )
        return response.send(conn)
