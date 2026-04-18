# liveserverplus_lib/buffer_cache.py
"""Thread-safe cache of unsaved Sublime buffer content.

Populated from Sublime's modify event listener and consumed by HTTP worker
threads when serving files. Lets the dev server preview in-progress edits
without forcing a save (which would trigger on-save hooks like
trim_trailing_white_space_on_save, format-on-save, ensure_newline_at_eof, etc).
"""
import os
import threading


class BufferCache:
    """Singleton {abs_path -> bytes} cache of dirty buffer snapshots."""

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def getInstance(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    @staticmethod
    def _normalize(path):
        if not path:
            return None
        try:
            # realpath resolves symlinks so cache keys agree with paths the
            # file_server produces via validate_and_secure_path (which calls
            # pathlib's resolve()). normcase handles platform case-insensitivity.
            return os.path.normcase(os.path.realpath(path))
        except Exception:
            try:
                return os.path.normcase(os.path.normpath(path))
            except Exception:
                return path

    def put(self, path, content):
        key = self._normalize(path)
        if not key:
            return
        if isinstance(content, str):
            content = content.encode('utf-8', errors='replace')
        elif not isinstance(content, (bytes, bytearray)):
            return
        with self._lock:
            self._cache[key] = bytes(content)

    def get(self, path):
        key = self._normalize(path)
        if not key:
            return None
        with self._lock:
            return self._cache.get(key)

    def evict(self, path):
        key = self._normalize(path)
        if not key:
            return
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()
