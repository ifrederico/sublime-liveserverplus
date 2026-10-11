# liveserverplus_lib/qr_utils.py
"""QR code generation utilities for mobile device access"""
import socket
import io
import base64
import ipaddress
import platform
import re
import subprocess
from .logging import info, error
from .path_utils import build_base_url

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


_LAN_NETWORKS = tuple(
    ipaddress.ip_network(block) for block in ('192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12')
)

# One "inet" line from `ifconfig` (macOS, BSD, old Linux), `ip -4 -o addr`
# (Linux) or `ipconfig` (Windows, any language: the label always contains
# "IPv4"). "inet " with the space leaves inet6 lines alone.
_ADDRESS_RE = re.compile(r'(?:inet (?:addr:)?|IPv4[^:\r\n]*:\s*)(\d+\.\d+\.\d+\.\d+)')


def _is_lan_address(ip):
    """True for a private address another device on the network could reach.

    Loopback, link-local (169.254/16: an interface with no DHCP lease) and
    the CGNAT block (100.64/10, which VPN tunnels such as Tailscale, WARP
    and corporate clients hand out) all fall outside the private ranges,
    and a phone on the Wi-Fi cannot reach any of them.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in _LAN_NETWORKS)


def _source_address_towards(destination):
    """The local address the OS would send from to reach ``destination``.

    Nothing is sent: connecting a UDP socket only picks the route.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.connect((destination, 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _hostname_addresses():
    try:
        return [entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def _listed_addresses():
    """Addresses from the OS's own interface listing, in interface order.

    The standard library cannot enumerate interfaces, so this asks the
    system tool and reads the inet lines out of whatever it prints.
    """
    if platform.system().lower() == 'windows':
        commands = [['ipconfig']]
    else:
        commands = [['ip', '-4', '-o', 'addr'], ['ifconfig']]

    for command in commands:
        try:
            output = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found = _ADDRESS_RE.findall(output)
        if found:
            return found
    return []


def get_local_ip():
    """The address other devices on the local network can reach this machine at.

    Candidates are tried cheapest first: the address the OS would send
    from towards the internet, towards multicast, towards broadcast, then
    the hostname's addresses, then the OS's interface listing. The first
    one in a private LAN range wins.

    The internet route alone is not enough: with a VPN up it runs through
    the tunnel and reports the tunnel's 100.64.x.x address, which a phone
    on the Wi-Fi cannot reach and which the VPN usually refuses even
    locally. The multicast and broadcast routes still point at the real
    network interface, and the listing has every address.

    Falls back to the internet-route address, then to 127.0.0.1.
    """
    outbound = _source_address_towards('8.8.8.8')
    sources = (
        lambda: [outbound],
        lambda: [_source_address_towards('224.0.0.1')],
        lambda: [_source_address_towards('255.255.255.255')],
        _hostname_addresses,
        _listed_addresses,
    )
    for source in sources:
        for ip in source():
            if ip and _is_lan_address(ip):
                return ip

    if outbound and outbound != '0.0.0.0' and not outbound.startswith('127.'):
        return outbound
    return '127.0.0.1'


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
        primary_url = build_base_url(scheme, local_ip, port).rstrip('/')
        urls.append(primary_url)
        urls.append(build_base_url(scheme, 'localhost', port).rstrip('/'))
        if local_ip != "127.0.0.1":
            urls.append(build_base_url(scheme, '127.0.0.1', port).rstrip('/'))
    else:
        primary_url = build_base_url(scheme, host, port).rstrip('/')
        urls.append(primary_url)

    return {
        'primary': primary_url,
        'all': list(dict.fromkeys(urls))  # Remove duplicates
    }
