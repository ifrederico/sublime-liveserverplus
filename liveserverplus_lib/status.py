# liveserverplus_lib/status.py
"""Status bar management utilities."""
from __future__ import annotations

import time
from typing import Optional

import sublime


class ServerStatus:
    """Manages server status presentation in Sublime Text."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.messages = {
            'starting': '((•)) Starting server...',
            'running': '[Ø] Server running on port {}',
            'stopping': '[/] Stopping server...',
            'stopped': '[X] Server stopped',
            'error': '[!] Server error: {}'
        }
        self._current_status: Optional[str] = None
        self._port: Optional[int] = None
        self._last_update = 0.0

    def update(self, status: str, port: Optional[int] = None, error: Optional[str] = None) -> None:
        """Update the status bar and status message."""
        current_time = time.time()
        if status == self._current_status and current_time - self._last_update < 0.1:
            return
        self._last_update = current_time

        self._current_status = status
        self._port = port

        if status not in self.messages:
            return

        message = self.messages[status]
        if status == 'running' and port:
            message = message.format(port)
        elif status == 'error' and error:
            message = message.format(error)

        if self.settings.showOnStatusbar:
            window = sublime.active_window()
            if window:
                for view in window.views():
                    if status == 'stopped':
                        view.erase_status('start_server')
                    else:
                        view.set_status('start_server', message)

        if not self.settings.suppressInfoMessages or status == 'error':
            sublime.status_message(message)

    def getCurrentStatus(self):
        return self._current_status, self._port

    def get_current_status(self):
        return self.getCurrentStatus()

    def clear(self) -> None:
        window = sublime.active_window()
        if window:
            for view in window.views():
                view.erase_status('start_server')
