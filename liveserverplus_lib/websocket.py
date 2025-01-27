import base64
import hashlib
import struct
import os
import sublime

class WebSocketHandler:
    """Handles WebSocket connections and live reload functionality"""
    
    def __init__(self):
        self.clients = set()
        self._load_injected_code()
        
    def _load_injected_code(self):
        """Load WebSocket injection code from template"""
        try:
            resource_path = "Packages/LiveServerPlus/liveserverplus_lib/templates/websocket.html"
            template_str = sublime.load_resource(resource_path)
            self.INJECTED_CODE = template_str
        except Exception as e:
            print(f"Error loading WebSocket template: {e}")
            # Fallback to empty script if template can't be loaded
            self.INJECTED_CODE = "<script></script></body>"
        
    def handle_websocket_upgrade(self, headers):
        """Handle WebSocket upgrade request"""
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
        
    def notify_clients(self, file_path):
        """Notify all clients of file changes"""
        is_css = file_path.lower().endswith('.css')
        message = 'refreshcss' if is_css else 'reload'
        
        dead_clients = set()
        for client in self.clients:
            try:
                frame = self._create_websocket_frame(message)
                try:
                    client.send(frame)
                except (socket.error, OSError) as e:
                    print(f"Error sending to client: {e}")
                    dead_clients.add(client)
            except Exception as e:
                print(f"Error creating frame: {e}")
                dead_clients.add(client)
            finally:
                if client in dead_clients:
                    try:
                        client.shutdown(socket.SHUT_RDWR)
                        client.close()
                    except (socket.error, OSError):
                        pass
        
        self.clients.difference_update(dead_clients)
        
    def _create_websocket_frame(self, message):
        """Create a WebSocket frame from a message"""
        frame = bytearray()
        frame.append(0x81)  # Text frame
        
        msg_bytes = message.encode()
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