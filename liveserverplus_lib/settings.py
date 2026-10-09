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
    'showInfoMessages': True,
    'verifyTags': True,
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
    'openBrowser': True,
    'port': 5500,
    'showOnStatusbar': True,
    'useLocalIp': False,
    'useWebExt': False,
    'wait': 100,
    'maxThreads': 64,
    'maxWatchedDirs': 50,
    'renderMarkdownPreview': True,
    'markdownScrollSync': 'editor',
    'markdownSyntaxHighlighting': False,
    'markdownMath': False,
    'markdownMermaid': False,
}

# Keys that are only read when the server starts (socket, thread pool, file
# watcher, script injection, ignore rules). The running server keeps the
# values it started with; ServerManager restarts it when one of these changes
# in the settings file. Every other key is re-read while the server runs.
RESTART_KEYS = (
    'port', 'host', 'useLocalIp', 'liveReload', 'maxThreads',
    'maxWatchedDirs', 'ignoreFiles', 'ignoreDirs', 'useWebExt',
)


def _deep_merge(target: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dictionary values without mutating defaults."""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_merge(copy.deepcopy(target[key]), value)
        else:
            target[key] = value
    return target


def changed_keys(old: Dict[str, Any], new: Dict[str, Any], keys) -> List[str]:
    """Return the ``keys`` whose value differs between ``old`` and ``new``."""
    return [key for key in keys if old.get(key) != new.get(key)]


class ServerSettings:
    """Manages LiveServerPlus settings with project overrides."""

    _global_ephemeral_port: Optional[int] = None
    # When set, the next ServerSettings takes these project overrides instead
    # of the active window's. ServerManager sets it while it builds the server
    # that replaces a running one, which may have come from another window.
    inherited_project_settings: Optional[Dict[str, Any]] = None

    def __init__(self) -> None:
        self._settings: Optional[sublime.Settings] = None
        self._project_settings: Dict[str, Any] = {}
        self._config: Dict[str, Any] = {}
        self._allowed_types_cache: Optional[set[str]] = None
        self._ephemeral_port_cache: Optional[int] = None
        self.load_settings()

    def load_settings(self) -> None:
        """Load global and project-level settings.

        The result is a snapshot: it does not follow later edits of the
        settings file. ``refresh()`` re-reads the keys that may change while
        the server runs.
        """
        self._settings = sublime.load_settings('LiveServerPlus.sublime-settings')

        project_settings = ServerSettings.inherited_project_settings
        if project_settings is None:
            window = sublime.active_window()
            project_data = (window.project_data() or {}) if window else {}
            project_settings = project_data.get('liveserverplus')
        self._project_settings = copy.deepcopy(project_settings) if isinstance(project_settings, dict) else {}

        self._config = self._read_config()
        self._allowed_types_cache = None
        self._ephemeral_port_cache = None

    @property
    def project_settings(self) -> Dict[str, Any]:
        """The project's "liveserverplus" overrides captured at start."""
        return copy.deepcopy(self._project_settings)

    def refresh(self) -> None:
        """Re-read the settings file, keeping the values of ``RESTART_KEYS``.

        Project overrides are the ones captured when the server started.
        """
        config = self._read_config()
        for key in RESTART_KEYS:
            config[key] = self._config.get(key)
        self._config = config

    def changed_restart_keys(self) -> List[str]:
        """Return the ``RESTART_KEYS`` whose configured value differs from the snapshot."""
        return changed_keys(self._config, self._read_config(), RESTART_KEYS)

    def _read_config(self) -> Dict[str, Any]:
        """Merge defaults, the settings file and the captured project overrides."""
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
        for key, value in self._project_settings.items():
            if key not in DEFAULT_SETTINGS:
                if key == 'ignore_dirs':
                    base_config['ignoreDirs'] = value
                continue
            if isinstance(value, dict) and isinstance(base_config.get(key), dict):
                base_config[key] = _deep_merge(base_config[key], value)
            else:
                base_config[key] = value

        return base_config

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
            # Keep the same random port across restarts so open tabs reconnect.
            configured = (ServerSettings._global_ephemeral_port
                          or getFreePort(49152, 65535) or 8080)
            ServerSettings._global_ephemeral_port = configured
        self._ephemeral_port_cache = configured
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
    def openBrowser(self) -> bool:
        return bool(self._config.get('openBrowser', DEFAULT_SETTINGS['openBrowser']))

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
    def showInfoMessages(self) -> bool:
        return bool(self._config.get('showInfoMessages', DEFAULT_SETTINGS['showInfoMessages']))

    @property
    def renderMarkdownPreview(self) -> bool:
        return bool(self._config.get('renderMarkdownPreview', DEFAULT_SETTINGS['renderMarkdownPreview']))

    @property
    def markdownSyntaxHighlighting(self) -> bool:
        return bool(self._config.get(
            'markdownSyntaxHighlighting', DEFAULT_SETTINGS['markdownSyntaxHighlighting']))

    @property
    def markdownMath(self) -> bool:
        return bool(self._config.get('markdownMath', DEFAULT_SETTINGS['markdownMath']))

    @property
    def markdownMermaid(self) -> bool:
        return bool(self._config.get('markdownMermaid', DEFAULT_SETTINGS['markdownMermaid']))

    @property
    def markdownScrollSyncMode(self) -> str:
        raw_value = self._config.get('markdownScrollSync', DEFAULT_SETTINGS['markdownScrollSync'])

        if isinstance(raw_value, bool):
            return 'sync' if raw_value else 'off'

        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in ('sync', 'editor'):
                return normalized
            if normalized in ('false', 'off', 'none', 'disabled'):
                return 'off'

        return DEFAULT_SETTINGS['markdownScrollSync']

    @property
    def verifyTags(self) -> bool:
        return bool(self._config.get('verifyTags', DEFAULT_SETTINGS['verifyTags']))

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
