# liveserverplus_lib/cache.py
import time
import os
import hashlib
from collections import OrderedDict
from .logging import debug, info, warning, error

class FileCache:
    """Simple in-memory cache for file contents to reduce disk reads"""
    
    def __init__(self, max_size=50, max_age=300):
        """
        Initialize a new file cache
        
        Args:
            max_size (int): Maximum number of files to cache
            max_age (int): Maximum age of cache entries in seconds
        """
        self.max_size = max_size  # Max number of files to cache
        self.max_age = max_age    # Max age in seconds
        self.cache = OrderedDict()  # {file_path: (content, timestamp, etag)}
        
    def get(self, file_path):
        """
        Get file content from cache if available and not expired
        
        Args:
            file_path (str): Path to the file
            
        Returns:
            tuple: (content, etag) or (None, None) if not in cache
        """
        if file_path not in self.cache:
            return None, None
            
        content, timestamp, etag = self.cache[file_path]
        
        # Check if entry has expired
        if time.time() - timestamp > self.max_age:
            # Remove expired entry
            del self.cache[file_path]
            return None, None
            
        # Move to end (mark as recently used)
        self.cache.move_to_end(file_path)
        
        return content, etag
        
    def set(self, file_path, content):
        """
        Store file content in cache
        
        Args:
            file_path (str): Path to the file
            content (bytes): File content
            
        Returns:
            str: ETag for the content
        """
        # Generate ETag (hash of content)
        etag = hashlib.md5(content).hexdigest()
        
        # If we're at capacity, remove oldest item
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
            
        # Store in cache
        self.cache[file_path] = (content, time.time(), etag)
        
        return etag
        
    def invalidate(self, file_path):
        """
        Remove file from cache
        
        Args:
            file_path (str): Path to the file
        """
        if file_path in self.cache:
            del self.cache[file_path]
            
    def clear(self):
        """Clear all cache entries"""
        self.cache.clear()
        
    def get_stats(self):
        """
        Get cache statistics
        
        Returns:
            dict: Cache statistics
        """
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'max_age': self.max_age,
            'memory_usage': sum(len(content) for content, _, _ in self.cache.values())
        }


class CacheManager:
    """Manages caching for the server"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the cache manager"""
        self.file_cache = FileCache()
        self.cache_enabled = True
        
    def configure(self, settings):
        """
        Configure the cache manager from settings
        
        Args:
            settings: ServerSettings object
        """
        if hasattr(settings, '_settings'):
            cache_settings = settings._settings.get('cache', {})
            self.cache_enabled = cache_settings.get('enabled', True)
            
            max_size = cache_settings.get('max_files', 50)
            max_age = cache_settings.get('max_age', 300)
            
            self.file_cache = FileCache(max_size=max_size, max_age=max_age)
            
    def get_cache_headers(self, file_path, mime_type, etag=None):
        """
        Generate appropriate cache headers based on file type
        
        Args:
            file_path (str): Path to the file
            mime_type (str): MIME type of the file
            etag (str): Optional ETag value
            
        Returns:
            list: List of cache headers as bytes
        """
        headers = []
        
        # Add ETag if provided
        if etag:
            headers.append(f"ETag: \"{etag}\"".encode('utf-8'))
        
        # For HTML, CSS, and JavaScript, use shorter cache time
        if mime_type in ['text/html', 'text/css', 'application/javascript']:
            headers.append(b"Cache-Control: max-age=60, must-revalidate")
        # For images, fonts, and other static assets, use longer cache time
        elif mime_type.startswith(('image/', 'font/', 'application/pdf')):
            headers.append(b"Cache-Control: max-age=86400, public")  # 1 day
        else:
            # Default cache policy
            headers.append(b"Cache-Control: max-age=300, must-revalidate")  # 5 minutes
            
        return headers