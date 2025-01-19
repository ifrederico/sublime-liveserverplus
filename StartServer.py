# StartServer.py
import sublime
import sublime_plugin
import webbrowser
import os

# Import the renamed class from server.py
from .lib.server import StartServer

# Global reference to the server instance
start_server_instance = None

def get_start_server_settings():
    """
    Load user settings from StartServer.sublime-settings
    """
    return sublime.load_settings("StartServer.sublime-settings")

def plugin_unloaded():
    """
    Called by Sublime Text when the plugin is unloaded (e.g., disabled).
    We ensure the server is shut down so no threads/sockets remain.
    """
    global start_server_instance
    if start_server_instance is not None and start_server_instance.is_alive():
        start_server_instance.stop_server()
        start_server_instance = None

def update_status_bar(running, port=None):
    """
    Update or clear the 'start_server' status in all open views.
    """
    window = sublime.active_window()
    if not window:
        return
    for view in window.views():
        if running:
            view.set_status("start_server", "StartServer: Running on http://localhost:{}".format(port))
        else:
            view.erase_status("start_server")

def check_server_bound():
    """
    Called ~300ms after starting the server to see if port binding failed.
    If 'bind_failed' is True, we stop the server and clear the status bar.
    """
    global start_server_instance
    if start_server_instance and start_server_instance.is_alive():
        if start_server_instance.bind_failed:
            # The server couldn't bind to the specified port
            start_server_instance.stop_server()
            start_server_instance = None
            update_status_bar(False)
        # else it’s running fine

class ToggleStartServerCommand(sublime_plugin.WindowCommand):
    """
    A single command that toggles the server:
      - If no folder is open, it shows 'No Folder Opened' in the Tools menu (disabled).
      - If the server is running, it stops it.
      - If it's not running, it starts it AND opens the current file in the browser.
    The visible caption is set by description().
    """
    def run(self):
        global start_server_instance

        folders = self.window.folders()
        if not folders:
            sublime.status_message("[StartServer] No folder open.")
            return

        # If already running, stop it:
        if start_server_instance and start_server_instance.is_alive():
            start_server_instance.stop_server()
            start_server_instance = None
            sublime.status_message("[StartServer] Stopped server.")
            update_status_bar(False)
            return

        # Otherwise, start it:
        settings = get_start_server_settings()
        port = settings.get("port", 8080)
        poll_interval = settings.get("poll_interval", 1.0)
        # Create the server instance
        start_server_instance = StartServer(folders, port, poll_interval)
        start_server_instance.start()

        # Wait a short moment, then check if binding failed:
        sublime.set_timeout_async(check_server_bound, 300)

        # Attempt to open the current file in the browser:
        self._open_current_file_in_browser(port)

        sublime.status_message("[StartServer] Started on port {}".format(port))
        update_status_bar(True, port)

    def _open_current_file_in_browser(self, port):
        settings = get_start_server_settings()
        open_browser = settings.get("open_browser_on_start", True)
        if not open_browser:
            return

        view = self.window.active_view()
        if not view or not view.file_name():
            # If there's no current file, open root
            webbrowser.open("http://localhost:{}".format(port), new=2)
            return

        file_path = view.file_name()
        # Check if it's inside any of the open folders
        rel_path = None
        for folder in self.window.folders():
            if file_path.startswith(folder):
                rel_path = os.path.relpath(file_path, folder)
                break

        if not rel_path:
            # Not in an open folder => fallback to root index
            webbrowser.open("http://localhost:{}".format(port), new=2)
            return

        # Convert Windows backslashes to forward slashes
        rel_path = rel_path.replace("\\", "/")
        url = "http://localhost:{}/{}".format(port, rel_path)
        webbrowser.open(url, new=2)

    def description(self):
        """
        Determines the caption shown in the Tools menu & Command Palette.
        """
        global start_server_instance
        folders = self.window.folders()
        if not folders:
            return "No Folder Opened"
        if start_server_instance and start_server_instance.is_alive():
            return "Stop Server"
        return "Start Server (Open Current File)"

    def is_enabled(self):
        """
        Disable the command entirely if there's no open folder.
        """
        return bool(self.window.folders())

class OpenCurrentFileStartServerCommand(sublime_plugin.WindowCommand):
    """
    Command that opens the active view’s file in the browser,
    but ONLY if the server is running and there's a valid file/folder.
    """
    def run(self):
        global start_server_instance
        if not start_server_instance or not start_server_instance.is_alive():
            sublime.status_message("[StartServer] Server not running.")
            return

        view = self.window.active_view()
        if not view or not view.file_name():
            sublime.status_message("[StartServer] No file to open.")
            return

        file_path = view.file_name()
        rel_path = None
        for folder in self.window.folders():
            if file_path.startswith(folder):
                rel_path = os.path.relpath(file_path, folder)
                break

        if not rel_path:
            sublime.status_message("[StartServer] File is not in the project folders.")
            return

        rel_path = rel_path.replace("\\", "/")
        url = "http://localhost:{}/{}".format(start_server_instance.port, rel_path)
        webbrowser.open(url, new=2)
        sublime.status_message("[StartServer] Opened current file: {}".format(url))

    def description(self):
        """
        If not possible to open, show a helpful label.
        We also use is_visible() to hide the command if it's not applicable.
        """
        global start_server_instance
        if not (start_server_instance and start_server_instance.is_alive()):
            return "Server not running"
        view = self.window.active_view()
        if not view or not view.file_name():
            return "No file to open"
        return "Open Current File"

    def is_enabled(self):
        """
        Grays out the item if not possible to open.
        """
        global start_server_instance
        if not (start_server_instance and start_server_instance.is_alive()):
            return False
        view = self.window.active_view()
        if not view or not view.file_name():
            return False
        return True

    def is_visible(self):
        """
        Hides the command entirely if it's not usable.
        """
        return self.is_enabled()