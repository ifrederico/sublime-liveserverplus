# liveserverplus_lib/constants.py
"""Shared constants and data structures"""

# File type to icon mapping for directory listings
FILE_ICONS = {
    # HTML/Web
    '.html': '📄',
    '.htm': '📄',
    '.css': '🎨',
    '.js': '📜',
    '.json': '📝',
    '.xml': '📋',
    
    # Images
    '.jpg': '🖼️',
    '.jpeg': '🖼️',
    '.png': '🖼️',
    '.gif': '🖼️',
    '.svg': '🖼️',
    '.ico': '🖼️',
    '.webp': '🖼️',
    '.avif': '🖼️',
    
    # Documents
    '.pdf': '📕',
    '.doc': '📘',
    '.docx': '📘',
    '.txt': '📝',
    '.md': '📝',
    
    # Code
    '.py': '🐍',
    '.jsx': '📜',
    '.ts': '📜',
    '.tsx': '📜',
    '.vue': '📜',
    '.svelte': '📜',
    
    # Archives
    '.zip': '📦',
    '.rar': '📦',
    '.7z': '📦',
    '.tar': '📦',
    '.gz': '📦',
    
    # Media
    '.mp3': '🎵',
    '.wav': '🎵',
    '.ogg': '🎵',
    '.mp4': '🎬',
    '.avi': '🎬',
    '.mov': '🎬',
    '.webm': '🎬',
    
    # Fonts
    '.woff': '🔤',
    '.woff2': '🔤',
    '.ttf': '🔤',
    '.eot': '🔤',
    '.otf': '🔤',
    
    # Data
    '.sql': '🗄️',
    '.db': '🗄️',
    '.csv': '📊',
    '.xlsx': '📊',
    '.xls': '📊'
}

# Default file icon
DEFAULT_FILE_ICON = '📄'

# Directory icon
DIRECTORY_ICON = '📁'

# MIME type mappings (moved from utils.py)
MIME_TYPES = {
    # Web
    '.html': 'text/html',
    '.htm': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.mjs': 'application/javascript',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.wasm': 'application/wasm',
    
    # Modern JS
    '.ts': 'application/typescript',
    '.tsx': 'application/typescript',
    '.jsx': 'application/javascript',
    '.vue': 'application/javascript',
    '.svelte': 'application/javascript',
    
    # Images
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    
    # Fonts
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.eot': 'application/vnd.ms-fontobject',
    '.otf': 'font/otf',
    
    # Media
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.ogg': 'audio/ogg',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    
    # Documents
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.txt': 'text/plain',
    '.md': 'text/markdown',
    '.csv': 'text/csv',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    
    # Development
    '.map': 'application/json',
    '.py': 'text/x-python',
    '.php': 'application/x-httpd-php',
    '.rb': 'application/x-ruby',
    '.java': 'text/x-java',
    '.c': 'text/x-c',
    '.cpp': 'text/x-c++',
    '.h': 'text/x-c',
    '.sh': 'application/x-sh',
    '.bat': 'application/x-bat',
    
    # Archives
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip'
}

# File extensions that should not be compressed (already compressed)
NO_COMPRESS_EXTENSIONS = {
    # Images
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif',
    
    # Archives
    '.zip', '.rar', '.7z', '.gz', '.bz2',
    
    # Media
    '.mp3', '.mp4', '.avi', '.mov', '.webm',
    
    # Other compressed formats
    '.pdf', '.woff', '.woff2'
}

# MIME types that should skip compression
SKIP_COMPRESSION_TYPES = {
    # Images
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/x-icon',
    
    # Audio/Video
    'audio/mpeg',
    'audio/mp4',
    'video/mp4',
    'video/webm',
    'audio/ogg',
    
    # Archives
    'application/zip',
    'application/x-rar-compressed',
    'application/x-7z-compressed',
    
    # PDFs
    'application/pdf',
    
    # Fonts
    'font/woff',
    'font/woff2',
}

# Text file extensions (for encoding detection)
TEXT_FILE_EXTENSIONS = {
    '.html', '.htm', '.css', '.js', '.mjs', '.json',
    '.xml', '.txt', '.md', '.jsx', '.ts', '.tsx', 
    '.svg', '.vue', '.svelte', '.py', '.php', '.rb',
    '.java', '.c', '.cpp', '.h', '.sh', '.bat',
    '.sql', '.csv', '.yaml', '.yml', '.toml', '.ini',
    '.scss', '.sass', '.less', '.postcss'
}

# Default server settings
DEFAULT_SETTINGS = {
    'host': 'localhost',
    'port': 8080,
    'open_browser_on_start': True,
    'browser': '',
    'status_bar_enabled': True,
    'logging': False,
    'enable_compression': True,
    'cors_enabled': False,
    'max_file_size': 100,  # MB
    'poll_interval': 1.0,
    'live_reload': {
        'enabled': False,
        'css_injection': True,
        'delay': 500,
        'ignore_exts': ['.log', '.map']
    },
    'connections': {
        'max_concurrent': 100,
        'timeout': 30,
        'max_threads': 10
    }
}

# Socket error codes to ignore
IGNORED_SOCKET_ERRORS = {9, 57}  # Bad file descriptor, Socket not connected

# File watcher settings
MAX_WATCHED_DIRECTORIES = 50
FILE_CHANGE_DEBOUNCE_TIME = 0.5  # seconds

# Browser command mappings by platform
BROWSER_COMMANDS = {
    'chrome': {
        'darwin': 'google chrome',
        'linux': 'google-chrome',
        'windows': 'chrome'
    },
    'firefox': {
        'darwin': 'firefox',
        'linux': 'firefox',
        'windows': 'firefox'
    },
    'safari': {
        'darwin': 'safari'
    },
    'edge': {
        'darwin': 'microsoft-edge',
        'linux': 'microsoft-edge',
        'windows': 'msedge'
    }
}

# Performance tuning constants
STREAMING_THRESHOLD = 1024 * 1024  # 1MB - files larger than this are streamed
DEFAULT_CHUNK_SIZE = 8192  # Default chunk size for file reading
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB - threshold for special handling
STATUS_UPDATE_THROTTLE = 0.1  # Minimum seconds between status bar updates
CACHE_DURATION = 2  # Directory listing cache duration in seconds