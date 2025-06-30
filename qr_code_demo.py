# qr_code_demo.py - Standalone demo for QR code feature
# This would go in your LiveServerPlus package folder to test

import sublime
import sublime_plugin
import socket
import base64
import io

# This simulates having pyqrcode vendored - for demo purposes, 
# I'll create a simple QR code generator
def generate_simple_qr_placeholder(text):
    """
    Generate a simple placeholder that looks like a QR code
    In real implementation, this would use pyqrcode
    """
    # This is just a placeholder - real implementation would use pyqrcode
    # For demo, return a simple checkerboard pattern as base64 PNG
    
    # In real implementation:
    # import pyqrcode
    # import pypng
    # qr = pyqrcode.create(text)
    # buffer = io.BytesIO()
    # qr.png(buffer, scale=8)
    # return base64.b64encode(buffer.getvalue()).decode()
    
    # For demo, return a placeholder image (1x1 white pixel PNG)
    placeholder_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x00\x00\x00\x0c\x02R\xcb\x00\x00\x00\x00IEND\xaeB`\x82'
    return base64.b64encode(placeholder_png).decode()

def get_local_ip():
    """Get the local IP address for the machine"""
    try:
        # Create a socket to external address to find local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

class LiveServerShowQrCommand(sublime_plugin.WindowCommand):
    """Demo command to show QR code for mobile access"""
    
    def run(self):
        # Import from your existing code
        try:
            from .ServerManager import ServerManager
            manager = ServerManager.get_instance()
        except:
            # For standalone demo
            sublime.error_message("This is a demo - ServerManager not found")
            # Simulate server running on port 8080
            self.show_qr_demo("localhost", 8080)
            return
        
        if not manager.is_running():
            sublime.status_message("Live Server is not running")
            return
            
        server = manager.get_server()
        if server:
            # Get host and port from running server
            host = server.settings.host
            port = server.settings.port
            
            # Show QR code popup
            self.show_qr_popup(host, port)
    
    def show_qr_demo(self, host, port):
        """Show demo QR popup"""
        # Get local IP for mobile access
        local_ip = get_local_ip()
        url = f"http://{local_ip}:{port}"
        
        # Generate QR code (placeholder for demo)
        qr_base64 = generate_simple_qr_placeholder(url)
        
        # Create HTML content for popup
        html_content = f"""
        <div style="padding: 20px; background-color: #f8f8f8; text-align: center;">
            <style>
                body {{ margin: 0; padding: 0; }}
                .qr-container {{ 
                    background: white; 
                    border-radius: 8px; 
                    padding: 20px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                h3 {{ 
                    color: #333; 
                    margin: 0 0 15px 0;
                    font-size: 16px;
                }}
                .qr-image {{
                    width: 200px;
                    height: 200px;
                    margin: 10px auto;
                    background: #f0f0f0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 1px solid #ddd;
                }}
                .url-text {{
                    font-family: monospace;
                    font-size: 12px;
                    color: #666;
                    margin: 10px 0;
                    padding: 8px;
                    background: #f5f5f5;
                    border-radius: 4px;
                    word-break: break-all;
                }}
                .info-text {{
                    font-size: 11px;
                    color: #999;
                    margin-top: 10px;
                }}
                .close-hint {{
                    font-size: 10px;
                    color: #aaa;
                    margin-top: 15px;
                    font-style: italic;
                }}
            </style>
            <div class="qr-container">
                <h3>📱 Open on Mobile Device</h3>
                <div class="qr-image">
                    <!-- In real implementation, this would be the QR code -->
                    <div style="padding: 20px; color: #999;">
                        [QR Code Would Be Here]<br>
                        <small>Demo Mode</small>
                    </div>
                </div>
                <div class="url-text">{url}</div>
                <div class="info-text">
                    Local IP: {local_ip}<br>
                    Port: {port}
                </div>
                <div class="close-hint">Press ESC or click outside to close</div>
            </div>
        </div>
        """
        
        # Show popup
        view = self.window.active_view()
        if view:
            view.show_popup(
                html_content,
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                location=-1,  # Show at cursor
                max_width=300,
                max_height=400,
                on_navigate=self.on_navigate
            )
    
    def show_qr_popup(self, host, port):
        """Show actual QR popup with real server info"""
        # If host is localhost/127.0.0.1, use local network IP
        if host in ['localhost', '127.0.0.1']:
            host = get_local_ip()
            
        url = f"http://{host}:{port}"
        
        # Generate QR code
        qr_base64 = generate_simple_qr_placeholder(url)
        
        # Create HTML content
        html_content = f"""
        <div style="padding: 15px; background-color: #f8f8f8;">
            <style>
                body {{ margin: 0; padding: 0; font-family: -apple-system, sans-serif; }}
                .qr-container {{ 
                    background: white; 
                    border-radius: 8px; 
                    padding: 20px;
                    text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                h3 {{ 
                    color: #333; 
                    margin: 0 0 15px 0;
                    font-size: 16px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }}
                .qr-code {{
                    margin: 15px auto;
                    padding: 10px;
                    background: white;
                    border: 1px solid #eee;
                    border-radius: 4px;
                }}
                .url-display {{
                    margin: 15px 0;
                }}
                .url-text {{
                    font-family: 'SF Mono', Consolas, monospace;
                    font-size: 13px;
                    color: #0066cc;
                    background: #f5f7fa;
                    padding: 10px;
                    border-radius: 4px;
                    word-break: break-all;
                    cursor: pointer;
                    text-decoration: none;
                    display: inline-block;
                }}
                .url-text:hover {{
                    background: #e8eef5;
                }}
                .info {{
                    font-size: 12px;
                    color: #666;
                    margin-top: 10px;
                }}
                .hint {{
                    font-size: 11px;
                    color: #999;
                    margin-top: 15px;
                    font-style: italic;
                }}
            </style>
            <div class="qr-container">
                <h3>
                    <span>📱</span>
                    <span>Scan to Preview</span>
                </h3>
                <div class="qr-code">
                    <img src="data:image/png;base64,{qr_base64}" width="180" height="180" alt="QR Code">
                </div>
                <div class="url-display">
                    <a href="{url}" class="url-text">{url}</a>
                </div>
                <div class="info">
                    Scan with your phone's camera<br>
                    or tap the URL to copy
                </div>
                <div class="hint">ESC or click outside to close</div>
            </div>
        </div>
        """
        
        view = self.window.active_view()
        if view:
            view.show_popup(
                html_content,
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                location=-1,
                max_width=280,
                max_height=420
            )
    
    def on_navigate(self, url):
        """Handle clicks on URLs in the popup"""
        sublime.set_clipboard(url)
        sublime.status_message(f"URL copied to clipboard: {url}")
    
    def is_enabled(self):
        """Only enable when server is running"""
        try:
            from .ServerManager import ServerManager
            return ServerManager.get_instance().is_running()
        except:
            # For demo
            return True

# Demo command to test the popup without server running
class LiveServerQrDemoCommand(sublime_plugin.WindowCommand):
    """Pure demo command to test QR popup appearance"""
    
    def run(self):
        cmd = LiveServerShowQrCommand(self.window)
        cmd.show_qr_demo("localhost", 8080)

# To test this demo:
# 1. Save this file in your LiveServerPlus package folder
# 2. Open command palette and run "Live Server QR Demo"
# 3. Or if server is running, run "Live Server Show QR"