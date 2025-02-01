import base64
import hashlib
import struct
import socket
import threading
import os
import sublime

class WebSocketHandler:
    """Handles WebSocket connections and live reload functionality"""
    
    def __init__(self):
        # Set of connected WebSocket clients
        self.clients = set()
        
        # A lock to protect self.clients from concurrent access
        self._lock = threading.Lock()
        
        # Load the injected HTML/JS for live reload
        self._load_injected_code()
        
    def _load_injected_code(self):
        """Load WebSocket injection code from template"""
        try:
            resource_path = "Packages/LiveServerPlus/liveserverplus_lib/templates/websocket.html"
            template_str = sublime.load_resource(resource_path)
            self.INJECTED_CODE = template_str
        except Exception as e:
            print(f"Error loading WebSocket template: {e}")
            # Fallback to an empty script if the template can't be loaded
            self.INJECTED_CODE = "<script></script></body>"
        
    def handle_websocket_upgrade(self, headers):
        """Handle WebSocket upgrade request, returning the response handshake or None."""
        ws_key = None
        for header in headers:
            if header.startswith('Sec-WebSocket-Key:'):
                ws_key = header.split(': ')[1].strip()
                break
                
        if not ws_key:
            return None
        
        # Generate accept key per WebSocket spec
        ws_accept = base64.b64encode(
            hashlib.sha1(
                f"{ws_key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()
            ).digest()
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
        """Notify all connected WebSocket clients of file changes in a thread-safe manner."""
        # Try to retrieve live_reload settings from our attached settings.
        if hasattr(self, 'settings'):
            live_reload_settings = self.settings._settings.get("live_reload", {})
        else:
            # Fallback if no settings were attached.
            import sublime
            live_reload_settings = sublime.load_settings("LiveServerPlus.sublime-settings").get("live_reload", {})

        # Check the css_injection flag. If disabled, then we force a full reload even for CSS files.
        css_injection_enabled = live_reload_settings.get("css_injection", True)

        if file_path.lower().endswith('.css') and css_injection_enabled:
            message = 'refreshcss'
        else:
            message = 'reload'
        
        try:
            frame = self._create_websocket_frame(message)
        except Exception as e:
            print(f"Error creating frame: {e}")
            return

        dead_clients = set()

        with self._lock:
            for client in self.clients:
                try:
                    client.send(frame)
                except (socket.error, OSError) as e:
                    print(f"Error sending to client: {e}")
                    dead_clients.add(client)
            for client in dead_clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except (socket.error, OSError):
                    pass
                finally:
                    client.close()
            self.clients.difference_update(dead_clients)
        
    def _create_websocket_frame(self, message):
        """Create a simple WebSocket text frame from a string message."""
        frame = bytearray()
        frame.append(0x81)  # 0x1: text frame; final frame bit => 0x80 => combined => 0x81
        
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
        return frame