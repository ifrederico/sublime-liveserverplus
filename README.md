# LiveServerPlus for Sublime Text

A lightweight development server with live reload capabilities for Sublime Text. Perfect for web development with automatic browser refresh on file changes.

## Features

- **Live Reload**: Automatically refreshes your browser when files are modified
- **Multi-Folder Support**: Serves files from all open project folders
- **Zero Configuration**: Works out of the box with sensible defaults
- **Custom Port Selection**: Choose your preferred port number
- **Status Bar Integration**: See server status, port, and connected clients at a glance

---

## Installation

### Via Package Control (Recommended)

1. Open Command Palette (<kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> on Windows/Linux, <kbd>Cmd</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> on macOS).
2. Select **"Package Control: Install Package"**.
3. Search for **"LiveServerPlus"** and install.

### Manual Installation

1. Download or clone this repository.
2. In Sublime Text, go to **Preferences > Browse Packages...**.
3. Copy the downloaded repository into the `Packages` directory.

---

## Usage

### From Command Palette

1. Open Command Palette (<kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> / <kbd>Cmd</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd>).
2. Available commands:
   - **"Live Server Plus: Toggle"** – Start/Stop the server
   - **"Live Server Plus: Custom Port"** – Start the server on a specific port
   - **"Live Server Plus: Open Current File"** – Open the current file in your browser

### Optional Key Bindings

You can add keyboard shortcuts by creating or editing your custom key bindings file. For example:

```json
[
    {
        "keys": ["alt+shift+s"],
        "command": "toggle_start_server"
    },
    {
        "keys": ["alt+shift+o"],
        "command": "open_current_file_start_server"
    }
]
```

### Settings

Customize settings in `Preferences > Package Settings > StartServer > Settings`:

```json
{
    "port": 5500,
    "poll_interval": 1.0,
    "browser": "",    // Empty for default, or "chrome", "firefox", "safari", "edge"
}
```

### Example with Live Reload
```json
{
    "port": 5500,
    "poll_interval": 1.0,
    "browser": "",
    "live_reload": {
        "enabled": true,
        "reload": true,
        "css_injection": true,
        "delay": 500,
        "ignore_exts": [".log", ".map"]
    }
}

```

- enabled: If true, Sublime’s own file events trigger reload instead of an internal file watcher.
- reload: If true, a full page refresh occurs when any allowed file changes; if false, CSS changes are injected without a full reload.
- css_injection: If true, .css changes are injected live (no page reload).
- delay: Debounce (in milliseconds) for changes before triggering a reload or injection.
- ignore_exts: A list of file extensions to ignore when auto-reloading or injecting.

## Features

### Live Reload
- Auto-refreshes browser on file changes
- Watches HTML, CSS, and JavaScript files
- Real-time WebSocket communication

### Multi-Folder Support
- Serves files from all open project folders
- Smart file watching across directories

### Status Bar Integration
- Shows server status
- Displays current port
- Indicates connected clients

## Requirements

- Sublime Text 3 or 4
- Modern web browser with WebSocket support

## License

Modified MIT License- see LICENSE file for details.

## Support

If you encounter any issues or have suggestions:

1. Check the [Issues](https://github.com/ifrederico/sublime-liveserverplus/issues) page
2. Create a new issue with:
   - Sublime Text version
   - Operating System
   - Steps to reproduce
   - Expected vs actual behavior