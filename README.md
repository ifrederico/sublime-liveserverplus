# StartServer for Sublime Text

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
3. Search for "StartServer"

### Manual Installation

1. Download or clone this repository
2. Go to `Preferences > Browse Packages...` in Sublime Text
3. Copy the downloaded repository into the `Packages` directory

## Usage

### Basic Commands

- Toggle Server: `Alt+S`
- Open Current File in Browser: `Alt+Shift+S` (Mac) / `Alt+Shift+S` (Windows/Linux)

### From Command Palette

1. Open Command Palette (Cmd/Ctrl + Shift + P)
2. Available commands:
   - "Start Server: Toggle"
   - "Start Server: Custom Port"
   - "Start Server: Open Current File"

### From Tools Menu

Find the Start Server submenu in the Tools menu with options to:
- Toggle server
- Choose custom port
- Open current file

## Settings

Default settings can be modified via `Preferences > Package Settings > StartServer > Settings`:

```json
{
    "port": 8080,
    "poll_interval": 1.0,
    "open_browser_on_start": true
}
```

## Features

- **Live Reload**: 
  - Auto-refreshes browser on file changes
  - Watches HTML, CSS, and JavaScript files
  - Real-time WebSocket communication

- **Multi-Folder Support**:
  - Serves files from all open project folders
  - Smart file watching across directories

- **Status Bar Integration**:
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

## Credits

Developed by Frederico