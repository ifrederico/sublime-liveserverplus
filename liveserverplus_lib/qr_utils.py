# liveserverplus_lib/qr_utils.py
"""QR code generation utilities for mobile device access"""
import socket
import io
import base64
from .logging import info, error

# Import vendored libraries
try:
    import sys
    import os
    
    # Temporarily add vendor directory to sys.path
    vendor_dir = os.path.join(os.path.dirname(__file__), 'vendor')
    if vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    # Import QR libraries
    import pyqrcode
    import png

    # Clean up sys.path
    if vendor_dir in sys.path:
        sys.path.remove(vendor_dir)

    HAS_QR_SUPPORT = True
except ImportError as e:
    error(f"QR code libraries not available: {e}")
    HAS_QR_SUPPORT = False


def get_local_ip():
    """
    Get the local IP address of the machine on the network.
    Returns localhost if unable to determine.
    """
    try:
        # Method 1: Connect to external server to discover outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and ip != "0.0.0.0":
                return ip
        except:
            pass

        # Method 2: Query all addresses for the hostname
        hostname = socket.gethostname()
        addresses = socket.getaddrinfo(hostname, None)
        ipv4_addresses = [
            addr[4][0] for addr in addresses
            if addr[0] == socket.AF_INET and not addr[4][0].startswith("127.")
        ]
        if ipv4_addresses:
            # Prefer private network IPs
            for candidate in ipv4_addresses:
                if candidate.startswith(("192.168.", "10.")):
                    return candidate
            return ipv4_addresses[0]
    except:
        pass

    # Fallback
    return "127.0.0.1"


def generate_qr_code_base64(url):
    """
    Generate QR code as base64-encoded PNG.

    Args:
        url (str): URL to encode in QR code

    Returns:
        str: Base64-encoded PNG image data (empty on error)
    """
    if not HAS_QR_SUPPORT:
        error("QR code generation not available - missing libraries")
        return ""

    try:
        # Create the QR object
        qr = pyqrcode.create(url)

        # Render PNG into in-memory buffer
        buffer = io.BytesIO()
        qr.png(buffer, scale=6)

        # Convert to base64
        png_data = buffer.getvalue()
        base64_data = base64.b64encode(png_data).decode('utf-8')

        return base64_data
    except Exception as e:
        error(f"Error generating QR code: {e}")
        return ""


def get_server_urls(host, port, protocol='http', prefer_local_ip=True):
    """
    Get all possible URLs for accessing the server.

    Args:
        host (str): Server host
        port (int): Server port

    Returns:
        dict: {'primary': primary_url, 'all': [list_of_urls]}
    """
    urls = []
    
    # Always use network IP for mobile access
    scheme = protocol or 'http'

    if prefer_local_ip and host in ['localhost', '127.0.0.1', '0.0.0.0']:
        local_ip = get_local_ip()
        primary_url = f"{scheme}://{local_ip}:{port}"
        urls.append(primary_url)
        urls.append(f"{scheme}://localhost:{port}")
        if local_ip != "127.0.0.1":
            urls.append(f"{scheme}://127.0.0.1:{port}")
    else:
        primary_url = f"{scheme}://{host}:{port}"
        urls.append(primary_url)

    return {
        'primary': primary_url,
        'all': list(dict.fromkeys(urls))  # Remove duplicates
    }
