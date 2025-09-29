# liveserverplus_lib/directory_listing.py
"""Directory listing module"""
import os
from datetime import datetime
from typing import Dict, List, Any
import sublime
import time
from string import Template
from .logging import info, error
from .constants import FILE_ICONS, DEFAULT_FILE_ICON, DIRECTORY_ICON
from .text_utils import format_file_size, extract_file_extension
from .file_utils import isFileAllowed


class DirectoryListing:
    """Handles directory listing pages"""
    
    _MAX_CACHE_SIZE = 50  # Maximum number of cached directories
    _CACHE_CLEANUP_INTERVAL = 300  # Clean cache every 5 minutes

    def __init__(self, settings=None):
        self.settings = settings
        self._cache = {}
        self._cache_time = {}
        self._last_cleanup = time.time()
        self.cache_duration = 2  # seconds

        try:
            # Must match your actual package and folder names:
            resource_path = "Packages/LiveServerPlus/liveserverplus_lib/templates/directory_listing.html"
            raw_template = sublime.load_resource(resource_path)
            self.template = raw_template
        except Exception as e:
            error(f"Error loading template: {e}")
            self.template = "<html><body>Error loading template</body></html>"
    
    def _cleanup_cache(self):
        """Clean up old cache entries to prevent memory growth"""
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = [
            key for key, cached_time in self._cache_time.items()
            if current_time - cached_time > self.cache_duration
        ]
        
        for key in expired_keys:
            del self._cache[key]
            del self._cache_time[key]
        
        # If still too large, remove oldest entries
        if len(self._cache) > self._MAX_CACHE_SIZE:
            # Sort by time and remove oldest
            sorted_items = sorted(self._cache_time.items(), key=lambda x: x[1])
            remove_count = len(self._cache) - self._MAX_CACHE_SIZE + 10  # Remove extra
            
            for key, _ in sorted_items[:remove_count]:
                del self._cache[key]
                del self._cache_time[key]
            
            info(f"Directory cache cleaned, removed {remove_count} entries")
        
        self._last_cleanup = current_time
        
    def get_file_info(self, path: str, entry: os.DirEntry = None) -> Dict[str, Any]:
        """Get standardized file information"""
        try:
            if entry:
                is_dir = entry.is_dir()
                name = entry.name
                stat_info = entry.stat()
            else:
                is_dir = os.path.isdir(path)
                name = os.path.basename(path)
                stat_info = os.stat(path)

            if is_dir:
                return {
                    'name': name,
                    'icon': DIRECTORY_ICON,
                    'type': "directory",
                    'size': "-",
                    'modified': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')
                }
            else:
                ext = extract_file_extension(name)
                return {
                    'name': name,
                    'icon': FILE_ICONS.get(ext, DEFAULT_FILE_ICON),
                    'type': "file",
                    'size': format_file_size(stat_info.st_size),
                    'modified': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')
                }
        except Exception as e:
            error(f"Error getting file info for {path}: {e}")
            return None

    def generate_items_list(self, dir_path: str, include_hidden: bool = False) -> List[Dict[str, Any]]:
        """Generate list of directory items with consistent formatting"""
        items = []
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if not include_hidden and entry.name.startswith('.'):
                        continue
                    file_info = self.get_file_info(entry.path, entry)
                    if file_info:
                        items.append(file_info)
            
            # Sort: directories first, then files, all alphabetically
            return sorted(items, key=lambda x: (x['type'] != 'directory', x['name'].lower()))
        except Exception as e:
            error(f"Error generating items list for {dir_path}: {e}")
            return []

    def generate_listing(self, dir_path: str, url_path: str, root_path: str) -> bytes:
        """Generate complete directory listing page"""
        # Check if we need to clean cache
        current_time = time.time()
        if current_time - self._last_cleanup > self._CACHE_CLEANUP_INTERVAL:
            self._cleanup_cache()
        
        # Check cache first
        cache_key = f"{dir_path}:{url_path}"
        if cache_key in self._cache:
            if current_time - self._cache_time.get(cache_key, 0) < self.cache_duration:
                return self._cache[cache_key]
            
        try:
            items = self.generate_items_list(dir_path)
            
            # Add URL paths to items
            for item in items:
                item_path = os.path.join(url_path, item['name']).replace('\\', '/')
                if item['type'] == 'directory':
                    item_path += '/'
                item['url'] = item_path

            # Create parent link HTML if not at root
            parent_link = ''
            if url_path != '/':
                parent = os.path.dirname(url_path.rstrip('/'))
                parent_path = parent or "/"
                parent_link = f'''
                    <a href="{parent_path}" class="parent-link">
                        <span class="icon">{DIRECTORY_ICON}</span>
                        Parent Directory
                    </a>
                '''

            # Generate items HTML
            items_html = ''.join(self._generate_item_html(item) for item in items)

            # Simple template substitution
            template = Template(self.template)
            html = template.safe_substitute(
                path=url_path,
                parent_link=parent_link,
                items=items_html
            )
            
            # Cache the result
            result = html.encode('utf-8')
            self._cache[cache_key] = result
            self._cache_time[cache_key] = current_time
            return result
            
        except Exception as e:
            return f"<p>Error reading directory: {e}</p>".encode('utf-8')