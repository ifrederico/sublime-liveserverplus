import os
import threading
import time
from fnmatch import fnmatch

# Import Watchdog from the vendored location
from .vendor.watchdog.observers import Observer
from .vendor.watchdog.events import FileSystemEventHandler

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
        
        # Set a limit to avoid too many open files
        self._max_directories = 50
        self._dir_count = 0
        
        # Add debounce tracking to prevent duplicate events
        self._last_events = {}
        self._debounce_time = 0.5  # seconds
        
        # Set up the observers for the folders
        self._setup_observers()
    
    def _setup_observers(self):
        """Set up Watchdog observers for each folder"""
        import os.path
        
        watched_dirs = []
        
        for folder in self.folders:
            if not os.path.exists(folder):
                print(f"[LiveServerPlus] Skipping non-existent folder: {folder}")
                continue
                
            # Skip directories in the ignore list
            folder_name = os.path.basename(folder)
            if folder_name in self.settings.ignore_dirs:
                print(f"[LiveServerPlus] Skipping ignored directory: {folder}")
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
                    dirs[:] = [d for d in dirs if d not in self.settings.ignore_dirs]
                    
                    # Check if this directory has any web files
                    has_web_files = any(f.endswith(tuple(self.settings.allowed_file_types)) for f in files)
                    
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
                        print(f"[LiveServerPlus] Could not watch directory {web_dir}: {e}")
                
                if len(web_dirs_to_watch) > remaining_slots:
                    print(f"[LiveServerPlus] Warning: Only watching {self._max_directories} directories to avoid resource issues")
            except Exception as e:
                print(f"[LiveServerPlus] Error setting up watchdog for {folder}: {e}")
        
        # Print summary of watched directories
        print(f"[LiveServerPlus] Watching {len(watched_dirs)} directories for changes")
    
    def run(self):
        """Thread's run method - starts the observer and keeps thread alive"""
        self.observer.start()
        
        # Keep the thread alive until stopped
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)  # Check for stop signal every 0.5 seconds
    
    def stop(self):
        """Stop the file watcher with a graceful timeout."""
        from .logging import info, warning
        
        info("Setting file watcher stop event")
        self._stop_event.set()
        
        if self.observer:
            info("Attempting to stop file watcher with timeout")
            self.observer.stop()
            self.observer.join(timeout=5)  # Wait up to 5 seconds
            if self.observer.is_alive():
                warning("File watcher did not stop in time, detaching")
            else:
                info("File watcher stopped successfully")
            self.observer = None  # Clear reference regardless
        
        self._last_events.clear()
    
    def debounced_callback(self, file_path):
        """Call the callback with debouncing to prevent duplicate events"""
        current_time = time.time()
        last_time = self._last_events.get(file_path, 0)
        
        # Only trigger if enough time has passed since the last event for this file
        if current_time - last_time > self._debounce_time:
            self._last_events[file_path] = current_time
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
        if not any(filename.endswith(ext) for ext in self.watcher.settings.allowed_file_types):
            return False
            
        # Check if the file is in an ignored directory
        for ignored in self.watcher.settings.ignore_dirs:
            if ignored in filepath:
                return False
                
        return True
    
    def on_modified(self, event):
        """Handle file modification events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    print(f"[LiveServerPlus] Error in file change callback: {e}")
    
    def on_created(self, event):
        """Handle file creation events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    print(f"[LiveServerPlus] Error in file creation callback: {e}")
    
    def on_deleted(self, event):
        """Handle file deletion events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.src_path):
                try:
                    self.watcher.debounced_callback(event.src_path)
                except Exception as e:
                    print(f"[LiveServerPlus] Error in file deletion callback: {e}")
    
    def on_moved(self, event):
        """Handle file move/rename events"""
        if not self.watcher._stop_event.is_set() and not event.is_directory:
            if self._should_watch_file(event.dest_path):
                try:
                    self.watcher.debounced_callback(event.dest_path)
                except Exception as e:
                    print(f"[LiveServerPlus] Error in file move callback: {e}")