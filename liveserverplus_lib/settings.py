# liveserverplus_lib/settings.py
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import sublime

from .utils import getFreePort

DEFAULT_ALLOWED_FILE_TYPES = [
    '.html', '.htm', '.css', '.js', '.mjs',
    '.jsx', '.tsx', '.ts', '.vue', '.svelte',
    '.scss', '.sass', '.less', '.postcss',
    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp', '.avif',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp4', '.webm', '.ogg', '.mp3', '.wav',
    '.pdf', '.json', '.xml', '.map', '.md', '.txt'
]

DEFAULT_SETTINGS: Dict[str, Any] = {
    'customBrowser': '',
    'donotShowInfoMsg': False,
    'donotVerifyTags': False,
    'fullReload': False,
    'liveReload': False,
    'host': '127.0.0.1',
    'ignoreFiles': [
        '**/node_modules/**',
        '**/.git/**',
        '**/__pycache__/**'
    ],
    'ignoreDirs': [
        'node_modules', '.git', '__pycache__',
        '.svn', '.hg', '.sass-cache', '.pytest_cache'
    ],
    'logging': False,
    'noBrowser': False,
    'port': 5500,
    'showOnStatusbar': True,
    'useLocalIp': False,
    'useWebExt': False,
    'wait': 100,
    'maxThreads': 64,
    'maxWatchedDirs': 50,
}


def _deep_merge(target: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dictionary values without mutating defaults."""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_merge(copy.deepcopy(target[key]), value)
        else:
            target[key] = value
    return target


class ServerSettings:
    """Manages LiveServerPlus settings with project overrides."""

    _global_ephemeral_port: Optional[int] = None

    def __init__(self) -> None:
        self._settings: Optional[sublime.Settings] = None
        self._config: Dict[str, Any] = {}
        self._allowed_types_cache: Optional[set[str]] = None
        self._ephemeral_port_cache: Optional[int] = None
        self.load_settings()

    def load_settings(self) -> None:
        """Load global and project-level settings."""
        if self._settings:
            self._settings.clear_on_change('live_server_settings')

        self._settings = sublime.load_settings('LiveServerPlus.sublime-settings')
        self._settings.add_on_change('live_server_settings', self.on_settings_change)

        base_config = copy.deepcopy(DEFAULT_SETTINGS)

        # Apply user overrides from the global settings file
        for key in DEFAULT_SETTINGS.keys():
            value = self._settings.get(key)
            if value is not None:
                if isinstance(value, dict) and isinstance(base_config.get(key), dict):
                    base_config[key] = _deep_merge(base_config[key], value)
                else:
                    base_config[key] = value

        legacy_ignore_dirs = self._settings.get('ignore_dirs')
        if legacy_ignore_dirs is not None:
            base_config['ignoreDirs'] = legacy_ignore_dirs

        # Apply project specific overrides ("liveserverplus")
        window = sublime.active_window()
        if window:
            project_data = window.project_data() or {}
            project_settings = project_data.get('liveserverplus')
            if isinstance(project_settings, dict):
                for key, value in project_settings.items():
                    if key not in DEFAULT_SETTINGS:
                        if key == 'ignore_dirs':
                            base_config['ignoreDirs'] = value
                        continue
                    if isinstance(value, dict) and isinstance(base_config.get(key), dict):
                        base_config[key] = _deep_merge(base_config[key], value)
                    else:
                        base_config[key] = value

        self._config = base_config
        self._allowed_types_cache = None
        self._ephemeral_port_cache = ServerSettings._global_ephemeral_port

    def on_settings_change(self) -> None:
        """Reload settings when LiveServerPlus.sublime-settings updates."""
        self.load_settings()

    # ------------------------------------------------------------------
    # Basic server configuration
    # ------------------------------------------------------------------
    @property
    def host(self) -> str:
        return str(self._config.get('host', DEFAULT_SETTINGS['host']))

    @property
    def port(self) -> int:
        if self._ephemeral_port_cache is not None:
            return self._ephemeral_port_cache

        configured = int(self._config.get('port', DEFAULT_SETTINGS['port']))
        if configured == 0:
            if self._ephemeral_port_cache is not None:
                configured = self._ephemeral_port_cache
            else:
                configured = getFreePort(49152, 65535) or 8080
        self._ephemeral_port_cache = configured
        ServerSettings._global_ephemeral_port = configured
        return configured

    @property
    def waitTimeMs(self) -> int:
        try:
            value = int(self._config.get('wait', DEFAULT_SETTINGS['wait']))
        except (TypeError, ValueError):
            value = DEFAULT_SETTINGS['wait']
        return max(0, value)

    @property
    def fullReload(self) -> bool:
        return bool(self._config.get('fullReload', DEFAULT_SETTINGS['fullReload']))

    @property
    def liveReload(self) -> bool:
        return bool(self._config.get('liveReload', DEFAULT_SETTINGS['liveReload']))

    @property
    def ignorePatterns(self) -> List[str]:
        patterns = self._config.get('ignoreFiles', [])
        if not isinstance(patterns, list):
            return []
        return [str(item) for item in patterns]

    @property
    def ignoreExtensions(self) -> List[str]:
        return []

    @property
    def ignoreDirs(self) -> List[str]:
        dirs = self._config.get('ignoreDirs', DEFAULT_SETTINGS['ignoreDirs'])
        if not isinstance(dirs, list):
            return []
        return [str(item) for item in dirs]

    # ------------------------------------------------------------------
    # Browser and UI configuration
    # ------------------------------------------------------------------
    @property
    def customBrowser(self) -> str:
        return str(self._config.get('customBrowser') or '').strip()

    @property
    def noBrowser(self) -> bool:
        return bool(self._config.get('noBrowser', DEFAULT_SETTINGS['noBrowser']))

    @property
    def useLocalIp(self) -> bool:
        return bool(self._config.get('useLocalIp', DEFAULT_SETTINGS['useLocalIp']))

    @property
    def useWebExt(self) -> bool:
        return bool(self._config.get('useWebExt', DEFAULT_SETTINGS['useWebExt']))

    @property
    def showOnStatusbar(self) -> bool:
        return bool(self._config.get('showOnStatusbar', DEFAULT_SETTINGS['showOnStatusbar']))

    @property
    def suppressInfoMessages(self) -> bool:
        return bool(self._config.get('donotShowInfoMsg', DEFAULT_SETTINGS['donotShowInfoMsg']))

    @property
    def suppressTagWarnings(self) -> bool:
        return bool(self._config.get('donotVerifyTags', DEFAULT_SETTINGS['donotVerifyTags']))

    # ------------------------------------------------------------------
    # Internal server tuning defaults
    # ------------------------------------------------------------------
    @property
    def maxThreads(self) -> int:
        try:
            value = int(self._config.get('maxThreads', DEFAULT_SETTINGS['maxThreads']))
        except (TypeError, ValueError):
            value = DEFAULT_SETTINGS['maxThreads']
        return max(4, min(value, 512))

    @property
    def maxWatchedDirs(self) -> int:
        try:
            value = int(self._config.get('maxWatchedDirs', DEFAULT_SETTINGS['maxWatchedDirs']))
        except (TypeError, ValueError):
            value = DEFAULT_SETTINGS['maxWatchedDirs']
        return max(10, min(value, 5000))

    @property
    def maxFileSize(self) -> int:
        return 100

    @property
    def enableCompression(self) -> bool:
        return True

    @property
    def corsEnabled(self) -> bool:
        return False

    @property
    def allowedFileTypes(self) -> List[str]:
        return DEFAULT_ALLOWED_FILE_TYPES

    @property
    def allowedFileTypesSet(self) -> set:
        if self._allowed_types_cache is None:
            self._allowed_types_cache = {ext.lower() for ext in self.allowedFileTypes}
        return self._allowed_types_cache

    def reset_ephemeral_port(self) -> None:
        self._ephemeral_port_cache = None
        ServerSettings._global_ephemeral_port = None
