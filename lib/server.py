# lib/server.py
import os
import time
import socket
import threading
import base64
import hashlib
import sys
import mimetypes

import sublime  # for showing error messages from the server thread (via set_timeout)

# Fallback MIME dictionary if mimetypes doesn't detect properly:
FALLBACK_MIME = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml"
}


class FileWatcher(threading.Thread):
    """
    Watches a single folder for changes in .html, .htm, .css, .js files.
    Calls `on_change_callback(path)` whenever a file is modified.

    Uses naive polling with `os.walk` + file mtime checks.
    """
    def __init__(self, root_folder, on_change_callback, poll_interval=1.0):
        super(FileWatcher, self).__init__()
        self.root_folder = root_folder
        self.on_change_callback = on_change_callback
        self.poll_interval = poll_interval
        self._stop_flag = False
        self._last_mtimes = {}

    def run(self):
        """
        Main thread loop: repeatedly scan the folder until stopped.
        """
        while not self._stop_flag:
            self.scan_folder()
            time.sleep(self.poll_interval)

    def scan_folder(self):
        """
        Recursively walks `self.root_folder`, checking .html, .htm, .css, .js files for changes.
        """
        for dirpath, dirnames, filenames in os.walk(self.root_folder):
            for f in filenames:
                # Monitor only HTML, HTM, CSS, JS
                if not f.lower().endswith(('.html', '.htm', '.css', '.js')):
                    continue

                fullpath = os.path.join(dirpath, f)
                try:
                    mtime = os.path.getmtime(fullpath)
                    if fullpath not in self._last_mtimes:
                        self._last_mtimes[fullpath] = mtime
                    else:
                        if mtime != self._last_mtimes[fullpath]:
                            self._last_mtimes[fullpath] = mtime
                            # A file changed -> notify callback
                            self.on_change_callback(fullpath)
                except OSError:
                    # File might have been deleted or be inaccessible
                    pass

    def stop(self):
        """
        Signal this thread to exit.
        """
        self._stop_flag = True


class MultiFolderWatcher(threading.Thread):
    """
    Creates and manages multiple FileWatcher threads, one per folder.
    This allows monitoring all project folders simultaneously.
    """
    def __init__(self, folders, on_change_callback, poll_interval=1.0):
        super(MultiFolderWatcher, self).__init__()
        self.folders = folders
        self.on_change_callback = on_change_callback
        self.poll_interval = poll_interval
        self._stop_flag = False
        self.watchers = []

    def run(self):
        """
        Spawns a FileWatcher for each folder, then waits until stop() is called.
        """
        # Create and start one FileWatcher per folder
        for folder in self.folders:
            fw = FileWatcher(folder, self.on_change_callback, self.poll_interval)
            fw.start()
            self.watchers.append(fw)

        # Keep running until stop() is invoked
        while not self._stop_flag:
            time.sleep(0.2)

        # Stop all watchers
        for fw in self.watchers:
            fw.stop()
            fw.join()
        self.watchers = []

    def stop(self):
        """
        Stop all underlying watchers and end this thread.
        """
        self._stop_flag = True


class StartServer(threading.Thread):
    """
    A combined HTTP + WebSocket dev server that:
      - Serves static files from one or more folders
      - Injects a "live reload" script in HTML responses
      - Implements a minimal WebSocket to broadcast "reload" messages
      - Watches files for changes (using MultiFolderWatcher)
      - Gracefully handles port conflicts (bind failures)
    """

    MAGIC_STRING = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

    def __init__(self, folders, port=8080, poll_interval=1.0):
        """
        :param folders: List of folders to serve & watch
        :param port: Port on localhost to listen on
        :param poll_interval: Seconds between file system checks
        """
        super(StartServer, self).__init__()
        self.folders = folders
        self.port = port
        self.poll_interval = poll_interval

        self._running = False
        self.sock = None
        self.clients = []        # Active WebSocket connections
        self.file_watcher = None
        self.threads = []        # Connection-handler threads
        self.bind_failed = False
        self.bind_error = None

    def run(self):
        """
        Entry point for the server thread:
         1. Start MultiFolderWatcher
         2. Bind & listen on self.port
         3. Accept connections, handle HTTP or WebSocket
         4. Cleanup on stop
        """
        self._running = True

        # Start multi-folder watcher (one FileWatcher per folder)
        self.file_watcher = MultiFolderWatcher(
            self.folders,
            on_change_callback=self.on_file_change,
            poll_interval=self.poll_interval
        )
        self.file_watcher.start()

        # Create a TCP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(('localhost', self.port))
        except OSError as e:
            print("[StartServer] Could not bind on port {}: {}".format(self.port, e))
            self.bind_failed = True
            self.bind_error = e
            self._running = False

            # Notify the user via a Sublime error message on the main thread
            def show_error():
                sublime.error_message(
                    "StartServer:\n\nCould not bind to port {}.\n\nError:\n{}".format(self.port, e)
                )
            sublime.set_timeout(show_error, 0)
            return

        self.sock.listen(5)
        print("[StartServer] Listening on http://localhost:{}".format(self.port))

        # Main accept() loop
        while self._running:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                # Socket was closed in stop_server()
                break

            t = threading.Thread(target=self.handle_connection, args=(conn, addr))
            t.daemon = True
            t.start()
            self.threads.append(t)

        # Cleanup
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

        for t in self.threads:
            t.join()

        # Stop file watcher
        if self.file_watcher:
            self.file_watcher.stop()
            self.file_watcher.join()

        # Close any WS clients
        for c in self.clients:
            try:
                c.close()
            except:
                pass
        self.clients = []
        print("[StartServer] Stopped.")

    def handle_connection(self, conn, addr):
        """
        Distinguishes between standard HTTP requests and WebSocket upgrade requests.
        """
        try:
            request_data = conn.recv(2048)
        except:
            conn.close()
            return

        if not request_data:
            conn.close()
            return

        headers = request_data.decode('utf-8', errors='replace').split('\r\n')
        if len(headers) < 1:
            conn.close()
            return

        request_line = headers[0]  # e.g. "GET / HTTP/1.1"
        parts = request_line.split()
        if len(parts) < 3:
            conn.close()
            return

        method, path, http_version = parts[0], parts[1], parts[2]

        # Check for WebSocket upgrade
        upgrade_websocket = False
        ws_key = None
        for line in headers:
            if line.lower().startswith("upgrade:") and "websocket" in line.lower():
                upgrade_websocket = True
            if line.lower().startswith("sec-websocket-key:"):
                ws_key = line.split(":", 1)[1].strip()

        if upgrade_websocket and ws_key:
            self.handle_websocket_upgrade(conn, ws_key)
        else:
            self.handle_http_request(conn, method, path)

    def handle_http_request(self, conn, method, path):
        """
        Serve static files over HTTP. If a directory is requested, attempt index.html.
        """
        if method != "GET":
            self.http_send_response(conn, 405, b"Method Not Allowed", b"text/plain")
            return

        # Default to /index.html if path is just "/"
        if path == "/":
            path = "/index.html"
        rel_path = path.lstrip("/")

        file_found = False
        for folder in self.folders:
            file_path = os.path.join(folder, rel_path)

            # If it's a directory, try index.html
            if os.path.isdir(file_path):
                index_file = os.path.join(file_path, "index.html")
                if os.path.isfile(index_file):
                    file_path = index_file
                else:
                    # No index.html => skip
                    continue

            if os.path.isfile(file_path):
                self.serve_file(conn, file_path)
                file_found = True
                break

        if not file_found:
            self.http_send_response(conn, 404, b"File Not Found", b"text/plain")

    def serve_file(self, conn, file_path):
        """
        Reads and serves the file, injecting the live reload script if HTML.
        """
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except Exception as e:
            err_msg = ("Error reading file: {}".format(e)).encode('utf-8')
            self.http_send_response(conn, 500, err_msg, b"text/plain")
            return

        mime_type = self.guess_mime_type(file_path)

        # If it's HTML, inject the WebSocket script
        if mime_type.startswith(b"text/html"):
            try:
                content_str = content.decode("utf-8", errors="replace")
                inject_code = (
                    "<script>\n"
                    "  (function() {\n"
                    "    var ws = new WebSocket('ws://localhost:%d');\n"
                    "    ws.onmessage = function(evt) {\n"
                    "      if (evt.data === 'reload') {\n"
                    "        location.reload();\n"
                    "      }\n"
                    "    };\n"
                    "  })();\n"
                    "</script>\n" % self.port
                )
                insertion_index = content_str.lower().rfind("</body>")
                if insertion_index == -1:
                    content_str += inject_code
                else:
                    content_str = (
                        content_str[:insertion_index]
                        + inject_code
                        + content_str[insertion_index:]
                    )
                content = content_str.encode("utf-8")
            except:
                pass

        self.http_send_response(conn, 200, content, mime_type)

    def guess_mime_type(self, path):
        """
        Attempts to guess a file's MIME type using Python's mimetypes,
        falling back to our custom dict for known extensions.
        """
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type:
            return mime_type.encode("utf-8")
        ext = os.path.splitext(path.lower())[1]
        return FALLBACK_MIME.get(ext, "application/octet-stream").encode("utf-8")

    def http_send_response(self, conn, status_code, content, mime_type):
        """
        Sends a minimal HTTP response with status, Content-Type, and length.
        Closes the connection afterwards.
        """
        try:
            status_text = self.http_status_text(status_code)
            status_line = "HTTP/1.1 {} {}\r\n".format(status_code, status_text)
            headers = (
                "Content-Type: {}\r\n"
                "Content-Length: {}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).format(mime_type.decode("utf-8"), len(content))

            conn.send(status_line.encode("utf-8"))
            conn.send(headers.encode("utf-8"))
            conn.send(content)
        except:
            pass
        finally:
            conn.close()

    def http_status_text(self, code):
        """
        Simple mapping of HTTP status codes to reason phrases.
        """
        mapping = {
            200: "OK",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
        }
        return mapping.get(code, "Unknown")

    def handle_websocket_upgrade(self, conn, ws_key):
        """
        Completes the WebSocket handshake and stores the connection in self.clients.
        """
        accept_val = self.make_websocket_accept(ws_key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n"
        ).format(accept_val)

        try:
            conn.send(response.encode("utf-8"))
            self.clients.append(conn)
            print("[StartServer] WebSocket client connected.")
        except:
            conn.close()

    def make_websocket_accept(self, key):
        """
        Generates the 'Sec-WebSocket-Accept' header value from the client's key + magic string.
        """
        sha = hashlib.sha1((key + self.MAGIC_STRING).encode("utf-8")).digest()
        return base64.b64encode(sha).decode("utf-8")

    def on_file_change(self, path):
        """
        Called by FileWatcher threads when a relevant file changes.
        Broadcast a 'reload' message to all WS clients.
        """
        print("[StartServer] File changed: {} -> broadcasting reload".format(path))
        self.broadcast_reload()

    def broadcast_reload(self):
        """
        Sends a 'reload' message to all connected WebSocket clients.
        Removes dead clients that fail to send.
        """
        frame = self.build_ws_frame("reload")
        dead_clients = []
        for c in self.clients:
            try:
                c.send(frame)
            except:
                dead_clients.append(c)

        for dc in dead_clients:
            try:
                self.clients.remove(dc)
            except:
                pass

    def build_ws_frame(self, message):
        """
        Builds a single-frame, unmasked text message for the WebSocket protocol.
        """
        msg_bytes = message.encode("utf-8")
        frame = bytearray([0x81])  # 0x81 = FIN + text frame
        length = len(msg_bytes)
        if length < 126:
            frame.append(length)
        else:
            frame.append(126)
            frame.append((length >> 8) & 0xFF)
            frame.append(length & 0xFF)
        frame.extend(msg_bytes)
        return frame

    def stop_server(self):
        """
        Graceful shutdown:
         - Mark not running
         - Close main socket to break accept()
         - The thread cleans up watchers, websockets, etc.
        """
        print("[StartServer] Stopping server...")
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass