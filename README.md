# LiveServerPlus for Sublime Text

A lightweight development server with live reload capabilities for Sublime Text. Perfect for web development with automatic browser refresh on file changes.

## Features

- **Live Reload**: Automatically refreshes your browser when files are modified
- **Multi-Folder Support**: Serves files from all open project folders
- **Zero Configuration**: Works out of the box with sensible defaults
- **Custom Port Selection**: Choose your preferred port number
- **Status Bar Integration**: See server status, port, and connected clients at a glance

## Installation

### Via Package Control (Recommended)

1. Open Command Palette (Cmd/Ctrl + Shift + P)
2. Select "Package Control: Install Package"
3. Search for "LiveServerPlus"

### Manual Installation

1. Download or clone this repository
2. Go to `Preferences > Browse Packages...` in Sublime Text
3. Copy the downloaded repository into the `Packages` directory

## Usage

### From Command Palette

1. Open Command Palette (Cmd/Ctrl + Shift + P)
2. Available commands:
   - "Live Server Plus: Toggle" - Start/Stop the server
   - "Live Server Plus: Custom Port" - Start server on a specific port
   - "Live Server Plus: Open Current File" - Open current file in browser

### Optional Key Bindings

You can add keyboard shortcuts by creating a custom key binding file. Here's a suggested configuration:

```json
[
    { 
        "keys": ["alt+s"], 
        "command": "toggle_start_server"
    },
    { 
        "keys": ["alt+shift+s"], 
        "command": "open_current_file_start_server"
    }
]
```

## Settings

Customize settings in `Preferences > Package Settings > StartServer > Settings`:

```json
{
    "port": 550,
    "poll_interval": 1.0,
    "browser": "",    // Empty for default, or "chrome", "firefox", "safari", "edge"
}
```

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

MIT License - see LICENSE file for details.

## Support

If you encounter any issues or have suggestions:

1. Check the [Issues](https://github.com/ifrederico/sublime-text-start-server/issues) page
2. Create a new issue with:
   - Sublime Text version
   - Operating System
   - Steps to reproduce
   - Expected vs actual behavior
