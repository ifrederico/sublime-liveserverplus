# liveserverplus_lib/logging.py
import logging
import sublime
import os
from datetime import datetime

# Constants for log levels
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR

# Default format for log messages
DEFAULT_FORMAT = '[%(levelname)s][%(asctime)s] LiveServerPlus: %(message)s'
DEFAULT_DATE_FORMAT = '%H:%M:%S'

class SublimeOutputHandler(logging.Handler):
    """Log handler that writes to Sublime's output panel"""
    
    def __init__(self, panel_name="LiveServerPlus"):
        super().__init__()
        self.panel_name = panel_name
        self._last_window = None
    
    def emit(self, record):
        """Write log record to output panel"""
        try:
            window = sublime.active_window()
            if not window:
                return
            
            # Create or get output panel
            output_view = window.find_output_panel(self.panel_name)
            if not output_view:
                output_view = window.create_output_panel(self.panel_name)
                output_view.settings().set("line_numbers", False)
                output_view.settings().set("gutter", False)
                output_view.settings().set("scroll_past_end", False)
                output_view.settings().set("word_wrap", True)
                
                # Set syntax for better readability
                output_view.assign_syntax("Packages/Python/Python.sublime-syntax")
            
            # Format and append message
            msg = self.format(record)
            output_view.run_command('append', {
                'characters': msg + '\n',
                'force': True,
                'scroll_to_end': True
            })
            
            # Show panel for errors
            if record.levelno >= logging.ERROR:
                window.run_command("show_panel", {"panel": f"output.{self.panel_name}"})
                
        except Exception as e:
            print(f"Error in SublimeOutputHandler: {e}")

class LogManager:
    """Central logging manager for LiveServerPlus"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        # Create logger
        self.logger = logging.getLogger('LiveServerPlus')
        self.logger.setLevel(logging.INFO)  # Default level
        
        # Clear any existing handlers (important for plugin reloads)
        if self.logger.handlers:
            for handler in self.logger.handlers:
                self.logger.removeHandler(handler)
                
        # Console handler for Sublime's console
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            fmt=DEFAULT_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # Add output panel handler
        self._setup_output_handler()
        
        # Optionally add a file handler for persistent logs
        self._setup_file_handler()
        
    def _setup_output_handler(self):
        """Set up Sublime output panel handler"""
        if sublime.active_window():
            output_handler = SublimeOutputHandler()
            output_formatter = logging.Formatter(
                fmt='[%(levelname)s] %(message)s',
                datefmt='%H:%M:%S'
            )
            output_handler.setFormatter(output_formatter)
            output_handler.setLevel(self.logger.level)
            self.logger.addHandler(output_handler)
        
    def _setup_file_handler(self):
        """Set up optional file logging"""
        try:
            # Get Sublime's packages path
            packages_path = sublime.packages_path()
            log_dir = os.path.join(packages_path, 'User', 'LiveServerPlus', 'logs')
            
            # Create logs directory if it doesn't exist
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
                
            # Create log file with timestamp
            timestamp = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(log_dir, f'liveserver_{timestamp}.log')
            
            # Add file handler
            file_handler = logging.FileHandler(log_file)
            file_formatter = logging.Formatter(
                fmt='[%(levelname)s][%(asctime)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            self.logger.addHandler(file_handler)
        except Exception as e:
            # Don't fail if file logging setup fails
            self.logger.warning(f"Failed to set up file logging: {e}")
            
    def set_level(self, level):
        """Set the logging level"""
        self.logger.setLevel(level)
        # Update output handler level if it exists
        for handler in self.logger.handlers:
            if isinstance(handler, SublimeOutputHandler):
                handler.setLevel(level)
        
    def debug(self, message):
        """Log a debug message"""
        self.logger.debug(message)
        
    def info(self, message):
        """Log an info message"""
        self.logger.info(message)
        
    def warning(self, message):
        """Log a warning message"""
        self.logger.warning(message)
        
    def error(self, message):
        """Log an error message"""
        self.logger.error(message)
        
# Helper functions
def get_logger():
    """Get the logger instance"""
    return LogManager.get_instance()

def debug(message):
    """Log a debug message"""
    get_logger().debug(message)
    
def info(message):
    """Log an info message"""
    get_logger().info(message)
    
def warning(message):
    """Log a warning message"""
    get_logger().warning(message)
    
def error(message):
    """Log an error message"""
    get_logger().error(message)
    
def set_level(level):
    """Set the logging level"""
    get_logger().set_level(level)
