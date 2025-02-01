import os
import time
import threading
from fnmatch import fnmatch

class FileWatcher(threading.Thread):
    """Watches for file changes in specified directories"""
    
    def __init__(self, folders, callback, settings):
        super().__init__()
        self.folders = folders
        self.callback = callback
        self.settings = settings
        self._stop_event = threading.Event()
        self._mtimes = {}
        self._scan_lock = threading.Lock()
        
    def run(self):
        """Start watching for file changes with improved interrupt handling"""
        while not self._stop_event.is_set():
            try:
                self.scan_folders()
                # Use event wait instead of sleep for more responsive shutdown
                self._stop_event.wait(self.settings.poll_interval)
            except Exception as e:
                print(f"Error in file watcher: {e}")
                if not self._stop_event.is_set():
                    # Add a small delay before retrying if there's an error
                    self._stop_event.wait(1)
                
    def scan_folders(self):
        """Scan folders for changes with thread safety"""
        with self._scan_lock:
            for folder in self.folders:
                if self._stop_event.is_set():
                    return
                self.scan_folder(folder)
                
    def scan_folder(self, folder):
        """Scan a single folder for changes"""
        try:
            for root, dirs, files in os.walk(folder, followlinks=False):
                if self._stop_event.is_set():
                    return
                    
                # Skip ignored directories
                dirs[:] = [d for d in dirs if not self._should_ignore(d)]
                
                for filename in files:
                    if self._stop_event.is_set():
                        return
                        
                    if self._should_watch_file(filename):
                        filepath = os.path.join(root, filename)
                        self._check_file(filepath)
                        
        except Exception as e:
            print(f"Error scanning folder {folder}: {e}")
            
    def _check_file(self, filepath):
        """Check if a file has changed with proper error handling"""
        if self._stop_event.is_set():
            return
            
        try:
            mtime = os.path.getmtime(filepath)
            stored_time = self._mtimes.get(filepath)
            
            if stored_time is None:
                # First time seeing this file
                self._mtimes[filepath] = mtime
            elif mtime > stored_time:
                # File has been modified
                self._mtimes[filepath] = mtime
                try:
                    self.callback(filepath)
                except Exception as e:
                    print(f"Error in file change callback for {filepath}: {e}")
                
        except OSError as e:
            # File may have been deleted or inaccessible
            if filepath in self._mtimes:
                del self._mtimes[filepath]
                try:
                    self.callback(filepath)
                except Exception as callback_error:
                    print(f"Error in file deletion callback for {filepath}: {callback_error}")
        except Exception as e:
            print(f"Unexpected error checking file {filepath}: {e}")
                
    def _should_ignore(self, name):
        """Check if a directory should be ignored"""
        return any(
            ignored in name
            for ignored in self.settings.ignore_dirs
        )
        
    def _should_watch_file(self, filename):
        """Check if a file should be watched based on extension"""
        return any(
            filename.endswith(ext)
            for ext in self.settings.allowed_file_types
        )
        
    def stop(self):
        """Stop the file watcher with proper cleanup"""
        self._stop_event.set()
        
        # Clear internal state
        with self._scan_lock:
            self._mtimes.clear()