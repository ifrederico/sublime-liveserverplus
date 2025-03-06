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
        
        # Optionally add a file handler for persistent logs
        self._setup_file_handler()
        
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