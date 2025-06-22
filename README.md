# Live Server Plus for Sublime Text

A lightweight development server with WebSocket-based live reload and directory listings—all from within Sublime Text.

![Live Server Plus Demo](./images/liveserverplus1.gif)

---

## Installation

### Via Package Control (Recommended)

1. Open the Command Palette: **`Cmd/Ctrl + Shift + P`**  
2. Select **“Package Control: Install Package”**  
3. Search for **“LiveServerPlus”** and install.

### Manual Installation

1. Download or clone this repository.
2. In Sublime Text, go to **`Preferences > Browse Packages…`**.
3. Move/copy the downloaded folder into the `Packages` directory.
4. Ensure the folder name is **`LiveServerPlus`**.

---

## Usage

First, open a folder or workspace (**File » Open Folder**) in Sublime Text. Then:

### 1. Main Menu

- **Tools » Live Server Plus**:
  - **Start Server**: Starts the live server.
  - **Stop Server**: Stops the server.
  - **Open Current File**: Opens active file in browser.

### 2. Command Palette

Press `Cmd/Ctrl + Shift + P`, then select:
- **Live Server Plus: Start**
- **Live Server Plus: Stop**
- **Live Server Plus: Open Current File**
- **Live Server Plus: Settings**

### Example Workflow

1. Launch Sublime and open your web project folder.
2. Run **Live Server Plus: Start** from the Command Palette.
3. Edit and save files; browser refreshes automatically.

---

## Features

- **Instant Refresh**: Automatically refreshes the browser on file changes.
- **No External Dependencies**: Runs directly in Sublime’s bundled Python environment.
- **Friendly Directory View & Smart 404s**: Easily navigate your project; get helpful suggestions on missing files.
- **Flexible File Watching**:
  - **Sublime Events**: Fast, built-in method for most users.
  - **Built-in Watcher**: Poll-based watcher as a fallback (handles external changes).
- **Customizable Settings**: Adjust port, host, compression, browser, and more.
- **Status Bar Integration**: Quickly see server status.

---

## Optional Key Bindings

Add keyboard shortcuts via **`Preferences > Key Bindings`**:

```json
[
    { "keys": ["alt+shift+s"], "command": "live_server_start" },
    { "keys": ["alt+shift+o"], "command": "open_current_file_live_server" },
    { "keys": ["alt+shift+x"], "command": "live_server_stop" }
]
```

---

## Settings (Customizing Live Server)

Open via **`Preferences > Package Settings > Live Server Plus > Settings`**.

**Note:** Restart the server after changing settings.

---

## Requirements

- **Sublime Text 4**
- Browser with WebSocket support (Chrome, Firefox, Edge, Safari)

---

## Known Limitations

- No built-in HTTPS support. Use reverse proxy if HTTPS is required.
- File watcher limits directories (50 max).

---

## Contributing

Contributions welcome! Please open issues or PRs.

---

## Vendored Dependencies

To ensure compatibility and avoid external dependency issues, this plugin includes the following vendored libraries:

- Watchdog (v6.0.0) for file system event monitoring.

These libraries are included in the liveserverplus_lib/vendor directory and are loaded dynamically by the plugin.

---

## Support

Report bugs/issues on [GitHub Issues](https://github.com/ifrederico/sublime-liveserverplus/issues).

---

## License

MIT License ([LICENSE](./LICENSE)).
