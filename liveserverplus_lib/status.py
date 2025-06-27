import sublime
import time

class ServerStatus:
    """Manages server status and status bar updates"""
    
    def __init__(self):
        self.messages = {
            'starting': '((•)) Starting server on port {}...',
            'running': '[Ø] Server running on port {}',
            'stopping': '[/] Stopping server...',
            'stopped': '[X] Server stopped',
            'error_bind': '[!] Port {} bind error: {}',
            'error_generic': '[!] Server error: {}',
            'reloading': '<> Reloading: {}', 
            'no_files': '[∅] No files to serve' 
        }
        self._current_status = None
        self._port = None
        self._last_update = 0
        
    def update(self, status, port=None, error=None):
        """Update status across all views"""
        # Throttle rapid updates
        current_time = time.time()
        if current_time - self._last_update < 0.1:
            return
        self._last_update = current_time
        self._current_status = status
        self._port = port

        if status not in self.messages:
            return

        msg = self.messages[status]
        if port:
            msg = msg.format(port)
        if error:
            msg = msg.format(port, error)

        import sublime
        # Load the settings and check the status_bar_enabled flag.
        settings = sublime.load_settings("LiveServerPlus.sublime-settings")
        if settings.get("status_bar_enabled", True):
            window = sublime.active_window()
            if window:
                for view in window.views():
                    if status == 'stopped':
                        view.erase_status('start_server')
                    else:
                        view.set_status('start_server', msg)

        # Always show a transient status message.
        sublime.status_message(msg)
        
    def get_current_status(self):
        """Get current status and port"""
        return self._current_status, self._port
        
    def clear(self):
        """Clear status from all views"""
        window = sublime.active_window()
        if window:
            for view in window.views():
                view.erase_status('start_server')