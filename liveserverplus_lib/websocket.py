# liveserverplus_lib/websocket.py
import base64
import hashlib
import struct
import socket
import threading
import os
import sublime
from .logging import info, error

class WebSocketHandler:
    """Handles WebSocket connections and live reload functionality"""
    
    def __init__(self):
        # Set of connected WebSocket clients
        self.clients = set()
        
        # A lock to protect self.clients from concurrent access
        self._lock = threading.Lock()
        
        # Load the injected HTML/JS for live reload
        self._load_injected_code()
        
        # Pre-compute common frames
        self._reload_frame = self._build_websocket_frame('reload')
        self._refreshcss_frame = self._build_websocket_frame('refreshcss')
        
    def _load_injected_code(self):
        """Load WebSocket injection code from template"""
        try:
            resource_path = "Packages/LiveServerPlus/liveserverplus_lib/templates/websocket.html"
            template_str = sublime.load_resource(resource_path)
            self.INJECTED_CODE = template_str
        except Exception as e:
            error(f"Error loading WebSocket template: {e}")
            # Fallback to an empty script if the template can't be loaded
            self.INJECTED_CODE = "<script></script></body>"
        
    def handle_websocket_upgrade(self, headers):
        """Handle WebSocket upgrade request, returning the response handshake or None."""
        ws_key = None
        for header in headers:
            # In some systems, the header name could be upper/lower case. Let's be safe.
            if header.lower().startswith('sec-websocket-key:'):
                ws_key = header.split(':', 1)[1].strip()
                break
                
        if not ws_key:
            return None
        
        # Generate accept key per WebSocket spec
        magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        ws_accept = base64.b64encode(
            hashlib.sha1((ws_key + magic).encode()).digest()
        ).decode()
        
        return (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {ws_accept}\r\n\r\n"
        )

    def add_client(self, client):
        """Add a client connection to the set in a thread-safe manner."""
        with self._lock:
            self.clients.add(client)

    def remove_client(self, client):
        """Remove a client connection from the set in a thread-safe manner."""
        with self._lock:
            if client in self.clients:
                self.clients.remove(client)

    def notify_clients(self, file_path):
        """
        Notify all connected WebSocket clients of file changes in a thread-safe manner,
        avoiding 'Set changed size during iteration' errors by taking a snapshot
        of self.clients before sending.
        """
        # Try to retrieve live_reload settings from our attached settings.
        if hasattr(self, 'settings'):
            live_reload_settings = self.settings._settings.get("live_reload", {})
        else:
            # Fallback if no settings were attached.
            live_reload_settings = sublime.load_settings("LiveServerPlus.sublime-settings").get("live_reload", {})

        # Check the css_injection flag. If disabled, we force a full reload even for CSS files.
        css_injection_enabled = live_reload_settings.get("css_injection", True)
        if file_path.lower().endswith('.css') and css_injection_enabled:
            message = 'refreshcss'
        else:
            message = 'reload'
        
        # Build the frame for all clients
        try:
            frame = self._create_websocket_frame(message)
        except Exception as e:
            error(f"Error creating frame: {e}")
            return

        # Take a snapshot of the current clients under lock
        with self._lock:
            active_clients = list(self.clients)

        # Send to each client outside the lock
        dead_clients = set()
        for client in active_clients:
            try:
                client.send(frame)
            except (socket.error, OSError) as e:
                info(f"Error sending to client: {e}")
                dead_clients.add(client)

        # Reacquire lock to remove dead clients
        with self._lock:
            for client in dead_clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass
                finally:
                    client.close()
            self.clients.difference_update(dead_clients)
        
    def _create_websocket_frame(self, message):
        """Return pre-computed frame if available, otherwise build it."""
        if message == 'reload':
            return self._reload_frame
        elif message == 'refreshcss':
            return self._refreshcss_frame
        return self._build_websocket_frame(message)

    def _build_websocket_frame(self, message):
        """Build a WebSocket text frame from a string message."""
        frame = bytearray()
        frame.append(0x81)  # FIN + text frame
        
        msg_bytes = message.encode('utf-8', errors='replace')
        length = len(msg_bytes)
        
        if length <= 125:
            frame.append(length)
        elif length <= 65535:
            frame.append(126)
            frame.extend(struct.pack('>H', length))
        else:
            frame.append(127)
            frame.extend(struct.pack('>Q', length))
            
        frame.extend(msg_bytes)
        return bytes(frame)  # Return immutable bytes