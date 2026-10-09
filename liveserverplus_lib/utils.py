# liveserverplus_lib/utils.py
"""General utilities - cleaned up version with imports from new modules"""
import os
import webbrowser
import platform
from .logging import info, error
from .constants import BROWSER_COMMANDS


def createFileReader(file_path, chunk_size=8192):
    """
    Create a generator that reads a file in chunks.
    
    Args:
        file_path (str): Path to the file
        chunk_size (int): Size of chunks to read
        
    Returns:
        generator: Generator that yields chunks of the file

    Read errors propagate to the caller: by then the response headers,
    including Content-Length, are usually sent, so the only honest thing
    left is to close the connection.
    """
    # Get file size for progress reporting
    file_size = os.path.getsize(file_path)
    bytes_read = 0
        
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
                
            bytes_read += len(chunk)
            # Only log for large files to reduce noise
            if file_size > 1024 * 1024:  # > 1MB
                info(f"Read {bytes_read}/{file_size} bytes from {os.path.basename(file_path)}")
            yield chunk

# Browser and network utilities
def _build_macos_open_command(app_name, url):
    """Build the native macOS command for opening a URL in a foreground app."""
    return ['open', '-a', str(app_name), str(url)]


def _macos_browser_app_name(browser_key):
    browser_map = {
        'brave': 'Brave Browser',
        'chrome': 'Google Chrome',
        'firefox': 'Firefox',
        'safari': 'Safari',
        'edge': 'Microsoft Edge'
    }
    return browser_map.get(browser_key)


def _format_subprocess_error(exc):
    output = []
    returncode = getattr(exc, 'returncode', None)
    if returncode is not None:
        output.append(f"exit={returncode}")
    stderr = (getattr(exc, 'stderr', '') or '').strip()
    stdout = (getattr(exc, 'stdout', '') or '').strip()
    if stderr:
        output.append(f"stderr={stderr}")
    if stdout:
        output.append(f"stdout={stdout}")
    return ', '.join(output) or str(exc)


def openInBrowser(url, browser_name=None):
    """
    Open URL in specified browser or system default
    
    Args:
        url (str): URL to open
        browser_name (str, optional): Browser to use ('chrome', 'firefox', 'safari', 'edge')
    """
    try:
        if not browser_name:
            # Use default browser
            info(f"Opening URL in default browser: {url}")
            webbrowser.open(url)
            return

        # Handle specific browsers based on platform
        system = platform.system().lower()
        browser_name = str(browser_name).strip()
        if not browser_name:
            info(f"Opening URL in default browser: {url}")
            webbrowser.open(url)
            return

        browser_key = browser_name.lower()

        if system == 'darwin':  # macOS
            # Use macOS "open -a" so the selected browser is foregrounded.
            app_name = _macos_browser_app_name(browser_key)
            
            if app_name:
                info(f"Opening URL in {app_name} on macOS: {url}")
                
                import subprocess
                try:
                    command = _build_macos_open_command(app_name, url)
                    info(f"Running macOS open command for {app_name}")
                    result = subprocess.run(
                        command,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    if result.stdout.strip():
                        info(f"macOS open stdout: {result.stdout.strip()}")
                    if result.stderr.strip():
                        info(f"macOS open stderr: {result.stderr.strip()}")
                    return
                except (subprocess.CalledProcessError, OSError) as exc:
                    info(f"Failed to open {app_name}, falling back to default browser ({_format_subprocess_error(exc)})")
            # Fall through to generic handling below.

        elif system == 'windows':
            import subprocess

            def _launch_windows_exe(exe_path: str) -> bool:
                if not exe_path:
                    return False

                try:
                    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    subprocess.Popen([exe_path, url], close_fds=True, creationflags=creationflags)
                    return True
                except Exception as exc:
                    info(f"Failed to launch {exe_path}: {exc}")
                    return False

            def _normalize_windows_exe_path(raw_value) -> str:
                if not raw_value:
                    return ''
                try:
                    raw = str(raw_value).strip()
                except Exception:
                    return ''

                if not raw:
                    return ''

                # Strip quotes and any trailing args.
                if raw.startswith('"'):
                    end_quote = raw.find('"', 1)
                    if end_quote != -1:
                        raw = raw[1:end_quote]
                    else:
                        raw = raw.strip('"')
                else:
                    lower = raw.lower()
                    exe_index = lower.find('.exe')
                    if exe_index != -1:
                        raw = raw[:exe_index + 4]

                return os.path.expandvars(raw).strip()

            def _query_windows_app_paths_exe(exe_name: str) -> str:
                """Resolve executable via Windows 'App Paths' registry entries."""
                if not exe_name:
                    return ''

                try:
                    import winreg  # type: ignore
                except Exception:
                    return ''

                subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
                hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)

                view_flags = [0]
                for flag_name in ('KEY_WOW64_64KEY', 'KEY_WOW64_32KEY'):
                    if hasattr(winreg, flag_name):
                        view_flags.append(getattr(winreg, flag_name))

                for hive in hives:
                    for view_flag in view_flags:
                        try:
                            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view_flag) as key:  # type: ignore[arg-type]
                                try:
                                    value, _ = winreg.QueryValueEx(key, '')
                                except OSError:
                                    value = None

                                exe_path = _normalize_windows_exe_path(value)
                                if exe_path and os.path.isfile(exe_path):
                                    return exe_path

                                # Some entries provide only a directory in "Path".
                                try:
                                    dir_value, _ = winreg.QueryValueEx(key, 'Path')
                                except OSError:
                                    dir_value = None

                                dir_path = _normalize_windows_exe_path(dir_value)
                                if dir_path:
                                    candidate = os.path.join(dir_path, exe_name)
                                    if os.path.isfile(candidate):
                                        return candidate
                        except OSError:
                            continue

                return ''

            def _find_windows_browser_exe(key: str) -> str:
                program_files = os.environ.get('PROGRAMFILES') or ''
                program_files_x86 = os.environ.get('PROGRAMFILES(X86)') or ''
                local_app_data = os.environ.get('LOCALAPPDATA') or ''

                candidates = []
                if key == 'firefox':
                    candidates = [
                        os.path.join(program_files, 'Mozilla Firefox', 'firefox.exe'),
                        os.path.join(program_files_x86, 'Mozilla Firefox', 'firefox.exe'),
                        os.path.join(local_app_data, 'Mozilla Firefox', 'firefox.exe'),
                    ]
                elif key == 'chrome':
                    candidates = [
                        os.path.join(program_files, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                        os.path.join(program_files_x86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                        os.path.join(local_app_data, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                    ]
                elif key == 'edge':
                    candidates = [
                        os.path.join(program_files, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                        os.path.join(program_files_x86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                        os.path.join(local_app_data, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                    ]
                elif key == 'brave':
                    candidates = [
                        os.path.join(program_files, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
                        os.path.join(program_files_x86, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
                        os.path.join(local_app_data, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
                    ]
                else:
                    return ''

                for candidate in candidates:
                    if candidate and os.path.isfile(candidate):
                        return candidate

                # Windows Registry fallback: App Paths (covers non-standard install locations).
                exe_names = {
                    'firefox': 'firefox.exe',
                    'chrome': 'chrome.exe',
                    'edge': 'msedge.exe',
                    'brave': 'brave.exe',
                }
                exe_name = exe_names.get(key, '')
                resolved = _query_windows_app_paths_exe(exe_name)
                if resolved:
                    return resolved

                return ''

            # Allow passing an explicit executable path (or "%ProgramFiles%\\...").
            expanded = os.path.expandvars(os.path.expanduser(browser_name))
            if any(sep in expanded for sep in ('\\', '/')) or expanded.lower().endswith('.exe'):
                if os.path.isfile(expanded) and _launch_windows_exe(expanded):
                    return

            # Edge can be launched via protocol handler reliably.
            if browser_key == 'edge':
                info(f"Opening URL in Microsoft Edge on Windows: {url}")
                try:
                    os.startfile(f"microsoft-edge:{url}")  # type: ignore[attr-defined]
                    return
                except OSError:
                    info("Failed to launch Edge via protocol handler, falling back to executable lookup")

            # Try common install locations (works even when browser isn't on PATH).
            resolved_exe = _find_windows_browser_exe(browser_key)
            if resolved_exe and _launch_windows_exe(resolved_exe):
                return

            # Try cmd.exe "start" (uses App Paths registry if present).
            token = None
            if browser_key in BROWSER_COMMANDS:
                token = BROWSER_COMMANDS[browser_key].get('windows')
            if token:
                info(f"Opening URL in {browser_key} on windows via start: {url}")
                try:
                    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    subprocess.Popen(['cmd', '/c', 'start', '', token, url], close_fds=True, creationflags=creationflags)
                    return
                except Exception as exc:
                    info(f"Failed to use cmd start for {browser_key}: {exc}")

            # Last attempt: try webbrowser with command token (may work if on PATH).
            if token:
                try:
                    browser = webbrowser.get(token)
                    browser.open(url)
                    return
                except Exception as exc:
                    info(f"Failed to use {browser_key} via webbrowser token {token}: {exc}")

        else:
            # Use the existing BROWSER_COMMANDS for non-Windows platforms
            if browser_key in BROWSER_COMMANDS and system in BROWSER_COMMANDS[browser_key]:
                info(f"Opening URL in {browser_key} on {system}: {url}")
                try:
                    browser = webbrowser.get(BROWSER_COMMANDS[browser_key][system])
                    browser.open(url)
                    return
                except Exception as e:
                    info(f"Failed to use {browser_key}: {e}")

        # Fallback to default browser
        info(f"Browser '{browser_key}' not available, using default")
        webbrowser.open(url)
        
    except Exception as e:
        error(f"Error opening browser: {e}")
        # Final fallback to default browser
        try:
            webbrowser.open(url)
        except Exception:
            error(f"Failed to open URL: {url}")

def getFreePort(start_port=8000, max_port=9000):
    """
    Find a random available port in range
    
    Args:
        start_port (int): Port to start checking from
        max_port (int): Maximum port to check
        
    Returns:
        int: First available port or None if none found
    """
    import socket
    import random
    
    # Create a list of ports to check in random order
    port_range = list(range(start_port, max_port))
    random.shuffle(port_range)
    
    for port in port_range:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('localhost', port))
                info(f"Found free port: {port}")
                return port
        except OSError:
            pass
    
    info(f"No free ports found in range {start_port}-{max_port}")
    return None
