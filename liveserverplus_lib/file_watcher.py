import os
import threading
import time
from pathlib import PurePosixPath

# Import Watchdog from the vendored location
from .vendor.watchdog.observers import Observer
from .vendor.watchdog.events import FileSystemEventHandler
from .logging import info, error

class FileWatcher(threading.Thread):
    """Watches for file changes in specified directories using Watchdog"""
    
    def __init__(self, folders, callback, settings):
        super().__init__()
        self.folders = folders
        self.callback = callback
        self.settings = settings
        self._stop_event = threading.Event()
        self.observer = Observer()
        self.event_handler = WatchdogEventHandler(self)
        self._ignore_patterns = [self._normalize_pattern(p) for p in self.settings.ignorePatterns]
        
        # Set a limit to avoid too many open files
        self._max_directories = 50
        self._dir_count = 0
        
        # Add debounce tracking to prevent duplicate events
        self._last_events = {}
        self._debounce_time = 0.5  # seconds
        self._debounce_lock = threading.Lock() 
        
        # Set up the observers for the folders
        self._setup_observers()

    def _normalize_pattern(self, pattern):
        if not pattern:
            return ''
        normalized = pattern.replace('\\', '/').strip()
        return normalized or ''

    def _matches_ignore(self, path):
        if not path or not self._ignore_patterns:
            return False
        normalized_path = os.path.normpath(path).replace('\\', '/')
        path_obj = PurePosixPath(normalized_path)
        for pattern in self._ignore_patterns:
            if not pattern:
                continue
            if path_obj.match(pattern):
                return True
        return False

    def _setup_observers(self):
        """Set up Watchdog observers for each folder"""
        import os.path
        
        watched_dirs = []
        
        for folder in self.folders:
            if not os.path.exists(folder):
                info(f"Skipping non-existent folder: {folder}")
                continue
                
            # Skip directories in the ignore list
            folder_name = os.path.basename(folder)
            if self._matches_ignore(folder):
                info(f"Skipping ignored directory: {folder}")
                continue
            
            try:
                # Schedule the root folder for watching
                self.observer.schedule(
                    self.event_handler,
                    folder,
                    recursive=False
                )
                self._dir_count += 1
                watched_dirs.append(folder)
                
                # Find all subdirectories that contain web files
                web_dirs_to_watch = []
                
                for root, dirs, files in os.walk(folder):
                    # Filter out ignored directories
                    dirs[:] = [d for d in dirs if d not in self.settings.ignoreDirs]
                    
                    # Check if this directory has any web files
                    has_web_files = any(f.endswith(tuple(self.settings.allowedFileTypes)) for f in files)
                    
                    if has_web_files:
                        web_dirs_to_watch.append(root)
                
                # Only watch up to the max directory limit
                remaining_slots = self._max_directories - self._dir_count
                for web_dir in web_dirs_to_watch[:remaining_slots]:
                    try:
                        self.observer.schedule(
                            self.event_handler,
                            web_dir,
                            recursive=False
                        )
                        self._dir_count += 1
                        watched_dirs.append(web_dir)
                    except Exception as e:
                        info(f"Could not watch directory {web_dir}: {e}")
                
                if len(web_dirs_to_watch) > remaining_slots:
                    info(f"Only watching {self._max_directories} directories to avoid resource issues")
            except Exception as e:
                error(f"Error setting up watchdog for {folder}: {e}")
        
        # Print summary of watched directories
        info(f"Watching {len(watched_dirs)} directories for changes")
    
    def run(self):
        """Thread's run method - starts the observer and keeps thread alive"""
        self.observer.start()
        
        # Keep the thread alive until stopped
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)  # Check for stop signal every 0.5 seconds
    
    def stop(self):
        """Stop the file watcher with a graceful timeout."""
        info("Setting file watcher stop event")
        self._stop_event.set()
        
        if self.observer:
            info("Attempting to stop file watcher with timeout")
            self.observer.stop()
            self.observer.join(timeout=5)  # Wait up to 5 seconds
            if self.observer.is_alive():
                info("File watcher did not stop in time, detaching")
            else:
                info("File watcher stopped successfully")
            self.observer = None  # Clear reference regardless
        
        self._last_events.clear()
    
    def debounced_callback(self, file_path):
        """Call the callback with debouncing to prevent duplicate events"""
        current_time = time.time()
        
        # Use lock to prevent race condition
        with self._debounce_lock:
        # Clean up old entries to prevent memory leak
            # Remove entries older than 60 seconds
            self._last_events = {
                path: timestamp 
                for path, timestamp in self._last_events.items() 
                if current_time - timestamp < 60
            }
            
            last_time = self._last_events.get(file_path, 0)
            
            # Only trigger if enough time has passed since the last event for this file
            if current_time - last_time > self._debounce_time:
                self._last_events[file_path] = current_time
                should_callback = True
            else:
                should_callback = False
        
        # Call callback outside the lock to prevent deadlocks
        if should_callback:
            self.callback(file_path)

class WatchdogEventHandler(FileSystemEventHandler):
    """Handles file system events from Watchdog"""
    
    def __init__(self, watcher):
        self.watcher = watcher
    
    def _should_watch_file(self, filepath):
        """Check if a file should be watched based on extension and ignored directories"""
        if not filepath:
            return False

        filename = os.path.basename(filepath)

        # Check if the file matches allowed extensions
        if not any(filename.endswith(ext) for ext in self.watcher.settings.allowedFileTypes):
            return False

        # Check if the file is in an ignored directory
        if self.watcher._matches_ignore(filepath):
            return False

        return True
    
    def on_modified(self, event):
        """Handle file modification events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    error(f"Error in file change callback: {e}")
    
    def on_created(self, event):
        """Handle file creation events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    error(f"Error in file creation callback: {e}")
    
    def on_deleted(self, event):
        """Handle file deletion events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    error(f"Error in file deletion callback: {e}")
    
    def on_moved(self, event):
        """Handle file move/rename events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.dest_path):
                try:
                    self.watcher.debounced_callback(event.dest_path)
                except Exception as e:
                    error(f"Error in file move callback: {e}")
