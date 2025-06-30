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
| **Open Current File** | Opens the active file through the server. |
| **Show Mobile QR Code** | Displays a QR linking devices on the LAN to the dev URL. |
| **Live Reload** | Toggles live‑reload on or off. |
| **Change Port…** | Enter any port or **0** for “find a free one”. |
| **Settings…** | Opens the user settings file. |

### Command Palette

`Cmd/Ctrl + Shift + P` → type:

- **Live Server Plus: Start Server**  
- **Live Server Plus: Stop Server**  
- **Live Server Plus: Open Current File in Browser**  
- **Live Server Plus: Show Mobile QR Code**  
- **Live Server Plus: Toggle Live Reload**  
- **Live Server Plus: Change Port…**  
- **Live Server Plus: Settings**

### Example workflow

1. Open your project folder.  
2. Run **Live Server Plus: Start Server**.  
3. Edit and save—your browser refreshes automatically.

---

## Features

- **Instant reload** on file changes; optional CSS‑only injection.  
- **Mobile preview**: scan a QR code to open the site on any device.  
- **Port selection**: choose a port at startup or set `"port": 0` for a free one.  
- **Two watcher modes**: Sublime on‑save events (fast) or Watchdog polling (external changes). 
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
    "host": "localhost",
    "port": 0,                       // 0 = choose a free port
    "open_browser_on_start": true,
    "browser": "",                   // "chrome", "firefox", "edge", ...
    "status_bar_enabled": true,

    "live_reload": {
        "enabled": false,
        "css_injection": true,
        "delay": 500,                // ms debounce (0 = instant)
        "ignore_exts": [".log", ".map"]
    },

    "enable_compression": true,
    "cors_enabled": false,
    "max_file_size": 100,            // MB

    "connections": {
        "max_concurrent": 100,
        "timeout": 30,
        "max_threads": 10
    },

    "allowed_file_types": [".html", ".css", ".js", "..."],
    "ignore_dirs": ["node_modules", ".git", "__pycache__"]
}
```

Restart the server after changing settings.

---

## Requirements

- **Sublime Text 4** (Build ≥ 4152)  
- Browser with WebSocket support (Chrome, Firefox, Edge, Safari)

---

## Known limitations

- No built‑in HTTPS.
- Watchdog mode watches up to 50 directories; switch to Sublime‑event mode for very large projects.

---

## Contributing

Contributions welcome! Issues and pull requests are welcome.

---

## Vendored dependencies

- **Watchdog 6.0.0** – filesystem events  
- **PyQRCode** and **pypng** – QR generation  

All vendored under `liveserverplus_lib/vendor/`.

---

## Support

Report bugs/issues on GitHub: <https://github.com/ifrederico/sublime-liveserverplus/issues>

---

## License

[MIT](./LICENSE)