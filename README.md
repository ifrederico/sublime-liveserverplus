# Live Server Plus for Sublime Text

A lightweight development server with WebSocket‑based live reload.

![Live Server Plus Demo](./images/liveserverplus1.gif)

---

## Installation

### Package Control (recommended)

1. Open the Command Palette: **`Cmd/Ctrl + Shift + P`**  
2. Select **Package Control: Install Package**  
3. Search for **“LiveServerPlus”** and install.

### Manual

1. Download or clone this repository.  
2. In Sublime Text, choose **Preferences ▸ Browse Packages…**  
3. Copy the folder into the `Packages` directory and name it **`LiveServerPlus`**.

---

## Usage

Open a file, folder or workspace (**File ▸ Open Folder**) first.

### Main menu

*Tools ▸ Live Server Plus*:

| Action | Description |
| ------ | ----------- |
| **Start Server** | Starts the server (multi‑folder picker). |
| **Stop Server** | Stops the server. |
| **Open in Browser** | Opens the active file through the server. |
| **Show Mobile QR Code** | Displays a QR for phones/tablets. If LAN access is off, Sublime asks before enabling it. |
| **Enable LAN Access** | Allows devices on your network to reach the server. |
| **Disable LAN Access** | Returns to local-only serving. |
| **Enable Live Reload** | Switch to Sublime-driven reload (auto-save option). |
| **Disable Live Reload** | Return to Watchdog-based external file watching. |
| **Change Port…** | Enter any port or **0** for “find a free one”. |
| **Enable Debug Logging** | Print LiveServerPlus diagnostics to the Sublime console. |
| **Settings…** | Opens the user settings file. |

### Command Palette

`Cmd/Ctrl + Shift + P` → type:

- **Live Server Plus: Start Server**  
- **Live Server Plus: Stop Server**  
- **Live Server Plus: Open in Browser**  
- **Live Server Plus: Show Mobile QR Code**  
- **Live Server Plus: Enable LAN Access**
- **Live Server Plus: Disable LAN Access**
- **Live Server Plus: Enable Live Reload**  
- **Live Server Plus: Disable Live Reload**  
- **Live Server Plus: Change Port…**  
- **Live Server Plus: Enable Debug Logging**
- **Live Server Plus: Disable Debug Logging**
- **Live Server Plus: Settings**

### Example workflow

1. Open your project folder.  
2. Run **Live Server Plus: Start Server**.  
3. Edit and save—your browser refreshes automatically.

---

## Features

- **Instant reload** on file changes; optional CSS-only injection. Enable Sublime-only mode when you want immediate reloads on save, or leave it disabled to monitor external tools via Watchdog.  
- **GitHub-style Markdown preview** with live scroll sync—defaults to editor→browser, switch to "sync" for two-way or `false` to disable.  
- **Mobile preview**: scan a QR code to open the site on devices on the same network. Local-only is the default; LAN access is opt-in.
- **Port selection**: choose a port at startup or set `"port": 0` for a free one.  
- **Automatic watcher fallback**: native watchers for performance, seamless polling fallback when macOS hits the file-descriptor limit.  
- **Runs in Sublime’s bundled Python**—no external runtime required.

---

## Optional key bindings

```json
[
    { "keys": ["alt+shift+s"], "command": "live_server_start" },
    { "keys": ["alt+shift+o"], "command": "open_current_file_live_server" },
    { "keys": ["alt+shift+x"], "command": "live_server_stop" }
]
```

---

## Settings quick reference

```js
// LiveServerPlus.sublime-settings (user)
{
    "customBrowser": "",
    "openBrowser": true,
    "showInfoMessages": true,
    "verifyTags": true,
    "fullReload": false,
    "liveReload": false,
    "host": "127.0.0.1",
    // Local-only by default. Use "useLocalIp": true or Enable LAN Access for phone/tablet QR preview.
    "maxThreads": 64,
    "maxWatchedDirs": 50,
    "renderMarkdownPreview": true,
    "markdownScrollSync": "editor", // "editor", "sync", or false
    "ignoreFiles": ["**/node_modules/**", "**/.git/**", "**/__pycache__/**"],
    "logging": false,
    "port": 5500,
    "showOnStatusbar": true,
    "useLocalIp": false,
    "useWebExt": false,
    "wait": 100
}
```

Restart the server after changing settings.

### Local vs LAN access

By default Live Server Plus is local-only:

```json
{
    "host": "127.0.0.1",
    "useLocalIp": false
}
```

This is the safest mode. Your desktop browser can open the server, but your phone cannot.

For phone/tablet preview, run **Live Server Plus: Enable LAN Access** or set:

```json
{
    "useLocalIp": true
}
```

LAN access lets devices on the same network reach your dev server. The server still opens in your desktop browser, and the mobile QR code uses your machine's LAN IP.

> **Security note:** LAN access exposes the dev server to devices on your local network. Use it on trusted networks.

### Troubleshooting

- **QR code does not open on the phone:** make sure LAN access is enabled, the phone is on the same Wi-Fi/network, and firewall/VPN settings are not blocking local connections.
- **Browser does not open where expected:** set `"customBrowser"` to `"chrome"`, `"firefox"`, `"safari"`, `"edge"`, or `"brave"`. Leave it empty to use the system default.
- **Package Control has not updated yet:** Package Control can take a while to index new releases. Run **Package Control: Upgrade Package** or try again later.

---

## Requirements

- **Sublime Text 4** (Build ≥ 4152)  
- Browser with WebSocket support (Chrome, Firefox, Edge, Safari)

---

## Known limitations

- Watchdog mode watches up to 50 directories; adjust ignore globs or reduce scope for very large projects. When Live Reload is enabled, only saves inside Sublime trigger refreshes.

---

## Contributing

Contributions welcome! Issues and pull requests are welcome.

---

## Vendored dependencies

- **Watchdog** – filesystem events  
- **PyQRCode** and **pypng** – QR generation
- **markdown2** – Markdown → HTML conversion 

All vendored under `liveserverplus_lib/vendor/`.

---

## Support

Report bugs/issues on GitHub: <https://github.com/ifrederico/sublime-liveserverplus/issues>

---

## License

[MIT](./LICENSE)
