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
        
        # Locks for connection and debounce management
        self._lock = threading.Lock()
        self._timer_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._message_handler = None

        # Settings reference provided by the server
        self._settings = None

        # Load the injected HTML/JS for live reload
        self._loadInjectedCode()

        # Pre-compute common frames
        self._reload_frame = self._buildWebSocketFrame('reload')
        self._refreshcss_frame = self._buildWebSocketFrame('refreshcss')
        self._pending_timer = None
        self._pending_message = None

    @property
    def settings(self):
        """Thread-safe accessor for server settings."""
        with self._settings_lock:
            return self._settings

    @settings.setter
    def settings(self, value):
        """Thread-safe setter for server settings."""
        with self._settings_lock:
            self._settings = value

    def _loadInjectedCode(self):
        """Load WebSocket injection code from template"""
        try:
            resource_path = "Packages/LiveServerPlus/liveserverplus_lib/templates/websocket.html"
            template_str = sublime.load_resource(resource_path)
            self.INJECTED_CODE = template_str
        except Exception as e:
            error(f"Error loading WebSocket template: {e}")
            # Fallback to an empty script if the template can't be loaded
            self.INJECTED_CODE = "<script></script></body>"
        
    def handleWebSocketUpgrade(self, headers):
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

    def addClient(self, client):
        """Add a client connection to the set in a thread-safe manner."""
        with self._lock:
            self.clients.add(client)

    def removeClient(self, client):
        """Remove a client connection from the set in a thread-safe manner."""
        with self._lock:
            if client in self.clients:
                self.clients.remove(client)

    def notifyClients(self, file_path):
        """
        Notify all connected WebSocket clients of file changes in a thread-safe manner,
        avoiding 'Set changed size during iteration' errors by taking a snapshot
        of self.clients before sending.
        """
        full_reload = getattr(self.settings, 'fullReload', True)
        if full_reload:
            message = 'reload'
        else:
            message = 'refreshcss' if file_path.lower().endswith('.css') else 'reload'

        wait_seconds = getattr(self.settings, 'waitTimeMs', 0) / 1000.0
        if wait_seconds <= 0:
            self._broadcast(message)
            return

        with self._timer_lock:
            if message == 'reload':
                self._pending_message = 'reload'
            elif self._pending_message != 'reload':
                self._pending_message = message

            if self._pending_timer:
                self._pending_timer.cancel()

            self._pending_timer = threading.Timer(wait_seconds, self._flushPendingMessage)
            self._pending_timer.daemon = True
            self._pending_timer.start()

    def _flushPendingMessage(self):
        with self._timer_lock:
            message = self._pending_message or 'reload'
            self._pending_message = None
            self._pending_timer = None
        self._broadcast(message)

    def _broadcast(self, message):
        # Build the frame for all clients
        try:
            frame = self._createWebSocketFrame(message)
        except Exception as e:
            error(f"Error creating frame: {e}")
            return

        with self._lock:
            active_clients = list(self.clients)

        if not active_clients:
            return

        dead_clients = []
        # One broadcast at a time: the file watcher, the debounce timer and
        # scroll sync all end up here, and the timeout juggling below must
        # not interleave between them.
        with self._send_lock:
            for client in active_clients:
                try:
                    # Cap the send so a stalled client cannot hold up the
                    # broadcast, then put the timeout back. The worker thread
                    # reading this socket relies on it; clearing it left that
                    # thread blocked for ever once the server stopped.
                    previous_timeout = client.gettimeout()
                    client.settimeout(1.0)
                    try:
                        client.sendall(frame)
                    finally:
                        client.settimeout(previous_timeout)
                except (socket.error, OSError, socket.timeout) as e:
                    info(f"Error sending to client: {e}")
                    dead_clients.append(client)
                except Exception as e:
                    error(f"Unexpected error sending to WebSocket client: {e}")
                    dead_clients.append(client)

        if dead_clients:
            with self._lock:
                for client in dead_clients:
                    self.clients.discard(client)
                    self._disconnect(client)
            info(f"Removed {len(dead_clients)} dead WebSocket clients")

    @staticmethod
    def _disconnect(client):
        """Hang up on a client without closing its socket.

        Each client socket is read by a worker thread, and that thread is
        the one that closes it. shutdown() makes its recv return EOF so it
        exits; closing here as well would free the descriptor number while
        the worker may be about to use it, and the next socket to open
        could inherit the number and the worker with it.
        """
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def broadcast_message(self, message):
        """Public helper to broadcast arbitrary text messages."""
        if not isinstance(message, str):
            try:
                message = str(message)
            except Exception:
                error("WebSocket broadcast_message received non-string payload")
                return
        self._broadcast(message)

    def _createWebSocketFrame(self, message):
        """Return pre-computed frame if available, otherwise build it."""
        if message == 'reload':
            return self._reload_frame
        elif message == 'refreshcss':
            return self._refreshcss_frame
        return self._buildWebSocketFrame(message)

    def _buildWebSocketFrame(self, message):
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

    def set_message_handler(self, handler):
        """Register callback for incoming text messages."""
        self._message_handler = handler

    def _notify_incoming_message(self, message, conn):
        if not self._message_handler:
            return
        try:
            self._message_handler(message, conn)
        except Exception as exc:
            error(f"Error in WebSocket message handler: {exc}")

    def read_message(self, conn):
        """Read a text frame from the WebSocket connection."""
        try:
            header = self._recv_exact(conn, 2)
            if not header:
                return None

            fin = header[0] & 0x80
            opcode = header[0] & 0x0F
            masked = header[1] & 0x80
            payload_len = header[1] & 0x7F

            if payload_len == 126:
                extended = self._recv_exact(conn, 2)
                if not extended:
                    return None
                payload_len = struct.unpack('>H', extended)[0]
            elif payload_len == 127:
                extended = self._recv_exact(conn, 8)
                if not extended:
                    return None
                payload_len = struct.unpack('>Q', extended)[0]

            mask = b''
            if masked:
                mask = self._recv_exact(conn, 4)
                if not mask:
                    return None

            payload = self._recv_exact(conn, payload_len) if payload_len else b''
            if payload is None:
                return None

            if masked and payload:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:  # Close
                return None
            if opcode == 0x9:  # Ping -> respond with pong
                try:
                    conn.sendall(self._build_pong_frame(payload))
                except Exception:
                    pass
                return ''
            if opcode == 0xA:  # Pong
                return ''
            if opcode != 0x1:  # Only handle text frames
                return ''

            try:
                return payload.decode('utf-8', errors='ignore')
            except Exception:
                return ''

        except socket.timeout:
            return ''
        except (socket.error, OSError):
            return None

    def _recv_exact(self, conn, num_bytes):
        """Receive exactly num_bytes or return None if connection closed."""
        if num_bytes == 0:
            return b''
        chunks = []
        bytes_recd = 0
        while bytes_recd < num_bytes:
            chunk = conn.recv(num_bytes - bytes_recd)
            if not chunk:
                return None
            chunks.append(chunk)
            bytes_recd += len(chunk)
        return b''.join(chunks)

    def _build_pong_frame(self, payload):
        """Build a pong frame in response to ping."""
        frame = bytearray()
        frame.append(0x8A)  # FIN + opcode for pong
        length = len(payload)
        if length <= 125:
            frame.append(length)
        elif length <= 65535:
            frame.append(126)
            frame.extend(struct.pack('>H', length))
        else:
            frame.append(127)
            frame.extend(struct.pack('>Q', length))
        frame.extend(payload)
        return bytes(frame)

    def shutdown(self):
        """Cancel the pending broadcast and hang up on every client.

        Each client has a worker thread blocked in recv on it. Hanging up
        wakes that thread so it can exit and release its connection slot,
        and the browser sees the close and reconnects, which is how an
        open tab finds the next server instance.
        """
        with self._timer_lock:
            if self._pending_timer:
                self._pending_timer.cancel()
                self._pending_timer = None
            self._pending_message = None

        with self._lock:
            clients = list(self.clients)
            self.clients.clear()

        for client in clients:
            self._disconnect(client)
