import sublime

class ServerSettings:
    """Manages server settings with live reload capability"""
    
    def __init__(self):
        self._settings = None
        self.load_settings()
        
    def load_settings(self):
        """Load settings from sublime-settings file"""
        self._settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        # Changed the key here to avoid referencing "start_server"
        self._settings.add_on_change('live_server_settings', self.on_settings_change)
        
    def on_settings_change(self):
        """Handle settings changes"""
        self.load_settings()
        
    @property
    def host(self):
        """Get server host"""
        return self._settings.get('host', 'localhost')
        
    @property
    def port(self):
        """Get server port with validation"""
        port = self._settings.get('port', 8080)
        if not isinstance(port, int) or port < 1 or port > 65535:
            print(f"Invalid port {port}, using default 8080")
            return 8080
        return port

    @property
    def poll_interval(self):
        """Get file watcher poll interval with validation"""
        interval = float(self._settings.get('poll_interval', 1.0))
        return max(0.1, min(interval, 10.0))  # Clamp between 0.1 and 10 seconds
        
    @property
    def browser_open_on_start(self):
        """Whether to open browser on server start"""
        return bool(self._settings.get('open_browser_on_start', True))
        
    @property
    def allowed_file_types(self):
        """Get list of allowed file extensions"""
        return self._settings.get('allowed_file_types', [
            '.html', '.htm', '.css', '.js', '.mjs',
            '.jpg', '.jpeg', '.png', '.gif', '.svg', 
            '.ico', '.woff', '.woff2', '.ttf', '.eot',
            '.mp4', '.webm', '.mp3', '.wav', '.ogg',
            '.pdf', '.json', '.xml', '.webp', '.map'
        ])
        
    @property
    def ignore_dirs(self):
        """Get list of directories to ignore"""
        return self._settings.get('ignore_dirs', [
            'node_modules', '.git', '__pycache__', 
            '.svn', '.hg', '.sass-cache', '.pytest_cache'
        ])
        
    @property
    def max_file_size(self):
        """Maximum file size in MB that can be served"""
        return int(self._settings.get('max_file_size', 100))
        
    @property
    def enable_compression(self):
        """Whether to enable GZIP compression"""
        return bool(self._settings.get('enable_compression', True))
        
    @property
    def cors_enabled(self):
        """Whether to enable CORS headers"""
        return bool(self._settings.get('cors_enabled', False))
        
    @property
    def status_bar_enabled(self):
        """Whether to show status in the status bar"""
        return bool(self._settings.get('status_bar_enabled', True))

    @property
    def browser(self):
        """Get browser setting"""
        return self._settings.get('browser', '')