# liveserverplus_lib/status.py
"""Status bar management utilities."""
from __future__ import annotations

import time
from typing import List, Optional

import sublime


class ServerStatus:
    """Manages server status presentation in Sublime Text."""

    STATUS_KEY = 'liveserverplus'

    # What the status bar shows right now, shared by every instance: views
    # opened later pick it up through apply_to_view(), and a restart creates
    # a new ServerStatus while the old one is still finishing its 'stopped'.
    _shown_text: Optional[str] = None
    _shown_serial = 0

    def __init__(self, settings) -> None:
        self.settings = settings
        self.messages = {
            'starting': 'Starting server',
            'running': '[Ø:{}]',
            'stopping': 'Stopping server',
            'stopped': '[X] Server stopped',
            'restarting': 'Restarting server',
            'error': '[!] Server error: {}'
        }
        self._current_status: Optional[str] = None
        self._port: Optional[int] = None
        self._last_update = 0.0
        self._spinner_frames: List[str] = ["✧", "✴", "✶", "⋆", "✦", "✪", "❋", "✺", "*", "✷", "✹", "✻", "✼", "✽", "✾"]
        self._spinner_index = 0
        self._spinner_active = False
        self._spinner_status: Optional[str] = None

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

        if status == 'running':
            message = self._format_running_message(port)
        elif status == 'error' and error:
            message = self.messages[status].format(error)
        else:
            message = self.messages[status]

        if self.settings.showOnStatusbar:
            if status in ('starting', 'stopping'):
                self._start_spinner(status)
            else:
                self._stop_spinner()
                self._set_view_status(message)
                if status == 'stopped':
                    self._schedule_clear_after_stop()
        else:
            self._stop_spinner()
            self._clear_view_status()

        if self._should_toast(status):
            sublime.status_message(message)

    def getCurrentStatus(self):
        return self._current_status, self._port

    def get_current_status(self):
        return self.getCurrentStatus()

    def clear(self) -> None:
        self._stop_spinner()
        self._clear_view_status()

    def refresh(self) -> None:
        """Redraw the running status after ``showOnStatusbar`` may have changed."""
        if self._current_status != 'running':
            return
        if self.settings.showOnStatusbar:
            self._set_view_status(self._format_running_message(self._port))
        else:
            self.clear()

    @classmethod
    def current_text(cls) -> Optional[str]:
        """Return the status bar text currently shown, or None."""
        return cls._shown_text

    @classmethod
    def apply_to_view(cls, view) -> None:
        """Give ``view`` the current status text (or remove a stale one)."""
        if view is None:
            return
        text = cls._shown_text
        if text:
            view.set_status(cls.STATUS_KEY, text)
        else:
            view.erase_status(cls.STATUS_KEY)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _format_running_message(self, port: Optional[int]) -> str:
        if port:
            return self.messages['running'].format(port)
        return '[Ø]'

    def _should_toast(self, status: str) -> bool:
        if status == 'error':
            return True
        if not self.settings.showInfoMessages:
            return False
        if not self.settings.showOnStatusbar:
            return True
        return False

    def _set_view_status(self, message: str) -> None:
        ServerStatus._shown_text = message
        ServerStatus._shown_serial += 1

        for window in sublime.windows():
            views = window.views()

            if not views:
                # No views open - use window-level persistent status
                window.status_message(message)
            else:
                # Set on all open views (per-view status)
                for view in views:
                    view.set_status(self.STATUS_KEY, message)

    def _clear_view_status(self) -> None:
        ServerStatus._shown_text = None
        ServerStatus._shown_serial += 1

        for window in sublime.windows():
            for view in window.views():
                view.erase_status(self.STATUS_KEY)

    def _start_spinner(self, status: str) -> None:
        if not self.settings.showOnStatusbar:
            return
        if self._spinner_active and self._spinner_status == status:
            return
        self._spinner_status = status
        self._spinner_active = True
        self._spinner_index = 0
        self._spinner_tick()

    def _stop_spinner(self) -> None:
        self._spinner_active = False
        self._spinner_index = 0
        self._spinner_status = None

    def _spinner_tick(self) -> None:
        if not self._spinner_active or not self._spinner_status:
            return
        frame = self._spinner_frames[self._spinner_index]
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_frames)
        base_message = self.messages.get(self._spinner_status, '')
        message = f"{frame} {base_message}".strip()
        self._set_view_status(message)
        sublime.set_timeout(self._spinner_tick, 150)

    def _schedule_clear_after_stop(self) -> None:
        serial = ServerStatus._shown_serial

        def clear_if_still_stopped() -> None:
            # Skip if anything was shown since, e.g. the next server of a restart.
            if self._current_status == 'stopped' and ServerStatus._shown_serial == serial:
                self._clear_view_status()

        sublime.set_timeout(clear_if_still_stopped, 2000)