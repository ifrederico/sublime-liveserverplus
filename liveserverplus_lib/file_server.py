# liveserverplus_lib/file_server.py
"""File serving utilities"""
import os
from urllib.parse import quote, unquote

import sublime
from .utils import createFileReader
from .path_utils import validate_and_secure_path, resolve_served_path
from .file_utils import get_mime_type, isFileAllowed, find_index_file
from .http_utils import (HTTPResponse, create_file_response, create_error_response,
                         create_redirect_response)
from .logging import info, error
from .constants import STREAMING_THRESHOLD, LARGE_FILE_THRESHOLD
from .markdown_renderer import MarkdownRenderer, guess_markdown_title, ASSET_URL_PREFIX
from .buffer_cache import BufferCache

# Vendored browser assets (highlight.js, KaTeX, Mermaid) served under a
# reserved URL prefix so Markdown previews never reach out to a CDN. Sublime's
# resource API works for both unpacked development packages and installed
# .sublime-package archives; ordinary filesystem APIs do not work inside the
# latter.
VENDOR_ASSET_RESOURCE_ROOT = (
    'Packages/LiveServerPlus/liveserverplus_lib/vendor/assets'
)


def _vendor_asset_resource_path(rel_path):
    """Return a safe Sublime resource path for a vendored browser asset."""
    rel_path = unquote(rel_path)
    if not rel_path or '\x00' in rel_path or '\\' in rel_path:
        return None

    parts = rel_path.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return None

    return VENDOR_ASSET_RESOURCE_ROOT + '/' + '/'.join(parts)


class FileServer:
    """Handles file serving operations"""

    def __init__(self, settings):
        self.settings = settings
        self.websocket_injector = None  # Will be set by RequestHandler
        self.markdown_renderer = MarkdownRenderer()

    def _cachedBufferFor(self, file_path):
        """Return cached buffer bytes for ``file_path`` only when live
        reload is active. The cache is populated by the Sublime modify
        listener which runs only in that mode, so consulting it
        otherwise risks serving stale snapshots from a previous session.
        """
        if not getattr(self.settings, 'liveReload', False):
            return None
        return BufferCache.getInstance().get(file_path)
        
    def serveFile(self, conn, path, folders):
        """
        Main entry point for serving files.
        Returns True if a response was sent, False when nothing may be
        served for ``path`` (the caller then sends the 404 page).

        Dotfiles, dot-directories and paths matching ``ignoreFiles`` are
        treated as missing. A directory serves its index.html / index.htm
        from the first folder that has one, otherwise a listing.
        """
        # Vendored preview assets are served from the package, not the
        # user's folders, so they are resolved before anything else.
        if path.startswith(ASSET_URL_PREFIX + '/'):
            return self._serveVendorAsset(conn, path[len(ASSET_URL_PREFIX) + 1:])

        rel_path = unquote(path.lstrip('/'))
        ignore_patterns = getattr(self.settings, 'ignorePatterns', None) or []
        listing = None
            
        for folder in folders:
            target = resolve_served_path(folder, rel_path, ignore_patterns)
            if not target:
                continue
            
            if os.path.isdir(target):
                if not path.endswith('/'):
                    # Relative links inside the page resolve against the
                    # URL, so a directory needs its trailing slash.
                    location = '/' + quote(rel_path.lstrip('/\\'), safe='/')
                    if not location.endswith('/'):
                        location += '/'
                    return create_redirect_response(location, permanent=True).send(conn)
                index_path = find_index_file(target)
                if index_path:
                    index_rel = rel_path + os.path.basename(index_path)
                    if resolve_served_path(folder, index_rel, ignore_patterns):
                        return self._serveFile(conn, index_path, index_rel, folder)
                if listing is None:
                    listing = (target, folder)
            elif listing is None and os.path.isfile(target):
                return self._serveFile(conn, target, rel_path, folder)
                
        if listing:
            return self._serveDirectory(conn, listing[0], path, listing[1])
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

    def _serveVendorAsset(self, conn, rel_path):
        """Serve a vendored preview asset (highlight.js / KaTeX / Mermaid).

        These ship with the package and only change when the plugin itself
        is updated, so unlike user files they are served with a long-lived
        cache header. The Markdown preview reloads in full on every
        debounced keystroke; without this the browser would re-fetch and
        re-parse megabytes of JavaScript each time.
        """
        resource_path = _vendor_asset_resource_path(rel_path)
        if not resource_path:
            return False

        try:
            content = sublime.load_binary_resource(resource_path)
        except Exception as exc:
            error(f"Error loading vendored asset {resource_path}: {exc}")
            return False

        response = HTTPResponse(200)
        response.set_header('Content-Type', get_mime_type(resource_path))
        response.set_body(content)
        response.add_cache_headers('public, max-age=31536000, immutable')

        if self.settings.corsEnabled:
            response.add_cors_headers()

        return response.send(conn)

    def _serveMarkdown(self, conn, file_path):
        """Render and serve Markdown documents as HTML."""
        if getattr(self.settings, 'logging', False):
            info(f"Rendering Markdown preview: {file_path}")

        cached = self._cachedBufferFor(file_path)
        if cached is not None:
            try:
                markdown_source = cached.decode('utf-8', errors='replace')
            except Exception as exc:
                error(f"Error decoding cached markdown buffer for {file_path}: {exc}")
                return False
        else:
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
            html_doc = self.markdown_renderer.render(
                markdown_source,
                title=title,
                scroll_mode=scroll_mode,
                syntax_highlighting=getattr(self.settings, 'markdownSyntaxHighlighting', False),
                math=getattr(self.settings, 'markdownMath', False),
                mermaid=getattr(self.settings, 'markdownMermaid', False),
            )
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

        mime_type = get_mime_type(full_path)

        # If a Sublime view holds an unsaved edit for this path, serve that
        # snapshot instead of the on-disk bytes so live reload reflects
        # in-progress typing without forcing a save. Only consulted while
        # the live-reload feature is on; otherwise stale cache entries from
        # a prior session would shadow the disk file.
        cached = self._cachedBufferFor(full_path)
        if cached is not None and is_allowed:
            return self._sendFileContents(conn, full_path, mime_type, override_bytes=cached)

        # Get file size for streaming decision
        try:
            file_size = os.path.getsize(full_path)
            should_stream = file_size > STREAMING_THRESHOLD
        except OSError:
            return False

        # Every type is served inline; unknown extensions go out as
        # application/octet-stream, which browsers download on their own.
        if should_stream and not full_path.lower().endswith(('.html', '.htm')):
            return self._streamFile(conn, full_path, mime_type)
        return self._sendFileContents(conn, full_path, mime_type)
        
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
            
    def _sendFileContents(self, conn, file_path, mime_type, override_bytes=None):
        """Send file contents with optional WebSocket injection.

        ``override_bytes`` lets callers bypass the disk read (used when a
        dirty Sublime buffer snapshot should be served instead of the
        on-disk contents).
        """
        if override_bytes is None:
            # Check file size first to avoid loading large files
            try:
                file_size = os.path.getsize(file_path)
                # Large files should be streamed, not loaded into memory
                if file_size > LARGE_FILE_THRESHOLD and not file_path.lower().endswith(('.html', '.htm')):
                    return self._streamFile(conn, file_path, mime_type)
            except OSError:
                pass

            content = self._readFileFromDisk(file_path)
        else:
            content = override_bytes

        if content is None:
            return False
            
        # Inject WebSocket script for HTML files
        if file_path.lower().endswith(('.html', '.htm')) and self.websocket_injector:
            if getattr(self.settings, 'logging', False):
                info(f"Injecting WebSocket code into {file_path}")
            content = self.websocket_injector(content)

        # No compression: the server is usually reached over loopback,
        # where gzip only costs CPU on every reload.
        response = create_file_response(
            content=content,
            mime_type=mime_type,
            enable_cors=self.settings.corsEnabled
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
                
            # Send headers first
            headers_data = response.build()
            headers_only = headers_data[:headers_data.rfind(b'\r\n\r\n') + 4]
            conn.sendall(headers_only)
            
        except Exception as e:
            error(f"Error streaming file: {e}")
            return False
            
        try:
            for chunk in createFileReader(file_path):
                conn.sendall(chunk)
        except Exception as e:
            # The headers are already out, so report the response as sent:
            # the connection closes with a short body, and the caller must
            # not append a 404 page to it.
            error(f"Error streaming file: {e}")
                
        return True
            
    def _sendForbidden(self, conn):
        """Send 403 Forbidden response"""
        response = create_error_response(
            403, 
            body="<h1>403 Forbidden</h1><p>Access denied.</p>"
        )
        return response.send(conn)
