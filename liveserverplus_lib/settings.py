import sublime
from .utils import get_free_port

class ServerSettings:
    """Manages server settings with live reload capability."""
    
    def __init__(self):
        self._settings = None
        self._ephemeral_port_cache = None
        self.load_settings()
        
    def load_settings(self):
        """Load settings from the sublime-settings file and reset ephemeral port cache."""
        self._settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        self._settings.add_on_change('live_server_settings', self.on_settings_change)
        # Clear any previously cached ephemeral port whenever settings reload:
        self._ephemeral_port_cache = None

    def on_settings_change(self):
        """Reload settings (triggered when the user updates LiveServerPlus.sublime-settings)."""
        self.load_settings()

    @property
    def host(self):
        """Return the server host."""
        return self._settings.get('host', 'localhost')

    @property
    def port(self):
        """
        Return the server port.

        If the user sets "port": 0, we pick a random free port once and store
        it in _ephemeral_port_cache so that future calls (like "Open Current File")
        see the same ephemeral port. If a specific port is given, we validate it
        and also cache it.
        """
        # If we've already picked an ephemeral port, reuse it:
        if self._ephemeral_port_cache is not None:
            return self._ephemeral_port_cache

        configured_port = self._settings.get('port', 8080)

        if configured_port == 0:
            # Use a free port in the dynamic range (49152-65535).
            free_port = get_free_port(49152, 65535)
            if free_port is None:
                print("No free port found in range 49152-65535; using default port 8080")
                free_port = 8080
            self._ephemeral_port_cache = free_port
            return free_port
        else:
            # Validate user-supplied port
            if not isinstance(configured_port, int) or configured_port < 1 or configured_port > 65535:
                print(f"Invalid port {configured_port}, using default port 8080")
                self._ephemeral_port_cache = 8080
                return 8080

            # Otherwise just cache the valid user port:
            self._ephemeral_port_cache = configured_port
            return configured_port

    @property
    def poll_interval(self):
        """Return the file watcher poll interval (clamped between 0.1 and 10 seconds)."""
        interval = float(self._settings.get('poll_interval', 1.0))
        return max(0.1, min(interval, 10.0))

    @property
    def browser_open_on_start(self):
        """Return True if the browser should be opened when the server starts."""
        return bool(self._settings.get('open_browser_on_start', True))

    @property
    def allowed_file_types(self):
        """Return a list of file extensions allowed to be served."""
        return self._settings.get('allowed_file_types', [
            '.html', '.htm', '.css', '.js', '.mjs',
            '.jpg', '.jpeg', '.png', '.gif', '.svg',
            '.ico', '.woff', '.woff2', '.ttf', '.eot',
            '.mp4', '.webm', '.mp3', '.wav', '.ogg',
            '.pdf', '.json', '.xml', '.webp', '.map'
        ])

    @property
    def ignore_dirs(self):
        """Return a list of directory names to ignore."""
        return self._settings.get('ignore_dirs', [
            'node_modules', '.git', '__pycache__',
            '.svn', '.hg', '.sass-cache', '.pytest_cache'
        ])

    @property
    def max_file_size(self):
        """Return the maximum file size (in MB) allowed to be served."""
        return int(self._settings.get('max_file_size', 100))

    @property
    def enable_compression(self):
        """Return True if GZIP compression is enabled."""
        return bool(self._settings.get('enable_compression', True))

    @property
    def cors_enabled(self):
        """Return True if CORS headers should be enabled."""
        return bool(self._settings.get('cors_enabled', False))

    @property
    def status_bar_enabled(self):
        """Return True if the status bar should be updated."""
        return bool(self._settings.get('status_bar_enabled', True))

    @property
    def browser(self):
        """Return the preferred browser name (e.g. 'chrome', 'firefox')."""
        return self._settings.get('browser', '')

    @property
    def max_threads(self):
        """Return the maximum number of threads for the connection pool."""
        return int(self._settings.get('connections', {}).get('max_threads', 10))
